"""The strip above the pages that shows the artifacts clone and its git state.

Pull, Commit and Push run git in a worker thread so the window stays
responsive while a clone or an LFS transfer is in progress.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.workspace import WorkspaceError

from .widgets import label


class Task(QThread):
    """Run ``fn`` off the GUI thread; report its result or its error."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], object], parent=None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self._fn())
        except WorkspaceError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # never lose a worker error silently
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class WorkspaceBar(QWidget):
    def __init__(self, window) -> None:
        super().__init__()
        self.setObjectName("Content")
        self.window_ = window
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 12, 20, 8)
        outer.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(8)
        outer.addLayout(row)
        scope_row = QHBoxLayout()
        scope_row.setSpacing(8)
        outer.addLayout(scope_row)
        self.where = label("", "Hint")
        self.state = label("", "Pill")
        self.state.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.where.setMinimumWidth(0)
        row.addWidget(label("Artifacts", "CardTitle"))
        row.addWidget(self.state)
        row.addWidget(self.where, 1)
        self.product_box = QComboBox()
        self.batch_box = QComboBox()
        self.product_box.setToolTip("Product (a folder under products/)")
        self.batch_box.setToolTip("Production batch of the product")
        self.product_box.setMinimumWidth(110)
        self.batch_box.setMinimumWidth(100)
        self.new_batch_button = QPushButton("New batch…")
        self.new_batch_button.setObjectName("Secondary")
        self.new_batch_button.setToolTip(
            "Create a product/batch folder with sample CSVs and rules.csv")
        scope_row.addWidget(label("Product", "Hint"))
        scope_row.addWidget(self.product_box)
        scope_row.addWidget(label("Batch", "Hint"))
        scope_row.addWidget(self.batch_box)
        scope_row.addWidget(self.new_batch_button)
        scope_row.addStretch(1)
        self.product_box.activated.connect(self._product_chosen)
        self.batch_box.activated.connect(self._batch_chosen)
        self.new_batch_button.clicked.connect(window.new_product_batch)
        self.pull_button = QPushButton("Pull")
        self.pull_button.setToolTip("Fetch and fast-forward the artifacts clone")
        self.commit_button = QPushButton("Commit…")
        self.commit_button.setToolTip(
            "Commit the CSVs and generated files (nothing is pushed)")
        self.push_button = QPushButton("Push")
        self.push_button.setToolTip("Push the committed work to origin")
        for button in (self.pull_button, self.commit_button, self.push_button):
            button.setObjectName("Secondary")
            row.addWidget(button)
        self.pull_button.clicked.connect(window.workspace_pull)
        self.commit_button.clicked.connect(window.workspace_commit)
        self.push_button.clicked.connect(window.workspace_push)
        self.set_busy("Not set up")

    NONE = "(flat layout)"

    def set_scopes(self, products: list[str], batches: list[str],
                   product: str, batch: str) -> None:
        """Fill the product and batch lists without raising selection signals."""
        for box, items, current in ((self.product_box, products, product),
                                    (self.batch_box, batches, batch)):
            box.blockSignals(True)
            box.clear()
            if box is self.product_box:
                box.addItem(self.NONE, "")
            for item in items:
                box.addItem(item, item)
            index = box.findData(current)
            box.setCurrentIndex(max(index, 0))
            box.blockSignals(False)
        self.batch_box.setEnabled(bool(product))

    def _product_chosen(self, _index: int) -> None:
        product = self.product_box.currentData() or ""
        self.window_.select_scope(product, "")

    def _batch_chosen(self, _index: int) -> None:
        self.window_.select_scope(self.product_box.currentData() or "",
                                  self.batch_box.currentData() or "")

    def set_busy(self, text: str) -> None:
        self.state.setText(text)
        for button in (self.pull_button, self.commit_button, self.push_button):
            button.setEnabled(False)

    def show_status(self, where: str, state) -> None:
        self.where.setText(where)
        self.where.setToolTip(where)
        self.state.setText(state.summary())
        self.pull_button.setEnabled(True)
        self.commit_button.setEnabled(state.changed > 0)
        self.push_button.setEnabled(
            bool(state.ahead) or state.ahead is None)

    def show_problem(self, where: str, text: str) -> None:
        self.where.setText(where)
        self.state.setText(text)
        self.pull_button.setEnabled(True)
        self.commit_button.setEnabled(False)
        self.push_button.setEnabled(False)

    def set_cloned(self, cloned: bool) -> None:
        """The first button clones until the repository is there."""
        self.pull_button.setText("Pull" if cloned else "Clone")
        self.pull_button.setToolTip(
            "Fetch and fast-forward the artifacts clone" if cloned else
            "Clone the artifacts repository into the workspace folder")
