"""Transient board/notation entry state, never part of the saved analysis."""
from dataclasses import dataclass, field

import chess
from textual.binding import Binding
from textual.widgets import Input


class MoveNotationInput(Input):
    # Input consumes printable keys before ancestor bindings, including Space.
    BINDINGS = [Binding("space", "app.select_square", "Select square", show=False, priority=True)]


@dataclass
class MoveEntry:
    persistent: bool
    cursor: chess.Square
    source: chess.Square | None = None
    promotions: list[chess.Move] = field(default_factory=list)
    error: str = ""
