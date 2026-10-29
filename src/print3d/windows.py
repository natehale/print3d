"""Standard Windows installation locations, without launching applications."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path

from print3d import targets
from print3d.targets import Target


def program_files_dirs() -> Iterator[Path]:
    if sys.platform != "win32":
        return
    seen: set[Path] = set()
    # ProgramW6432 also finds native 64-bit installs from a 32-bit Python.
    for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        value = os.environ.get(variable, "").strip()
        if value:
            path = Path(value)
            if path not in seen:
                seen.add(path)
                yield path


def blender_locations() -> Iterator[Path]:
    for root in program_files_dirs():
        # Compare numeric versions: Blender 4.10 must sort after Blender 4.9.
        candidates = root.glob("Blender Foundation/Blender */blender.exe")
        yield from sorted(
            candidates,
            key=lambda path: (tuple(int(n) for n in re.findall(r"\d+", path.parent.name)), str(path)),
            reverse=True,
        )


def slicer_locations(target: Target) -> Iterator[Path]:
    """Where `target`'s slicer installs on Windows, under each program-files root."""
    if not target.windows_dir:
        return
    for root in program_files_dirs():
        yield root.joinpath(*target.windows_dir)


def studio_locations() -> Iterator[Path]:
    """Bambu Studio's install, for the callers that predate targets."""
    yield from slicer_locations(targets.active())
