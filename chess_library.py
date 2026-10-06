"""Named local analyses, separate from the automatic continue snapshot."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path

from chess_game import Analysis
from chess_session import analysis_from_data, analysis_to_data, write_json


def library_path() -> Path:
    return user_data_path("chess-analyzer", appauthor=False) / "analyses"


@dataclass(frozen=True)
class SavedAnalysis:
    title: str
    path: Path
    modified: float


def analysis_path(directory: Path, title: str) -> Path:
    title = title.strip()
    if not title or len(title) > 120 or any(ord(char) < 32 for char in title):
        raise ValueError("Use a name of 1–120 characters without control characters.")
    # A title is data, never a filesystem path.
    return directory / (hashlib.sha256(title.encode("utf-8")).hexdigest() + ".json")


def save_analysis(analysis: Analysis, title: str, directory: Path, *,
                  overwrite: bool = False) -> SavedAnalysis:
    path = analysis_path(directory, title)
    title = title.strip()
    try:
        write_json(path, {"title": title, "analysis": analysis_to_data(analysis)}, overwrite=overwrite)
    except FileExistsError as exc:
        raise FileExistsError("That name already exists. Enable replacement to overwrite it.") from exc
    return SavedAnalysis(title, path, path.stat().st_mtime)


def load_analysis(path: Path) -> Analysis:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("title"), str):
        raise ValueError("Invalid saved analysis metadata.")
    return analysis_from_data(data.get("analysis"))


def list_analyses(directory: Path) -> tuple[list[SavedAnalysis], list[str]]:
    entries, warnings = [], []
    if not directory.exists():
        return entries, warnings
    for path in directory.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(data, dict) or not isinstance(data.get("title"), str)
                    or not isinstance(data.get("analysis"), dict)):
                raise ValueError("invalid metadata")
            entries.append(SavedAnalysis(data["title"], path, path.stat().st_mtime))
        except (OSError, ValueError, UnicodeError) as exc:
            warnings.append(f"{path.name}: {exc}")
    entries.sort(key=lambda entry: entry.modified, reverse=True)
    return entries, warnings
