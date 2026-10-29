"""Which printer a job is for: its slicer, profiles, plate and bed.

print3d began as an X2D-only tool, so the slicer binary, its profile names, the
plate and the nozzle count were constants scattered through the package. A
target gathers everything that differs between machines, so one pipeline can
serve both.

Selected with `PRINT3D_TARGET` (x2d, cc2), defaulting to x2d: an install that
sets nothing behaves exactly as it did before there was a choice.

The two slicers are the same code base -- Bambu Studio -> OrcaSlicer ->
ElegooSlicer -- and take the same command line. What differs is the vendor
directory in the profile tree, the profile names, whether the CLI resolves
`inherits` itself, and the machine's own limits.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TARGET_ENV = "PRINT3D_TARGET"
DEFAULT_TARGET = "x2d"
PACKAGE = Path(__file__).resolve().parent
TARGETS_DIR = PACKAGE / "targets"
# A wrapper installed for a target can be asked where its profiles live, so a
# checkout works wherever the app was unpacked.
PROFILES_ROOT_FLAG = "--print3d-profiles-root"


class TargetError(RuntimeError):
    """Raised for an unknown target, a missing slicer or a missing profile tree."""


@dataclass(frozen=True)
class Target:
    """One machine, as the rest of the package needs to see it."""

    key: str
    label: str
    slicer: str
    slicer_command: str
    vendor: str
    #: Pinned profile directory shipped inside this package (`profiles/<name>`),
    #: or None when the slicer's own installed profiles are the source of truth.
    pinned_profiles: str | None
    #: True when the CLI cannot resolve `inherits` and needs flattened profiles.
    flatten: bool
    #: Profile files, relative to the profile root. Used when nothing is pinned.
    machine_profile: str
    process_profile: str
    filament_profile: str
    machine: str
    process: str
    filament: str
    layer_height: float
    bed_type: str
    #: Bed type names this slicer accepts. Empty means "not validated here".
    bed_types: tuple[str, ...]
    #: Plain-English aliases for a bed type ("smooth" -> a name in bed_types).
    bed_aliases: dict[str, str]
    build_volume_mm: tuple[float, float, float]
    nozzle_mm: float
    #: Filaments that print without a purge: nozzles on the toolhead, or the
    #: colour slots the machine's changer offers.
    nozzles: int
    #: False when the slicer's CLI cannot be trusted to assign filaments yet.
    multicolour: bool
    #: True only for a slicer whose CLI export needs the 3mf patched to open.
    repair_3mf: bool
    #: The pinned process prints without supports, which is why an overhang is a
    #: defect rather than a setting to flip.
    supports_off: bool
    binary_env: str
    binary_commands: tuple[str, ...]
    binary_paths: tuple[str, ...]
    windows_dir: tuple[str, ...]
    profiles_env: str
    profiles_roots: tuple[str, ...]
    #: Material name -> filament profile, relative to the profile root. Empty
    #: when the pinned profile in `pinned_profiles` is the only material.
    materials: dict[str, str] = field(default_factory=dict)
    colours: dict[str, str] = field(default_factory=dict)
    default_colour: str = "green"

    def as_dict(self) -> dict[str, Any]:
        """Everything a report needs to say which machine produced it."""
        return {
            "key": self.key,
            "label": self.label,
            "slicer": self.slicer,
            "vendor": self.vendor,
            "flatten": self.flatten,
            "pinned_profiles": self.pinned_profiles,
            "layer_height": self.layer_height,
            "bed_type": self.bed_type,
            "bed_types": list(self.bed_types),
            "build_volume_mm": list(self.build_volume_mm),
            "nozzle_mm": self.nozzle_mm,
            "nozzles": self.nozzles,
            "multicolour": self.multicolour,
            "materials": sorted(self.materials),
            "source": "pinned" if self.pinned_profiles else "slicer",
        }

    @property
    def default_material(self) -> str:
        """The material a job gets when it asks for none."""
        if self.materials:
            return next(iter(self.materials))
        return "PLA Basic"

    def resolve_bed_type(self, name: str | None) -> str:
        """A plate name, an alias or None, as this slicer spells it."""
        if not name or not name.strip():
            return self.bed_type
        wanted = alias if (alias := self.bed_aliases.get(name.strip().lower())) else name.strip()
        if self.bed_types and wanted not in self.bed_types:
            raise TargetError(
                f"{self.slicer} has no bed type {name!r} for the {self.label}. "
                f"Choose one of: {', '.join(self.bed_types)}."
            )
        return wanted

    def resolve_material(self, material: str | None) -> str:
        """A material name as this target spells it."""
        if not self.materials:
            return self.default_material
        wanted = (material or self.default_material).strip()
        for name in self.materials:
            if name.lower() == wanted.lower():
                return name
        raise TargetError(
            f"The {self.label} has no material {material!r}. "
            f"Choose one of: {', '.join(sorted(self.materials))}."
        )

    def colour_hex(self, colour: str | None) -> str:
        """A colour name from this target's table, or a literal #RRGGBB."""
        name = (colour or self.default_colour).strip().lower()
        if name in self.colours:
            return self.colours[name]
        body = name.lstrip("#")
        if len(body) == 6 and all(c in "0123456789abcdef" for c in body):
            return "#" + body.upper()
        raise TargetError(
            f"Unknown colour {colour!r}. Use #RRGGBB or one of: "
            f"{', '.join(sorted(self.colours))}."
        )


def _target_files() -> dict[str, Path]:
    if not TARGETS_DIR.is_dir():
        raise TargetError(f"No targets directory at {TARGETS_DIR}")
    return {path.stem: path for path in sorted(TARGETS_DIR.glob("*.json"))}


def available() -> tuple[str, ...]:
    """The target keys on disk."""
    return tuple(_target_files())


def load(key: str) -> Target:
    """The target named by `key`, with its JSON lists turned into tuples."""
    files = _target_files()
    path = files.get(key)
    if path is None:
        raise TargetError(f"Unknown target {key!r}. Known targets: {', '.join(files)}.")
    data = json.loads(path.read_text(encoding="utf-8"))
    for key_name in ("bed_types", "binary_commands", "binary_paths", "windows_dir", "profiles_roots"):
        data[key_name] = tuple(data.get(key_name, ()))
    data["build_volume_mm"] = tuple(float(v) for v in data.get("build_volume_mm", (0.0, 0.0, 0.0)))
    data["bed_aliases"] = dict(data.get("bed_aliases", {}))
    data["materials"] = dict(data.get("materials", {}))
    data["colours"] = dict(data.get("colours", {}))
    return Target(**data)


def active_key() -> str:
    return os.environ.get(TARGET_ENV, "").strip() or DEFAULT_TARGET


def active() -> Target:
    """The target this process is working for."""
    return load(active_key())


def find_slicer(target: Target | None = None, search_path: str | None = None) -> Path:
    """The slicer CLI: `$<TARGET>_BIN`, then PATH, then the usual install spots."""
    target = target or active()
    candidates: list[Any] = []
    if env := os.environ.get(target.binary_env, "").strip():
        candidates.append(env)
    if which := shutil.which(target.slicer_command, path=search_path):
        candidates.append(which)
    candidates.extend(target.binary_paths)
    candidates.extend(windows_slicer_locations(target))
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.is_file():
            return path.resolve()
    raise TargetError(
        f"{target.slicer} CLI not found. Install {target.slicer} or set {target.binary_env}."
    )


def windows_slicer_locations(target: Target) -> list[Path]:
    if sys.platform != "win32" or not target.windows_dir:
        return []
    from print3d.windows import program_files_dirs

    return [root.joinpath(*target.windows_dir) for root in program_files_dirs()]


def profiles_root(target: Target | None = None, *, slicer: Path | None = None) -> Path:
    """The directory holding `<vendor>/machine|process|filament`.

    In order: the target's env var, a root derived from the slicer's own
    location, the roots the target lists, then the slicer itself, when the
    wrapper it was installed with can say where its profiles are.
    """
    target = target or active()
    candidates: list[Path] = []
    if env := os.environ.get(target.profiles_env, "").strip():
        candidates.append(Path(env).expanduser())
    binary = slicer
    if binary is None:
        try:
            binary = find_slicer(target)
        except TargetError:
            binary = None
    if binary is not None:
        # .../squashfs-root/bin/slicer and .../squashfs-root/AppRun both live
        # inside the unpacked app, which keeps its profiles beside itself.
        for parent in [binary.parent, *binary.parents]:
            candidates.append(parent / "resources" / "profiles")
    candidates.extend(Path(root).expanduser() for root in target.profiles_roots)
    for candidate in candidates:
        if (candidate / target.vendor / "machine").is_dir():
            return candidate.resolve()
    if binary is not None and (root := _ask_slicer(binary, target)) is not None:
        return root
    raise TargetError(
        f"Could not find the {target.slicer} profiles for the {target.label}. "
        f"Set {target.profiles_env}, or install {target.slicer}."
    )


def _ask_slicer(binary: Path, target: Target) -> Path | None:
    """A wrapper installed for this target prints its profiles root when asked."""
    try:
        result = subprocess.run(
            [str(binary), PROFILES_ROOT_FLAG], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in (result.stdout or "").splitlines():
        text = line.strip()
        candidate = Path(text).expanduser()
        if text and (candidate / target.vendor / "machine").is_dir():
            return candidate.resolve()
    return None


@dataclass(frozen=True)
class JobProfiles:
    """The three profile files one slice needs, and where they came from."""

    machine: Path
    process: Path
    filament: Path
    material: str
    bed_type: str
    source: str  # "pinned" | "slicer"

    def as_dict(self) -> dict[str, str]:
        return {
            "machine": str(self.machine),
            "process": str(self.process),
            "filament": str(self.filament),
            "material": self.material,
            "bed_type": self.bed_type,
            "source": self.source,
        }


def job_profiles(
    target: Target | None = None,
    *,
    material: str | None = None,
    bed_type: str | None = None,
) -> JobProfiles:
    """The profiles to slice with: this package's pinned set, or the slicer's own."""
    target = target or active()
    plate = target.resolve_bed_type(bed_type)
    if target.pinned_profiles:
        pinned = PACKAGE / "profiles" / target.pinned_profiles
        for name in ("machine.json", "process.json", "filament.json"):
            if not (pinned / name).is_file():
                raise TargetError(
                    f"Pinned profile missing: {pinned / name}. Run: python -m print3d flatten"
                )
        return JobProfiles(
            machine=pinned / "machine.json",
            process=pinned / "process.json",
            filament=pinned / "filament.json",
            material=target.default_material,
            bed_type=plate,
            source="pinned",
        )
    root = profiles_root(target)
    chosen = target.resolve_material(material)
    return JobProfiles(
        machine=shipped_profile(target, target.machine_profile, root=root),
        process=shipped_profile(target, target.process_profile, root=root),
        filament=shipped_profile(target, target.materials[chosen], root=root),
        material=chosen,
        bed_type=plate,
        source="slicer",
    )


def shipped_profile(target: Target, relative: str, *, root: Path | None = None) -> Path:
    """A profile file the slicer installed, checked before it reaches the CLI."""
    path = (root or profiles_root(target)) / relative
    if not path.is_file():
        raise TargetError(f"Missing {target.slicer} profile: {path}")
    return path


def describe(target: Target | None = None) -> str:
    """One line for a report or a hand-off: machine, nozzle, bed, slicer."""
    target = target or active()
    x, y, z = target.build_volume_mm
    nozzle = "nozzle" if target.nozzles == 1 else "nozzles"
    return (
        f"{target.label}: {target.nozzle_mm} mm {nozzle}, {x:.0f} x {y:.0f} x {z:.0f} mm bed, "
        f"{target.layer_height} mm layers, sliced by {target.slicer}"
    )
