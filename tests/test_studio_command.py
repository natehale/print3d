import subprocess
from pathlib import Path
from typing import Any

import pytest

from print3d import studio, targets
from print3d.studio import SliceRequest, build_project_command, build_slice_command
from print3d.targets import TargetError

SLICER = Path("/opt/elegoo-slicer/AppRun")
MAC_STUDIO = Path("/Applications/BambuStudio.app/Contents/MacOS/BambuStudio")


def _request(tmp_path: Path, **overrides: Any) -> SliceRequest:
    fields: dict[str, Any] = dict(
        input_mesh=tmp_path / "cube.stl",
        output_3mf=tmp_path / "out" / "cube.gcode.3mf",
        output_project_3mf=tmp_path / "out" / "cube.3mf",
        machine=tmp_path / "machine.json",
        process=tmp_path / "process.json",
        filaments=(tmp_path / "filament.json",),
        datadir=tmp_path / "datadir",
        output_dir=tmp_path / "out",
    )
    fields.update(overrides)
    return SliceRequest(**fields)


def test_command_uses_relative_export_and_slice_0(tmp_path: Path):
    request = _request(tmp_path)
    studio_bin = MAC_STUDIO
    command = build_slice_command(studio_bin, request)
    assert "--slice" in command
    assert command[command.index("--slice") + 1] == "0"
    assert command[command.index("--export-3mf") + 1] == "cube.gcode.3mf"
    assert "--export-png" not in command
    assert command[command.index("--orient") + 1] == "1"
    assert "--datadir" in command


def test_project_export_has_no_slice(tmp_path: Path):
    request = _request(tmp_path)
    studio_bin = MAC_STUDIO
    command = build_project_command(studio_bin, request)
    assert "--slice" not in command
    assert command[command.index("--export-3mf") + 1] == "cube.3mf"


def test_x2d_default_command_is_unchanged_by_the_target_layer(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PRINT3D_TARGET", raising=False)
    request = _request(tmp_path)
    command = build_slice_command(MAC_STUDIO, request)
    # No target named and $PRINT3D_TARGET unset: the same command the x2d target builds.
    assert command == build_slice_command(MAC_STUDIO, request, target=targets.load("x2d"))
    assert command[command.index("--curr-bed-type") + 1] == "Textured PEI Plate"
    assert command[command.index("--load-settings") + 1] == (
        f"{request.machine.resolve()};{request.process.resolve()}"
    )


def test_x2d_slice_command_string_is_frozen(tmp_path: Path, monkeypatch):
    """The exact argument list must not drift: downstream reports quote it."""
    monkeypatch.delenv("PRINT3D_TARGET", raising=False)
    command = build_slice_command(MAC_STUDIO, _request(tmp_path))
    assert command == [
        str(MAC_STUDIO),
        "--datadir", str((tmp_path / "datadir").resolve()),
        "--debug", "2",
        "--orient", "1",
        "--arrange", "1",
        "--ensure-on-bed",
        "--load-settings",
        f"{(tmp_path / 'machine.json').resolve()};{(tmp_path / 'process.json').resolve()}",
        "--load-filaments", str((tmp_path / "filament.json").resolve()),
        "--curr-bed-type", "Textured PEI Plate",
        "--outputdir", str((tmp_path / "out").resolve()),
        "--slice", "0",
        "--export-3mf", "cube.gcode.3mf",
        str((tmp_path / "cube.stl").resolve()),
    ]


def test_cc2_loads_settings_filaments_and_default_plate(tmp_path: Path):
    request = _request(tmp_path)
    command = build_slice_command(SLICER, request, target=targets.load("cc2"))
    assert command[command.index("--load-settings") + 1] == (
        f"{request.machine.resolve()};{request.process.resolve()}"
    )
    assert command[command.index("--load-filaments") + 1] == str(request.filaments[0].resolve())
    assert command[command.index("--curr-bed-type") + 1] == "Textured PEI Plate"
    assert command[command.index("--slice") + 1] == "0"


def test_cc2_bed_type_alias_resolves_to_the_plate_name(tmp_path: Path):
    request = _request(tmp_path, bed_type="smooth")
    command = build_slice_command(SLICER, request, target=targets.load("cc2"))
    assert command[command.index("--curr-bed-type") + 1] == "Textured PEI Plate"


def test_cc2_unknown_plate_is_rejected(tmp_path: Path):
    request = _request(tmp_path, bed_type="glass")
    with pytest.raises(TargetError, match="glass"):
        build_slice_command(SLICER, request, target=targets.load("cc2"))


def test_slice_plan_carries_the_target_and_its_plate(tmp_path: Path):
    request = _request(tmp_path, bed_type="textured")
    plan = studio.slice_plan(request, studio=MAC_STUDIO, target=targets.load("cc2"))
    for key in ("studio", "project_command", "command", "request", "open_in_studio", "note", "dry_run"):
        assert key in plan
    assert plan["target"]["key"] == "cc2"
    assert plan["request"]["bed_type"] == "Textured PEI Plate"
    assert plan["note"].startswith("Open the .3mf (not .gcode.3mf) in ElegooSlicer File > Open.")


def _write_exports(command: list[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
    out = Path(command[command.index("--outputdir") + 1])
    name = command[command.index("--export-3mf") + 1]
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_bytes(b"3mf")
    return subprocess.CompletedProcess(command, 0, "", "")


def test_cc2_run_never_repairs_the_3mf(tmp_path: Path, monkeypatch):
    repaired: list[Path] = []
    monkeypatch.setattr(studio, "repair_bambu_3mf", repaired.append)
    monkeypatch.setattr(studio, "_run", _write_exports)
    plan = studio.run_slice(_request(tmp_path), studio=SLICER, target=targets.load("cc2"))
    assert repaired == []
    assert plan["dry_run"] is False
    assert plan["target"]["key"] == "cc2"


def test_x2d_run_repairs_both_3mf(tmp_path: Path, monkeypatch):
    repaired: list[Path] = []
    monkeypatch.setattr(studio, "repair_bambu_3mf", repaired.append)
    monkeypatch.setattr(studio, "_run", _write_exports)
    monkeypatch.delenv("PRINT3D_TARGET", raising=False)
    studio.run_slice(_request(tmp_path), studio=MAC_STUDIO, target=targets.load("x2d"))
    assert len(repaired) == 2
