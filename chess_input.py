"""Read and parse chess positions and games from text, files, or the clipboard."""
from __future__ import annotations

import io
import ipaddress
import json
import re
import socket
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import chess
import chess.pgn
import pyperclip


MAX_DOWNLOAD_BYTES = 4 * 1024 * 1024
URL_TIMEOUT = 10


def player_name(value: str | None, fallback: str) -> str:
    name = (value or "").strip()
    return fallback if name in {"", "?"} else name


def parse_input(text: str) -> tuple[chess.Board, list[chess.Move] | None, str, str]:
    text = text.strip()
    try:
        return chess.Board(text), None, "White", "Black"
    except ValueError:
        pass
    game = chess.pgn.read_game(io.StringIO(text))
    if game is None:
        raise SystemExit("Input does not contain a FEN position or PGN game.")
    if game.errors:
        raise SystemExit(f"Could not parse PGN: {game.errors[0]}")
    moves = list(game.mainline_moves())
    if not moves:
        raise SystemExit("Input does not contain a valid FEN or PGN game with moves.")
    return (game.board(), moves,
            player_name(game.headers.get("White"), "White"),
            player_name(game.headers.get("Black"), "Black"))


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


def _fetch_text(url: str) -> str:
    _validate_url(url)
    request = Request(url, headers={
        "User-Agent": "chess-analyzer-tui",
        "Accept": "text/plain, application/x-chess-pgn, application/json",
    })
    try:
        with build_opener(_SafeRedirectHandler()).open(request, timeout=URL_TIMEOUT) as response:
            if int(response.headers.get("Content-Length", 0)) > MAX_DOWNLOAD_BYTES:
                raise ValueError("Remote file exceeds the 4 MiB download limit.")
            data = response.read(MAX_DOWNLOAD_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise ValueError(f"Could not fetch URL: {exc}") from exc
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise ValueError("Remote file exceeds the 4 MiB download limit.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("URL response is not UTF-8 text.") from exc


def _load_chesscom_game(game_id: str) -> str:
    callback = json.loads(_fetch_text(f"https://www.chess.com/callback/live/game/{game_id}"))
    game = callback.get("game", {})
    headers = game.get("pgnHeaders", {})
    date = headers.get("Date", "")
    match = re.fullmatch(r"(\d{4})\.(\d{2})\.\d{2}", date)
    if not match:
        raise ValueError("Chess.com did not provide a game date.")
    usernames = [headers.get(color) for color in ("White", "Black")]
    for username in usernames:
        if not username:
            continue
        url = (f"https://api.chess.com/pub/player/{quote(username, safe='')}/games/"
               f"{match.group(1)}/{match.group(2)}/pgn")
        archive = _fetch_text(url)
        stream = io.StringIO(archive)
        while pgn := chess.pgn.read_game(stream):
            if pgn.headers.get("Link", "").rstrip("/").endswith(f"/{game_id}"):
                exporter = chess.pgn.StringExporter(headers=True, variations=False)
                pgn.accept(exporter)
                return exporter.result()
    raise ValueError("That game was not found in either player's public Chess.com archive.")


def load_url(url: str) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.strip("/")
    if host in {"chess.com", "www.chess.com"}:
        match = re.fullmatch(r"(?:live/game|game/live)/(\d+)", path)
        if match:
            return _load_chesscom_game(match.group(1))
    if host in {"lichess.org", "www.lichess.org"}:
        match = re.fullmatch(r"study/([A-Za-z0-9]{8})(?:/([A-Za-z0-9]{8}))?", path)
        if match:
            chapter = f"/{match.group(2)}" if match.group(2) else ""
            return _fetch_text(f"https://lichess.org/study/{match.group(1)}{chapter}.pgn")
        match = re.fullmatch(r"(?:game/)?([A-Za-z0-9]{8})", path)
        if match:
            return _fetch_text(f"https://lichess.org/game/export/{match.group(1)}")
    return _fetch_text(url)


def load_input(text: str | None = None, *, file: str | None = None,
               clipboard: bool = False) -> tuple[chess.Board, list[chess.Move] | None, str, str]:
    text = text if text is not None else chess.STARTING_FEN
    if file is not None:
        try:
            text = Path(file).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise SystemExit(f"Could not read file: {exc}") from exc
    elif clipboard:
        try:
            text = pyperclip.paste()
        except (pyperclip.PyperclipException, OSError) as exc:
            raise SystemExit(f"Could not read clipboard: {exc}") from exc
    if text.strip().lower().startswith(("https://", "http://")):
        try:
            text = load_url(text.strip())
        except (ValueError, json.JSONDecodeError) as exc:
            raise SystemExit(f"Could not load URL: {exc}") from exc
    return parse_input(text)
