#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import math
import os
import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path

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
from textual.widget import Widget
from textual.widgets import Footer, Header, Static

from piece_art import PIECE_ART


@dataclass
class Candidate:
    move: chess.Move
    score: str
    pv: str


@dataclass
class Node:
    board: chess.Board
    parent: Node | None = None
    move_from_parent: chess.Move | None = None
    mainline_next: Node | None = None
    is_mainline: bool = False
    candidates: list[Candidate] = field(default_factory=list)
    selected: int = 0
    children: dict[chess.Move, Node] = field(default_factory=dict)
    analyzed: bool = False

    def child(self, move: chess.Move) -> Node:
        if move not in self.children:
            board = self.board.copy()
            board.push(move)
            self.children[move] = Node(board, parent=self, move_from_parent=move)
        return self.children[move]


def find_stockfish() -> str | None:
    local = Path(__file__).with_name("stockfish.exe" if os.name == "nt" else "stockfish")
    paths = [shutil.which("stockfish"), str(local), "/usr/games/stockfish",
             "/usr/bin/stockfish", "/usr/local/bin/stockfish"]
    return next((p for p in paths if p and os.path.isfile(p) and os.access(p, os.X_OK)), None)


def missing_engine_message() -> str:
    system = platform.system()
    label = "macOS" if system == "Darwin" else system
    suggestion = "Download an executable from https://stockfishchess.org/download/"
    if system == "Windows":
        suggestion = "winget install --id Stockfish.Stockfish --exact"
    elif system == "Darwin":
        suggestion = "brew install stockfish (requires Homebrew)"
    elif system == "Linux":
        try:
            release = platform.freedesktop_os_release()
        except OSError:
            release = {}
        if release.get("PRETTY_NAME"):
            label += f" ({release['PRETTY_NAME']})"
        families = {release.get("ID"), *release.get("ID_LIKE", "").split()}
        if families & {"debian", "ubuntu"}:
            suggestion = "sudo apt install stockfish"
        elif "arch" in families:
            suggestion = "sudo pacman -S stockfish"
        elif release.get("ID") == "fedora":
            suggestion = "sudo dnf install stockfish"
    executable = '"C:\\path\\to\\stockfish.exe"' if system == "Windows" else "/path/to/stockfish"
    return (
        "No engine detected on PATH or beside the application.\n"
        f"OS detection: {label}\n"
        f"Suggested Stockfish installation: {suggestion}\n"
        "After installation, make sure Stockfish is on PATH; restart your shell if needed.\n"
        f"Or pass your engine: chess-analyzer --engine {executable}"
    )


def format_score(score: chess.engine.PovScore) -> str:
    """Evaluation in pawns, from White's perspective."""
    white = score.white()
    mate = white.mate()
    if mate is not None:
        sign = "" if white > chess.engine.Cp(0) else "-"
        return f"{sign}M{abs(mate)}"
    cp = white.score()
    return "?" if cp is None else f"{cp / 100:+.2f}"


def history_to_san(node: Node) -> str:
    moves = []
    while node.parent:
        moves.append(node.move_from_parent)
        node = node.parent
    return node.board.variation_san(reversed(moves)) if moves else "(starting position)"


class EvaluationBar(Widget):
    def render(self) -> Text:
        candidate = next(iter(self.app.current.candidates), None)
        score = candidate.score if candidate else "0.00"
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
        board = app.current.board
        selected = app.selected_move()
        last = app.current.move_from_parent
        files = list(range(7, -1, -1) if app.flipped else range(8))
        ranks = range(8) if app.flipped else range(7, -1, -1)
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
    TITLE = "Stockfish Analysis"
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
    #position-info, #engine-title { text-style: bold; }
    #board-area, #board {
        width: 1fr; height: 1fr; min-height: 9; content-align: center middle;
    }
    #evaluation-bar { width: 2; height: 1fr; margin: 1 0; }
    #fen, #status { color: #8b949e; }
    #fen { max-height: 3; }
    .narrow #main { layout: vertical; }
    .narrow #board-side { width: 1fr; height: 14; }
    .narrow #analysis-side { width: 1fr; height: 1fr; }
    #engine-title, #return-game, #candidates { margin-bottom: 1; }
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
        ("q", "quit", "Quit"),
    ]

    def __init__(self, board: chess.Board, engine: chess.engine.UciProtocol,
                 think_time: float, multipv: int, ascii_pieces: bool = False,
                 moves: list[chess.Move] | None = None):
        super().__init__()
        self.engine = engine
        self.think_time = think_time
        self.multipv = multipv
        self.ascii_pieces = ascii_pieces
        self.has_pgn = moves is not None
        self.root = Node(board.copy(), is_mainline=self.has_pgn)
        self.current = self.root
        self.return_position: Node | None = None
        for move in moves or []:
            child = self.current.child(move)
            child.is_mainline = True
            self.current.mainline_next = child
            self.current = child
        self.flipped = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            with Vertical(id="board-side"):
                yield Static(id="position-info")
                with Horizontal(id="board-area"):
                    yield ChessBoard(id="board")
                    yield EvaluationBar(id="evaluation-bar")
                yield Static(id="fen")
            with VerticalScroll(id="analysis-side"):
                for name in ("engine-title", "return-game", "candidates", "pv", "history", "status"):
                    yield Static(id=name)
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_ui()
        self.analyze_node(self.current)

    def on_resize(self, event: Resize) -> None:
        self.screen.set_class(event.size.width < 64, "narrow")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:
        return action != "return_to_game" or self.return_position is not None

    def refresh_ui(self) -> None:
        self.refresh_board()
        self.refresh_analysis_panel()
        board = self.current.board
        info = Text("White to move" if board.turn else "Black to move", style="bold")
        if board.is_check():
            info.append("   CHECKMATE" if board.is_checkmate() else "   CHECK", style="bold red")
        if self.current.is_mainline:
            info.append("   Original game", style="bold #e3b341")
        elif self.return_position:
            branch = self.return_position.board
            turn = "." if branch.turn else "..."
            info.append(f"   Exploring from {branch.fullmove_number}{turn} · Esc: game",
                        style="bold #58a6ff")
        self.query_one("#position-info", Static).update(info)
        self.query_one("#fen", Static).update(Text(f"FEN  {board.fen()}", style="dim"))

    def move_choices(self, node: Node) -> list[chess.Move | None]:
        original = node.mainline_next.move_from_parent if node.mainline_next else None
        # A non-playable end row prevents jumping from the PGN into an engine line.
        moves = [original] if node.is_mainline else []
        return moves + [c.move for c in node.candidates if c.move != original]

    def selected_move(self) -> chess.Move | None:
        moves = self.move_choices(self.current)
        if not moves:
            return None
        self.current.selected %= len(moves)
        return moves[self.current.selected]

    def refresh_board(self) -> None:
        self.query_one("#board", ChessBoard).refresh()
        self.query_one("#evaluation-bar", EvaluationBar).refresh()

    def refresh_analysis_panel(self) -> None:
        node = self.current
        board = node.board
        candidates = {c.move: c for c in node.candidates}
        self.query_one("#engine-title", Static).update(
            Text(f"Stockfish   {self.think_time:g}s / {self.multipv} lines", style="bold")
        )
        return_link = self.query_one("#return-game", Static)
        return_link.display = self.return_position is not None
        return_link.update(Text("← Back to original game [Esc]", style=Style(
            color="#e3b341", meta={"@click": "app.return_to_game"},
        )))
        selected_move = self.selected_move()
        lines = Text("Next move · ↑/↓ choose\n", style="bold")
        for index, move in enumerate(self.move_choices(node)):
            original = node.is_mainline and index == 0
            candidate = candidates.get(move)
            san = board.san(move) if move else "End of original game"
            label = "Original" if original else "Stockfish"
            row = f"{'▶' if index == node.selected else ' '} {label:<9} {san}"
            if candidate:
                row += f"  {candidate.score}"
            lines.append(row + "\n", style=Style(
                color="#e3b341" if original else "#58a6ff", reverse=index == node.selected,
                meta={"@click": f"app.follow_choice({index})"},
            ))
        lines.append("→ / Enter follows selection\n", style="dim")
        if board.is_game_over():
            lines.append(f"Game over: {board.result()}\n", style="dim")
        elif not node.candidates:
            lines.append("No engine lines. Press r to retry." if node.analyzed
                         else "Stockfish is thinking…", style="dim")
        self.query_one("#candidates", Static).update(lines)
        candidate = candidates.get(selected_move)
        pv = Text()
        if selected_move is None and not board.is_game_over():
            pv.append("↑/↓ choose a Stockfish move to keep exploring.", style="dim")
        elif candidate:
            pv.append("Selected continuation\n\n", style="bold")
            pv.append(candidate.pv)
        elif node.mainline_next:
            pv.append("Continue the original game with → or Enter.", style="dim")
        self.query_one("#pv", Static).update(pv)

        history = Text()
        if self.has_pgn:
            history.append("Original game · click a move\n", style="bold #e3b341")
            anchor = node if node.is_mainline else self.return_position
            history.append("Start", style=Style(
                color="#e3b341", reverse=anchor is self.root,
                meta={"@click": "app.game_position(0)"},
            ))
            cursor = self.root
            index = 0
            while cursor.mainline_next:
                parent = cursor
                cursor = cursor.mainline_next
                index += 1
                prefix = f"{parent.board.fullmove_number}. " if parent.board.turn else ""
                if index == 1 and not parent.board.turn:
                    prefix = f"{parent.board.fullmove_number}... "
                history.append("  " + prefix + parent.board.san(cursor.move_from_parent), style=Style(
                    color="#e3b341", reverse=cursor is anchor,
                    meta={"@click": f"app.game_position({index})"},
                ))
            if not node.is_mainline:
                history.append("\n\nExplored line\n", style="bold #58a6ff")
                history.append(history_to_san(node))
        else:
            history.append("Current line\n\n", style="bold")
            history.append(history_to_san(node))
        self.query_one("#history", Static).update(history)

    def set_status(self, message: str, style: str = "dim") -> None:
        self.query_one("#status", Static).update(Text(message, style=style))

    @work(exclusive=True, group="stockfish")
    async def analyze_node(self, node: Node) -> None:
        if node.analyzed or node.board.is_game_over():
            return
        self.set_status("Stockfish is thinking…", "yellow")
        try:
            result = await self.engine.analyse(
                node.board.copy(), chess.engine.Limit(time=self.think_time), multipv=self.multipv,
            )
        except chess.engine.EngineError as exc:
            if node is self.current:
                self.set_status(f"Engine error: {exc} · r to retry", "bold red")
            return
        previous = self.move_choices(node)
        selected = previous[node.selected] if node.selected < len(previous) else None
        node.candidates = [
            Candidate(info["pv"][0], format_score(info["score"]),
                      node.board.variation_san(info["pv"]))
            for info in result if info.get("pv")
        ]
        node.analyzed = True
        choices = self.move_choices(node)
        node.selected = choices.index(selected) if selected in choices else 0
        if node is self.current:
            self.set_status("Analysis ready.")
            self.refresh_ui()

    def action_select_move(self, direction: int) -> None:
        moves = self.move_choices(self.current)
        if moves:
            self.current.selected = (self.current.selected + direction) % len(moves)
            self.refresh_board()
            self.refresh_analysis_panel()

    def action_next_position(self) -> None:
        move = self.selected_move()
        if move is not None:
            if self.current.is_mainline:
                original = self.current.mainline_next
                self.return_position = (
                    None if original and original.move_from_parent == move else self.current
                )
            self.show_position(self.current.child(move))

    def action_follow_choice(self, index: int) -> None:
        self.current.selected = index
        self.action_next_position()

    def action_game_position(self, index: int) -> None:
        node = self.root
        for _ in range(index):
            if node.mainline_next is None:
                break
            node = node.mainline_next
        self.return_position = None
        node.selected = 0
        self.show_position(node)

    def show_position(self, node: Node) -> None:
        self.workers.cancel_group(self, "stockfish")
        self.current = node
        self.refresh_bindings()
        self.set_status("Analysis ready." if node.analyzed else "")
        self.refresh_ui()
        self.query_one("#candidates").scroll_visible(animate=False)
        self.analyze_node(node)

    def action_return_to_game(self) -> None:
        if self.return_position:
            node = self.return_position
            self.return_position = None
            node.selected = 0
            self.show_position(node)

    def action_previous_position(self) -> None:
        node = self.current.parent
        if node:
            if node.is_mainline:
                self.return_position = None
            self.show_position(node)

    def action_flip_board(self) -> None:
        self.flipped = not self.flipped
        self.refresh_board()

    def action_reanalyze(self) -> None:
        self.current.analyzed = False
        self.analyze_node(self.current)


async def run_app(args, board: chess.Board, engine_path: str, moves: list[chess.Move]) -> None:
    transport, engine = await chess.engine.popen_uci(engine_path)
    try:
        await engine.configure({"Threads": args.threads, "Hash": args.hash})
        app = ChessAnalysisApp(board, engine, args.time, args.lines, args.ascii,
                               moves=moves if args.pgn else None)
        await app.run_async()
    finally:
        try:
            await asyncio.wait_for(engine.quit(), timeout=3)
        finally:
            transport.close()


def load_pgn(path: str) -> tuple[chess.Board, list[chess.Move]]:
    try:
        with open(path, encoding="utf-8") as pgn_file:
            game = chess.pgn.read_game(pgn_file)
    except OSError as exc:
        raise SystemExit(f"Could not read PGN: {exc}") from exc
    if game is None:
        raise SystemExit("The PGN file does not contain a game.")
    if game.errors:
        raise SystemExit(f"Could not parse PGN: {game.errors[0]}")
    return game.board(), list(game.mainline_moves())


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="chess-analyzer", description="Interactive Stockfish terminal analyzer.",
    )
    parser.add_argument("fen", nargs="?", help="FEN position (mutually exclusive with --pgn)")
    parser.add_argument("--pgn", help="PGN file to analyze from its final position")
    parser.add_argument("-t", "--time", type=float, default=1.0, help="Thinking time per position")
    parser.add_argument("-n", "--lines", type=int, default=5, help="Number of engine continuations")
    parser.add_argument("--threads", type=int, default=2, help="Stockfish threads")
    parser.add_argument("--hash", type=int, default=256, help="Stockfish hash size in MB")
    parser.add_argument("--engine", help="Path to Stockfish executable")
    parser.add_argument("--ascii", action="store_true", help="Use letters instead of chess glyphs")
    args = parser.parse_args()
    if not math.isfinite(args.time) or args.time <= 0:
        parser.error("--time must be a positive, finite number")
    if min(args.lines, args.threads, args.hash) < 1:
        parser.error("--lines, --threads and --hash must be positive")
    if args.fen and args.pgn:
        parser.error("provide either a FEN or --pgn, not both")
    moves = []
    if args.pgn:
        board, moves = load_pgn(args.pgn)
    else:
        try:
            board = chess.Board(args.fen or chess.STARTING_FEN)
        except ValueError as exc:
            raise SystemExit(f"Invalid FEN: {exc}") from exc
    if not board.is_valid():
        raise SystemExit("The starting position is invalid.")
    engine_path = args.engine or find_stockfish()
    if not engine_path:
        raise SystemExit(missing_engine_message())
    try:
        asyncio.run(run_app(args, board, engine_path, moves))
    except (OSError, chess.engine.EngineError, asyncio.TimeoutError) as exc:
        raise SystemExit(f"Stockfish error: {exc}") from exc


if __name__ == "__main__":
    main()
