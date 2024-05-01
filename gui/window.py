"""Main window of the factory data GUI.

Sidebar: the three generators (System info, Calibration, Diagnostics) and the
Inspect tool.  Content: the selected page above a shared output log.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QGuiApplication,
    QKeySequence,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core import capi, paths
from core.generators import CsvError, detect_kind, read_csv
from core.rules import Rules, RulesError
from core.units import Registry, RegistryError
from core.workspace import Workspace, WorkspaceError, default_repo_path, ensure_workspace_dir

from . import icons, soc_native
from . import soc_theme as theme
from .pages import GeneratorPage, InspectPage, Page, build_pages
from .widgets import NavItem, label
from .workspace_bar import Task, WorkspaceBar

FluentNavItem = soc_native.fluent_nav(NavItem)

APP_NAME = "Factory Data"
VERSION = "1.1"
MAX_RECENT = 10
FACTORY_SUFFIXES = (".sys", ".cal", ".diag")


def badge_pixmap(glyph: str, accent: str, size: int) -> QPixmap:
    """Rounded accent tile with a glyph, the app badge in the sidebar."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QPainter

    ratio = 2.0
    pix = QPixmap(int(size * ratio), int(size * ratio))
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(accent))
    painter.drawRoundedRect(QRectF(0, 0, size * ratio, size * ratio),
                            9 * ratio, 9 * ratio)
    inset = size * ratio * 0.24
    icons.paint(painter, glyph,
                QRectF(inset, inset, size * ratio - 2 * inset,
                       size * ratio - 2 * inset), "#ffffff", 2.0)
    painter.end()
    pix.setDevicePixelRatio(ratio)
    return pix


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        soc_native.prepare_window(self)
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1000, 700)
        self.settings = QSettings("soccentric", "factory-data")
        self.setAcceptDrops(True)
        self.workspace: Workspace | None = None
        self._batch_defaults: dict[str, str] = {}
        self._tasks: list[Task] = []
        self.pages: list[Page] = build_pages(self)
        self._build_ui()
        self._build_menus()
        self._load_settings()
        self._open_workspace()
        self.apply_theme()
        for page in self.pages:
            page.refresh()
        self.switch_page(self._initial_page)
        if self.workspace.cloned:
            self._sync_workspace()
        else:
            self.log(f"No artifacts clone in {paths.display(self.workspace.root)}"
                     "; use Clone in the Artifacts bar.")
            self._refresh_bar()
        QGuiApplication.styleHints().colorSchemeChanged.connect(
            lambda _scheme: self.apply_theme())

    # ---- layout ---------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._sidebar())

        content = QWidget()
        content.setObjectName("Content")
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 16)
        column.setSpacing(0)

        self.bar = WorkspaceBar(self)
        column.addWidget(self.bar)

        self.stack = QStackedWidget()
        for page in self.pages:
            scroll = QScrollArea()
            scroll.setObjectName("PageScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)

        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)
        self.splitter.addWidget(self.stack)
        self.splitter.addWidget(self._console())
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 1)
        column.addWidget(self.splitter, 1)
        row.addWidget(content, 1)
        self.setCentralWidget(root)

    def _sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(248)
        column = QVBoxLayout(side)
        column.setContentsMargins(12, 16, 12, 12)
        column.setSpacing(2)

        head = QHBoxLayout()
        head.setContentsMargins(8, 0, 8, 0)
        head.setSpacing(12)
        self.app_badge = QLabel()
        self.app_badge.setFixedSize(36, 36)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(label(APP_NAME, "AppTitle"))
        titles.addWidget(label("sys · cal · diag files", "AppSubtitle"))
        head.addWidget(self.app_badge)
        head.addLayout(titles, 1)
        column.addLayout(head)
        column.addSpacing(24)

        def section(text: str) -> None:
            heading = label(text, "SidebarSection")
            heading.setContentsMargins(8, 0, 0, 4)
            column.addWidget(heading)

        section("GENERATE")
        for index, page in enumerate(self.pages):
            if isinstance(page, InspectPage):
                column.addSpacing(16)
                section("TOOLS")
            page.nav = FluentNavItem(page.icon_name, page.title,
                                     page.nav_subtitle)
            page.nav.clicked.connect(
                lambda _checked=False, i=index: self.switch_page(i))
            column.addWidget(page.nav)
        column.addStretch(1)
        column.addWidget(label(f"Version {VERSION}", "Caption"))
        return side

    def _console(self) -> QFrame:
        box = QFrame()
        box.setObjectName("Card")
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(16, 10, 8, 8)
        head.setSpacing(4)
        head.addWidget(label("Output", "CardTitle"))
        head.addStretch(1)
        self.copy_button = QPushButton()
        self.copy_button.setObjectName("IconButton")
        self.copy_button.setToolTip("Copy the output")
        self.copy_button.clicked.connect(self.copy_output)
        self.clear_button = QPushButton()
        self.clear_button.setObjectName("IconButton")
        self.clear_button.setToolTip("Clear the output (Ctrl+K)")
        self.clear_button.clicked.connect(self.clear_output)
        head.addWidget(self.copy_button)
        head.addWidget(self.clear_button)
        column.addLayout(head)
        self.console = QPlainTextEdit()
        self.console.setObjectName("Console")
        self.console.setReadOnly(True)
        self.console.setFont(theme.mono_font())
        self.console.setMaximumBlockCount(5000)
        column.addWidget(self.console, 1)
        outer = QVBoxLayout()
        outer.setContentsMargins(20, 0, 20, 0)
        wrapper = QFrame()
        wrapper.setLayout(outer)
        wrapper.setObjectName("Content")
        outer.addWidget(box)
        return wrapper

    # ---- menus ----------------------------------------------------------

    def _build_menus(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("&File")
        open_action = QAction("Open CSV…", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self._open_csv)
        file_menu.addAction(open_action)
        inspect_action = QAction("Inspect File or Folder…", self)
        inspect_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        inspect_action.triggered.connect(self._open_inspect)
        file_menu.addAction(inspect_action)
        self.recent_menu = file_menu.addMenu("Open Recent")
        self._fill_recent()
        batch_action = QAction("New Batch of Units…", self)
        batch_action.setShortcut(QKeySequence("Ctrl+Shift+N"))
        batch_action.triggered.connect(self.new_batch)
        file_menu.addAction(batch_action)
        sample_action = QAction("Write Sample CSV…", self)
        sample_action.triggered.connect(
            lambda: self.current_page().write_sample())
        file_menu.addAction(sample_action)
        capi_action = QAction("Generate Firmware C API…", self)
        capi_action.setToolTip(
            "Write factory_data.h/.c: get/set/commit functions for the "
            ".sys, .cal and .diag blocks")
        capi_action.triggered.connect(self.generate_c_api)
        file_menu.addAction(capi_action)
        file_menu.addSeparator()
        repo_action = QAction("Artifacts Repository…", self)
        repo_action.triggered.connect(self.choose_workspace)
        file_menu.addAction(repo_action)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.setMenuRole(QAction.QuitRole)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        edit_menu = bar.addMenu("&Edit")
        for text, key, method in (("Undo", QKeySequence.Undo, "undo"),
                                  ("Redo", QKeySequence.Redo, "redo"),
                                  (None, None, None),
                                  ("Cut", QKeySequence.Cut, "cut"),
                                  ("Copy", QKeySequence.Copy, "copy"),
                                  ("Paste", QKeySequence.Paste, "paste"),
                                  ("Select All", QKeySequence.SelectAll,
                                   "selectAll")):
            if text is None:
                edit_menu.addSeparator()
                continue
            action = QAction(text, self)
            action.setShortcut(key)
            action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            action.triggered.connect(
                lambda _checked=False, m=method: self._route_edit(m))
            edit_menu.addAction(action)

        view_menu = bar.addMenu("&View")
        self.page_actions: list[QAction] = []
        group = QActionGroup(self)
        for index, page in enumerate(self.pages):
            action = QAction(page.title, self)
            action.setCheckable(True)
            action.setShortcut(QKeySequence(f"Ctrl+{index + 1}"))
            action.triggered.connect(
                lambda _checked=False, i=index: self.switch_page(i))
            group.addAction(action)
            view_menu.addAction(action)
            self.page_actions.append(action)
        view_menu.addSeparator()
        clear_action = QAction("Clear Output", self)
        clear_action.setShortcut(QKeySequence("Ctrl+K"))
        clear_action.triggered.connect(self.clear_output)
        view_menu.addAction(clear_action)

        gen_menu = bar.addMenu("&Generate")
        self.generate_action = QAction("Generate File", self)
        self.generate_action.setShortcut(QKeySequence("Ctrl+Return"))
        self.generate_action.triggered.connect(
            lambda: self.current_page().run_primary())
        self.generate_all_action = QAction("Generate All Records", self)
        self.generate_all_action.setShortcut(QKeySequence("Ctrl+Shift+Return"))
        self.generate_all_action.triggered.connect(
            lambda: self.current_page().run_all())
        reload_action = QAction("Reload CSV", self)
        reload_action.setShortcut(QKeySequence.Refresh)
        reload_action.triggered.connect(self._reload)
        for action in (self.generate_action, self.generate_all_action):
            gen_menu.addAction(action)
        gen_menu.addSeparator()
        gen_menu.addAction(reload_action)

        help_menu = bar.addMenu("&Help")
        about_action = QAction(f"About {APP_NAME}", self)
        about_action.setMenuRole(QAction.AboutRole)
        about_action.triggered.connect(self._about)
        help_menu.addAction(about_action)

    # ---- artifacts repository -------------------------------------------

    def _open_workspace(self) -> None:
        """Point the pages at the artifacts clone; no network here."""
        try:
            ensure_workspace_dir()
        except OSError as exc:
            self.log(f"Cannot create the workspace folder: {exc}")
        saved = self.settings.value("workspace/repo", "", type=str)
        if saved:
            portable = paths.display(saved)
            if portable != saved:
                self.settings.setValue("workspace/repo", portable)
            saved = portable
        self.workspace = Workspace(
            paths.shown(saved) if saved else default_repo_path())
        product = self.settings.value("workspace/product", "", type=str)
        batch = self.settings.value("workspace/batch", "", type=str)
        if product and batch and batch in self.workspace.batches(product):
            self.workspace.select(product, batch)
        self._apply_workspace()

    def _apply_workspace(self, force: bool = False) -> None:
        ws = self.workspace
        if ws is None or not ws.cloned:
            return
        try:
            made = ws.ensure_layout()
        except OSError as exc:
            self.log(f"Cannot prepare {paths.display(ws.base)}: "
                     f"{paths.message(exc, ws.base)}")
            return
        for name in made:
            self.log(f"Created {name} from the built-in sample")
        for page in self.pages:
            if isinstance(page, GeneratorPage):
                page.apply_workspace(ws, force=force)

    def _run(self, text: str, fn, done=None) -> None:
        """Run git work off the GUI thread; log its result or its error."""
        self.bar.set_busy(text)
        task = Task(fn, self)
        self._tasks.append(task)

        def finish(result) -> None:
            self._tasks.remove(task)
            if done is not None:
                done(result)
            self._refresh_bar()

        def fail(message: str) -> None:
            self._tasks.remove(task)
            ws = self.workspace
            text = paths.message(message, ws.root) if ws else message
            self.log(text)
            self._refresh_bar(problem=text)

        task.done.connect(finish)
        task.failed.connect(fail)
        task.start()

    def _refresh_bar(self, problem: str | None = None) -> None:
        ws = self.workspace
        if ws is None:
            return
        self.bar.set_cloned(ws.cloned)
        self.bar.set_scopes(ws.products(), ws.batches(ws.product),
                            ws.product, ws.batch)
        self.bar.new_batch_button.setEnabled(ws.cloned)
        if problem is not None or not ws.cloned:
            first = (problem or "Not cloned yet").splitlines()[0]
            self.bar.show_problem(paths.display(ws.root), first[:80])
            return
        try:
            self.bar.show_status(paths.display(ws.root), ws.status())
        except WorkspaceError as exc:
            self.bar.show_problem(paths.display(ws.root), str(exc)[:80])

    def _sync_workspace(self) -> None:
        ws = self.workspace

        def done(lines) -> None:
            for line in lines:
                self.log(line)
            self._apply_workspace()
            for page in self.pages:
                if isinstance(page, GeneratorPage):
                    page.reload(quiet=True)

        self._run("Syncing…", ws.sync, done)

    def workspace_changed(self) -> None:
        """Files were written: show the new git state."""
        if self.workspace is not None and not self._tasks:
            self._run("Checking…", lambda: None)

    def workspace_pull(self) -> None:
        self._sync_workspace()

    def workspace_commit(self) -> None:
        ws = self.workspace
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        message, ok = QInputDialog.getText(
            self, "Commit factory data", "Commit message:",
            text=f"Update factory data {stamp}")
        if ok and message.strip():
            self._run("Committing…", lambda: ws.commit(message.strip()),
                      self.log)

    def workspace_push(self) -> None:
        ws = self.workspace
        state = ws.status()
        count = (f"{state.ahead} commit(s)" if state.ahead
                 else "the current branch")
        answer = QMessageBox.question(
            self, "Push to origin?",
            f"Push {count} of {paths.display(ws.root)} to origin?\n\nThe "
            "generated files are uploaded as Git LFS objects.")
        if answer == QMessageBox.Yes:
            self._run("Pushing…", ws.push, self.log)

    def select_scope(self, product: str, batch: str) -> None:
        """Work in another product/batch folder of the clone."""
        ws = self.workspace
        if ws is None or not ws.cloned:
            return
        if product and not batch:
            batches = ws.batches(product)
            batch = batches[-1] if batches else ""
        if batch:
            ws.select(product, batch)
        else:
            ws.select("", "")
        self.settings.setValue("workspace/product", ws.product)
        self.settings.setValue("workspace/batch", ws.batch)
        self._apply_workspace(force=True)
        for page in self.pages:
            if isinstance(page, GeneratorPage):
                page.reload(quiet=True)
        self.units_changed()
        self._refresh_bar()
        self.log(f"Working in {paths.display(ws.base)}")

    def new_product_batch(self) -> None:
        """Create a product/batch folder (samples and rules.csv) and open it."""
        ws = self.workspace
        if ws is None or not ws.cloned:
            return
        products = ws.products()
        product, ok = QInputDialog.getItem(
            self, "New batch", "Product (pick or type a new one):",
            products, max(len(products) - 1, 0), True)
        if not ok or not product.strip():
            return
        batch, ok = QInputDialog.getText(
            self, "New batch", f"Batch name for {product.strip()}:")
        if not ok or not batch.strip():
            return
        try:
            made = ws.create_batch(product.strip(), batch.strip())
        except (WorkspaceError, OSError) as exc:
            self.error("New batch", str(exc))
            return
        for name in made:
            self.log(f"Created {name}")
        self.select_scope(ws.product, ws.batch)

    def project_rules(self) -> Rules:
        """The rules of the selected product (empty when there are none)."""
        ws = self.workspace
        if ws is None or not ws.cloned:
            return Rules()
        try:
            return Rules.load(ws.rules_path)
        except RulesError as exc:
            self.log(f"rules.csv ignored: {exc}")
            return Rules()

    def project_registry(self) -> Registry | None:
        ws = self.workspace
        if ws is None or not ws.cloned:
            return None
        try:
            return Registry.load(ws.units_path)
        except RegistryError as exc:
            self.log(f"units.csv ignored: {exc}")
            return None

    def units_changed(self) -> None:
        """The registry or the scope changed: let the Units page re-read it."""
        for page in self.pages:
            if hasattr(page, "reload_units"):
                page.reload_units()

    def generate_c_api(self) -> None:
        """Write factory_data.h/.c into the clone's c/ folder, or a chosen one."""
        ws = self.workspace
        if ws is not None and ws.cloned:
            folder = ws.c_dir_path
        else:
            chosen = QFileDialog.getExistingDirectory(
                self, "Folder for factory_data.h and factory_data.c",
                str(paths.resolve(".")))
            if not chosen:
                return
            folder = Path(chosen)
        try:
            written = capi.write(folder)
        except OSError as exc:
            self.error("Generate C API", paths.message(exc, folder))
            return
        for path in written:
            self.log(f"Wrote {paths.display(path)}")
        self.workspace_changed()

    def choose_workspace(self) -> None:
        start = (paths.display(self.workspace.root.parent)
                 if self.workspace else ".")
        path = QFileDialog.getExistingDirectory(
            self, "Choose the artifacts clone, or an empty folder to clone "
            "into", str(paths.resolve(start)))
        if not path:
            return
        saved = paths.display(path)
        self.settings.setValue("workspace/repo", saved)
        self.workspace = Workspace(Path(saved))
        self._apply_workspace()
        self._sync_workspace()

    def event(self, event) -> bool:
        if event.type() == QEvent.WindowActivate:
            self.workspace_changed()
        return super().event(event)

    # ---- theme ----------------------------------------------------------

    def apply_theme(self) -> None:
        t = theme.set_dark(theme.system_is_dark())
        qss = theme.stylesheet(t)
        qss = qss.replace("__CHEVRON_UP__", icons.asset("chevron-up",
                                                        t.text_secondary))
        qss = qss.replace("__CHEVRON__", icons.asset("chevron-down",
                                                     t.text_secondary))
        qss = qss.replace("__CHECK__", icons.asset("check", t.on_accent))
        QApplication.instance().setStyleSheet(qss)
        self.app_badge.setPixmap(badge_pixmap("file", t.accent, 36))
        self.copy_button.setIcon(icons.icon("copy", t.text_secondary))
        self.clear_button.setIcon(icons.icon("trash", t.text_secondary))
        for page in self.pages:
            page.apply_theme()

    # ---- pages ----------------------------------------------------------

    def current_page(self) -> Page:
        return self.pages[self.stack.currentIndex()]

    def switch_page(self, index: int) -> None:
        index = max(0, min(index, len(self.pages) - 1))
        self.stack.setCurrentIndex(index)
        page = self.pages[index]
        for i, other in enumerate(self.pages):
            other.nav.setChecked(i == index)
            self.page_actions[i].setChecked(i == index)
        self.setWindowTitle(f"{page.title} — {APP_NAME}")
        generator = isinstance(page, GeneratorPage)
        self.generate_action.setEnabled(generator)
        self.generate_all_action.setEnabled(generator)

    def _open_csv(self) -> None:
        from .pages import pick_open

        page = self.current_page()
        if isinstance(page, GeneratorPage):
            path = pick_open(self, f"Open the {page.gen.kind} CSV",
                             page.csv_edit.text(), "CSV files (*.csv);;All files (*)")
            if path:
                page.open_csv(path)
        elif isinstance(page, InspectPage):
            page._browse()

    def _reload(self) -> None:
        page = self.current_page()
        if isinstance(page, GeneratorPage):
            page.reload()
        elif isinstance(page, InspectPage):
            page.inspect()

    def new_batch(self) -> None:
        """Append a run of consecutive units to the .sys CSV and open it."""
        from core import batch
        from gui.batch_dialog import BatchDialog

        page = next(p for p in self.pages if getattr(getattr(p, "gen", None), "kind", "") == "sys")
        text = page.csv_edit.text().strip()
        if text:
            target = paths.resolve(text)
        elif self.workspace is not None:
            target = paths.resolve(self.workspace.csv_path("sys"))
        else:
            target = paths.resolve("sys.csv")
        dialog = BatchDialog(self, target.name, self._batch_defaults)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            added = batch.append_rows(target, dialog.rows)
        except (CsvError, OSError) as exc:
            self.error("New Batch of Units", paths.message(exc, target))
            return
        self._batch_defaults = dialog.values()
        self.log(f"Added {added} units to {paths.display(target)}")
        self.open_path(str(target))

    def _open_inspect(self) -> None:
        page = next(p for p in self.pages if isinstance(p, InspectPage))
        self.switch_page(self.pages.index(page))
        page._browse()

    def inspect_path(self, path: str) -> None:
        """Show a file or folder on the Inspect page."""
        page = next(p for p in self.pages if isinstance(p, InspectPage))
        self.switch_page(self.pages.index(page))
        page.open_file(path)

    def open_path(self, path: str) -> None:
        """Open whatever was dropped or picked: a CSV, a data file or a folder."""
        target = paths.resolve(path)
        if target.is_dir() or target.suffix.lower() in FACTORY_SUFFIXES:
            self.inspect_path(str(target))
            return
        if target.suffix.lower() != ".csv":
            self.log(f"Cannot open {target.name}: expected a .csv, .sys, "
                     ".cal or .diag file, or a folder")
            return
        try:
            columns, _rows = read_csv(target)
        except CsvError as exc:
            self.log(str(exc))
            return
        kind = detect_kind(columns)
        page = next((p for p in self.pages
                     if isinstance(p, GeneratorPage) and p.gen.kind == kind),
                    None)
        if page is None:
            current = self.current_page()
            if not isinstance(current, GeneratorPage):
                self.log(f"{target.name}: the columns match no file kind "
                         "(sys, cal or diag)")
                return
            page = current
            self.log(f"{target.name}: the columns match no file kind; "
                     f"trying the {page.title} page")
        self.switch_page(self.pages.index(page))
        page.open_csv(str(target))

    # ---- drag and drop --------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and any(
                u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.isLocalFile()]
        if paths:
            self.open_path(paths[0])
            if len(paths) > 1:
                self.log(f"Opened {Path(paths[0]).name}; drop one file at a "
                         "time")
            event.acceptProposedAction()

    # ---- recent files ---------------------------------------------------

    def _recent(self) -> list[str]:
        """Usable (absolute) paths for opening; settings store the relative form."""
        return [str(paths.resolve(p)) for p in self._recent_settings()]

    def _recent_settings(self) -> list[str]:
        value = self.settings.value("recent", [])
        if isinstance(value, str):
            value = [value]
        return [p for p in (value or []) if isinstance(p, str)]

    def remember(self, path: str) -> None:
        key = paths.display(path)
        recent = [key] + [p for p in self._recent_settings() if p != key]
        self.settings.setValue("recent", recent[:MAX_RECENT])
        self._fill_recent()

    def _fill_recent(self) -> None:
        self.recent_menu.clear()
        stored = self._recent_settings()
        portable = [paths.display(p) for p in stored]
        if portable != stored:
            self.settings.setValue("recent", portable[:MAX_RECENT])
        recent = [p for p in portable if paths.resolve(p).exists()]
        for path in recent:
            target = str(paths.resolve(path))
            action = QAction(paths.display(path), self)
            action.triggered.connect(
                lambda _checked=False, p=target: self.open_path(p))
            self.recent_menu.addAction(action)
        if recent:
            self.recent_menu.addSeparator()
            clear = QAction("Clear Menu", self)
            clear.triggered.connect(self._clear_recent)
            self.recent_menu.addAction(clear)
        self.recent_menu.setEnabled(bool(recent))

    def _clear_recent(self) -> None:
        self.settings.setValue("recent", [])
        self._fill_recent()

    # ---- output ---------------------------------------------------------

    def log(self, text: str) -> None:
        self.console.appendPlainText(text)

    def clear_output(self) -> None:
        self.console.clear()

    def copy_output(self) -> None:
        QGuiApplication.clipboard().setText(self.console.toPlainText())

    def error(self, title: str, text: str) -> None:
        self.log(f"{title}: {text}")
        QMessageBox.warning(self, title, text)

    def _about(self) -> None:
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<b>{APP_NAME} {VERSION}</b><br>Generate the .sys, .cal and "
            ".diag factory data files from CSV files, in the format the "
            "factory station and the factory firmware use. Records are "
            "checked line by line, every file is read back after writing, "
            "and a manifest lets Inspect verify a whole folder.")

    @staticmethod
    def _route_edit(method: str) -> None:
        widget = QApplication.focusWidget()
        target = getattr(widget, method, None)
        if callable(target):
            target()

    # ---- settings -------------------------------------------------------

    def _load_settings(self) -> None:
        geometry = self.settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1200, 880)
        state = self.settings.value("window/splitter")
        if state is not None:
            self.splitter.restoreState(state)
        else:
            self.splitter.setSizes([640, 150])
        for page in self.pages:
            page.load(self.settings)
        saved = self.settings.value("page", "sys", type=str)
        self._initial_page = next(
            (i for i, page in enumerate(self.pages) if page.key == saved), 0)

    def closeEvent(self, event) -> None:
        for task in list(self._tasks):
            task.wait()
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/splitter", self.splitter.saveState())
        self.settings.setValue("page", self.current_page().key)
        for page in self.pages:
            page.save(self.settings)
        super().closeEvent(event)
