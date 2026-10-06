"""UI-independent analysis tree and navigation state."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import chess
import chess.engine
import chess.pgn


def winning_chances(score: chess.engine.Score) -> float:
    """Lichess's centipawn conversion; forced mates map to 0 or 100 percent."""
    if score.is_mate():
        return 100.0 if score > chess.engine.Cp(0) else 0.0
    cp = max(-10000, min(10000, score.score()))
    return 100 / (1 + math.exp(-0.00368208 * cp))


def quality_label(loss: float) -> str:
    """Approximate Chess.com bands, measured in percentage points lost."""
    for limit, label in ((2, "Excellent"), (5, "Good"), (10, "Inaccuracy"), (20, "Mistake")):
        if loss < limit:
            return label
    return "Blunder"


@dataclass
class Candidate:
    move: chess.Move
    score: chess.engine.Score  # Always from White's perspective, not the side to move.
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
    imported: bool = False
    comment: str = ""
    starting_comment: str = ""

    def quality(self, move: chess.Move | None) -> str | None:
        if not self.analyzed or not self.candidates:
            return None
        best = self.candidates[0]
        played = next((candidate for candidate in self.candidates if candidate.move == move), None)
        if played is None:
            return None
        if move == best.move:
            return "Best"
        best_score, played_score = best.score, played.score
        if self.board.turn == chess.BLACK:
            best_score, played_score = -best_score, -played_score
        return quality_label(max(0, winning_chances(best_score) - winning_chances(played_score)))

    def child(self, move: chess.Move) -> Node:
        if move not in self.children:
            board = self.board.copy()
            board.push(move)
            self.children[move] = Node(board, parent=self, move_from_parent=move)
        return self.children[move]


@dataclass
class Analysis:
    root: Node
    current: Node
    return_position: Node | None = None
    white_name: str = "White"
    black_name: str = "Black"
    flipped: bool = False

    @property
    def has_pgn(self) -> bool:
        return self.root.is_mainline

    @classmethod
    def from_input(cls, board: chess.Board, game: chess.pgn.Game | None = None,
                   white_name: str = "White", black_name: str = "Black") -> Analysis:
        if not board.is_valid():
            raise ValueError("The starting position is invalid.")
        root = Node(board.copy(), is_mainline=game is not None)
        if game is not None:
            pending = [(root, game)]
            while pending:
                node, source = pending.pop()
                node.imported = True
                node.comment = source.comment
                node.starting_comment = source.starting_comment
                for index, variation in enumerate(source.variations):
                    child = node.child(variation.move)
                    child.is_mainline = node.is_mainline and index == 0
                    if child.is_mainline:
                        node.mainline_next = child
                    pending.append((child, variation))
        current = root
        while current.mainline_next:
            current = current.mainline_next
        return cls(root, current, white_name=white_name, black_name=black_name)


def history_to_san(node: Node) -> str:
    moves = []
    while node.parent:
        moves.append(node.move_from_parent)
        node = node.parent
    return node.board.variation_san(reversed(moves)) if moves else "(starting position)"
