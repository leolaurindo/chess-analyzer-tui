"""Portable FEN/PGN files, separate from saved analysis snapshots."""
import os
import tempfile
from pathlib import Path

from platformdirs import user_data_path

from .game import Analysis


def export_directory() -> Path:
    return user_data_path("chess-analyzer", appauthor=False) / "exports"


def export_analysis(analysis: Analysis, path: Path, format: str, *, overwrite: bool = False) -> Path:
    if format not in {"fen", "pgn"}:
        raise ValueError("Choose FEN or PGN.")
    text = analysis.current.board.fen() if format == "fen" else analysis.to_pgn()
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=path.parent, prefix=".export-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text + "\n")
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path
