#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import math
from collections.abc import Callable

import chess
import chess.engine
import chess.pgn
from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Footer, Header, Static

from .browser import GameBrowser
from .dialogs import CommentEditor, LibraryDialog, SaveAnalysisDialog
from .game import Analysis, Candidate, Node, history_to_san
from .library import SavedAnalysis, library_path
from .openings import opening_label
from .piece_art import PIECE_ART


QUALITY_COLORS = {
    "Best": "#22d3ee", "Excellent": "#22d3ee", "Good": "#4ade80",
    "Inaccuracy": "#9ca3af", "Mistake": "#facc15", "Blunder": "#ef4444",
}


def quality_badge(label: str) -> Text:
    return Text(f" {label} ", style=Style(
        color="black", bgcolor=QUALITY_COLORS[label], bold=True, reverse=False,
    ))


def side_label(color: str, name: str) -> str:
    return color if name == color else f"{color} · {name}"


def format_score(score: chess.engine.Score) -> str:
    """Format a raw White-perspective evaluation in pawns."""
    mate = score.mate()
    if mate is not None:
        sign = "" if score > chess.engine.Cp(0) else "-"
        return f"{sign}M{abs(mate)}"
    cp = score.score()
    return "?" if cp is None else f"{cp / 100:+.2f}"


class EvaluationBar(Widget):
    def render(self) -> Text:
        outcome = self.app.analysis.current.board.outcome()
        if outcome is not None:
            white_share = 0.5 if outcome.winner is None else float(outcome.winner)
        else:
            candidate = next(iter(self.app.analysis.current.candidates), None)
            score = format_score(candidate.score) if candidate else "0.00"
            if score.startswith("M"):
                white_share = 1.0
            elif score.startswith("-M"):
                white_share = 0.0
            else:
                white_share = 1 / (1 + math.exp(-float(score) / 1.5)) if score != "?" else 0.5
        height = max(1, self.size.height)
        white_rows = round(height * white_share)
        return Text("\n").join(
            Text("  ", style=f"on {'#f0f0e8' if row < white_rows else '#30343b'}")
            for row in range(height)
        )


class ChessBoard(Widget):
    """Native terminal cells; piece art is credited in piece_art.py and README.md."""

    def render(self) -> Text:
        app = self.app
        board = app.analysis.current.board
        selected = app.selected_move()
        last = app.analysis.current.move_from_parent
        files = list(range(7, -1, -1) if app.analysis.flipped else range(8))
        ranks = range(8) if app.analysis.flipped else range(7, -1, -1)
        cell_width = max(2, min(10, (self.size.width - 3) // 8))
        cell_height = max(1, min(5, (self.size.height - 1) // 8))
        art = {}
        if not app.ascii_pieces:
            for (height, width), sprites in PIECE_ART.items():
                if cell_height >= height and cell_width >= width:
                    art = sprites
        text = Text(no_wrap=True)
        for rank in ranks:
            for row in range(cell_height):
                text.append(f"{rank + 1}  " if row == cell_height // 2 else "   ")
                for file in files:
                    square = chess.square(file, rank)
                    piece = board.piece_at(square)
                    background = "#899779" if (rank + file) % 2 else "#536747"
                    if last and square in (last.from_square, last.to_square):
                        background = "#898e3c"
                    if selected and square in (selected.from_square, selected.to_square):
                        background = "#4c809c"
                    if board.is_check() and square == board.king(board.turn):
                        background = "#ad4b4b"
                    symbol = " "
                    if piece:
                        lines = art[piece.piece_type] if art else (
                            piece.symbol() if app.ascii_pieces else piece.unicode_symbol(),
                        )
                        piece_row = row - (cell_height // 2 - len(lines) // 2)
                        if 0 <= piece_row < len(lines):
                            symbol = lines[piece_row]
                    color = "#ffffff" if art and piece and piece.color else "#121212"
                    text.append(symbol.center(cell_width), style=f"bold {color} on {background}")
                text.append("\n")
        text.append("   " + "".join(chess.FILE_NAMES[file].center(cell_width) for file in files))
        return text


class ChessAnalysisApp(App):
    ENABLE_COMMAND_PALETTE = False
    TITLE = "Chess Analysis"
    CSS = """
    Widget { link-style: none; link-style-hover: none; }
    Screen { background: #0d1117; color: #e6edf3; }
    Header, Footer { background: #161b22; }
    Static { height: auto; }
    #main { height: 1fr; padding: 0 1; }
    #board-side { width: 1fr; min-width: 22; padding: 0 1; }
    #analysis-side {
        width: 1fr; min-width: 27; border: round #30363d;
        background: #161b22; padding: 0 1;
    }
    #position-info, #engine-title, .player-name { text-style: bold; }
    .player-name { color: #c9d1d9; }
    #board-area, #board {
        width: 1fr; height: 1fr; min-height: 9; content-align: center middle;
    }
    #evaluation-bar { width: 2; height: 1fr; margin: 1 0; }
    #opening { color: #e3b341; margin-bottom: 1; }
    #fen, #status { color: #8b949e; }
    #fen { max-height: 3; }
    .narrow #main { layout: vertical; }
    .narrow #board-side { width: 1fr; height: 14; }
    .narrow #analysis-side { width: 1fr; height: 1fr; }
    #engine-title, #move-quality, #return-game, #candidates { margin-bottom: 1; }
    #return-game { color: #e3b341; }
    #pv, #history { border-top: solid #30363d; padding-top: 1; margin-top: 1; }
    #history { color: #c9d1d9; }
    #status { margin-top: 1; }
    """
    BINDINGS = [
        Binding("left", "previous_position", "Back", priority=True),
        Binding("right", "next_position", "Follow", priority=True),
        Binding("enter", "next_position", "Follow", show=False, priority=True),
        Binding("up", "select_move(-1)", "Choose", priority=True),
        Binding("down", "select_move(1)", "Choose", priority=True),
        Binding("escape", "return_to_game", "Original game", priority=True),
        ("f", "flip_board", "Flip"),
        ("r", "reanalyze", "Re-analyze"),
        ("c", "edit_comment", "Comment"),
        ("s", "save_analysis", "Save"),
        ("l", "open_library", "Library"),
        ("b", "browse_games", "Games"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, board: chess.Board, engine: chess.engine.UciProtocol,
                 think_time: float, multipv: int, ascii_pieces: bool = False,
                 game: chess.pgn.Game | None = None, engine_name: str = "Engine",
                 white_name: str = "White", black_name: str = "Black",
                 on_session_change: Callable[[Analysis], None] | None = None,
                 open_library: bool = False,
                 browse_provider: str | None = None, browse_user: str | None = None):
        super().__init__()
        self.on_session_change = on_session_change
        self.open_library = open_library
        self.browse_provider = browse_provider
        self.browse_user = browse_user
        self.engine = engine
        self.think_time = think_time
        self.multipv = multipv
        self.ascii_pieces = ascii_pieces
        self.engine_name = engine_name
        self.analysis = Analysis.from_input(board, game, white_name, black_name)
        self.saved_title = ""
        self.analysis_requested = asyncio.Event()

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            with Vertical(id="board-side"):
                yield Static(id="position-info")
                yield Static(id="top-player", classes="player-name")
                with Horizontal(id="board-area"):
                    yield ChessBoard(id="board")
                    yield EvaluationBar(id="evaluation-bar")
                yield Static(id="bottom-player", classes="player-name")
                yield Static(id="fen")
            with VerticalScroll(id="analysis-side"):
                for name in ("opening", "engine-title", "move-quality", "return-game", "candidates", "comments",
                             "pv", "history", "status"):
                    yield Static(id=name)
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_ui()
        self.analyze_requested_position()
        self.analysis_loop()
        self.save_session()
        if self.open_library:
            self.action_open_library()
        elif self.browse_provider:
            self.action_browse_games()

    def save_session(self) -> None:
        if self.on_session_change is not None:
            self.on_session_change(self.analysis)

    def on_resize(self, event: Resize) -> None:
        self.screen.set_class(event.size.width < 64, "narrow")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:
        if isinstance(self.screen, ModalScreen):
            return False
        if action == "browse_games":
            return bool(self.browse_provider and self.browse_user)
        return action != "return_to_game" or self.analysis.return_position is not None

    def refresh_ui(self) -> None:
        self.refresh_board()
        self.refresh_analysis_panel()
        board = self.analysis.current.board
        info = Text("White to move" if board.turn else "Black to move", style="bold")
        if board.is_check():
            info.append("   CHECKMATE" if board.is_checkmate() else "   CHECK", style="bold red")
        if self.analysis.current.is_mainline:
            info.append("   Original game", style="bold #e3b341")
        elif self.analysis.return_position:
            branch = self.analysis.return_position.board
            turn = "." if branch.turn else "..."
            info.append(f"   Exploring from {branch.fullmove_number}{turn} · Esc: game",
                        style="bold #58a6ff")
        self.query_one("#position-info", Static).update(info)
        opening = opening_label(board)
        opening_panel = self.query_one("#opening", Static)
        opening_panel.display = opening is not None
        opening_panel.update(Text(opening or ""))
        self.query_one("#fen", Static).update(Text(f"FEN  {board.fen()}", style="dim"))

    def move_choices(self, node: Node) -> list[chess.Move | None]:
        original = node.mainline_next.move_from_parent if node.mainline_next else None
        # A non-playable end row prevents jumping from the PGN into an engine line.
        moves = [original] if node.is_mainline else []
        moves += [move for move in node.children if move != original]
        return moves + [c.move for c in node.candidates if c.move not in moves]

    def selected_move(self) -> chess.Move | None:
        moves = self.move_choices(self.analysis.current)
        if not moves:
            return None
        self.analysis.current.selected %= len(moves)
        return moves[self.analysis.current.selected]

    def refresh_board(self) -> None:
        self.query_one("#board", ChessBoard).refresh()
        self.query_one("#evaluation-bar", EvaluationBar).refresh()
        top_color, top_name, bottom_color, bottom_name = (
            ("White", self.analysis.white_name, "Black", self.analysis.black_name) if self.analysis.flipped
            else ("Black", self.analysis.black_name, "White", self.analysis.white_name)
        )
        self.query_one("#top-player", Static).update(side_label(top_color, top_name))
        self.query_one("#bottom-player", Static).update(side_label(bottom_color, bottom_name))

    def refresh_analysis_panel(self) -> None:
        node = self.analysis.current
        board = node.board
        candidates = {c.move: c for c in node.candidates}
        self.query_one("#engine-title", Static).update(
            Text(f"{self.engine_name}   {self.think_time:g}s / {self.multipv} lines", style="bold")
        )
        quality = node.parent.quality(node.move_from_parent) if node.parent else None
        quality_panel = self.query_one("#move-quality", Static)
        quality_panel.display = node.parent is not None
        san = node.parent.board.san(node.move_from_parent) if node.parent else ""
        last_move = Text(f"Last move · {san} ·", style="bold")
        last_move.append(quality_badge(quality) if quality else " Unrated")
        quality_panel.update(last_move)
        return_link = self.query_one("#return-game", Static)
        return_link.display = self.analysis.return_position is not None
        return_link.update(Text("← Back to original game [Esc]", style=Style(
            color="#e3b341", meta={"@click": "app.return_to_game"},
        )))
        selected_move = self.selected_move()
        lines = Text("Next move · ↑/↓ choose\n", style="bold")
        for index, move in enumerate(self.move_choices(node)):
            original = node.is_mainline and index == 0
            candidate = candidates.get(move)
            san = board.san(move) if move else "End of original game"
            child = node.children.get(move)
            imported = child is not None and child.imported
            label = ("Original" if original else "Variation" if imported
                     else "Engine" if candidate else "Explored")
            row = f"{'▶' if index == node.selected else ' '} {label:<9} {san}"
            if candidate:
                row += f"  {format_score(candidate.score)}"
            row = Text(row, style=Style(
                color="#e3b341" if original else "#58a6ff", reverse=index == node.selected,
                meta={"@click": f"app.follow_choice({index})"},
            ))
            quality = node.quality(move)
            if quality:
                row.append(" ·").append(quality_badge(quality))
            lines.append(row).append("\n")
        lines.append("→ / Enter follows selection\n", style="dim")
        if board.is_game_over():
            lines.append(f"Game over: {board.result()}\n", style="dim")
        elif not node.candidates:
            lines.append("No engine lines. Press r to retry." if node.analyzed
                         else "Engine is thinking…", style="dim")
        self.query_one("#candidates", Static).update(lines)
        comments = Text()
        if node.starting_comment:
            comments.append(node.starting_comment + "\n\n")
        if node.comment:
            comments.append(node.comment)
        selected_child = node.children.get(selected_move)
        if selected_child and selected_child.starting_comment:
            comments.append("\n\nVariation: " + selected_child.starting_comment)
        comment_panel = self.query_one("#comments", Static)
        comment_panel.display = bool(comments.plain)
        comment_panel.update(comments)
        candidate = candidates.get(selected_move)
        pv = Text()
        if selected_move is None and not board.is_game_over():
            pv.append("↑/↓ choose an engine move to keep exploring.", style="dim")
        elif candidate:
            pv.append("Selected continuation\n\n", style="bold")
            pv.append(candidate.pv)
        elif node.mainline_next:
            pv.append("Continue the original game with → or Enter.", style="dim")
        self.query_one("#pv", Static).update(pv)

        history = Text()
        if self.analysis.has_pgn:
            history.append("Original game · click a move\n", style="bold #e3b341")
            anchor = node if node.is_mainline else self.analysis.return_position
            history.append("Start", style=Style(
                color="#e3b341", reverse=anchor is self.analysis.root,
                meta={"@click": "app.game_position(0)"},
            ))
            cursor = self.analysis.root
            index = 0
            while cursor.mainline_next:
                parent = cursor
                cursor = cursor.mainline_next
                index += 1
                prefix = f"{parent.board.fullmove_number}. " if parent.board.turn else ""
                if index == 1 and not parent.board.turn:
                    prefix = f"{parent.board.fullmove_number}... "
                san = parent.board.san(cursor.move_from_parent)
                entry = Text("  " + prefix + san, style=Style(
                    color="#e3b341", reverse=cursor is anchor,
                    meta={"@click": f"app.game_position({index})"},
                ))
                quality = parent.quality(cursor.move_from_parent)
                if quality:
                    entry.append(quality_badge(quality))
                history.append(entry)
            if not node.is_mainline:
                history.append("\n\nExplored line\n", style="bold #58a6ff")
                history.append(history_to_san(node))
        else:
            history.append("Current line\n\n", style="bold")
            history.append(history_to_san(node))
        self.query_one("#history", Static).update(history)

    def set_status(self, message: str, style: str = "dim") -> None:
        self.query_one("#status", Static).update(Text(message, style=style))

    def analyze_requested_position(self) -> None:
        self.analysis_requested.set()

    async def search(self, node: Node, multipv: int, root_moves=None) -> list[dict] | None:
        analysis = await self.engine.analysis(
            node.board.copy(), chess.engine.Limit(time=self.think_time),
            multipv=multipv, root_moves=root_moves,
        )
        with analysis:
            finished = asyncio.create_task(analysis.wait())
            changed = asyncio.create_task(self.analysis_requested.wait())
            try:
                done, _ = await asyncio.wait((finished, changed), return_when=asyncio.FIRST_COMPLETED)
                if changed in done:
                    analysis.stop()
                await finished
            finally:
                changed.cancel()
                await asyncio.gather(changed, return_exceptions=True)
        return None if self.analysis_requested.is_set() else analysis.multipv

    async def analyze_node(self, node: Node, played: chess.Move | None = None) -> bool:
        if node.board.is_game_over():
            node.analyzed = True
            return True
        if played is None and node.mainline_next:
            played = node.mainline_next.move_from_parent
        previous = self.move_choices(node)
        selected = previous[node.selected] if node.selected < len(previous) else None
        if not node.analyzed:
            infos = await self.search(node, self.multipv)
            if infos is None:
                return False
            node.candidates = [Candidate(info["pv"][0], info["score"].white(),
                                         node.board.variation_san(info["pv"]))
                               for info in infos if info.get("pv")]
        # The played move may be outside MultiPV; assess it without pretending it is best.
        if played and node.candidates and all(c.move != played for c in node.candidates):
            infos = await self.search(node, 1, [played])
            if infos is None:
                return False
            node.candidates += [Candidate(info["pv"][0], info["score"].white(),
                                          node.board.variation_san(info["pv"]))
                                for info in infos if info.get("pv")]
        node.analyzed = True
        choices = self.move_choices(node)
        node.selected = choices.index(selected) if selected in choices else 0
        return True

    @work(group="engine")
    async def analysis_loop(self) -> None:
        while True:
            await self.analysis_requested.wait()
            self.analysis_requested.clear()
            node = self.analysis.current
            self.set_status("Engine is thinking…", "yellow")
            self.refresh_ui()
            try:
                if node.parent and not await self.analyze_node(node.parent, node.move_from_parent):
                    continue
                if not await self.analyze_node(node):
                    continue
            except chess.engine.EngineError as exc:
                if node is self.analysis.current:
                    self.set_status(f"Engine error: {exc} · r to retry", "bold red")
                continue
            if node is self.analysis.current:
                self.set_status("Analysis ready.")
                self.refresh_ui()

    def action_select_move(self, direction: int) -> None:
        moves = self.move_choices(self.analysis.current)
        if moves:
            self.analysis.current.selected = (self.analysis.current.selected + direction) % len(moves)
            self.refresh_board()
            self.refresh_analysis_panel()

    def action_next_position(self) -> None:
        move = self.selected_move()
        if move is not None:
            if self.analysis.current.is_mainline:
                original = self.analysis.current.mainline_next
                self.analysis.return_position = (
                    None if original and original.move_from_parent == move else self.analysis.current
                )
            self.show_position(self.analysis.current.child(move))

    def action_follow_choice(self, index: int) -> None:
        self.analysis.current.selected = index
        self.action_next_position()

    def action_game_position(self, index: int) -> None:
        node = self.analysis.root
        for _ in range(index):
            if node.mainline_next is None:
                break
            node = node.mainline_next
        self.analysis.return_position = None
        node.selected = 0
        self.show_position(node)

    def show_position(self, node: Node) -> None:
        self.analysis.current = node
        self.refresh_bindings()
        self.set_status("Analysis ready." if node.analyzed else "")
        self.refresh_ui()
        self.query_one("#candidates").scroll_visible(animate=False)
        self.analyze_requested_position()
        self.save_session()

    def action_return_to_game(self) -> None:
        if self.analysis.return_position:
            node = self.analysis.return_position
            self.analysis.return_position = None
            node.selected = 0
            self.show_position(node)

    def action_previous_position(self) -> None:
        node = self.analysis.current.parent
        if node:
            if node.is_mainline:
                self.analysis.return_position = None
            self.show_position(node)

    def action_flip_board(self) -> None:
        self.analysis.flipped = not self.analysis.flipped
        self.refresh_board()
        self.save_session()

    def action_reanalyze(self) -> None:
        self.analysis.current.analyzed = False
        self.analyze_requested_position()

    def replace_analysis(self, analysis: Analysis, title: str = "") -> None:
        self.analysis = analysis
        self.saved_title = title
        self.sub_title = title
        self.show_position(analysis.current)

    def action_edit_comment(self) -> None:
        node = self.analysis.current

        def edited(comment: str | None) -> None:
            if comment is not None:
                node.comment = comment
                self.save_session()
            self.refresh_ui()

        self.push_screen(CommentEditor(node.comment), edited)

    def action_save_analysis(self) -> None:
        title = self.saved_title or f"{self.analysis.white_name} vs {self.analysis.black_name}"

        def saved(entry: SavedAnalysis | None) -> None:
            if entry is not None:
                self.saved_title = entry.title
                self.sub_title = entry.title
                self.notify(f"Saved: {entry.title}")
            self.refresh_ui()

        self.push_screen(SaveAnalysisDialog(self.analysis, title, library_path()), saved)

    def analysis_selected(self, result: tuple[str, Analysis] | None) -> None:
        if result is not None:
            title, analysis = result
            self.replace_analysis(analysis, title)
        else:
            self.refresh_ui()

    def action_open_library(self) -> None:
        self.push_screen(LibraryDialog(library_path()), self.analysis_selected)

    def action_browse_games(self) -> None:
        if self.browse_provider and self.browse_user:
            self.push_screen(GameBrowser(self.browse_provider, self.browse_user), self.analysis_selected)
