import os
import subprocess
import unittest
from unittest.mock import patch

import pyperclip

from chess_analyzer.clipboard import paste_text


class ClipboardTests(unittest.TestCase):
    def test_wayland_input_uses_active_desktop_instead_of_wsl_host(self):
        with (patch("chess_analyzer.clipboard.platform.system", return_value="Linux"),
              patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}, clear=True),
              patch("chess_analyzer.clipboard.shutil.which", return_value="/usr/bin/wl-paste"),
              patch("chess_analyzer.clipboard.subprocess.run") as run,
              patch("pyperclip.paste") as host_paste):
            run.return_value.stdout = "A FEN position"
            self.assertEqual(paste_text(), "A FEN position")
            self.assertEqual(run.call_args.args[0], ["wl-paste", "--no-newline", "--type", "text"])
            self.assertTrue(run.call_args.kwargs["check"])
            self.assertEqual(run.call_args.kwargs["timeout"], 5)
            host_paste.assert_not_called()

    def test_x11_input_uses_clipboard_selection_and_reports_failures(self):
        with (patch("chess_analyzer.clipboard.platform.system", return_value="Linux"),
              patch.dict(os.environ, {"DISPLAY": ":0"}, clear=True),
              patch("chess_analyzer.clipboard.shutil.which", return_value="/usr/bin/xclip"),
              patch("chess_analyzer.clipboard.subprocess.run") as run):
            run.return_value.stdout = "PGN"
            self.assertEqual(paste_text(), "PGN")
            self.assertEqual(run.call_args.args[0], ["xclip", "-selection", "clipboard", "-out"])
            for error in (subprocess.CalledProcessError(1, "xclip"), subprocess.TimeoutExpired("xclip", 5)):
                with self.subTest(error=error):
                    run.side_effect = error
                    with self.assertRaisesRegex(pyperclip.PyperclipException, "xclip failed"):
                        paste_text()

    def test_non_graphical_and_other_platforms_keep_native_paste(self):
        for platform, env in (("Linux", {}), ("Windows", {"DISPLAY": ":0"}), ("Darwin", {})):
            with (self.subTest(platform=platform),
                  patch("chess_analyzer.clipboard.platform.system", return_value=platform),
                  patch.dict(os.environ, env, clear=True),
                  patch("pyperclip.paste", return_value="native clipboard") as paste):
                self.assertEqual(paste_text(), "native clipboard")
                paste.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
