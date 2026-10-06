"""Bounded HTTPS transport and documented public chess-provider APIs."""
from __future__ import annotations

import ipaddress
import json
import re
import socket
from threading import Lock
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_DOWNLOAD_BYTES = 4 * 1024 * 1024
URL_TIMEOUT = 10
_REQUEST_LOCK = Lock()


def _validate_url(url: str) -> None:
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid URL port.") from exc
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or port not in (None, 443)):
        raise ValueError("Only public HTTPS URLs are supported.")
    try:
        addresses = {ipaddress.ip_address(result[4][0])
                     for result in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)}
    except (OSError, ValueError) as exc:
        raise ValueError(f"Could not resolve URL host: {parsed.hostname}") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("URLs must resolve only to public IP addresses.")


class _SafeRedirectHandler(HTTPRedirectHandler):
    def __init__(self):
        super().__init__()
        self.redirects = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.redirects += 1
        if self.redirects > 3:
            raise ValueError("Too many redirects while fetching URL.")
        _validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_text(url: str, *, accept: str = "text/plain, application/x-chess-pgn, application/json",
               max_bytes: int = MAX_DOWNLOAD_BYTES) -> str:
    _validate_url(url)
    request = Request(url, headers={
        "User-Agent": "chess-analyzer-tui (+https://github.com/leolaurindo/chess-analyzer-tui)",
        "Accept": accept,
    })
    try:
        with _REQUEST_LOCK, build_opener(_SafeRedirectHandler()).open(request, timeout=URL_TIMEOUT) as response:
            if int(response.headers.get("Content-Length", 0)) > max_bytes:
                raise ValueError("Remote file exceeds the download size limit.")
            data = response.read(max_bytes + 1)
    except HTTPError as exc:
        if exc.code == 429:
            raise ValueError("Rate limited. Wait at least one minute before retrying.") from exc
        raise ValueError(f"Could not fetch URL: {exc}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ValueError(f"Could not fetch URL: {exc}") from exc
    if len(data) > max_bytes:
        raise ValueError("Remote file exceeds the download size limit.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("URL response is not UTF-8 text.") from exc


@dataclass(frozen=True)
class OnlineGame:
    id: str
    white: str
    black: str
    date: str
    result: str
    speed: str
    pgn: str | None = None

    @property
    def label(self) -> str:
        return f"{self.date} · {self.white} vs {self.black} · {self.result} · {self.speed}"


@dataclass(frozen=True)
class GamePage:
    games: list[OnlineGame]
    until: int | None


def validate_username(username: str) -> str:
    username = username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,50}", username):
        raise ValueError("Enter a username using letters, numbers, underscores or hyphens.")
    return username


def chesscom_months(username: str) -> list[str]:
    username = validate_username(username)
    data = json.loads(fetch_text(f"https://api.chess.com/pub/player/{quote(username)}/games/archives"))
    if not isinstance(data, dict) or not isinstance(data.get("archives"), list):
        raise ValueError("Chess.com returned an invalid archive list.")
    months = []
    for archive in data["archives"]:
        if not isinstance(archive, str):
            raise ValueError("Invalid Chess.com archive URL.")
        match = re.fullmatch(
            rf"https://api\.chess\.com/pub/player/{re.escape(username)}/games/(\d{{4}})/(0[1-9]|1[0-2])",
            archive, re.IGNORECASE,
        )
        if not match:
            raise ValueError("Invalid Chess.com archive URL.")
        months.append(f"{match[1]}-{match[2]}")
    return sorted(set(months), reverse=True)


def chesscom_game_id(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"chess.com", "www.chess.com"}:
        return None
    match = re.fullmatch(r"/(?:game/(?:live|daily)|(?:live|daily)/game)/(\d+)/?", parsed.path)
    return match[1] if match else None


def chesscom_games(username: str, month: str) -> list[OnlineGame]:
    username = validate_username(username)
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise ValueError("Use an archive month in YYYY-MM format.")
    url = f"https://api.chess.com/pub/player/{quote(username)}/games/{month.replace('-', '/')}"
    data = json.loads(fetch_text(url, max_bytes=16 * 1024 * 1024))
    if not isinstance(data, dict) or not isinstance(data.get("games"), list):
        raise ValueError("Chess.com returned an invalid game list.")
    if any(not isinstance(game, dict) for game in data["games"]):
        raise ValueError("Chess.com returned an invalid game record.")
    games = []
    for game in sorted(data["games"], key=lambda game: game.get("end_time", 0), reverse=True):
        if game.get("rules") != "chess":
            continue
        pgn = game.get("pgn", "")
        if not isinstance(pgn, str):
            raise ValueError("Chess.com returned an invalid PGN.")
        result = re.search(r'\[Result "(1-0|0-1|1/2-1/2)"\]', pgn)
        game_id = chesscom_game_id(game.get("url", ""))
        if not result or not game_id:
            continue
        date = datetime.fromtimestamp(game["end_time"], timezone.utc).strftime("%Y-%m-%d %H:%M")
        games.append(OnlineGame(game_id, game["white"]["username"], game["black"]["username"],
                                date, result[1], game.get("time_class", ""), pgn))
    return games


def lichess_games(username: str, *, until: int | None = None, limit: int = 50) -> GamePage:
    username = validate_username(username)
    if not 1 <= limit <= 50:
        raise ValueError("Lichess pages must contain between 1 and 50 games.")
    params = {"max": limit, "ongoing": "false", "finished": "true", "moves": "false",
              "perfType": "ultraBullet,bullet,blitz,rapid,classical,correspondence"}
    if until is not None:
        params["until"] = until
    url = f"https://lichess.org/api/games/user/{quote(username)}?{urlencode(params)}"
    text = fetch_text(url, accept="application/x-ndjson")
    records = [json.loads(line) for line in text.splitlines() if line.strip()]
    if any(not isinstance(game, dict) for game in records):
        raise ValueError("Lichess returned an invalid game record.")
    games = []
    for game in records:
        if (game.get("variant") != "standard"
                or game.get("status") not in {"mate", "resign", "stalemate", "timeout", "draw",
                                           "outoftime", "cheat", "variantEnd", "unknownFinish"}):
            continue
        if not re.fullmatch(r"[A-Za-z0-9]{8}", game.get("id", "")):
            raise ValueError("Lichess returned an invalid game ID.")
        players = game["players"]
        names = [players[color].get("user", {}).get("name", "AI") for color in ("white", "black")]
        result = {"white": "1-0", "black": "0-1"}.get(game.get("winner"), "1/2-1/2")
        date = datetime.fromtimestamp(game["createdAt"] / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")
        games.append(OnlineGame(game["id"], *names, date, result, game.get("speed", "")))
    cursor = min(game["createdAt"] for game in records) - 1 if len(records) == limit else None
    return GamePage(games, cursor)


def lichess_pgn(game_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9]{8}", game_id):
        raise ValueError("Invalid Lichess game ID.")
    return fetch_text(f"https://lichess.org/game/export/{game_id}")


def load_url(url: str, *, chesscom_user: str | None = None,
             chesscom_month: str | None = None) -> str:
    _validate_url(url)
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.strip("/")
    if host in {"chess.com", "www.chess.com"}:
        game_id = chesscom_game_id(url)
        if game_id:
            if not chesscom_user or not chesscom_month:
                raise ValueError("Chess.com game URLs require --chesscom-user NAME and "
                                 "--chesscom-month YYYY-MM. Alternatively, use --browse.")
            for game in chesscom_games(chesscom_user, chesscom_month):
                if game.id == game_id:
                    return game.pgn
            raise ValueError("Game not found in that user's archive month. Check the username and month.")
    if host in {"lichess.org", "www.lichess.org"}:
        match = re.fullmatch(r"study/([A-Za-z0-9]{8})(?:/([A-Za-z0-9]{8}))?", path)
        if match:
            chapter = f"/{match[2]}" if match[2] else ""
            return fetch_text(f"https://lichess.org/study/{match[1]}{chapter}.pgn")
        match = re.fullmatch(r"(?:game/)?([A-Za-z0-9]{8})", path)
        if match:
            return lichess_pgn(match[1])
    return fetch_text(url)


