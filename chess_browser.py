"""Interactive, cancellable browser for public completed games."""
import asyncio

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.worker import get_current_worker
from textual.widgets import Button, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

from chess_dialogs import AnalysisDialog
from chess_game import Analysis
from chess_input import parse_input
from chess_online import OnlineGame, chesscom_games, chesscom_months, lichess_games, lichess_pgn, validate_username


class GameBrowser(AnalysisDialog):
    DEFAULT_CSS = """
    GameBrowser > Vertical { width: 95%; height: 90%; padding: 0 1; }
    GameBrowser Label { margin-bottom: 0; }
    GameBrowser Horizontal { margin-top: 0; }
    GameBrowser Button { min-width: 0; width: 1fr; margin-right: 0; }
    GameBrowser #browser-status { height: auto; max-height: 2; }
    GameBrowser OptionList { height: 1fr; min-height: 2; max-height: 100%; }
    """

    def __init__(self):
        super().__init__()
        self.games: list[OnlineGame] = []
        self.until: int | None = None
        self.archive_user = ""
        self.busy = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Public completed games · choose a game with ↑/↓ and Enter")
            yield Select([("Chess.com", "chesscom"), ("Lichess", "lichess")],
                         value="chesscom", allow_blank=False, id="provider")
            yield Input(placeholder="Public username (no token needed)", id="username")
            yield Select([], prompt="Archive month", disabled=True, id="month")
            with Horizontal():
                yield Button("Load games", id="load", variant="primary")
                yield Button("Older", id="older", disabled=True)
                yield Button("Newest", id="newest", disabled=True)
            yield Static("Enter a username, then Load games. Esc cancels.", id="browser-status")
            yield OptionList(id="games")

    @on(Select.Changed, "#provider")
    @on(Input.Changed, "#username")
    def reset_listing(self) -> None:
        self.games = []
        self.until = None
        self.archive_user = ""
        self.query_one("#games", OptionList).clear_options()
        month = self.query_one("#month", Select)
        month.set_options([])
        month.disabled = True
        month.display = self.query_one("#provider", Select).value == "chesscom"
        self.query_one("#older", Button).disabled = True
        self.query_one("#newest", Button).disabled = True

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        for selector in ("#provider", "#username", "#load", "#games"):
            self.query_one(selector).disabled = busy
        lichess = self.query_one("#provider", Select).value == "lichess"
        self.query_one("#month", Select).disabled = busy or lichess or not self.archive_user
        self.query_one("#older", Button).disabled = busy or not lichess or self.until is None
        self.query_one("#newest", Button).disabled = busy or not lichess

    @on(Button.Pressed, "#load")
    @on(Button.Pressed, "#newest")
    @on(Input.Submitted, "#username")
    def load_newest(self) -> None:
        self.load_games()

    @on(Button.Pressed, "#older")
    def load_older(self) -> None:
        if self.until is not None:
            self.load_games(self.until)

    @work(group="online", exclusive=True)
    async def load_games(self, until: int | None = None) -> None:
        status = self.query_one("#browser-status", Static)
        status.update("Loading… · Esc cancels")
        self.set_busy(True)
        self.games = []
        self.until = None
        options = self.query_one("#games", OptionList)
        options.clear_options()
        try:
            username = validate_username(self.query_one("#username", Input).value)
            provider = self.query_one("#provider", Select).value
            if provider == "chesscom":
                month = self.query_one("#month", Select)
                if self.archive_user != username:
                    months = await asyncio.to_thread(chesscom_months, username)
                    month.set_options((value, value) for value in months)
                    if not months:
                        status.update("No public archive months for this username.")
                        return
                    month.value = months[0]
                    self.archive_user = username
                self.games = await asyncio.to_thread(chesscom_games, username, str(month.value))
            else:
                page = await asyncio.to_thread(lichess_games, username, until=until)
                self.games, self.until = page.games, page.until
            options.add_options(Option(Text(game.label), id=str(index))
                                for index, game in enumerate(self.games))
            options.highlighted = 0 if self.games else None
            status.update(f"{len(self.games)} completed standard games · Enter opens" if self.games
                          else "No completed standard games here. Try another month or Older.")
        except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
            status.update(Text(f"Could not list games: {exc}"))
        finally:
            if self.is_mounted and not get_current_worker().is_cancelled:
                self.set_busy(False)
        if self.is_mounted and self.games:
            options.focus()

    @on(OptionList.OptionSelected, "#games")
    def game_selected(self, event: OptionList.OptionSelected) -> None:
        if not self.busy:
            self.open_game(self.games[int(event.option.id)])

    @work(group="online", exclusive=True)
    async def open_game(self, game: OnlineGame) -> None:
        status = self.query_one("#browser-status", Static)
        status.update("Loading selected game… · Esc cancels")
        self.set_busy(True)
        try:
            pgn = game.pgn if game.pgn is not None else await asyncio.to_thread(lichess_pgn, game.id)
            parsed = parse_input(pgn)
            if parsed[1] is None or parsed[1].headers.get("Result") not in {"1-0", "0-1", "1/2-1/2"}:
                raise ValueError("Only completed games can be imported.")
            analysis = Analysis.from_input(*parsed)
        except (OSError, ValueError) as exc:
            status.update(Text(f"Could not import game: {exc}"))
            self.set_busy(False)
        else:
            self.dismiss(analysis)
