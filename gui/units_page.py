"""The Units page: every unit of the repository and how far it has got.

Author: Sandesh Ghimire <sandesh@soccentric.com>

Shows ``units.csv`` of the artifacts clone, filters it by text and status,
and moves the selected unit to its next status.  Generating a .sys batch adds
its units; the factory station and the command line set the later states.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QWidget,
)

from core import paths
from core.units import COLUMNS, STATUSES, Registry, RegistryError, can_move

from .pages import Page, plural, table_item
from .widgets import Card, label

HEADERS = ("Serial", "Id", "Product", "HW", "Batch", "MAC", "Chip UID", "Status",
           "Updated", "Note")


class UnitsPage(Page):
    key = "units"
    title = "Units"
    subtitle = ("Every unit generated in this repository, with its serial, MAC, "
                "chip UID and status. Serials and MACs are never reused.")
    icon_name = "app"
    nav_subtitle = "Registry and status"

    def __init__(self, window) -> None:
        super().__init__(window)
        self.registry: Registry | None = None
        self._build()

    def _build(self) -> None:
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find serial, id, MAC, UID, batch")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(260)
        self.search.textChanged.connect(self._fill)
        self.status_filter = QComboBox()
        self.status_filter.addItem("All statuses", "")
        for status in STATUSES:
            self.status_filter.addItem(status, status)
        self.status_filter.currentIndexChanged.connect(self._fill)
        self.count = label("", "Pill")
        reload_button = QPushButton("Reload")
        reload_button.setObjectName("Secondary")
        reload_button.clicked.connect(self.reload_units)

        self.table = QTableWidget()
        self.table.setObjectName("Table")
        self.table.setColumnCount(len(HEADERS))
        self.table.setHorizontalHeaderLabels(list(HEADERS))
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.table.setMinimumHeight(260)
        self.table.itemSelectionChanged.connect(self._selected)

        head = QWidget()
        row = QHBoxLayout(head)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        for widget in (self.count, self.status_filter, self.search,
                       reload_button):
            row.addWidget(widget)
        units = Card("Units", head)
        units.add_widget(self.table)
        self.column.addWidget(units, 1)

        self.next_status = QComboBox()
        self.note = QLineEdit()
        self.note.setPlaceholderText("Note (optional)")
        self.apply_button = QPushButton("Set Status")
        self.apply_button.clicked.connect(self._apply)
        self.hint = label("", "Hint")
        self.hint.setWordWrap(True)
        change = Card("Selected unit")
        change.add_row("Move to", self.next_status, self.note, self.apply_button,
                       stretch=1)
        change.add_row(None, self.hint, stretch=0)
        self.column.addWidget(change)
        self.apply_button.setEnabled(False)
        self.next_status.setEnabled(False)

    # ---- data ---------------------------------------------------------

    def refresh(self) -> None:
        self.reload_units()

    def reload_units(self) -> None:
        self.registry = self.window_.project_registry()
        self._fill()

    def _visible(self):
        if self.registry is None:
            return []
        wanted = self.status_filter.currentData() or ""
        units = self.registry.find(self.search.text())
        if wanted:
            units = [u for u in units if u.status == wanted]
        return sorted(units, key=lambda u: u.serial)

    def _fill(self, *_args) -> None:
        keep = self._current_serial()
        units = self._visible()
        self.table.setRowCount(len(units))
        for r, unit in enumerate(units):
            for c, name in enumerate(COLUMNS):
                self.table.setItem(r, c, table_item(getattr(unit, name)))
            if unit.serial == keep:
                self.table.selectRow(r)
        total = len(self.registry.units) if self.registry else 0
        counts = self.registry.counts() if self.registry else {}
        detail = ", ".join(f"{n} {s}" for s, n in counts.items() if n)
        self.count.setText(f"{plural(len(units), 'unit')} of {total}")
        self.count.setToolTip(detail)
        if self.registry is None:
            self.hint.setText("Clone the artifacts repository to see its units.")
        elif not total:
            self.hint.setText(
                f"No units yet. Generate a .sys batch and its units appear in "
                f"{paths.display(self.window_.workspace.units_path)}.")
        self._selected()

    def _current_serial(self) -> str:
        rows = self.table.selectionModel().selectedRows() if self.table.model() else []
        if not rows:
            return ""
        item = self.table.item(rows[0].row(), 0)
        return item.text() if item else ""

    def _selected(self) -> None:
        serial = self._current_serial()
        unit = self.registry.units.get(serial) if self.registry and serial else None
        self.next_status.clear()
        if unit is None:
            self.apply_button.setEnabled(False)
            self.next_status.setEnabled(False)
            if self.registry is not None and self.registry.units:
                self.hint.setText("Select a unit to change its status.")
            return
        options = [s for s in STATUSES if s != unit.status and can_move(unit.status, s)]
        self.next_status.addItems(options)
        usable = bool(options)
        self.apply_button.setEnabled(usable)
        self.next_status.setEnabled(usable)
        self.hint.setText(
            f"{unit.serial} ({unit.id}) is {unit.status}"
            + ("" if usable else "; it has no further status."))

    def _apply(self) -> None:
        serial = self._current_serial()
        status = self.next_status.currentText()
        if not serial or not status or self.registry is None:
            return
        try:
            self.registry.set_status(serial, status, self.note.text().strip())
            self.registry.save()
        except (RegistryError, OSError) as exc:
            self.window_.error("Cannot change the status", str(exc))
            return
        self.note.clear()
        self.window_.log(f"{serial}: {status}")
        self._fill()
        self.window_.workspace_changed()

