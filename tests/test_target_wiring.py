"""The machine target, wired through the pipeline, the CLI and the MCP surface.

Nothing here needs Blender or a slicer CLI: the model script is replaced with a
cube on disk, and each job stops at the dry run, which is where the target,
profiles and plate are already resolved.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from conftest import write_cube_stl
from print3d import cli, pipeline, targets


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PRINT3D_FITS", str(tmp_path / "fits.json"))
    monkeypatch.delenv("PRINT3D_TARGET", raising=False)
    return tmp_path


@pytest.fixture
def cube_model(monkeypatch):
    """A 20 mm cube instead of a Blender run."""

    def model(script, output, **kwargs):
        write_cube_stl(output, 20.0)
        return {"mesh": str(output), "size_mm": [20.0, 20.0, 20.0]}

    monkeypatch.setattr(pipeline, "run_model_script", model)


def _script(tmp_path: Path) -> Path:
    path = tmp_path / "model.py"
    path.write_text("# The mesh comes from the monkeypatched run_model_script.\n", encoding="utf-8")
    return path


def _cc2_profiles(root: Path) -> Path:
    """A stand-in for ElegooSlicer's installed profiles: the files, no `inherits` resolved.

    The filament profile deliberately carries no `filament_type`, the way
    Elegoo's CC2 presets inherit it from the profile they derive from.
    """
    target = targets.load("cc2")
    files = {
        target.machine_profile: {"name": "Elegoo Centauri Carbon 2 0.4 nozzle"},
        target.process_profile: {"name": "0.20mm Standard @Elegoo CC2 0.4 nozzle"},
        target.materials["PLA Basic"]: {"name": "Elegoo PLA Basic @ECC2", "inherits": "Elegoo PLA"},
        target.materials["PETG"]: {"name": "Elegoo PETG @ECC2", "inherits": "Elegoo PLA"},
        # The profile the CC2 presets inherit their filament_type from. A colour
        # copy inlines the chain, so a stand-in for the install has to resolve.
        "Elegoo/filament/base/Elegoo PLA.json": {
            "name": "Elegoo PLA",
            "filament_type": ["PLA"],
            "filament_colour": ["#FFFFFF"],
        },
    }
    for relative, payload in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return root


def test_report_carries_the_target(tmp_path, cube_model):
    report = pipeline.run_job(
        "target wiring cube", script=_script(tmp_path), jobs_dir=tmp_path / "jobs", execute=False
    )
    assert report["status"] == "dry_run"
    assert report["target"]["key"] == "x2d"
    assert report["slicer_profiles"]["source"] == "pinned"
    assert report["plate"] == "Textured PEI Plate"
    assert report["slice_plan"]["target"]["key"] == "x2d"


def test_cc2_job_resolves_the_elegoo_profile_paths(tmp_path, monkeypatch, cube_model):
    monkeypatch.setenv("PRINT3D_TARGET", "cc2")
    monkeypatch.setenv("ELEGOO_PROFILES_ROOT", str(_cc2_profiles(tmp_path / "elegoo")))

    report = pipeline.run_job(
        "cc2 wiring cube", script=_script(tmp_path), jobs_dir=tmp_path / "jobs", execute=False
    )
    assert report["target"]["key"] == "cc2"
    assert report["slicer_profiles"]["source"] == "slicer"
    assert report["slicer_profiles"]["machine"].endswith("Elegoo Centauri Carbon 2 0.4 nozzle.json")
    assert "Elegoo" in report["slicer_profiles"]["process"]
    assert Path(report["slicer_profiles"]["filament"]).is_file()
    assert report["plate"] == "Textured PEI Plate"
    assert report["slice_plan"]["target"]["key"] == "cc2"


def test_explicit_target_picks_the_machine_without_leaking(tmp_path, monkeypatch, cube_model):
    monkeypatch.setenv("ELEGOO_PROFILES_ROOT", str(_cc2_profiles(tmp_path / "elegoo")))

    report = pipeline.run_job(
        "cc2 by argument",
        script=_script(tmp_path),
        jobs_dir=tmp_path / "jobs",
        execute=False,
        target=targets.load("cc2"),
        plate="smooth",
        material="PETG",
    )
    assert report["target"]["key"] == "cc2"
    assert report["material"] == "PETG"
    assert report["plate"] == "Textured PEI Plate"  # the "smooth" alias, as the CC2 spells it
    assert report["slice_plan"]["target"]["key"] == "cc2"
    assert "PRINT3D_TARGET" not in os.environ  # scoped to the run, not left behind


def test_a_two_colour_cc2_job_is_an_error_not_a_colour_promise(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINT3D_TARGET", "cc2")
    monkeypatch.setenv("ELEGOO_PROFILES_ROOT", str(_cc2_profiles(tmp_path / "elegoo")))
    script = _script(tmp_path)

    def model(script, output, **kwargs):
        body = write_cube_stl(output.parent / "parts" / "body.stl", 20.0)
        cap = write_cube_stl(output.parent / "parts" / "cap.stl", 20.0)
        write_cube_stl(output.parent / "assembly" / "body.stl", 20.0)
        write_cube_stl(output.parent / "assembly" / "cap.stl", 20.0)
        return {
            "mesh": str(output),
            "size_mm": [20.0, 20.0, 20.0],
            "parts": [
                {"name": "body", "color": "white", "print_stl": str(body), "print_size_mm": [20.0] * 3, "settings": {}},
                {"name": "cap", "color": "red", "print_stl": str(cap), "print_size_mm": [20.0] * 3, "settings": {}},
            ],
            "objects": [
                {"name": "body", "parts": ["body"], "plate": 1, "stl": str(body)},
                {"name": "cap", "parts": ["cap"], "plate": 1, "stl": str(cap)},
            ],
            "fits": [],
            "declared_fits": [],
        }

    monkeypatch.setattr(pipeline, "run_model_script", model)
    report = pipeline.run_job(
        "two colour cc2 part", script=script, jobs_dir=tmp_path / "jobs", execute=False
    )
    assert report["target"]["key"] == "cc2"
    colours = [note for note in report["advice"] if note["code"] == "colours"]
    assert colours and colours[0]["severity"] == "error"
    assert "one filament per slice" in colours[0]["message"]
    assert report["severity"] == "error"


def test_cli_targets_lists_both_machines(monkeypatch, capsys):
    assert cli.main(["targets"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert {entry["key"] for entry in payload["targets"]} == {"x2d", "cc2"}
    assert payload["active"] == "x2d"
