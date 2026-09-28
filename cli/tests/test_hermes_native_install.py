"""Tests for the native-plugin install path of `_install_hermes`.

On Hermes versions with native plugin support the installer must drop the
plugin into ~/.hermes/plugins/stash/ and REMOVE the legacy shell-hook marker
block in one shot — leaving both wired would stream every event twice. The
plugin install itself is the trust decision: no config.yaml hooks, no
approval flow.
"""

from __future__ import annotations

from pathlib import Path

from cli.main import _install_hermes


def _enable_native(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr("cli.main._hermes_supports_native_plugins", lambda: True)
    # never shell out to the real hermes binary from tests
    import subprocess as sp

    monkeypatch.setattr(sp, "run", lambda cmd, **kw: sp.CompletedProcess(cmd, 0, b"", b""))


_LEGACY_BLOCK = """# stash-plugin:begin
hooks:
  on_session_start:
    - command: "stash hook run hermes on_session_start"
      timeout: 10
# stash-plugin:end
"""


def test_native_install_copies_plugin_dir(monkeypatch, tmp_path: Path) -> None:
    _enable_native(monkeypatch, tmp_path)

    status, detail = _install_hermes(False)

    assert status == "installed"
    plugin_dir = tmp_path / ".hermes" / "plugins" / "stash"
    assert (plugin_dir / "plugin.yaml").is_file()
    assert (plugin_dir / "__init__.py").is_file()
    assert (plugin_dir / "skills" / "stash" / "SKILL.md").is_file()
    assert "restart" in detail.lower()


def test_native_install_removes_legacy_marker_block(monkeypatch, tmp_path: Path) -> None:
    _enable_native(monkeypatch, tmp_path)
    cfg_path = tmp_path / ".hermes" / "config.yaml"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(f"model:\n  provider: nous\n{_LEGACY_BLOCK}")

    status, _ = _install_hermes(False)

    assert status == "installed"
    text = cfg_path.read_text()
    assert "stash-plugin:begin" not in text
    assert "stash hook run" not in text
    # user config survives the removal
    assert "provider: nous" in text


def test_native_install_skips_when_unchanged(monkeypatch, tmp_path: Path) -> None:
    _enable_native(monkeypatch, tmp_path)
    _install_hermes(False)
    plugin_dir = tmp_path / ".hermes" / "plugins" / "stash"
    before = (plugin_dir / "plugin.yaml").read_text()

    status, _ = _install_hermes(False)

    assert status == "skipped"
    assert (plugin_dir / "plugin.yaml").read_text() == before


def test_native_install_refreshes_drifted_files(monkeypatch, tmp_path: Path) -> None:
    _enable_native(monkeypatch, tmp_path)
    _install_hermes(False)
    plugin_dir = tmp_path / ".hermes" / "plugins" / "stash"
    target = plugin_dir / "__init__.py"
    target.write_text("# drifted by a user edit\n")

    status, _ = _install_hermes(False)

    assert status == "installed"
    assert target.read_text() != "# drifted by a user edit\n"


def test_native_install_writes_no_config_yaml_hooks(monkeypatch, tmp_path: Path) -> None:
    _enable_native(monkeypatch, tmp_path)

    _install_hermes(False)

    cfg = tmp_path / ".hermes" / "config.yaml"
    assert not cfg.exists() or "hooks:" not in cfg.read_text()


def test_detection_requires_plugins_subcommand(monkeypatch, tmp_path: Path) -> None:
    """Old Hermes has no `plugins` subcommand — detection must read its exit
    code, not guess from version strings."""
    import subprocess as sp

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return sp.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(sp, "run", fake_run)
    import cli.main as m

    assert m._hermes_supports_native_plugins() is True
    assert calls[0][:3] == ["hermes", "plugins", "list"]


def test_detection_false_when_hermes_missing(monkeypatch, tmp_path: Path) -> None:
    import subprocess as sp

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("no hermes binary")

    monkeypatch.setattr(sp, "run", fake_run)
    import cli.main as m

    assert m._hermes_supports_native_plugins() is False
