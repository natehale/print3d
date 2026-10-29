from pathlib import Path
from types import SimpleNamespace

import pytest

from print3d import blender, studio, targets, windows


@pytest.fixture
def windows_env(tmp_path, monkeypatch):
    monkeypatch.setattr(windows, "sys", SimpleNamespace(platform="win32"))
    # Discovery runs through targets for the slicer, so its platform check needs the same stub.
    monkeypatch.setattr(targets, "sys", SimpleNamespace(platform="win32"))
    for name in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)",
                 "BLENDER_BIN", "BAMBU_STUDIO_BIN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(blender, "BLENDER_LOCATIONS", ())
    monkeypatch.setattr(blender.shutil, "which", lambda *a, **kw: None)
    root = tmp_path / "Program Files"
    monkeypatch.setenv("ProgramFiles", str(root))
    return root


def executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path.resolve()


APPS = [
    (blender.find_blender, blender.BlenderError, "BLENDER_BIN",
     "Blender Foundation/Blender 4.2/blender.exe"),
    (studio.find_studio, studio.StudioError, "BAMBU_STUDIO_BIN",
     "Bambu Studio/bambu-studio.exe"),
]


@pytest.mark.parametrize("find,error,env,relative", APPS)
@pytest.mark.parametrize("variable", ["ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"])
def test_finds_standard_installs_without_path_or_override(
    windows_env, monkeypatch, find, error, env, relative, variable
):
    monkeypatch.delenv("ProgramFiles")
    monkeypatch.setenv(variable, str(windows_env))
    expected = executable(windows_env / relative)
    assert find(search_path="") == expected


@pytest.mark.parametrize("find,error,env,relative", APPS)
def test_override_then_path_then_standard_install(
    windows_env, tmp_path, monkeypatch, find, error, env, relative
):
    installed = executable(windows_env / relative)
    override = executable(tmp_path / "portable" / "override.exe")
    on_path = executable(tmp_path / "bin" / "app.exe")
    searched = []

    def which(name, *, path):
        searched.append(path)
        return str(on_path)

    monkeypatch.setattr(blender.shutil, "which", which)
    monkeypatch.setenv(env, str(override))
    assert find(search_path="controlled-path") == override
    monkeypatch.delenv(env)
    assert find(search_path="controlled-path") == on_path
    assert searched == ["controlled-path", "controlled-path"]
    monkeypatch.setattr(blender.shutil, "which", lambda *a, **kw: None)
    monkeypatch.setenv(env, str(tmp_path / "removed.exe"))
    assert find(search_path="") == installed


def test_blender_uses_numeric_version_order_and_skips_incomplete_installs(windows_env):
    base = windows_env / "Blender Foundation"
    executable(base / "Blender 4.9" / "blender.exe")
    expected = executable(base / "Blender 4.10" / "blender.exe")
    (base / "Blender 5.0").mkdir()
    (base / "Blender 6.0" / "blender.exe").mkdir(parents=True)
    assert blender.find_blender(search_path="") == expected


@pytest.mark.parametrize("find,error,env,relative", APPS)
def test_falls_back_from_missing_native_install_to_other_program_files(
    windows_env, tmp_path, monkeypatch, find, error, env, relative
):
    monkeypatch.setenv("ProgramW6432", str(tmp_path / "missing native programs"))
    expected = executable(windows_env / relative)
    assert find(search_path="") == expected


@pytest.mark.parametrize("find,error,env,relative", APPS)
def test_does_not_search_windows_locations_on_other_platforms(
    windows_env, monkeypatch, find, error, env, relative
):
    executable(windows_env / relative)
    monkeypatch.setattr(windows, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(targets, "sys", SimpleNamespace(platform="linux"))
    # Exclude actual macOS programs on the machine running the test.
    monkeypatch.setattr(Path, "is_file", lambda path: path.is_relative_to(windows_env))
    with pytest.raises(error, match=env):
        find(search_path="")


@pytest.mark.parametrize("find,error,env,relative", APPS)
def test_unset_program_files_does_not_search_current_directory(
    windows_env, tmp_path, monkeypatch, find, error, env, relative
):
    monkeypatch.setenv("ProgramFiles", "  ")
    monkeypatch.chdir(tmp_path)
    executable(tmp_path / relative)
    monkeypatch.setattr(Path, "is_file", lambda path: path.is_relative_to(tmp_path))
    with pytest.raises(error, match=env):
        find(search_path="")
