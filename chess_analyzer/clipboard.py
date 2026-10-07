"""Read from the active desktop clipboard before WSL's host clipboard."""
import os
import platform
import shutil
import subprocess

import pyperclip


def paste_text() -> str:
    command = None
    if platform.system() == "Linux":
        if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
            command = ["wl-paste", "--no-newline", "--type", "text"]
        elif os.environ.get("DISPLAY"):
            if shutil.which("xclip"):
                command = ["xclip", "-selection", "clipboard", "-out"]
            elif shutil.which("xsel"):
                command = ["xsel", "--clipboard", "--output"]
    if command is None:
        return pyperclip.paste()
    try:
        return subprocess.run(command, text=True, capture_output=True, check=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise pyperclip.PyperclipException(f"{command[0]} failed: {exc}") from exc
