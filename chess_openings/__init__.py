"""Offline labels from lichess-org/chess-openings (CC0; see README credits)."""
import csv
from functools import cache
from importlib.resources import files

import chess


@cache
def _openings() -> dict[str, str]:
    with files(__package__).joinpath("openings.tsv").open(encoding="utf-8") as stream:
        return {row["epd"]: f"{row['eco']} · {row['name']}"
                for row in csv.DictReader(stream, delimiter="\t")}


def opening_label(board: chess.Board) -> str | None:
    """Use the latest named position on this line, including transpositions."""
    position = board.copy()
    openings = _openings()
    while True:
        label = openings.get(position.epd())
        if label is not None:
            return label
        if not position.move_stack:
            return None
        position.pop()
