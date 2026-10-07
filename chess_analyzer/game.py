"""UI-independent analysis tree and navigation state."""
from __future__ import annotations

from dataclasses import dataclass, field

import chess
import chess.pgn

from .input import player_name


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
    imported: bool = False
    comment: str = ""
    starting_comment: str = ""

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
    headers: dict[str, str] = field(default_factory=dict)

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
        return cls(root, current, white_name=white_name, black_name=black_name,
                   headers=dict(game.headers) if game is not None else {})

    def to_pgn(self) -> str:
        game = chess.pgn.Game()
        game.setup(self.root.board)
        game.headers.update(self.headers)
        for color, name in (("White", self.white_name), ("Black", self.black_name)):
            if color not in self.headers or name != player_name(self.headers[color], color):
                game.headers[color] = name
        game.comment = self.root.comment
        pending = [(self.root, game)]
        while pending:
            node, target = pending.pop()
            children = sorted(node.children.values(), key=lambda child: child is not node.mainline_next)
            for child in children:
                variation = target.add_variation(child.move_from_parent, comment=child.comment,
                                                 starting_comment=child.starting_comment)
                pending.append((child, variation))
        return game.accept(chess.pgn.StringExporter(headers=True, variations=True, comments=True))


def history_to_san(node: Node) -> str:
    moves = []
    while node.parent:
        moves.append(node.move_from_parent)
        node = node.parent
    return node.board.variation_san(reversed(moves)) if moves else "(starting position)"
