import unittest
from unittest.mock import patch

from chess_tui import main


class CliTests(unittest.TestCase):
    def test_missing_engine_explains_installation_for_the_detected_os(self):
        cases = [
            ("Windows", {}, "Windows", "winget install --id Stockfish.Stockfish --exact"),
            ("Darwin", {}, "macOS", "brew install stockfish"),
            ("Linux", {"ID": "ubuntu"}, "Linux", "sudo apt install stockfish"),
            ("Linux", {"ID": "linuxmint", "ID_LIKE": "ubuntu debian", "PRETTY_NAME": "Linux Mint"},
             "Linux (Linux Mint)", "sudo apt install stockfish"),
            ("Linux", {"ID": "manjaro", "ID_LIKE": "arch"}, "Linux", "sudo pacman -S stockfish"),
            ("Linux", {"ID": "fedora"}, "Linux", "sudo dnf install stockfish"),
            ("Linux", {"ID": "unknown"}, "Linux", "https://stockfishchess.org/download/"),
            ("Linux", OSError("No os-release file"), "Linux", "https://stockfishchess.org/download/"),
            ("FreeBSD", {}, "FreeBSD", "https://stockfishchess.org/download/"),
        ]
        for system, release, label, suggestion in cases:
            with self.subTest(system=system, release=release):
                with (
                    patch("sys.argv", ["chess-analyzer"]),
                    patch("chess_tui.find_stockfish", return_value=None),
                    patch("platform.system", return_value=system),
                    patch("platform.freedesktop_os_release", side_effect=[release]),
                    self.assertRaises(SystemExit) as error,
                ):
                    main()
                message = str(error.exception)
                self.assertIn("No engine detected", message)
                self.assertIn(f"OS detection: {label}", message)
                self.assertIn(suggestion, message)
                self.assertIn("make sure Stockfish is on PATH", message)
                self.assertIn("chess-analyzer --engine", message)


if __name__ == "__main__":
    unittest.main()
