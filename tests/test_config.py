import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chess_analyzer.config import (Account, EngineSettings, config_path, load_account,
                                   load_engine_settings, save_account)


class AccountConfigTests(unittest.TestCase):
    def test_account_round_trip_preserves_engine_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("chess_analyzer.config.user_config_path", return_value=root) as location:
                self.assertEqual(config_path(), root / "config.json")
                location.assert_called_with("chess-analyzer", appauthor=False)
                self.assertIsNone(load_account())
                save_account(Account("chess.com", " Alice "))
                self.assertEqual(load_account(), Account("chess.com", "Alice"))
                save_account(Account("lichess", "Bob-2"))
                self.assertEqual(load_account(), Account("lichess", "Bob-2"))
                self.assertEqual(json.loads((root / "config.json").read_text()),
                                 {"provider": "lichess", "username": "Bob-2"})
                path = root / "config.json"
                data = json.loads(path.read_text())
                data["engine"] = {"time": 5, "lines": 3, "threads": 4, "hash": 512}
                path.write_text(json.dumps(data))
                save_account(Account("chess.com", "Alice"))
                self.assertEqual(load_account(), Account("chess.com", "Alice"))
                self.assertEqual(load_engine_settings(), EngineSettings(5.0, 3, 4, 512))
                self.assertEqual(list(root.iterdir()), [path])

    def test_missing_and_malformed_config_are_distinct_and_never_rewritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            self.assertIsNone(load_account(path))
            invalid = [b"{broken", b"\xff", b"null", b"[]",
                       json.dumps({"provider": "other", "username": "Alice"}).encode(),
                       json.dumps({"provider": [], "username": "Alice"}).encode(),
                       json.dumps({"provider": "lichess", "username": 5}).encode(),
                       json.dumps({"provider": "lichess", "username": "../Alice"}).encode()]
            for content in invalid:
                with self.subTest(content=content):
                    path.write_bytes(content)
                    with self.assertRaisesRegex(ValueError, "Invalid account configuration"):
                        load_account(path)
                    self.assertEqual(path.read_bytes(), content)

    def test_failed_atomic_save_keeps_previous_account_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "config.json"
            save_account(Account("chess.com", "Alice"), path)
            with (patch("chess_analyzer.session.os.replace", side_effect=OSError("disk failure")),
                  self.assertRaisesRegex(OSError, "disk failure")):
                save_account(Account("lichess", "Bob"), path)
            self.assertEqual(load_account(path), Account("chess.com", "Alice"))
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_engine_settings_defaults_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            self.assertEqual(load_engine_settings(path), EngineSettings())
            path.write_text(json.dumps({"engine": {"time": 5, "lines": 3}}))
            self.assertEqual(load_engine_settings(path), EngineSettings(5.0, 3, 2, 256))
            for value in (0, -1, True, "5", float("inf")):
                path.write_text(json.dumps({"engine": {"time": value}}))
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "Invalid engine settings"):
                    load_engine_settings(path)
            for value in (0, -1, True, 2.5, "3"):
                path.write_text(json.dumps({"engine": {"lines": value}}))
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "Invalid engine settings"):
                    load_engine_settings(path)

    def test_unreadable_config_is_not_treated_as_missing(self):
        with (patch.object(Path, "read_text", side_effect=PermissionError("denied")),
              self.assertRaisesRegex(PermissionError, "denied")):
            load_account(Path("config.json"))
        with (patch.object(Path, "read_text", side_effect=PermissionError("denied")),
              self.assertRaisesRegex(PermissionError, "denied")):
            load_engine_settings(Path("config.json"))


if __name__ == "__main__":
    unittest.main()
