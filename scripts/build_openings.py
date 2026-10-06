"""Regenerate the bundled CC0 opening index from a pinned Lichess revision."""
import csv
import io
from pathlib import Path
from urllib.request import urlopen

import chess.pgn


REVISION = "65bb03f76c7f077984db01a2f2d0534e4181ddfe"


def main() -> None:
    openings = {}
    for volume in "abcde":
        url = f"https://raw.githubusercontent.com/lichess-org/chess-openings/{REVISION}/{volume}.tsv"
        with urlopen(url, timeout=30) as response:
            source = response.read().decode("utf-8")
        for row in csv.DictReader(io.StringIO(source), delimiter="\t"):
            game = chess.pgn.read_game(io.StringIO(row["pgn"]))
            if game is None or game.errors:
                raise ValueError(f"Invalid opening: {row['name']}")
            # Keep the first entry for positions with multiple names.
            openings.setdefault(game.end().board().epd(), (row["eco"], row["name"]))
    path = Path(__file__).resolve().parents[1] / "chess_openings" / "openings.tsv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(("epd", "eco", "name"))
        writer.writerows((epd, *label) for epd, label in sorted(openings.items()))
    print(f"Wrote {len(openings)} opening positions to {path}")


if __name__ == "__main__":
    main()
