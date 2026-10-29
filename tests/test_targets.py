"""The target layer: which machine a job is for, and the slicer side that reads it."""

from dataclasses import replace

import pytest

from print3d import studio, targets
from print3d.paths import default_profiles_dir
from print3d.targets import TargetError


def test_available_and_default_active_target(monkeypatch):
    monkeypatch.delenv("PRINT3D_TARGET", raising=False)
    assert targets.available() == ("cc2", "x2d")
    assert targets.active_key() == "x2d"
    assert targets.active().key == "x2d"


def test_active_follows_the_environment(monkeypatch):
    monkeypatch.setenv("PRINT3D_TARGET", "cc2")
    assert targets.active_key() == "cc2"
    assert targets.active().label == "Elegoo Centauri Carbon 2"


def test_unknown_target_lists_the_known_ones():
    with pytest.raises(TargetError, match="nope"):
        targets.load("nope")


def test_x2d_is_the_pinned_flattened_multicolour_target():
    target = targets.load("x2d")
    assert target.pinned_profiles == "x2d-0.4"
    assert target.flatten is True
    assert target.repair_3mf is True
    assert target.nozzles == 2
    assert target.colours


def test_cc2_slices_from_the_slicers_own_profiles():
    target = targets.load("cc2")
    assert target.pinned_profiles is None
    assert target.flatten is False
    assert target.repair_3mf is False
    assert target.nozzles == 1
    assert target.binary_env == "ELEGOO_SLICER_BIN"
    assert target.default_material == "PLA Basic"


def test_bed_type_aliases_and_literal_names():
    target = targets.load("cc2")
    assert target.resolve_bed_type("smooth") == "Textured PEI Plate"
    assert target.resolve_bed_type("Cool Plate") == "Cool Plate"
    assert target.resolve_bed_type(None) == "Textured PEI Plate"
    # x2d validates nothing, so any plate name passes through.
    assert targets.load("x2d").resolve_bed_type("anything") == "anything"


def test_unknown_bed_type_lists_the_choices():
    with pytest.raises(TargetError, match="Choose one of"):
        targets.load("cc2").resolve_bed_type("glass")


def test_material_and_colour_resolution():
    target = targets.load("cc2")
    assert target.resolve_material("pla basic") == "PLA Basic"
    assert target.colour_hex("green") == "#00AE42"
    assert target.colour_hex("#aabbcc") == "#AABBCC"
    with pytest.raises(TargetError, match="colour"):
        target.colour_hex("chartreuse")


def test_describe_names_machine_and_slicer():
    line = targets.describe(targets.load("cc2"))
    assert "Elegoo Centauri Carbon 2" in line
    assert "ElegooSlicer" in line


def test_find_slicer_prefers_the_target_env_over_path(tmp_path, monkeypatch):
    override = tmp_path / "elegoo-slicer"
    override.write_bytes(b"")
    on_path = tmp_path / "bin" / "elegoo-slicer"
    on_path.parent.mkdir()
    on_path.write_bytes(b"")
    monkeypatch.setenv("ELEGOO_SLICER_BIN", str(override))
    monkeypatch.setattr("shutil.which", lambda *a, **kw: str(on_path))
    assert studio.find_slicer(targets.load("cc2"), search_path="") == override.resolve()


def test_find_slicer_reports_a_studio_error(monkeypatch):
    # Strip the machine-specific candidate lists so the search cannot win by accident.
    target = replace(targets.load("cc2"), binary_paths=(), windows_dir=())
    monkeypatch.delenv("ELEGOO_SLICER_BIN", raising=False)
    monkeypatch.setattr("shutil.which", lambda *a, **kw: None)
    with pytest.raises(studio.StudioError, match="ELEGOO_SLICER_BIN"):
        studio.find_slicer(target, search_path="")


def test_default_profiles_dir_is_the_pinned_x2d_set(monkeypatch):
    monkeypatch.delenv("PRINT3D_TARGET", raising=False)
    assert default_profiles_dir() == default_profiles_dir(targets.load("x2d"))
    assert default_profiles_dir().name == "x2d-0.4"


def test_default_profiles_dir_raises_for_a_target_with_none(monkeypatch):
    monkeypatch.delenv("PRINT3D_TARGET", raising=False)
    with pytest.raises(TargetError, match="Elegoo Centauri Carbon 2"):
        default_profiles_dir(targets.load("cc2"))
