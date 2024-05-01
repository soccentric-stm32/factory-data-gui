"""Dialog that adds a run of consecutive units to the .sys CSV."""

from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from core import batch
from core.generators import CsvError


class BatchDialog(QDialog):
    """Collects the first id, serial and MAC and how many units to add."""

    def __init__(self, parent, target_name: str, defaults: dict[str, str]) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Batch of Units")
        self.setMinimumWidth(420)
        self.rows: list[dict[str, str]] = []

        self.count = QSpinBox()
        self.count.setRange(1, 10_000)
        self.count.setValue(int(defaults.get("count", 10)))
        self.fields: dict[str, QLineEdit] = {}
        form = QFormLayout()
        form.addRow("Units", self.count)
        for key, label, fallback in (
            ("first_id", "First id", "SC0001"),
            ("first_serial", "First serial", "SC767-2611-00001"),
            ("product", "Product", "SC767"),
            ("hw_version", "Hardware version", "B"),
            ("fw_version", "Firmware version", "0.1.0"),
            ("batch", "Batch", "2611A"),
            ("mfg_date", "Manufacturing date", date.today().isoformat()),
            ("first_mac", "First MAC", "02:00:00:00:00:01"),
            ("notes", "Notes (optional)", ""),
        ):
            edit = QLineEdit(defaults.get(key, fallback))
            self.fields[key] = edit
            form.addRow(label, edit)

        self.message = QLabel(f"Appends to {target_name}. Ids, serials and MACs count up by one.")
        self.message.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Add Units")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.message)
        layout.addWidget(buttons)

    def values(self) -> dict[str, str]:
        out = {key: edit.text().strip() for key, edit in self.fields.items()}
        out["count"] = str(self.count.value())
        return out

    def _accept(self) -> None:
        values = self.values()
        count = int(values.pop("count"))
        try:
            self.rows = batch.sys_batch(count=count, **values)
        except CsvError as exc:
            self.message.setText(f"<span style='color:#c0392b'>{exc}</span>")
            return
        self.accept()
