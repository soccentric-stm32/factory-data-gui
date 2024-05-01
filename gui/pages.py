"""Pages of the factory data GUI: one generator page per file kind, and Inspect.

A generator page loads a CSV, previews its records, and writes the .sys, .cal
or .diag file of the selected record (or of every record) to an output folder.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core import fileformat as ff
from core import paths, service
from core.generators import GENERATORS, CsvError, Dataset, Generator, Issue
from core.manifest import MANIFEST_NAME, update_manifest, verify_folder
from core.units import RegistryError

from . import icons
from . import soc_theme as theme
from .widgets import Card, field, label, set_tone

#: Default output folder, relative to the app folder until a workspace is set.
DEFAULT_OUTPUT = Path("out")


class Page(QWidget):
    """Base page: title block, then cards; the window owns nav and console."""

    key = ""
    title = ""
    subtitle = ""
    icon_name = "file"
    nav_subtitle = ""

    def __init__(self, window) -> None:
        super().__init__()
        self.setObjectName("Page")
        self.window_ = window
        self.nav = None
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(28, 24, 28, 16)
        self.column.setSpacing(16)
        self.column.addWidget(label(self.title, "PageTitle"))
        sub = label(self.subtitle, "PageSubtitle")
        sub.setWordWrap(True)
        self.column.addWidget(sub)

    def apply_theme(self) -> None:
        """Re-apply theme-dependent icons."""

    def refresh(self) -> None:
        """Re-read state after startup."""

    def load(self, settings: QSettings) -> None:
        """Restore page settings."""

    def save(self, settings: QSettings) -> None:
        """Persist page settings."""

    def run_primary(self) -> None:
        """Ctrl+Return."""

    def run_all(self) -> None:
        """Ctrl+Shift+Return."""

    def write_sample(self) -> None:
        """Write a sample CSV."""


def pick_open(parent: QWidget, title: str, start: str, filt: str) -> str:
    path, _ = QFileDialog.getOpenFileName(
        parent, title, str(paths.resolve(start)), filt)
    return path


def no_drops(root: QWidget) -> None:
    """Let file drops reach the window instead of being pasted into a field."""
    for kind in (QLineEdit, QPlainTextEdit):
        for widget in root.findChildren(kind):
            widget.setAcceptDrops(False)


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def status_color(status: str) -> QColor:
    t = theme.current()
    return QColor({"error": t.danger, "warning": t.warning, "ok": t.success}
                  .get(status, t.text_tertiary))


def table_item(text: str, *, right: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if right:
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return item


class GeneratorPage(Page):
    """CSV in, one factory data file out."""

    def __init__(self, window, generator: Generator, icon_name: str,
                 subtitle: str, nav_subtitle: str) -> None:
        self.gen = generator
        self.key = generator.kind
        self.title = generator.title
        self.subtitle = subtitle
        self.icon_name = icon_name
        self.nav_subtitle = nav_subtitle
        super().__init__(window)
        self.data: Dataset | None = None
        self.issues: list[Issue] = []
        self.preview_bytes: bytes | None = None
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._csv_changed)
        self._watch_timer = QTimer(self)
        self._watch_timer.setSingleShot(True)
        self._watch_timer.setInterval(300)
        self._watch_timer.timeout.connect(self._auto_reload)
        self._validate_timer = QTimer(self)
        self._validate_timer.setSingleShot(True)
        self._validate_timer.setInterval(250)
        self._validate_timer.timeout.connect(self._revalidate)
        self._build()

    # ---- layout ---------------------------------------------------------

    def _build(self) -> None:
        gen = self.gen
        suffix = gen.suffix

        # Source
        self.csv_edit = QLineEdit()
        self.csv_edit.setPlaceholderText(f"{gen.kind}.csv")
        self.csv_edit.editingFinished.connect(self.reload)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_csv)
        self.reload_button = QPushButton("Reload")
        self.reload_button.clicked.connect(self.reload)
        self.status = label("", "Pill")
        self.sample_button = QPushButton("Write Sample CSV…")
        self.sample_button.setObjectName("Link")
        self.sample_button.clicked.connect(self.write_sample)
        source = Card("Source", self.status)
        source.add_row("CSV file", self.csv_edit, browse, self.reload_button,
                       stretch=0)
        self.source_hint = label("", "Hint")
        self.source_hint.setWordWrap(True)
        source.add_row(None, field(self.source_hint), None, self.sample_button,
                       stretch=0)
        self.column.addWidget(source)

        # Records
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter records")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(200)
        self.search.textChanged.connect(self._filter)
        self.table = QTableWidget()
        self.table.setObjectName("Table")
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setDefaultAlignment(
            Qt.AlignLeft | Qt.AlignVCenter)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.table.setMinimumHeight(170)
        self.table.setMaximumHeight(260)
        self.table.itemSelectionChanged.connect(self._table_selected)
        self.count_pill = label("", "Pill")
        records_head = QWidget()
        head_row = QHBoxLayout(records_head)
        head_row.setContentsMargins(0, 0, 0, 0)
        head_row.setSpacing(8)
        head_row.addWidget(self.count_pill)
        head_row.addWidget(self.search)
        records = Card("Records", records_head)
        records.add_widget(self.table)
        self.column.addWidget(records)

        # Problems
        self.issue_pill = label("", "Pill")
        self.issue_table = QTableWidget()
        self.issue_table.setObjectName("Table")
        self.issue_table.setColumnCount(4)
        self.issue_table.setHorizontalHeaderLabels(
            ["Severity", "Line", "Record", "Problem"])
        self.issue_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.issue_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.issue_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.issue_table.setAlternatingRowColors(True)
        self.issue_table.verticalHeader().setVisible(False)
        self.issue_table.horizontalHeader().setStretchLastSection(True)
        self.issue_table.horizontalHeader().setDefaultAlignment(
            Qt.AlignLeft | Qt.AlignVCenter)
        self.issue_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.issue_table.setMaximumHeight(170)
        self.issue_table.itemSelectionChanged.connect(self._issue_selected)
        self.issue_hint = label("", "Hint")
        self.issue_hint.setWordWrap(True)
        self.problems = Card("Problems", self.issue_pill)
        self.problems.add_widget(self.issue_table)
        self.problems.add_row(None, field(self.issue_hint), stretch=0)
        self.column.addWidget(self.problems)

        # Output
        self.record_combo = QComboBox()
        self.record_combo.setMinimumWidth(220)
        self.record_combo.currentTextChanged.connect(self._record_changed)
        self.revision = QSpinBox()
        self.revision.setRange(0, 65535)
        self.revision.setValue(1)
        self.revision.setFixedWidth(110)
        self.revision.valueChanged.connect(self._input_changed)
        self.uid_edit = QLineEdit()
        self.uid_edit.setPlaceholderText(
            "optional, 24 hex digits; blank = not bound to a chip")
        self.uid_edit.textChanged.connect(self._input_changed)
        self.out_edit = QLineEdit(str(DEFAULT_OUTPUT))
        out_browse = QPushButton("Browse…")
        out_browse.clicked.connect(self._browse_output)
        output = Card("Output")
        output.add_row("Record", self.record_combo, None, stretch=0)
        output.add_row("Revision", self.revision, None)
        output.add_row("Chip UID binding", self.uid_edit, stretch=0)
        output.add_row("Output folder", self.out_edit, out_browse, stretch=0)
        self.manifest_box = QCheckBox(
            f"Write {MANIFEST_NAME} (sizes and hashes) next to the files")
        self.manifest_box.setChecked(True)
        self.manifest_box.setToolTip(
            "Lets Inspect check the folder later: changed, missing or extra "
            "files are reported.")
        output.add_row("Manifest", self.manifest_box, None, stretch=0)
        self.column.addWidget(output)

        # Preview
        self.size_pill = label("", "Pill")
        self.preview = QPlainTextEdit()
        self.preview.setObjectName("Console")
        self.preview.setReadOnly(True)
        self.preview.setFont(theme.mono_font())
        self.preview.setMinimumHeight(150)
        self.preview.setMaximumHeight(260)
        self.preview_hint = label("", "Hint")
        self.preview_hint.setWordWrap(True)
        preview = Card(f"Preview of the {suffix} file", self.size_pill)
        preview.add_widget(self.preview)
        preview.add_row(None, field(self.preview_hint), stretch=0)
        self.column.addWidget(preview)

        # Actions
        self.generate_button = QPushButton(f"Generate {suffix}")
        self.generate_button.setObjectName("Primary")
        self.generate_button.clicked.connect(self.run_primary)
        self.all_button = QPushButton(f"Generate All {suffix}")
        self.all_button.setObjectName("Secondary")
        self.all_button.clicked.connect(self.run_all)
        self.verify_button = QPushButton("Verify Folder")
        self.verify_button.setObjectName("Link")
        self.verify_button.setToolTip(
            "Check every file in the output folder against its CRCs and the "
            "manifest")
        self.verify_button.clicked.connect(self.verify_folder)
        self.open_button = QPushButton("Open Folder")
        self.open_button.setObjectName("Link")
        self.open_button.clicked.connect(self.open_folder)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addWidget(self.generate_button)
        actions.addWidget(self.all_button)
        actions.addStretch(1)
        actions.addWidget(self.verify_button)
        actions.addWidget(self.open_button)
        self.column.addLayout(actions)
        self.column.addStretch(1)
        self._set_enabled(False)
        no_drops(self)

    def apply_theme(self) -> None:
        t = theme.current()
        self.generate_button.setIcon(icons.icon("file", t.on_accent))
        self.all_button.setIcon(icons.icon("copy", t.text))
        self.open_button.setIcon(icons.icon("folder", t.accent))
        self.verify_button.setIcon(icons.icon("shield", t.accent))
        self._paint_status()

    # ---- settings -------------------------------------------------------

    def load(self, settings: QSettings) -> None:
        key = self.gen.kind
        csv = settings.value(f"{key}/csv", "", type=str)
        self.csv_edit.setText(paths.display(csv) if csv else "")
        self.revision.setValue(settings.value(f"{key}/revision", 1, type=int))
        self.manifest_box.setChecked(
            settings.value(f"{key}/manifest", True, type=bool))

    def save(self, settings: QSettings) -> None:
        key = self.gen.kind
        csv = self.csv_edit.text().strip()
        settings.setValue(f"{key}/csv", paths.display(csv) if csv else "")
        settings.setValue(f"{key}/revision", self.revision.value())
        settings.setValue(f"{key}/manifest", self.manifest_box.isChecked())

    def refresh(self) -> None:
        self.reload(quiet=True)

    def apply_workspace(self, workspace, force: bool = False) -> None:
        """Work in the artifacts clone: write to its out/ folder and start on
        its csv/ file, unless the saved CSV is already inside the clone.
        ``force`` (a product or batch was chosen) always starts on its csv/."""
        self.out_edit.setText(paths.display(workspace.out_dir))
        current = self.csv_edit.text().strip()
        inside = False
        if current and not force:
            csv_path = paths.resolve(current)
            try:
                csv_path.relative_to(workspace.resolved_root)
                inside = csv_path.is_file()
            except ValueError:
                pass
        default = workspace.csv_path(self.gen.kind)
        if not inside and paths.resolve(default).is_file():
            self.csv_edit.setText(paths.display(default))

    # ---- CSV ------------------------------------------------------------

    def _browse_csv(self) -> None:
        start = self.csv_edit.text() or "."
        path = pick_open(self, f"Choose the {self.gen.kind} CSV", start,
                         "CSV files (*.csv);;All files (*)")
        if path:
            self.open_csv(path)

    def open_csv(self, path: str) -> None:
        self.csv_edit.setText(paths.display(path))
        self.reload()

    def reload(self, quiet: bool = False) -> None:
        text = self.csv_edit.text().strip()
        target = paths.resolve(text) if text else None
        self.data = None
        self.issues = []
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.record_combo.blockSignals(True)
        self.record_combo.clear()
        self.record_combo.blockSignals(False)
        self._show_issues()
        self._watch(target)
        if not text:
            self._status("", "no CSV", "")
            self.count_pill.setText("")
            self.source_hint.setText(
                f"Columns: {', '.join(self.gen.columns)}. "
                "Drop a CSV file anywhere in this window to load it.")
            set_tone(self.source_hint, "")
            self._set_enabled(False)
            self._update_preview()
            return
        try:
            self.data = self.gen.load(target)
        except CsvError as exc:
            self._status("danger", "invalid CSV", str(exc))
            self.count_pill.setText("")
            self.source_hint.setText(str(exc))
            set_tone(self.source_hint, "danger")
            self._set_enabled(False)
            self._update_preview()
            if not quiet:
                self.window_.log(f"{self.title}: {exc}")
            return
        data = self.data
        set_tone(self.source_hint, "")
        count = len(data.ids)
        self.source_hint.setText(
            f"{data.path.name}: {plural(len(data.rows), 'row')}, "
            f"{plural(count, 'id')}"
            + (f", {plural(len(data.shared), 'shared row')}"
               if data.shared else "")
            + ".")
        self._revalidate(redraw=False)
        self.table.setColumnCount(len(data.columns) + 2)
        self.table.setHorizontalHeaderLabels(
            ["Line", "Status", *data.columns])
        self.table.setRowCount(len(data.rows))
        for r, (row, line) in enumerate(zip(data.rows, data.lines)):
            self.table.setItem(r, 0, table_item(str(line), right=True))
            self.table.setItem(r, 1, table_item(""))
            for c, name in enumerate(data.columns):
                self.table.setItem(r, c + 2, table_item(row.get(name, "")))
        self._paint_status()
        self.record_combo.blockSignals(True)
        self.record_combo.addItems(data.ids)
        self.record_combo.blockSignals(False)
        self._filter(self.search.text())
        self._set_enabled(True)
        self._record_changed(self.record_combo.currentText())
        self._summarise()
        if not quiet:
            self.window_.log(f"{self.title}: loaded {paths.display(data.path)} "
                             f"({plural(count, 'record')}, "
                             f"{self._issue_summary()})")
            self.window_.remember(paths.display(data.path))

    # ---- validation -----------------------------------------------------

    def _input_changed(self, *_args) -> None:
        self._update_preview()
        self._validate_timer.start()

    def _revalidate(self, redraw: bool = True) -> None:
        """Check every record and show what is wrong, with its CSV line."""
        if self.data is None:
            return
        try:
            uid = self._uid()
        except ff.FileFormatError as exc:
            self.issues = [Issue("error", "", 0, str(exc))]
        else:
            self.issues = self._check(uid)
        if redraw:
            self._paint_status()
            self._summarise()
        self._show_issues()

    def _check(self, uid: bytes | None) -> list[Issue]:
        """Format checks, then the product rules and the unit registry."""
        registry = (self.window_.project_registry()
                    if self.gen.kind == "sys" else None)
        return service.check(
            self.gen, self.data, revision=self.revision.value(), uid=uid,
            rules=self.window_.project_rules(), registry=registry)

    def _record_status(self, ident: str) -> str:
        worst = "ok"
        for issue in self.issues:
            if issue.ident == ident:
                if issue.severity == "error":
                    return "error"
                worst = "warning"
        return worst

    def _paint_status(self) -> None:
        """Status column of the records table, in the current theme colours."""
        if self.data is None or self.table.columnCount() < 2:
            return
        for r, row in enumerate(self.data.rows):
            ident = row.get("id", "")
            status = ("shared" if ident == "*" else self._record_status(ident))
            item = self.table.item(r, 1)
            if item is None:
                continue
            item.setText({"ok": "OK", "warning": "Warning",
                          "error": "Error", "shared": "Shared"}[status])
            item.setForeground(status_color(status))

    def _issue_summary(self) -> str:
        errors = sum(1 for i in self.issues if i.severity == "error")
        warnings = len(self.issues) - errors
        if not self.issues:
            return "no problems"
        parts = []
        if errors:
            parts.append(plural(errors, "error"))
        if warnings:
            parts.append(plural(warnings, "warning"))
        return ", ".join(parts)

    def _summarise(self) -> None:
        """Pill and sidebar dot from the validation result."""
        if self.data is None:
            return
        count = len(self.data.ids)
        errors = sum(1 for i in self.issues if i.severity == "error")
        bad = len({i.ident for i in self.issues
                   if i.severity == "error" and i.ident})
        if errors:
            tone, text = "danger", (f"{bad} of {plural(count, 'record')} "
                                    "with errors" if bad else
                                    plural(errors, "error"))
        elif self.issues:
            tone, text = "warning", (f"{plural(count, 'record')}, "
                                     f"{self._issue_summary()}")
        else:
            tone, text = "success", plural(count, "record")
        self._status(tone, text, f"{self.data.path.name}: "
                                 f"{self._issue_summary()}")
        self.count_pill.setText(plural(len(self.data.rows), "row"))

    def _show_issues(self) -> None:
        table = self.issue_table
        table.setRowCount(0)
        visible = self.data is not None
        self.problems.setVisible(visible)
        if not visible:
            return
        table.setRowCount(len(self.issues))
        for r, issue in enumerate(self.issues):
            sev = table_item("Error" if issue.severity == "error"
                             else "Warning")
            sev.setForeground(status_color(issue.severity))
            table.setItem(r, 0, sev)
            table.setItem(r, 1, table_item(str(issue.line) if issue.line
                                           else "–", right=True))
            table.setItem(r, 2, table_item(issue.ident or "–"))
            table.setItem(r, 3, table_item(issue.message))
        has = bool(self.issues)
        table.setVisible(has)
        self.issue_hint.setVisible(True)
        errors = sum(1 for i in self.issues if i.severity == "error")
        if not has:
            self.issue_pill.setText("no problems")
            set_tone(self.issue_pill, "success")
            self.issue_hint.setText(
                "Every record builds into a valid file. Generate All writes "
                "them all.")
            set_tone(self.issue_hint, "")
        else:
            self.issue_pill.setText(self._issue_summary())
            set_tone(self.issue_pill, "danger" if errors else "warning")
            self.issue_hint.setText(
                "Records with errors are skipped by Generate All. Select a "
                "line to jump to its record." if errors else
                "Warnings do not stop a file from being written; check them "
                "before shipping.")
            set_tone(self.issue_hint, "danger" if errors else "warning")

    def _issue_selected(self) -> None:
        rows = self.issue_table.selectionModel().selectedRows()
        if not rows or self.data is None:
            return
        issue = self.issues[rows[0].row()]
        if issue.ident and issue.ident in self.data.ids:
            self.record_combo.setCurrentText(issue.ident)
            self.table.scrollToItem(self.table.item(
                self.table.currentRow(), 0))

    # ---- watching the file ----------------------------------------------

    def _watch(self, text: str | Path | None) -> None:
        old = self.watcher.files()
        if old:
            self.watcher.removePaths(old)
        if not text:
            return
        target = paths.resolve(text)
        if target.is_file():
            self.watcher.addPath(str(target))

    def _csv_changed(self, _path: str) -> None:
        self._watch_timer.start()

    def _auto_reload(self) -> None:
        """The CSV was saved in an editor: reload it and keep the record."""
        keep = self.record_combo.currentText()
        self.reload(quiet=True)
        if self.data is not None and keep in self.data.ids:
            self.record_combo.setCurrentText(keep)
        self.window_.log(f"{self.title}: {Path(self.csv_edit.text()).name} "
                         f"changed on disk, reloaded ({self._issue_summary()})"
                         if self.data is not None else
                         f"{self.title}: the CSV changed on disk and is "
                         "invalid")

    def _status(self, tone: str, text: str, tip: str) -> None:
        self.status.setText(text)
        self.status.setToolTip(tip)
        set_tone(self.status, tone)
        if self.nav is not None:
            self.nav.set_status({"success": "success", "danger": "danger",
                                 "warning": "warning"}.get(tone, ""),
                                tone != "", tip or text)

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (self.generate_button, self.all_button,
                       self.record_combo, self.search):
            widget.setEnabled(enabled)

    # ---- records --------------------------------------------------------

    def _filter(self, text: str) -> None:
        needle = text.strip().lower()
        for r in range(self.table.rowCount()):
            hit = not needle or any(
                needle in (self.table.item(r, c).text().lower()
                           if self.table.item(r, c) else "")
                for c in range(self.table.columnCount()))
            self.table.setRowHidden(r, not hit)

    def _table_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows or self.data is None:
            return
        ident = self.data.rows[rows[0].row()].get("id", "")
        if ident in self.data.ids and ident != self.record_combo.currentText():
            self.record_combo.setCurrentText(ident)

    def _record_changed(self, ident: str) -> None:
        if self.data is not None and ident:
            for r, row in enumerate(self.data.rows):
                if row.get("id") == ident:
                    self.table.blockSignals(True)
                    self.table.selectRow(r)
                    self.table.blockSignals(False)
                    break
        self._update_preview()

    def _uid(self) -> bytes | None:
        text = self.uid_edit.text().strip()
        return ff.parse_uid(text) if text else None

    def _build_current(self) -> bytes:
        if self.data is None or not self.record_combo.currentText():
            raise CsvError("no record selected")
        try:
            uid = self._uid()
        except ff.FileFormatError as exc:
            raise CsvError(str(exc)) from exc
        return self.gen.build(self.data, self.record_combo.currentText(),
                              revision=self.revision.value(), uid=uid)

    def _update_preview(self, *_args) -> None:
        self.preview_bytes = None
        if self.data is None:
            self.preview.setPlainText("")
            self.size_pill.setText("")
            self.preview_hint.setText("")
            return
        try:
            blob = self._build_current()
            parsed = ff.parse_file(blob, self.gen.kind)
        except (CsvError, ff.FileFormatError) as exc:
            self.preview.setPlainText("")
            self.size_pill.setText("error")
            set_tone(self.size_pill, "danger")
            self.preview_hint.setText(str(exc))
            set_tone(self.preview_hint, "danger")
            self.generate_button.setEnabled(False)
            return
        self.preview_bytes = blob
        self.generate_button.setEnabled(True)
        set_tone(self.preview_hint, "")
        self.size_pill.setText(f"{len(blob)} of 4096 bytes")
        set_tone(self.size_pill, "success")
        header = [
            ("file", self.gen.filename(self.record_combo.currentText())),
            ("flash address", f"{self.gen.address:#010x}"),
            ("revision", str(parsed.revision)),
            ("chip UID", parsed.uid.hex().upper() if parsed.bound
             else "not bound"),
            ("CRC", "header and payload verified"),
        ]
        rows = header + [("", "")] + ff.describe(parsed)
        width = max(len(name) for name, _ in rows)
        self.preview.setPlainText("\n".join(
            f"{name:<{width}}  {value}" if name or value else ""
            for name, value in rows))
        self.preview_hint.setText(
            f"{len(parsed.items)} TLV items. Written to the factory data "
            f"window at {self.gen.address:#010x}.")

    # ---- output ---------------------------------------------------------

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choose the output folder",
            str(paths.resolve(self.out_edit.text() or ".")))
        if path:
            self.out_edit.setText(paths.display(path))

    def _out_dir(self) -> Path | None:
        text = self.out_edit.text().strip()
        if not text:
            self.window_.error("No output folder",
                               "Choose a folder for the generated files.")
            return None
        folder = paths.resolve(text)
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.window_.error("Cannot create the output folder",
                               paths.message(exc, folder))
            return None
        return folder

    def open_folder(self) -> None:
        folder = self._out_dir()
        if folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def verify_folder(self) -> None:
        folder = self._out_dir()
        if folder:
            self.window_.inspect_path(str(folder))

    def _write(self, folder: Path, files: dict[str, bytes]) -> list[str]:
        """Write ``{name: bytes}``, read each back and compare.

        Returns the names that could not be written or did not read back the
        same.  The manifest is updated for the files that did.
        """
        bad: list[str] = []
        good: dict[str, bytes] = {}
        for name, blob in files.items():
            target = folder / name
            try:
                target.write_bytes(blob)
                same = target.read_bytes() == blob
                ff.parse_file(blob, self.gen.kind)
            except (OSError, ff.FileFormatError) as exc:
                self.window_.log(f"{name}: {paths.message(exc, target)}")
                bad.append(name)
                continue
            if not same:
                self.window_.log(f"{name}: read back differently from what "
                                 "was written")
                bad.append(name)
                continue
            good[name] = blob
        if good and self.manifest_box.isChecked():
            try:
                update_manifest(folder, good)
            except (OSError, ff.FileFormatError) as exc:
                self.window_.error("Cannot write the manifest",
                                   paths.message(exc, folder))
        return bad

    def run_primary(self) -> None:
        if self.data is None or self.preview_bytes is None:
            return
        folder = self._out_dir()
        if folder is None:
            return
        ident = self.record_combo.currentText()
        blocking = [i for i in self.issues
                    if i.severity == "error" and i.ident == ident]
        if blocking:
            self.window_.error(
                "Cannot write the file",
                f"{ident} has {plural(len(blocking), 'error')}:\n"
                + "\n".join(f"  line {i.line}: {i.message}"
                            for i in blocking[:6]))
            return
        name = self.gen.filename(ident)
        existed = (folder / name).exists()
        if self._write(folder, {name: self.preview_bytes}):
            self.window_.error("Cannot write the file",
                               f"{name} could not be written and verified.")
            return
        self.window_.log(
            f"{'Overwrote' if existed else 'Wrote'} {folder / name} "
            f"({len(self.preview_bytes)} bytes, verified)")
        self.window_.workspace_changed()

    def run_all(self) -> None:
        if self.data is None:
            return
        folder = self._out_dir()
        if folder is None:
            return
        try:
            uid = self._uid()
        except ff.FileFormatError as exc:
            self.window_.error("Invalid chip UID", str(exc))
            return
        self._revalidate(redraw=False)
        blocked = {i.ident for i in self.issues
                   if i.severity == "error" and i.ident}
        plan = service.plan(self.gen, self.data, folder,
                            revision=self.revision.value(), uid=uid,
                            blocked=blocked)
        errors = plan.errors
        if errors:
            shown = "\n".join(f"  {i}: {e.split(': ', 1)[-1]}"
                              for i, e in list(errors.items())[:8])
            more = (f"\n  and {len(errors) - 8} more"
                    if len(errors) > 8 else "")
            box = QMessageBox.question(
                self, "Records with errors",
                f"{plural(len(errors), 'record')} of "
                f"{len(self.data.ids)} cannot be generated and will be "
                f"skipped:\n\n{shown}{more}\n\nGenerate the other "
                f"{len(plan.files)}?")
            if box != QMessageBox.Yes:
                return
        if not plan.files:
            self.window_.error("Nothing to generate",
                               "No record builds into a valid file.")
            return
        files = plan.to_write()
        if not files:
            self.window_.log(
                f"Nothing to write: {plan.summary()} in "
                f"{paths.display(folder)}")
            return
        changed = plan.names(service.CHANGED)
        if changed:
            box = QMessageBox.question(
                self, "Overwrite files?",
                f"{plan.summary()} in {paths.display(folder)}.\n\n"
                f"{plural(len(changed), 'file')} will be overwritten and "
                "the unchanged ones are left alone.\n\nContinue?")
            if box != QMessageBox.Yes:
                return
        bad = self._write(folder, files)
        done = len(files) - len(bad)
        for ident, text in errors.items():
            self.window_.log(f"skipped {text}")
        self.window_.log(
            f"Generated {plural(done, self.gen.suffix + ' file')} in "
            f"{paths.display(folder)}, read back and verified"
            + (f"; {len(bad)} failed" if bad else "")
            + (f"; {len(errors)} skipped" if errors else "")
            + (f"; {MANIFEST_NAME} updated"
               if done and self.manifest_box.isChecked() else "")
            + (f"; {len(plan.names(service.SAME))} unchanged"
               if plan.names(service.SAME) else ""))
        if self.gen.kind == "sys" and done:
            self._register_units(plan, set(files) - set(bad))
        if bad:
            self.window_.error(
                "Some files failed",
                f"{done} written, {len(bad)} failed. The output shows why.")
        self.window_.workspace_changed()

    def _register_units(self, plan, written: set[str]) -> None:
        """Record the generated units in units.csv of the clone."""
        ws = self.window_.workspace
        registry = self.window_.project_registry()
        if ws is None or registry is None:
            return
        built = {plan.owner[n]: plan.files[n] for n in written}
        try:
            changed = service.register(
                registry, self.data, built, product=ws.product,
                batch=ws.batch)
            if changed:
                registry.save()
        except (RegistryError, OSError) as exc:
            self.window_.error("Cannot update units.csv", str(exc))
            return
        if changed:
            self.window_.log(
                f"units.csv: {plural(len(changed), 'unit')} added or changed")
            self.window_.units_changed()

    def write_sample(self) -> None:
        workspace = self.window_.workspace
        folder = (workspace.csv_dir if workspace is not None
                  else paths.resolve(self.csv_edit.text() or ".").parent)
        start = str(paths.resolve(folder) / f"{self.gen.kind}.csv")
        path, _ = QFileDialog.getSaveFileName(
            self, "Write a sample CSV", start, "CSV files (*.csv)")
        if not path:
            return
        target = paths.resolve(path)
        try:
            target.write_text(self.gen.sample(), encoding="utf-8")
        except OSError as exc:
            self.window_.error("Cannot write the sample",
                               paths.message(exc, target))
            return
        self.window_.log(f"Wrote sample {paths.display(target)}")
        self.open_csv(str(target))


class InspectPage(Page):
    """Open a .sys, .cal or .diag file, or a folder of them, and check it."""

    key = "inspect"
    title = "Inspect"
    subtitle = ("Open a generated .sys, .cal or .diag file to check both CRCs "
                "and see every item, field and byte, or open a folder to "
                "check all its files against the manifest.")
    icon_name = "search"
    nav_subtitle = "Check a file or folder"

    VIEWS = ("Items", "Fields", "Hex")

    def __init__(self, window) -> None:
        super().__init__(window)
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText(
            ".sys, .cal or .diag file, or a folder of them")
        self.file_edit.editingFinished.connect(self.inspect)
        browse = QPushButton("File…")
        browse.clicked.connect(self._browse)
        browse_dir = QPushButton("Folder…")
        browse_dir.clicked.connect(self._browse_folder)
        self.pill = label("", "Pill")
        card = Card("Source", self.pill)
        card.add_row("File or folder", self.file_edit, browse, browse_dir,
                     stretch=0)
        self.column.addWidget(card)

        self.view = QPlainTextEdit()
        self.view.setObjectName("Console")
        self.view.setReadOnly(True)
        self.view.setFont(theme.mono_font())
        self.fields = QTableWidget()
        self.fields.setObjectName("Table")
        self.fields.setColumnCount(4)
        self.fields.setHorizontalHeaderLabels(
            ["Offset", "Size", "Field", "Value"])
        self.fields.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.fields.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.fields.setAlternatingRowColors(True)
        self.fields.verticalHeader().setVisible(False)
        self.fields.horizontalHeader().setStretchLastSection(True)
        self.fields.horizontalHeader().setDefaultAlignment(
            Qt.AlignLeft | Qt.AlignVCenter)
        self.fields.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.fields.itemSelectionChanged.connect(self._field_selected)
        self.hex = QPlainTextEdit()
        self.hex.setObjectName("Console")
        self.hex.setReadOnly(True)
        self.hex.setFont(theme.mono_font())
        self.hex.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.stack = QStackedWidget()
        for widget in (self.view, self.fields, self.hex):
            widget.setMinimumHeight(300)
            self.stack.addWidget(widget)
        self.view_combo = QComboBox()
        self.view_combo.addItems(self.VIEWS)
        self.view_combo.setToolTip(
            "Items: what the file says. Fields: header and TLV items with "
            "their offsets. Hex: every byte.")
        self.view_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)
        self.hint = label("", "Hint")
        self.hint.setWordWrap(True)
        result = Card("Contents", self.view_combo)
        result.add_widget(self.stack)
        result.add_row(None, field(self.hint), stretch=0)
        self.column.addWidget(result)
        self.column.addStretch(1)
        self._raw = b""
        no_drops(self)

    def load(self, settings: QSettings) -> None:
        saved = settings.value("inspect/file", "", type=str)
        self.file_edit.setText(paths.display(saved) if saved else "")
        self.view_combo.setCurrentIndex(
            max(0, min(settings.value("inspect/view", 0, type=int), 2)))

    def save(self, settings: QSettings) -> None:
        text = self.file_edit.text().strip()
        settings.setValue("inspect/file", paths.display(text) if text else "")
        settings.setValue("inspect/view", self.view_combo.currentIndex())

    def refresh(self) -> None:
        self.inspect(quiet=True)

    def _browse(self) -> None:
        path = pick_open(self, "Open a factory data file",
                         self.file_edit.text() or ".",
                         "Factory data (*.sys *.cal *.diag);;All files (*)")
        if path:
            self.open_file(path)

    def _browse_folder(self) -> None:
        start = self.file_edit.text() or "."
        target = paths.resolve(start)
        if target.is_file():
            start = paths.display(target.parent)
        path = QFileDialog.getExistingDirectory(
            self, "Open a folder of factory data files",
            str(paths.resolve(start)))
        if path:
            self.open_file(path)

    def open_file(self, path: str) -> None:
        self.file_edit.setText(paths.display(path))
        self.inspect()

    def _clear(self) -> None:
        self._raw = b""
        self.view.setPlainText("")
        self.hex.setPlainText("")
        self.fields.setRowCount(0)

    def inspect(self, quiet: bool = False) -> None:
        text = self.file_edit.text().strip()
        self._clear()
        set_tone(self.hint, "")
        if not text:
            self.pill.setText("")
            self.hint.setText("Drop a file or a folder anywhere in this "
                              "window to check it.")
            return
        path = paths.resolve(text)
        if path.is_dir():
            self._inspect_folder(path, quiet)
        else:
            self._inspect_file(path, quiet)

    def _inspect_folder(self, folder: Path, quiet: bool) -> None:
        try:
            verdicts = verify_folder(folder)
        except (OSError, ValueError, KeyError) as exc:
            self.pill.setText("invalid")
            set_tone(self.pill, "danger")
            detail = paths.message(exc, folder)
            self.hint.setText(detail)
            set_tone(self.hint, "danger")
            if not quiet:
                self.window_.log(f"Inspect: {detail}")
            return
        self.view_combo.setCurrentIndex(0)
        if not verdicts:
            self.pill.setText("no files")
            set_tone(self.pill, "warning")
            self.hint.setText(f"No .sys, .cal or .diag files in "
                              f"{paths.display(folder)}.")
            set_tone(self.hint, "warning")
            return
        failed = [v for v in verdicts if not v.ok]
        width = max(len(v.name) for v in verdicts)
        self.view.setPlainText("\n".join(
            f"{'ok  ' if v.ok else 'FAIL'}  {v.name:<{width}}  {v.detail}"
            for v in sorted(verdicts, key=lambda v: (v.ok, v.name))))
        has_manifest = (folder / MANIFEST_NAME).is_file()
        if failed:
            self.pill.setText(f"{len(failed)} of {len(verdicts)} failed")
            set_tone(self.pill, "danger")
        else:
            self.pill.setText(f"{plural(len(verdicts), 'file')} ok")
            set_tone(self.pill, "success")
        self.hint.setText(
            "Header and payload CRCs checked"
            + (f", and every file compared with {MANIFEST_NAME}."
               if has_manifest else
               f". No {MANIFEST_NAME} here, so changed, missing or extra "
               "files cannot be told apart."))
        if not quiet:
            self.window_.log(
                f"Inspect {paths.display(folder)}: "
                f"{plural(len(verdicts), 'file')}, {len(failed)} failed")
            self.window_.remember(paths.display(folder))

    def _inspect_file(self, path: Path, quiet: bool) -> None:
        try:
            raw = path.read_bytes()
            parsed = ff.parse_file(raw)
            fields = ff.layout(raw)
        except (OSError, ff.FileFormatError) as exc:
            self.pill.setText("invalid")
            set_tone(self.pill, "danger")
            detail = paths.message(exc, path)
            self.hint.setText(detail)
            set_tone(self.hint, "danger")
            if raw_bytes := self._safe_read(path):
                self.hex.setPlainText(ff.hexdump(raw_bytes))
                self._raw = raw_bytes
            if not quiet:
                self.window_.log(f"Inspect: {detail}")
            return
        self._raw = raw
        self.pill.setText(f".{parsed.kind} · CRC ok")
        set_tone(self.pill, "success")
        rows = [
            ("kind", f".{parsed.kind}"),
            ("revision", str(parsed.revision)),
            ("chip UID", parsed.uid.hex().upper() if parsed.bound
             else "not bound"),
            ("size", f"{len(raw)} of {4096} bytes"),
            ("", ""),
            *ff.describe(parsed),
        ]
        width = max(len(name) for name, _ in rows)
        self.view.setPlainText("\n".join(
            f"{name:<{width}}  {value}" if name or value else ""
            for name, value in rows))
        self.fields.setRowCount(len(fields))
        for r, (offset, size, name, value) in enumerate(fields):
            self.fields.setItem(r, 0, table_item(f"{offset:04x}", right=True))
            self.fields.setItem(r, 1, table_item(str(size), right=True))
            self.fields.setItem(r, 2, table_item(name))
            self.fields.setItem(r, 3, table_item(value))
        self.hex.setPlainText(ff.hexdump(raw))
        self.hint.setText(f"{plural(len(parsed.items), 'TLV item')}, header "
                          "and payload CRC verified. Select a row in Fields to "
                          "highlight its bytes in Hex.")
        if not quiet:
            self.window_.log(f"Inspect {paths.display(path)}: .{parsed.kind}, "
                             f"{plural(len(parsed.items), 'item')}, CRC ok")
            self.window_.remember(paths.display(path))

    @staticmethod
    def _safe_read(path: Path) -> bytes:
        try:
            return path.read_bytes()[:4096]
        except OSError:
            return b""

    def _field_selected(self) -> None:
        """Select the bytes of a field in the hex view."""
        rows = self.fields.selectionModel().selectedRows()
        if not rows or not self._raw:
            return
        offset = int(self.fields.item(rows[0].row(), 0).text(), 16)
        size = int(self.fields.item(rows[0].row(), 1).text())
        # Each hex line is "oooo  " then 16 bytes of 3 characters each.
        per_line, prefix = 16, 6

        def column(byte: int) -> int:
            return prefix + (byte % per_line) * 3

        cursor = self.hex.textCursor()
        block = self.hex.document().findBlockByNumber(offset // per_line)
        cursor.setPosition(block.position() + column(offset))
        last = offset + size - 1
        end_block = self.hex.document().findBlockByNumber(last // per_line)
        cursor.setPosition(end_block.position() + column(last) + 2,
                           cursor.MoveMode.KeepAnchor)
        self.hex.setTextCursor(cursor)
        self.hex.ensureCursorVisible()


def build_pages(window) -> list[Page]:
    sys_g, cal_g, diag_g = (GENERATORS[k] for k in ("sys", "cal", "diag"))
    pages: list[Page] = [
        GeneratorPage(
            window, sys_g, "chip",
            "Serial, product, versions, batch, date and MAC of each unit, "
            "from a CSV with one row per unit.", ".sys · one row per unit"),
        GeneratorPage(
            window, cal_g, "sliders",
            "Gain and offset per channel, temperature reference, date and "
            "operator, from a CSV with one row per channel.",
            ".cal · one row per channel"),
        GeneratorPage(
            window, diag_g, "pulse",
            "Fault map, counters and log setup, from a CSV of fault, "
            "counter and log rows. An id of * applies to every unit.",
            ".diag · fault map"),
        InspectPage(window),
    ]
    # The Units page imports this module, so it is added here.
    from .units_page import UnitsPage
    pages.insert(len(pages) - 1, UnitsPage(window))
    return pages
