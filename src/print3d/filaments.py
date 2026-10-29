"""Coloured copies of the base filament, one per colour a job asks for.

Colour is the only thing that changes: the material stays the base profile's, so
every check and the slice keep meaning the same thing. The active target owns
the colour table and the nozzle count; the module-level `COLOURS` table is the
fallback for callers that have no target to hand.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from print3d import targets
from print3d.flatten import FlattenError, build_name_index, flatten_by_name, normalize_for_cli

# Bambu PLA Basic, as the colours are named on the spool. The active target's
# own table wins; this stands in only when a caller passes no target.
COLOURS = {
    "white": "#FFFFFF",
    "black": "#000000",
    "grey": "#8E9089",
    "gray": "#8E9089",
    "silver": "#A6A9AA",
    "red": "#C12E1F",
    "orange": "#FF6A13",
    "yellow": "#F4EE2A",
    "green": "#00AE42",
    "blue": "#0A2989",
    "cyan": "#0086D6",
    "purple": "#5E43B7",
    "pink": "#F55A74",
    "magenta": "#EC008C",
    "brown": "#9D432C",
    "beige": "#F7E6DE",
    "gold": "#E4BD68",
}
DEFAULT_COLOUR = "green"
HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")
# Deprecated: the X2D's two nozzles are now `target.nozzles`. Kept importable.
NOZZLES = 2


class FilamentError(ValueError):
    """Raised for a colour that is neither a known name nor #RRGGBB."""


def colour_hex(colour: str | None, target: targets.Target | None = None) -> str:
    """A colour as #RRGGBB, resolved through the target's table when it has one."""
    if target is not None and target.colours:
        return target.colour_hex(colour)
    name = (colour or DEFAULT_COLOUR).strip().lower()
    if name in COLOURS:
        return COLOURS[name]
    if HEX_RE.match(name):
        return "#" + name.lstrip("#").upper()
    raise FilamentError(
        f"Unknown colour {colour!r}. Use #RRGGBB or one of: {', '.join(sorted(COLOURS))}."
    )


def nozzles(target: targets.Target | None = None) -> int:
    """Filaments that print without a purge on the active (or given) target."""
    return (target or targets.active()).nozzles


def colour_filament(
    base: Path,
    colour: str,
    out_dir: Path,
    *,
    material: str | None = None,
    target: targets.Target | None = None,
) -> Path:
    """The base filament with only its colour and name changed.

    A profile may inherit `filament_type` from the one it derives from -- Elegoo's
    CC2 presets do -- so it can be absent here; the material the caller chose
    stands in for it then, so the name is never left dangling.

    A preset that still inherits is a vendor preset, and ElegooSlicer's CLI dies
    on one whose values have been changed (renaming alone is fine). So a colour
    goes onto a copy with its whole chain folded in first: a user preset that
    names itself and points at nothing.
    """
    hex_ = colour_hex(colour, target)
    profile = json.loads(base.read_text(encoding="utf-8"))
    if target is not None and not self_contained(profile):
        profile = _inline_chain(profile, target)
        folded = True
    else:
        folded = False
    types = profile.get("filament_type") or []
    kind = types[0] if types else (material or "filament")
    label = f"print3d {colour.strip().lower()} {kind}"
    profile["filament_colour"] = [hex_]
    if folded:
        normalize_for_cli(profile, "filament", label)
    else:
        profile["name"] = label
        profile["filament_settings_id"] = [label]
        for key in ("setting_id", "instantiation", "is_custom_defined"):
            profile.pop(key, None)
        profile["from"] = "User"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{hex_.lstrip('#').lower()}.json"
    path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    return path


def self_contained(profile: dict[str, Any]) -> bool:
    """True when a profile carries its own values, so nothing vendor-side is behind it."""
    return profile.get("from") == "User" and profile.get("inherits") == profile.get("name")


def _inline_chain(profile: dict[str, Any], target: targets.Target) -> dict[str, Any]:
    """A shipped profile with every value it inherits folded into it."""
    root = targets.profiles_root(target)
    index = build_name_index(root, target.vendor, nested=True)
    name = profile.get("name")
    if not isinstance(name, str) or name not in index:
        raise FilamentError(f"{name!r} is not a profile {target.slicer} installs.")
    try:
        return flatten_by_name(name, index)
    except FlattenError as exc:
        raise FilamentError(f"Cannot copy {name!r} for a colour: {exc}") from exc


def job_filaments(
    base: Path,
    colours: list[str],
    out_dir: Path,
    *,
    material: str | None = None,
    target: targets.Target | None = None,
) -> list[Path]:
    """One filament per colour, in order. The colour list is already de-duplicated."""
    return [
        colour_filament(base, colour, out_dir, material=material, target=target)
        for colour in colours
    ]
