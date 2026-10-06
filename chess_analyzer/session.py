"""One local session snapshot; engine evaluations are deliberately not stored."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import chess
from platformdirs import user_state_path

from .game import Analysis, Node


def session_path() -> Path:
    return user_state_path("chess-analyzer", appauthor=False) / "session.json"


def analysis_to_data(analysis: Analysis) -> dict:
    nodes = [analysis.root]
    records = []
    for parent_index, parent in enumerate(nodes):
        for child in parent.children.values():
            nodes.append(child)
            records.append([parent_index, child.move_from_parent.uci(), child.is_mainline,
                            child.imported, child.comment, child.starting_comment])
    indices = {id(node): index for index, node in enumerate(nodes)}
    return {
        "version": 2,
        "comment": analysis.root.comment,
        "fen": analysis.root.board.fen(),
        "has_pgn": analysis.has_pgn,
        "nodes": records,
        "current": indices[id(analysis.current)],
        "return": indices[id(analysis.return_position)] if analysis.return_position else None,
        "white": analysis.white_name,
        "black": analysis.black_name,
        "flipped": analysis.flipped,
    }


def write_json(path: Path, data: dict, *, overwrite: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".session-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
        # Close the file before replacing it: required on Windows.
        if overwrite:
            os.replace(temporary, path)
        else:
            # Atomically refuse an existing name, including concurrent saves.
            os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_session(analysis: Analysis, path: Path) -> None:
    write_json(path, analysis_to_data(analysis))


def analysis_from_data(data: dict) -> Analysis:
    try:
        if data["version"] != 2:
            raise ValueError("unsupported session version")
        if any(type(data[key]) is not bool for key in ("has_pgn", "flipped")):
            raise ValueError("invalid session flags")
        if any(not isinstance(data[key], str) for key in ("fen", "white", "black", "comment")):
            raise ValueError("invalid session text")
        board = chess.Board(data["fen"])
        if not board.is_valid():
            raise ValueError("invalid starting position")
        root = Node(board, is_mainline=data["has_pgn"], imported=data["has_pgn"],
                    comment=data["comment"])
        nodes = [root]
        if not isinstance(data["nodes"], list):
            raise ValueError("invalid game tree")
        for parent_index, uci, mainline, imported, comment, starting_comment in data["nodes"]:
            if type(parent_index) is not int or not 0 <= parent_index < len(nodes):
                raise ValueError("invalid parent position")
            if (not isinstance(uci, str) or type(mainline) is not bool
                    or type(imported) is not bool
                    or not isinstance(comment, str) or not isinstance(starting_comment, str)):
                raise ValueError("invalid move record")
            parent = nodes[parent_index]
            move = chess.Move.from_uci(uci)
            if move not in parent.board.legal_moves or move in parent.children:
                raise ValueError("invalid or duplicate move")
            child = parent.child(move)
            child.is_mainline = mainline
            child.imported = imported
            child.comment = comment
            child.starting_comment = starting_comment
            if mainline:
                if not parent.is_mainline or parent.mainline_next is not None:
                    raise ValueError("invalid original game")
                parent.mainline_next = child
            nodes.append(child)
        for key in ("current", "return"):
            index = data[key]
            if key == "return" and index is None:
                continue
            if type(index) is not int or not 0 <= index < len(nodes):
                raise ValueError("invalid saved position")
        current = nodes[data["current"]]
        anchor = nodes[data["return"]] if data["return"] is not None else None
        if anchor is not None and (not anchor.is_mainline or current.is_mainline):
            raise ValueError("invalid return position")
        if root.is_mainline and not current.is_mainline:
            ancestor = current.parent
            while ancestor is not None and not ancestor.is_mainline:
                ancestor = ancestor.parent
            if anchor is not ancestor:
                raise ValueError("missing or invalid original-game anchor")
        return Analysis(root, current, anchor, data["white"], data["black"], data["flipped"])
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise ValueError(f"Invalid analysis snapshot: {exc}") from exc


def load_session(path: Path) -> Analysis:
    return analysis_from_data(json.loads(path.read_text(encoding="utf-8")))
