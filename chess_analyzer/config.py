"""User defaults and account configuration."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_path

from .online import validate_username
from .session import write_json


@dataclass(frozen=True)
class Account:
    provider: str
    username: str

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or self.provider not in {"chess.com", "lichess"}:
            raise ValueError("Choose chess.com or lichess.")
        if not isinstance(self.username, str):
            raise ValueError("The public username must be text.")
        object.__setattr__(self, "username", validate_username(self.username))


@dataclass(frozen=True)
class EngineSettings:
    time: float = 1.0
    lines: int = 5
    threads: int = 2
    hash: int = 256


def config_path() -> Path:
    return user_config_path("chess-analyzer", appauthor=False) / "config.json"


def _read_config(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise ValueError("expected a configuration object")
    return data


def load_account(path: Path | None = None) -> Account | None:
    """Return None only when no account is configured; malformed data raises ValueError."""
    path = path if path is not None else config_path()
    try:
        data = _read_config(path)
        if "provider" not in data and "username" not in data:
            return None
        return Account(data["provider"], data["username"])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Invalid account configuration: {exc}") from exc


def load_engine_settings(path: Path | None = None) -> EngineSettings:
    path = path if path is not None else config_path()
    try:
        data = _read_config(path)
        values = data.get("engine", {})
        if not isinstance(values, dict):
            raise ValueError("engine must be an object")
        defaults = EngineSettings()
        time = values.get("time", defaults.time)
        lines = values.get("lines", defaults.lines)
        threads = values.get("threads", defaults.threads)
        hash_size = values.get("hash", defaults.hash)
        if (isinstance(time, bool) or not isinstance(time, (int, float))
                or not 0 < time < float("inf")):
            raise ValueError("engine.time must be a positive finite number")
        for name, value in (("lines", lines), ("threads", threads), ("hash", hash_size)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"engine.{name} must be a positive integer")
        return EngineSettings(float(time), lines, threads, hash_size)
    except ValueError as exc:
        raise ValueError(f"Invalid engine settings: {exc}") from exc


def save_account(account: Account, path: Path | None = None) -> None:
    path = path if path is not None else config_path()
    data = _read_config(path)
    data.update(provider=account.provider, username=account.username)
    write_json(path, data)
