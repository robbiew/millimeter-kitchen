"""Blender is found without a flag when it sits where its installer put it."""
from pathlib import Path

from mmk import export


def test_explicit_path_wins_even_if_missing():
    assert export.find_blender("/nowhere/blender", env={}) == "/nowhere/blender"


def test_env_var_beats_path(monkeypatch, tmp_path):
    exe = tmp_path / "blender"
    exe.write_text("")
    monkeypatch.setattr(export.shutil, "which", lambda name: "/usr/bin/blender-from-path")
    assert export.find_blender(None, env={"MMK_BLENDER": str(exe)}) == str(exe)
    assert export.find_blender(None, env={}) == "/usr/bin/blender-from-path"


def test_falls_back_to_install_locations(monkeypatch, tmp_path):
    exe = tmp_path / "Blender.app" / "Contents" / "MacOS" / "Blender"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.setattr(export.shutil, "which", lambda name: None)
    monkeypatch.setattr(export, "BLENDER_CANDIDATES", ("/nope/blender", str(exe)))
    assert export.find_blender(None, env={}) == str(exe)


def test_none_when_nothing_exists(monkeypatch):
    monkeypatch.setattr(export.shutil, "which", lambda name: None)
    monkeypatch.setattr(export, "BLENDER_CANDIDATES", ("/nope/blender",))
    assert export.find_blender(None, env={}) is None
