"""Tests for the Antigravity agent wiring in the stash CLI.

Purpose: Antigravity ignores ~/.gemini/settings.json hooks, so the installer
must drop the native plugin into ~/.gemini/config/plugins/stash/ (byte-exact,
skip when unchanged, repair drift) and keep exactly one Stash block in the
GEMINI.md it shares with Gemini CLI. Also pins detection and agent tables.
Usage: uv run pytest -o addopts="" cli/tests/test_install_antigravity.py -q
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cli import main
from cli.main import _agent_present, _install_antigravity, _plugin_installed


@pytest.fixture
def home(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def _plugin_dir(home: Path) -> Path:
    return home / ".gemini" / "config" / "plugins" / "stash"


def test_install_copies_native_plugin(home: Path) -> None:
    status, detail = _install_antigravity(False)
    assert status == "installed"
    assert (_plugin_dir(home) / "plugin.json").is_file()
    assert (_plugin_dir(home) / "hooks.json").is_file()
    assert "new Antigravity conversation" in detail


def test_install_skips_when_unchanged_and_force_reinstalls(home: Path) -> None:
    _install_antigravity(False)
    assert _install_antigravity(False)[0] == "skipped"
    assert _install_antigravity(True)[0] == "installed"


def test_install_repairs_drift(home: Path) -> None:
    _install_antigravity(False)
    hooks = _plugin_dir(home) / "hooks.json"
    hooks.write_text("{}")
    assert _install_antigravity(False)[0] == "installed"
    assert "stash hook run antigravity on_sync" in hooks.read_text()


def test_gemini_md_keeps_single_stash_block(home: Path) -> None:
    _install_antigravity(False)
    _install_antigravity(True)
    main._install_gemini(False)
    text = (home / ".gemini" / "GEMINI.md").read_text()
    assert text.count(main._AGENTS_MD_BEGIN) == 1


def test_detection_uses_antigravity_dir_not_gemini_dir(home: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _cmd: None)
    (home / ".gemini").mkdir()
    assert not _agent_present("antigravity")
    (home / ".gemini" / "antigravity").mkdir()
    assert _agent_present("antigravity")


def test_plugin_installed_reflects_manifest(home: Path) -> None:
    assert not _plugin_installed("antigravity")
    _install_antigravity(False)
    assert _plugin_installed("antigravity")


def test_agent_tables_include_antigravity() -> None:
    from stashai.plugin.session_upload import _SKILLS_DIR_BY_CLIENT

    assert "antigravity" in main._SUPPORTED_AGENTS
    assert main._AGENT_BINARY["antigravity"] == "agy"
    assert main._INSTALLERS["antigravity"] is _install_antigravity
    assert main._HOOK_EVENTS["antigravity"] == ("on_sync", "on_stop")
    assert main._AGENT_LABEL["antigravity"] == "Antigravity"
    assert main.PLUGIN_DATA_DIRS["antigravity"].parts[-3:] == (".stash", "plugins", "antigravity")
    assert _SKILLS_DIR_BY_CLIENT["antigravity"] == "~/.gemini/config/skills"
