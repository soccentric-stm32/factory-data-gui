"""The app keeps its own paths relative to the folder it lives in."""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from core import paths
from core.workspace import ENV_REPO, Workspace, default_repo_path
from gui.pages import DEFAULT_OUTPUT


def test_defaults_are_relative(monkeypatch):
    monkeypatch.delenv(ENV_REPO, raising=False)
    assert not default_repo_path().is_absolute()
    assert not DEFAULT_OUTPUT.is_absolute()
    workspace = Workspace(default_repo_path())
    assert not workspace.root.is_absolute()
    assert not workspace.csv_path("sys").is_absolute()
    assert workspace.resolved_root.is_absolute()


def test_relative_paths_resolve_against_the_app_folder():
    assert paths.resolve("csv/sys.csv") == paths.APP_DIR / "csv" / "sys.csv"
    assert paths.display(paths.APP_DIR / "csv" / "sys.csv") == "csv/sys.csv"


def test_workspace_shows_relative_but_uses_an_absolute_root(tmp_path):
    workspace = Workspace(tmp_path / "artifacts")
    assert workspace.root.is_absolute()
    assert not paths.shown(workspace.root).is_absolute()
    assert not pathlib.Path(paths.display(workspace.csv_path("sys"))).is_absolute()


def test_default_repo_is_inside_the_workspace_folder(monkeypatch):
    from core.workspace import REPO_NAME, WORKSPACE_DIR
    monkeypatch.delenv(ENV_REPO, raising=False)
    assert default_repo_path() == pathlib.Path(WORKSPACE_DIR) / REPO_NAME


def test_workspace_folder_is_created_when_missing(monkeypatch, tmp_path):
    from core import paths as core_paths
    from core.workspace import ensure_workspace_dir
    monkeypatch.setattr(core_paths, "APP_DIR", tmp_path)
    folder = ensure_workspace_dir()
    assert folder == tmp_path / "workspace" and folder.is_dir()
    assert ensure_workspace_dir() == folder    # idempotent
