"""Local analysis dialogs; persistence stays in library/session."""
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, OptionList, Static, TextArea

from .game import Analysis
from .library import SavedAnalysis, list_analyses, load_analysis, save_analysis


class AnalysisDialog(ModalScreen):
    DEFAULT_CSS = """
    AnalysisDialog { align: center middle; background: $background 70%; }
    AnalysisDialog > Vertical {
        width: 85%; max-width: 90; height: auto; max-height: 90%;
        border: round $accent; padding: 1 2; background: $surface;
    }
    AnalysisDialog Label { margin-bottom: 1; }
    AnalysisDialog Horizontal { height: auto; margin-top: 1; }
    AnalysisDialog Button { min-width: 0; width: 1fr; margin-right: 1; }
    AnalysisDialog #error { color: $error; height: auto; }
    AnalysisDialog OptionList { height: 1fr; min-height: 4; max-height: 18; }
    AnalysisDialog TextArea { height: 10; }
    """
    BINDINGS = [("escape", "cancel", "Cancel")]

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)


class CommentEditor(AnalysisDialog):
    BINDINGS = [("ctrl+s", "save", "Save")]

    def __init__(self, comment: str):
        super().__init__()
        self.comment = comment

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Comment on this position · Ctrl+S saves")
            yield TextArea(self.comment, id="comment-editor")
            with Horizontal():
                yield Button("Save", id="save", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one(TextArea).focus()

    @on(Button.Pressed, "#save")
    def action_save(self) -> None:
        self.dismiss(self.query_one(TextArea).text)


class SaveAnalysisDialog(AnalysisDialog):
    BINDINGS = [("ctrl+s", "save", "Save")]

    def __init__(self, analysis: Analysis, title: str, directory: Path):
        super().__init__()
        self.analysis, self.title, self.directory = analysis, title, directory

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Save analysis")
            yield Input(self.title, placeholder="Analysis name", id="analysis-name")
            yield Checkbox("Replace an existing analysis with this name", id="overwrite")
            yield Static(id="error")
            with Horizontal():
                yield Button("Save", id="save", variant="primary")
                yield Button("Cancel", id="cancel")

    @on(Button.Pressed, "#save")
    @on(Input.Submitted)
    def action_save(self) -> None:
        try:
            entry = save_analysis(self.analysis, self.query_one(Input).value, self.directory,
                                  overwrite=self.query_one(Checkbox).value)
        except (OSError, ValueError) as exc:
            self.query_one("#error", Static).update(Text(str(exc)))
        else:
            self.dismiss(entry)


class LibraryDialog(AnalysisDialog):
    def __init__(self, directory: Path):
        super().__init__()
        self.directory = directory
        self.entries: list[SavedAnalysis] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Saved analyses · ↑/↓ choose · Enter opens · Esc cancels")
            yield OptionList(id="analyses")
            yield Static(id="error")

    def on_mount(self) -> None:
        try:
            self.entries, warnings = list_analyses(self.directory)
        except OSError as exc:
            self.query_one("#error", Static).update(Text(str(exc)))
            return
        options = self.query_one(OptionList)
        options.add_options(Text(entry.title) for entry in self.entries)
        options.highlighted = 0 if self.entries else None
        options.focus()
        message = "\n".join(warnings)
        if not self.entries:
            message = "No saved analyses yet. Press s in analysis to save one.\n" + message
        self.query_one("#error", Static).update(Text(message.strip()))

    @on(OptionList.OptionSelected)
    def open_selected(self, event: OptionList.OptionSelected) -> None:
        entry = self.entries[event.option_index]
        try:
            analysis = load_analysis(entry.path)
        except (OSError, ValueError, UnicodeError) as exc:
            self.query_one("#error", Static).update(Text(f"Could not open analysis: {exc}"))
        else:
            self.dismiss((entry.title, analysis))
