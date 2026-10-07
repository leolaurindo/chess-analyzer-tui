"""One default public account, stored separately from analysis state."""
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


def config_path() -> Path:
    return user_config_path("chess-analyzer", appauthor=False) / "config.json"


def load_account(path: Path | None = None) -> Account | None:
    """Return None only for missing configuration; malformed files raise ValueError."""
    path = path if path is not None else config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("expected an account object")
        return Account(data["provider"], data["username"])
    except FileNotFoundError:
        return None
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Invalid account configuration: {exc}") from exc


def save_account(account: Account, path: Path | None = None) -> None:
    path = path if path is not None else config_path()
    write_json(path, {"provider": account.provider, "username": account.username})
