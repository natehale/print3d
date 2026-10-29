"""Colours on a filament profile that belongs to the slicer's own install.

ElegooSlicer's CLI dies on a vendor preset whose values have been changed in
place -- renaming one is fine -- so a colour has to go onto a preset that carries
its own values. That is the whole reason these tests exist.
"""

from __future__ import annotations

import json
from pathlib import Path

from print3d import filaments, targets


def _profiles(root: Path) -> Path:
    """A stand-in for an ElegooSlicer install: leaves that inherit a parent."""
    target = targets.load("cc2")
    files = {
        target.machine_profile: {"name": "Elegoo Centauri Carbon 2 0.4 nozzle"},
        target.process_profile: {"name": "0.20mm Standard @Elegoo CC2 0.4 nozzle"},
        target.materials["PLA Basic"]: {"name": "Elegoo PLA Basic @ECC2", "inherits": "Elegoo PLA"},
        "Elegoo/filament/base/Elegoo PLA.json": {
            "name": "Elegoo PLA",
            "filament_type": ["PLA"],
            "filament_colour": ["#FFFFFF"],
            "nozzle_temperature": ["220"],
        },
    }
    for relative, payload in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return root


def test_a_colour_copy_of_a_vendored_preset_carries_its_own_values(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEGOO_PROFILES_ROOT", str(_profiles(tmp_path / "elegoo")))
    target = targets.load("cc2")
    base = targets.shipped_profile(target, target.materials["PLA Basic"])

    copy = json.loads(
        filaments.colour_filament(base, "red", tmp_path / "out", material="PLA Basic", target=target).read_text()
    )

    assert copy["from"] == "User"
    assert copy["inherits"] == copy["name"]
    assert copy["filament_colour"] == ["#C12E1F"]
    assert copy["filament_type"] == ["PLA"]  # inlined from the profile it derived from
    assert copy["nozzle_temperature"] == ["220"]
    assert copy.get("setting_id") is None


def test_the_pinned_x2d_filament_is_used_as_it_stands(tmp_path):
    """The pinned profiles already carry their own values, so nothing is re-folded for them."""
    target = targets.load("x2d")
    base = targets.job_profiles(target).filament
    pinned = json.loads(base.read_text())
    assert filaments.self_contained(pinned)

    copy = json.loads(filaments.colour_filament(base, "blue", tmp_path / "out", target=target).read_text())

    assert copy["filament_colour"] == ["#0A2989"]
    assert copy["inherits"] == pinned["inherits"]
    assert copy["filament_type"] == pinned["filament_type"]


def test_a_modified_preset_that_names_no_parent_is_left_alone(tmp_path):
    """A profile with no chain behind it is already a user preset."""
    loose = tmp_path / "loose.json"
    loose.write_text(json.dumps({"name": "Loose", "from": "User", "inherits": "Loose"}), encoding="utf-8")
    copy = json.loads(filaments.colour_filament(loose, "white", tmp_path / "out").read_text())
    assert copy["filament_colour"] == ["#FFFFFF"]
    assert copy["name"] == "print3d white filament"
