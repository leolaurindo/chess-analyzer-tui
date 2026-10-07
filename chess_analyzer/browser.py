"""Keyboard-first game selection for a provider and username chosen in the app or on the CLI."""
import asyncio

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.worker import get_current_worker
from textual.widgets import Button, Footer, Label, OptionList, Static

from .dialogs import AnalysisDialog
from .game import Analysis
from .input import parse_input
from .online import OnlineGame, chesscom_games, chesscom_months, lichess_games, lichess_pgn, validate_username


class GameBrowser(AnalysisDialog):
    DEFAULT_CSS = """
    GameBrowser > Vertical { width: 95%; height: 90%; padding: 0 1; }
    GameBrowser Label { margin-bottom: 0; }
    GameBrowser Horizontal { margin-top: 0; }
    GameBrowser Button { min-width: 0; width: 1fr; margin-right: 0; }
    GameBrowser #browser-status { height: auto; max-height: 3; }
    GameBrowser OptionList { height: 1fr; min-height: 2; max-height: 100%; }
    """
    BINDINGS = [
        Binding("up", "choose(-1)", "Choose", show=False, priority=True),
        Binding("down", "choose(1)", "Choose", show=False, priority=True),
        Binding("enter", "open_selected", "Open", key_display="↵", priority=True),
        Binding("left", "page(-1)", "Newer", show=False, priority=True),
        Binding("right", "page(1)", "Older", show=False, priority=True),
        Binding("r", "page(0)", "Reload", show=False),
    ]

    def __init__(self, provider: str, username: str):
        super().__init__()
        if provider not in {"chess.com", "lichess"}:
            raise ValueError("Choose chess.com or lichess.")
        self.provider = provider
        self.username = validate_username(username)
        self.games: list[OnlineGame] = []
        self.months: list[str] = []
        self.cursors: list[int | None] = [None]
        self.page_index = 0
        self.busy = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(Text(f"{self.provider} · {self.username}"))
            yield Label("↑/↓ choose · Enter opens · ←/→ newer/older · r reload · Esc cancels")
            with Horizontal():
                yield Button("Newer", id="newer", disabled=True)
                yield Button("Older", id="older", disabled=True)
                yield Button("Reload", id="reload")
            yield Static("Loading…", id="browser-status")
            yield OptionList(id="games")
        yield Footer()

    def on_mount(self) -> None:
        self.load_games()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.query_one("#games", OptionList).disabled = busy
        self.query_one("#reload", Button).disabled = busy
        self.query_one("#newer", Button).disabled = busy or self.page_index == 0
        pages = self.months if self.provider == "chess.com" else self.cursors
        self.query_one("#older", Button).disabled = busy or self.page_index + 1 >= len(pages)

    def pause_for_help(self) -> None:
        self.workers.cancel_node(self)
        if self.busy:
            self.set_busy(False)
            self.query_one("#browser-status", Static).update("Download canceled · r retries")

    def action_choose(self, direction: int) -> None:
        if not self.busy and self.games:
            options = self.query_one("#games", OptionList)
            options.highlighted = ((options.highlighted or 0) + direction) % len(self.games)
            options.focus()

    @on(Button.Pressed)
    def page_clicked(self, event: Button.Pressed) -> None:
        self.action_page({"newer": -1, "older": 1, "reload": 0}[event.button.id])

    def action_page(self, offset: int) -> None:
        pages = self.months if self.provider == "chess.com" else self.cursors
        index = self.page_index + offset
        if not self.busy and 0 <= index < max(1, len(pages)):
            self.load_games(index)

    @work(group="online", exclusive=True)
    async def load_games(self, index: int = 0) -> None:
        status = self.query_one("#browser-status", Static)
        status.update("Loading… · Esc cancels")
        self.page_index = index
        self.set_busy(True)
        self.games = []
        options = self.query_one("#games", OptionList)
        options.clear_options()
        try:
            if self.provider == "chess.com":
                if not self.months:
                    self.months = await asyncio.to_thread(chesscom_months, self.username)
                if not self.months:
                    status.update("No public archive months for this username.")
                    return
                month = self.months[index]
                self.games = await asyncio.to_thread(chesscom_games, self.username, month)
                heading = month
            else:
                page = await asyncio.to_thread(lichess_games, self.username, until=self.cursors[index])
                self.games = page.games
                self.cursors = self.cursors[:index + 1]
                if page.until is not None:
                    self.cursors.append(page.until)
                heading = f"Page {index + 1}"
            options.add_options(Text(game.label) for game in self.games)
            options.highlighted = 0 if self.games else None
            status.update(f"{heading} · {len(self.games)} completed standard games" if self.games
                          else f"{heading} · No completed standard games. → tries older games.")
        except (OSError, ValueError) as exc:
            status.update(Text(f"Could not list games: {exc} · r retries"))
        finally:
            if self.is_mounted and not get_current_worker().is_cancelled:
                self.set_busy(False)
        if self.is_mounted:
            options.focus()

    @on(OptionList.OptionSelected, "#games")
    def action_open_selected(self, event: OptionList.OptionSelected | None = None) -> None:
        selected = event.option_index if event else self.query_one("#games", OptionList).highlighted
        if not self.busy and selected is not None:
            self.open_game(self.games[selected])

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
            self.query_one("#games", OptionList).focus()
        else:
            self.dismiss(("", analysis))
