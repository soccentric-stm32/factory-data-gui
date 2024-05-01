"""Smoke tests of the GUI on the offscreen Qt platform.

They drive the real pages: load a CSV, read the validation result, generate
every file, and verify the folder with Inspect.
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from core import paths
from core.generators import GENERATORS
from core.manifest import MANIFEST_NAME
from core.units import Registry


@pytest.fixture(scope="module")
def app():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    application.setStyle("Fusion")
    return application


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings

    # Never touch the real artifacts clone: use a throwaway one.
    from tests.test_workspace import make_remote

    remote = make_remote(tmp_path)
    monkeypatch.setenv("FACTORY_DATA_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setenv("FACTORY_DATA_ARTIFACTS_URL", str(remote))

    QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, str(tmp_path / "cfg"))
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path / "cfg"))
    box = QtWidgets.QMessageBox
    monkeypatch.setattr(box, "question", staticmethod(lambda *a, **k: box.Yes))
    monkeypatch.setattr(box, "warning", staticmethod(lambda *a, **k: box.Ok))
    from gui.window import MainWindow

    win = MainWindow()
    win.settings.clear()
    win.show()
    for task in list(win._tasks):
        task.wait()
    app.processEvents()
    yield win
    win.close()


def test_csv_with_errors_shows_lines_and_skips_bad_records(window, tmp_path):
    csv = tmp_path / "units.csv"
    csv.write_text(
        "# units\nid,serial,product,hw_version,fw_version,batch,mfg_date,mac\n"
        "A,1,P,B,1,b,2026-01-01,02:00:00:00:00:01\n"
        "B,2,P,B,1,b,2026-01-01,zz\n"
        "C,1,P,B,1,b,2026-01-01,02:00:00:00:00:03\n"
    )
    window.open_path(str(csv))
    page = window.current_page()
    assert page.gen.kind == "sys"
    errors = [i for i in page.issues if i.severity == "error"]
    assert [(i.ident, i.line) for i in errors] == [("B", 4)]
    assert page.table.item(1, 1).text() == "Error"
    assert page.table.item(0, 1).text() == "OK"
    assert page.issue_table.rowCount() == len(page.issues) == 2

    out = tmp_path / "out"
    page.out_edit.setText(str(out))
    page.run_all()
    assert sorted(p.name for p in out.iterdir()) == ["A.sys", "C.sys", MANIFEST_NAME]

    window.inspect_path(str(out))
    inspect = window.current_page()
    assert inspect.pill.text() == "2 files ok"
    (out / "A.sys").write_bytes((out / "A.sys").read_bytes() + b"x")
    inspect.inspect()
    assert inspect.pill.text() == "1 of 2 failed"


def test_dropped_csv_goes_to_the_page_for_its_columns(window, tmp_path):
    for kind, gen in GENERATORS.items():
        path = tmp_path / f"{kind}.csv"
        path.write_text(gen.sample())
        window.open_path(str(path))
        page = window.current_page()
        assert page.gen.kind == kind
        assert page.issues == []
        assert page.record_combo.count() == len(gen.load(path).ids)


def test_inspect_fields_and_hex(window, tmp_path):
    gen = GENERATORS["cal"]
    csv = tmp_path / "cal.csv"
    csv.write_text(gen.sample())
    data = gen.load(csv)
    blob = gen.build(data, "SC0001")
    target = tmp_path / "SC0001.cal"
    target.write_bytes(blob)
    window.inspect_path(str(target))
    page = window.current_page()
    assert page.pill.text() == ".cal · CRC ok"
    from core import fileformat as ff

    assert page.fields.rowCount() == 7 + len(ff.parse_file(blob).items)
    page.fields.selectRow(7)
    assert page.hex.textCursor().hasSelection()
    assert page.hex.toPlainText().startswith("0000  ")


def test_recent_files_are_remembered(window, tmp_path):
    csv = tmp_path / "sys.csv"
    csv.write_text(GENERATORS["sys"].sample())
    window.open_path(str(csv))
    assert window._recent()[0] == str(csv)
    assert window.recent_menu.isEnabled()


def test_pages_work_inside_the_artifacts_clone(window, tmp_path):
    from PySide6.QtCore import QCoreApplication

    def settle() -> None:
        for _ in range(50):
            QCoreApplication.processEvents()
            if not window._tasks:
                break
            window._tasks[0].wait()

    settle()
    ws = window.workspace
    assert not ws.cloned                       # nothing is cloned unasked
    assert window.bar.pull_button.text() == "Clone"
    window.bar.pull_button.click()
    settle()
    assert ws.cloned, (window.bar.state.text(), window.console.toPlainText())
    assert window.bar.pull_button.text() == "Pull"
    page = window.pages[0]
    assert page.csv_edit.text() == paths.display(ws.csv_path("sys"))
    assert page.out_edit.text() == paths.display(ws.out_dir)
    assert page.issues == []
    page.run_all()
    assert (ws.out_dir / "SC0001.sys").is_file()
    assert (ws.out_dir / MANIFEST_NAME).is_file()
    window.workspace_changed()
    for task in list(window._tasks):
        task.wait()
    QCoreApplication.processEvents()
    assert "changed" in window.bar.state.text()
    assert window.bar.commit_button.isEnabled()


def test_new_batch_appends_units_and_opens_the_csv(window, tmp_path, monkeypatch):
    from gui import batch_dialog

    sys_csv = tmp_path / "units.csv"
    window.switch_page(0)
    page = window.current_page()
    page.csv_edit.setText(str(sys_csv))

    def fake_exec(self):
        self.fields["first_id"].setText("U001")
        self.fields["first_serial"].setText("S-001")
        self.count.setValue(5)
        self._accept()
        return QtWidgets.QDialog.DialogCode.Accepted

    monkeypatch.setattr(batch_dialog.BatchDialog, "exec", fake_exec)
    window.new_batch()
    assert page.table.rowCount() == 5
    assert sys_csv.read_text().count("\n") == 6

    window.new_batch()  # same ids again: refused, file unchanged
    assert sys_csv.read_text().count("\n") == 6


def test_generate_c_api_writes_into_the_clone(window, monkeypatch):
    from PySide6.QtCore import QCoreApplication

    def settle() -> None:
        for _ in range(50):
            QCoreApplication.processEvents()
            if not window._tasks:
                break
            window._tasks[0].wait()

    # never open a real folder dialog if the clone is missing
    monkeypatch.setattr(QtWidgets.QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: ""))
    settle()
    window.bar.pull_button.click()
    settle()
    assert window.workspace.cloned
    window.generate_c_api()
    folder = window.workspace.c_dir_path
    assert (folder / "factory_data.h").is_file()
    assert "fd_sys_get_serial" in (folder / "factory_data.c").read_text()


def _settle(window):
    from PySide6.QtCore import QCoreApplication

    for _ in range(50):
        QCoreApplication.processEvents()
        if not window._tasks:
            break
        window._tasks[0].wait()


def _clone(window, monkeypatch):
    monkeypatch.setattr(QtWidgets.QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: ""))
    _settle(window)
    window.bar.pull_button.click()
    _settle(window)
    assert window.workspace.cloned


def test_products_and_batches_scope_the_pages(window, monkeypatch):
    _clone(window, monkeypatch)
    ws = window.workspace
    ws.create_batch("SC767", "2611A")
    window.select_scope("SC767", "2611A")
    assert (ws.product, ws.batch) == ("SC767", "2611A")
    sys_page = window.pages[0]
    assert sys_page.csv_edit.text() == paths.display(ws.csv_path("sys"))
    assert sys_page.out_edit.text() == paths.display(ws.out_dir)
    assert "products/SC767/2611A" in sys_page.out_edit.text()
    assert window.bar.product_box.currentData() == "SC767"
    assert window.bar.batch_box.currentData() == "2611A"
    # the choice is remembered
    assert window.settings.value("workspace/product", "", type=str) == "SC767"
    # back to the flat layout
    window.select_scope("", "")
    assert ws.scope.parts == () and "products/SC767" not in sys_page.out_edit.text()


def test_generate_all_registers_units_and_the_units_page_shows_them(window, monkeypatch):
    _clone(window, monkeypatch)
    ws = window.workspace
    ws.create_batch("SC767", "2611A")
    window.select_scope("SC767", "2611A")
    sys_page = window.pages[0]
    assert [i for i in sys_page.issues if i.severity == "error"] == []
    sys_page.run_all()
    registry = Registry.load(ws.units_path)
    assert len(registry.units) == 12
    unit = registry.units["SC767-2611-00001"]
    assert (unit.product, unit.batch, unit.status) == ("SC767", "2611A", "generated")
    # a second Generate All has nothing to write
    before = ws.units_path.read_text()
    sys_page.run_all()
    assert ws.units_path.read_text() == before

    units = next(p for p in window.pages if p.key == "units")
    units.reload_units()
    assert units.table.rowCount() == 12
    units.search.setText("00003")
    assert units.table.rowCount() == 1
    units.table.selectRow(0)
    assert "programmed" in [units.next_status.itemText(i)
                            for i in range(units.next_status.count())]
    units.next_status.setCurrentText("programmed")
    units.note.setText("bench 1")
    units._apply()
    assert Registry.load(ws.units_path).units["SC767-2611-00003"].status == "programmed"


def test_product_rules_block_a_record(window, monkeypatch):
    _clone(window, monkeypatch)
    ws = window.workspace
    ws.create_batch("SC767", "2611A")
    window.select_scope("SC767", "2611A")
    path = ws.csv_path_path("sys")
    path.write_text(path.read_text().replace("SC767-2611-00002", "WRONG"))
    sys_page = window.pages[0]
    sys_page.reload(quiet=True)
    assert any("rule: serial 'WRONG'" in i.message for i in sys_page.issues)
    sys_page.run_all()
    out = ws.out_dir_path
    assert (out / "SC0001.sys").is_file() and not (out / "SC0002.sys").exists()
    assert "WRONG" not in Registry.load(ws.units_path).units
