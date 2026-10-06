"""Piece art adapted from Thomas Mauran's chess-tui (MIT).

Source: https://github.com/thomas-mauran/chess-tui/tree/fc1d4841532bf72f5a25c5cb45abe82ec25e056b/src/pieces
Copyright (c) 2023 Thomas Mauran. See licenses/chess-tui-MIT.txt.
"""

import chess

# (required rows, required columns), ordered from compact to large.
PIECE_ART = {
    (3, 5): {
        chess.PAWN: ("  ▂  ", " ▆█▆ ", " ▔▔▔ "),
        chess.KNIGHT: (" ▄▟▟▖", " ▂█▛▘", "▝▀▀▀▘"),
        chess.BISHOP: (" ▆▖▆ ", " ▐▙▌ ", " ▀▀▀ "),
        chess.ROOK: (" ▅ ▅ ", " ███ ", "▝▀▀▀▘"),
        chess.QUEEN: (" ▆▄▆ ", " ▗█▖ ", " ▀▀▀ "),
        chess.KING: ("▗▂╋▂▖", " ▀█▀ ", " ▀▀▀ "),
    },
    (4, 5): {
        chess.PAWN: ("     ", " ▝█▘ ", " ▟█▙ ", " ▔▔▔ "),
        chess.KNIGHT: ("  ▖▗ ", "▗▇▟█▌", " ▟█▛ ", "▝▀▀▀▘"),
        chess.BISHOP: (" ▄▁▗ ", " ██▟ ", " ▟█▙ ", "▝▀▀▀▘"),
        chess.ROOK: ("▄ ▄ ▄", "█████", " ███ ", "▀▀▀▀▀"),
        chess.QUEEN: ("▂ ▄ ▂", "▜▙█▟▛", " ▜█▛ ", "▝▀▀▀▘"),
        chess.KING: (" ▂╋▂ ", "▜███▛", " ▜█▛ ", "▝▀▀▀▘"),
    },
    (5, 7): {
        chess.PAWN: ("     ", " ▄▇▄ ", " ▜█▛ ", "▄███▄", "▔▔▔▔▔"),
        chess.KNIGHT: ("  ▅ ▅", " ▟▛███▖", "▝▀▜███▊", " ▗███▛ ", " ▀▀▀▀▀ "),
        chess.BISHOP: ("▗▅  ▖", "██▍ █", "███▍█", "▝███▘", "▀▀▀▀▀"),
        chess.ROOK: ("▗▄ ▃ ▄▖", "▐█▄█▄█▌", "▝▜███▛▘", " ▟███▙ ", "▝▀▀▀▀▀▘"),
        chess.QUEEN: ("▗  ▂  ▖", "▐▙▟█▙▟▌", " ▜███▛ ", " ▗███▖ ", "▝▀▀▀▀▀▘"),
        # Remove one column of outer padding to fit the shared seven-column size.
        chess.KING: (" ▂▃╋▃▂ ", "▐█████▋", " ▜███▛ ", "  ▟█▙  ", " ▀▀▀▀▀ "),
    },
}
