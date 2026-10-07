"""Local analysis dialogs; persistence stays in library/session."""
import asyncio
from pathlib import Path
from threading import Event

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Footer, Input, Label, OptionList, Select, Static, TextArea

from .export import export_analysis
from .follow import load_latest_game
from .game import Analysis
from .input import load_input, player_name
from .library import SavedAnalysis, delete_analysis, list_analyses, load_analysis, save_analysis
from .online import validate_username


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
    BINDINGS = [
        ("escape", "cancel", "Back"),
        Binding("f1", "app.help", "Help", key_display="F1", priority=True),
        Binding("f2", "app.home", "Home", key_display="F2", priority=True),
    ]

    def cancel_pending(self) -> None:
        self.workers.cancel_node(self)

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.cancel_pending()
        self.dismiss(None)


class CommentEditor(AnalysisDialog):
    BINDINGS = [Binding("ctrl+s", "save", "Save", show=False)]

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
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(TextArea).focus()

    @on(Button.Pressed, "#save")
    def action_save(self) -> None:
        self.dismiss(self.query_one(TextArea).text)


class SaveAnalysisDialog(AnalysisDialog):
    BINDINGS = [Binding("ctrl+s", "save", "Save", show=False)]

    def __init__(self, analysis: Analysis, title: str, directory: Path):
        super().__init__()
        self.analysis, self.title, self.directory = analysis, title, directory

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Save analysis · Ctrl+S saves")
            yield Input(self.title, placeholder="Analysis name", id="analysis-name")
            yield Checkbox("Replace an existing analysis with this name", id="overwrite")
            yield Static(id="error")
            with Horizontal():
                yield Button("Save", id="save", variant="primary")
                yield Button("Cancel", id="cancel")
        yield Footer()

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


class ExportDialog(AnalysisDialog):
    DEFAULT_CSS = """
    ExportDialog > Vertical { width: 95%; height: 90%; padding: 0 1; }
    ExportDialog VerticalScroll { height: 1fr; }
    """

    def __init__(self, analysis: Analysis, directory: Path):
        super().__init__()
        self.analysis = analysis
        self.directory = directory.expanduser().resolve()
        self.format = "pgn"
        self.exported: Path | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Export · choose format and destination")
            with VerticalScroll():
                yield Label(Text(f"Default folder:\n{self.directory}"), id="export-folder")
                yield Select([("Current position (FEN)", "fen"), ("Full analysis (PGN)", "pgn")],
                             value=self.format, allow_blank=False, id="export-format")
                yield Input(str(self.directory / "analysis.pgn"), id="export-path")
                yield Checkbox("Allow replacing an existing file", id="overwrite")
                yield Static(id="export-status")
            with Horizontal():
                yield Button("Export", id="export", variant="primary")
                yield Button("Cancel", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.update_destination()
        self.query_one("#export-path", Input).focus()

    def destination(self) -> Path:
        value = self.query_one("#export-path", Input).value.strip()
        if not value:
            raise ValueError("Enter a file name or path.")
        path = Path(value).expanduser()
        return (path if path.is_absolute() else self.directory / path).resolve()

    @on(Input.Changed, "#export-path")
    def update_destination(self) -> None:
        if self.exported is not None:
            return
        try:
            text = f"Destination:\n{self.destination()}\nExport confirms writing this file."
        except (OSError, ValueError, RuntimeError) as exc:
            text = str(exc)
        self.query_one("#export-status", Static).update(Text(text))

    @on(Select.Changed, "#export-format")
    def change_format(self, event: Select.Changed) -> None:
        field = self.query_one("#export-path", Input)
        if field.value == str(self.directory / f"analysis.{self.format}"):
            field.value = str(self.directory / f"analysis.{event.value}")
        self.format = str(event.value)
        self.update_destination()

    @on(Button.Pressed, "#export")
    @on(Input.Submitted, "#export-path")
    def action_export(self) -> None:
        if self.exported is not None:
            self.dismiss(self.exported)
            return
        status = self.query_one("#export-status", Static)
        try:
            self.exported = export_analysis(self.analysis, self.destination(), self.format,
                                            overwrite=self.query_one(Checkbox).value)
        except FileExistsError:
            status.update("File exists. Choose another path or explicitly allow replacement.")
            status.scroll_visible(animate=False)
        except (OSError, ValueError, RuntimeError) as exc:
            status.update(Text(f"Could not export: {exc}"))
            status.scroll_visible(animate=False)
        else:
            for selector in ("#export-folder", "#export-format", "#export-path", "#overwrite"):
                self.query_one(selector).display = False
            status.update(Text(f"Exported {self.format.upper()} to:\n{self.exported}\nPress Done to close."))
            self.query_one("#export", Button).label = "Done"
            self.query_one("#cancel", Button).label = "Close"
            self.query_one("#export", Button).focus()
            status.scroll_visible(animate=False)


class DeleteAnalysisDialog(AnalysisDialog):
    def __init__(self, title: str):
        super().__init__()
        self.title = title

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(Text(f'Delete saved analysis “{self.title}”?'))
            yield Static("The current analysis and continue snapshot will not change.")
            with Horizontal():
                yield Button("Delete", id="delete", variant="error")
                yield Button("Cancel", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    @on(Button.Pressed, "#delete")
    def confirm(self) -> None:
        self.dismiss(True)


class LibraryDialog(AnalysisDialog):
    BINDINGS = [Binding("delete", "delete_selected", "Delete", show=False)]

    def __init__(self, directory: Path):
        super().__init__()
        self.directory = directory
        self.entries: list[SavedAnalysis] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Saved analyses · ↑/↓ choose · Enter opens · Delete removes")
            yield OptionList(id="analyses")
            yield Static(id="error")
        yield Footer()

    def on_mount(self) -> None:
        self.reload_analyses()

    def reload_analyses(self, selected: int = 0) -> None:
        try:
            self.entries, warnings = list_analyses(self.directory)
        except OSError as exc:
            self.query_one("#error", Static).update(Text(str(exc)))
            return
        options = self.query_one(OptionList)
        options.clear_options()
        options.add_options(Text(entry.title) for entry in self.entries)
        options.highlighted = min(selected, len(self.entries) - 1) if self.entries else None
        options.focus()
        message = "\n".join(warnings)
        if not self.entries:
            message = "No saved analyses yet. Press s in analysis to save one.\n" + message
        self.query_one("#error", Static).update(Text(message.strip()))

    def action_delete_selected(self) -> None:
        selected = self.query_one(OptionList).highlighted
        if selected is None:
            return
        entry = self.entries[selected]

        def confirmed(result: bool | None) -> None:
            if result:
                try:
                    delete_analysis(entry.path)
                except OSError as exc:
                    self.query_one("#error", Static).update(Text(f"Could not delete analysis: {exc}"))
                else:
                    self.reload_analyses(selected)

        self.app.push_screen(DeleteAnalysisDialog(entry.title), confirmed)

    @on(OptionList.OptionSelected)
    def open_selected(self, event: OptionList.OptionSelected) -> None:
        entry = self.entries[event.option_index]
        try:
            analysis = load_analysis(entry.path)
        except (OSError, ValueError, UnicodeError) as exc:
            self.query_one("#error", Static).update(Text(f"Could not open analysis: {exc}"))
        else:
            self.dismiss((entry.title, analysis))


class AccountSelectionDialog(AnalysisDialog):
    """Return a validated (provider, username) without storing configuration."""
    BINDINGS = [
        Binding("up", "cycle_provider", "Provider", show=False, priority=True),
        Binding("down", "cycle_provider", "Provider", show=False, priority=True),
    ]

    def __init__(self, provider: str | None = None, username: str | None = None):
        super().__init__()
        self.provider, self.username = provider, username

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Default account · ↑/↓ changes provider · Tab changes field")
            yield Select([("Chess.com", "chess.com"), ("Lichess", "lichess")],
                         value=self.provider or "chess.com", allow_blank=False, id="provider")
            yield Input(self.username or "", placeholder="Public username", id="username")
            yield Static(id="error")
            with Horizontal():
                yield Button("Save & browse", id="browse", variant="primary")
                yield Button("Cancel", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def action_cycle_provider(self) -> None:
        provider = self.query_one(Select)
        provider.expanded = False
        provider.value = "lichess" if provider.value == "chess.com" else "chess.com"

    @on(Button.Pressed, "#browse")
    @on(Input.Submitted)
    def select_account(self) -> None:
        try:
            username = validate_username(self.query_one(Input).value)
        except ValueError as exc:
            self.query_one("#error", Static).update(Text(str(exc)))
        else:
            self.dismiss((str(self.query_one(Select).value), username))


class ImportDialog(AnalysisDialog):
    BINDINGS = [Binding("ctrl+s", "load", "Import", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Import FEN, PGN or HTTPS URL · Ctrl+S loads")
            yield TextArea(id="import-text")
            yield Static(id="error")
            with Horizontal():
                yield Button("Import", id="load", variant="primary")
                yield Button("Cancel", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(TextArea).focus()

    @on(Button.Pressed, "#load")
    def action_load(self) -> None:
        text = self.query_one(TextArea).text.strip()
        if not text:
            self.query_one("#error", Static).update("Enter FEN, PGN or an HTTPS URL.")
            return
        if not self.query_one("#load", Button).disabled:
            self.load_analysis(text)

    def pause_for_help(self) -> None:
        self.workers.cancel_node(self)
        if self.query_one("#load", Button).disabled:
            self.query_one("#load", Button).disabled = False
            self.query_one(TextArea).disabled = False
            self.query_one("#error", Static).update("Download canceled · Ctrl+S retries")

    @work(group="import", exclusive=True)
    async def load_analysis(self, text: str) -> None:
        self.query_one("#load", Button).disabled = True
        self.query_one(TextArea).disabled = True
        self.query_one("#error", Static).update("Loading… · Esc cancels")
        try:
            parsed = await asyncio.to_thread(load_input, text)
            analysis = Analysis.from_input(*parsed)
        except (SystemExit, OSError, ValueError, UnicodeError) as exc:
            self.query_one("#error", Static).update(Text(str(exc)))
            self.query_one("#load", Button).disabled = False
            self.query_one(TextArea).disabled = False
            self.query_one(TextArea).focus()
        else:
            self.dismiss(("", analysis))


class LatestGameDialog(AnalysisDialog):
    BINDINGS = [Binding("r", "load", "Retry", show=False)]

    def __init__(self, provider: str, username: str, *,
                 white: str | None = None, black: str | None = None):
        super().__init__()
        self.provider, self.username = provider, username
        self.white, self.black = white, black
        self.cancelled = Event()

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(Text(f"Latest available · {self.provider} · {self.username}"))
            yield Static("Loading… · Esc cancels", id="latest-status")
            with Horizontal():
                yield Button("Retry", id="load", disabled=True)
                yield Button("Cancel", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.load_latest()

    def on_unmount(self) -> None:
        self.cancelled.set()

    def cancel_pending(self) -> None:
        self.cancelled.set()
        super().cancel_pending()

    def pause_for_help(self) -> None:
        self.cancel_pending()
        if self.query_one("#load", Button).disabled:
            self.query_one("#load", Button).disabled = False
            self.query_one("#latest-status", Static).update("Download canceled · r retries")

    @on(Button.Pressed, "#load")
    def action_load(self) -> None:
        if not self.query_one("#load", Button).disabled:
            self.load_latest()

    @work(group="latest", exclusive=True)
    async def load_latest(self) -> None:
        cancelled = self.cancelled = Event()
        retry = self.query_one("#load", Button)
        retry.disabled = True
        status = self.query_one("#latest-status", Static)
        status.update("Loading… · Esc cancels")
        try:
            analysis = await asyncio.to_thread(load_latest_game, self.provider, self.username,
                                               cancelled=cancelled)
            if cancelled.is_set():
                return
            if analysis is None:
                status.update("No completed standard games available · r retries")
                retry.disabled = False
                return
            for color, override in (("White", self.white), ("Black", self.black)):
                if override is not None and override.strip() not in {"", "?"}:
                    name = player_name(override, color)
                    setattr(analysis, color.lower() + "_name", name)
        except (OSError, ValueError) as exc:
            status.update(Text(f"Could not load latest game: {exc} · r retries"))
            retry.disabled = False
        else:
            self.dismiss(("", analysis))
        finally:
            cancelled.set()


class HelpDialog(AnalysisDialog):
    DEFAULT_CSS = """
    HelpDialog > Vertical { width: 95%; height: 90%; padding: 0 1; }
    HelpDialog VerticalScroll { height: 1fr; }
    """

    def __init__(self, title: str, text: str):
        super().__init__()
        self.title, self.text = title, text

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(Text(self.title, style="bold"))
            with VerticalScroll():
                yield Static(Text(self.text))
            yield Button("Close", id="cancel")
        yield Footer()
