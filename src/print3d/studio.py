"""Slicer CLI wrapper (Bambu Studio, ElegooSlicer). Isolated --datadir, dry-run first."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from print3d import targets
from print3d.repair_3mf import repair_bambu_3mf
from print3d.targets import Target, TargetError


class StudioError(RuntimeError):
    """Raised for slicer discovery or slice failures."""


@dataclass(frozen=True)
class SliceRequest:
    input_mesh: Path
    output_3mf: Path
    machine: Path
    process: Path
    filaments: tuple[Path, ...]
    datadir: Path
    output_dir: Path
    output_project_3mf: Path | None = None
    slice_plate: int = 0
    orient: bool = True
    arrange: bool = True
    ensure_on_bed: bool = True
    #: A plate name or an alias; None means the target's own default plate.
    bed_type: str | None = None
    debug_level: int = 2
    # Several parts: Studio reads the meshes, filaments and plates from this
    # file instead of from input_mesh.
    assemble_list: Path | None = None


def find_slicer(target: Target, search_path: str | None = None) -> Path:
    """The slicer CLI for `target`; search order is targets.find_slicer's."""
    try:
        return targets.find_slicer(target, search_path)
    except TargetError as exc:
        raise StudioError(str(exc)) from exc


def find_studio(search_path: str | None = None) -> Path:
    """Bambu Studio, for the callers that predate targets."""
    return find_slicer(targets.load("x2d"), search_path)


def _common_prefix(studio: Path, request: SliceRequest, *, target: Target | None = None) -> list[str]:
    target = target or targets.active()
    plate = target.resolve_bed_type(request.bed_type)
    filaments = ";".join(str(path.resolve()) for path in request.filaments)
    settings = f"{request.machine.resolve()};{request.process.resolve()}"
    command = [
        str(studio),
        "--datadir",
        str(request.datadir.resolve()),
        "--debug",
        str(request.debug_level),
    ]
    # Studio refuses an assemble list combined with transforms; each plate in
    # the list says whether to arrange it.
    if request.assemble_list is None:
        if request.orient:
            command.extend(["--orient", "1"])
        if request.arrange:
            command.extend(["--arrange", "1"])
        if request.ensure_on_bed:
            command.append("--ensure-on-bed")
    command.extend(
        [
            "--load-settings",
            settings,
            "--load-filaments",
            filaments,
            "--curr-bed-type",
            plate,
            "--outputdir",
            str(request.output_dir.resolve()),
        ]
    )
    return command


def _models(request: SliceRequest, input_path: Path | None = None) -> list[str]:
    if request.assemble_list is not None:
        return ["--load-assemble-list", str(request.assemble_list.resolve())]
    return [str((input_path or request.input_mesh).resolve())]


def assemble_list(objects: list[dict[str, Any]]) -> dict[str, Any]:
    """Studio's assemble list: one entry per part, fused by group, placed on numbered plates.

    Each object is {"plate": n, "parts": [{"stl", "filament", "settings"}]}; a
    part's filament is 1-based. Parts of one object share an assemble_index, so
    Studio prints them as one object with a filament per part.
    """
    plates: dict[int, list[dict[str, Any]]] = {}
    for index, obj in enumerate(objects, start=1):
        fused = len(obj["parts"]) > 1
        for part in obj["parts"]:
            entry = {
                "path": str(Path(part["stl"]).resolve()),
                "count": 1,
                "filaments": [part["filament"]],
                "assemble_index": [index if fused else 0],
            }
            if part.get("settings"):
                entry["print_params"] = part["settings"]
            plates.setdefault(obj["plate"], []).append(entry)
    return {
        "plates": [
            {"plate_name": f"plate {n}", "need_arrange": True, "objects": plates[n]}
            for n in sorted(plates)
        ]
    }


def project_3mf_path(request: SliceRequest) -> Path:
    if request.output_project_3mf is not None:
        return request.output_project_3mf
    return request.output_dir / (request.output_3mf.name.replace(".gcode.3mf", ".3mf"))


def build_project_command(
    studio: Path, request: SliceRequest, *, target: Target | None = None
) -> list[str]:
    """Export an unsliced Studio project. File > Open this in the Prepare tab."""
    command = _common_prefix(studio, request, target=target)
    command.extend(["--export-3mf", project_3mf_path(request).name])
    command.extend(_models(request))
    return command


def build_slice_command(
    studio: Path,
    request: SliceRequest,
    *,
    input_path: Path | None = None,
    target: Target | None = None,
) -> list[str]:
    command = _common_prefix(studio, request, target=target)
    command.extend(
        [
            "--slice",
            str(request.slice_plate),
            "--export-3mf",
            request.output_3mf.name,
        ]
    )
    command.extend(_models(request, input_path))
    return command


def _request_dict(request: SliceRequest, plate: str) -> dict[str, Any]:
    return {
        "input_mesh": str(request.input_mesh),
        "output_3mf": str(request.output_3mf),
        "output_project_3mf": str(project_3mf_path(request)),
        "machine": str(request.machine),
        "process": str(request.process),
        "filaments": [str(path) for path in request.filaments],
        "datadir": str(request.datadir),
        "output_dir": str(request.output_dir),
        "slice_plate": request.slice_plate,
        "bed_type": plate,
        "assemble_list": str(request.assemble_list) if request.assemble_list else None,
    }


def slice_plan(
    request: SliceRequest, *, studio: Path | None = None, target: Target | None = None
) -> dict[str, Any]:
    target = target or targets.active()
    binary = studio
    if binary is None:
        # A plan is only a preview; name the binary even when it is not installed.
        try:
            binary = find_slicer(target)
        except StudioError:
            binary = Path(target.slicer_command)
    plate = target.resolve_bed_type(request.bed_type)
    return {
        "dry_run": True,
        "studio": str(binary),
        "project_command": build_project_command(binary, request, target=target),
        "command": build_slice_command(binary, request, target=target),
        "request": _request_dict(request, plate),
        "open_in_studio": str(project_3mf_path(request)),
        "note": (
            f"Open the .3mf (not .gcode.3mf) in {target.slicer} File > Open. "
            ".gcode.3mf is a sliced print job and the Prepare tab reports no geometry."
        ),
        "target": target.as_dict(),
    }


def _run(command: list[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout_s)


def _require_file(
    path: Path, result: subprocess.CompletedProcess[str], label: str, target: Target
) -> None:
    if result.returncode != 0:
        raise StudioError(
            f"{target.slicer} {label} failed with exit {result.returncode}.\n"
            f"stderr tail:\n{(result.stderr or result.stdout)[-4000:]}"
        )
    if not path.is_file():
        raise StudioError(f"{target.slicer} {label} exited 0 but did not write {path}")


def run_slice(
    request: SliceRequest,
    *,
    studio: Path | None = None,
    timeout_s: float = 180,
    target: Target | None = None,
) -> dict[str, Any]:
    target = target or targets.active()
    binary = studio or find_slicer(target)
    plan = slice_plan(request, studio=binary, target=target)
    plan["dry_run"] = False
    request.datadir.mkdir(parents=True, exist_ok=True)
    request.output_dir.mkdir(parents=True, exist_ok=True)
    request.output_3mf.parent.mkdir(parents=True, exist_ok=True)
    project = project_3mf_path(request)
    project.parent.mkdir(parents=True, exist_ok=True)

    project_result = _run(build_project_command(binary, request, target=target), timeout_s)
    exported_project = request.output_dir / project.name
    _require_file(exported_project, project_result, "project export", target)
    if exported_project.resolve() != project.resolve():
        project.write_bytes(exported_project.read_bytes())
    if target.repair_3mf:
        repair_bambu_3mf(project)

    # Slice the STL, not the project 3mf. --load-settings on 3mf input has
    # segfaulted Studio CLI (bambulab/BambuStudio#10402).
    slice_cmd = build_slice_command(binary, request, input_path=request.input_mesh, target=target)
    plan["command"] = slice_cmd
    slice_result = _run(slice_cmd, timeout_s)
    exported = request.output_dir / request.output_3mf.name
    _require_file(exported, slice_result, "slice", target)
    if exported.resolve() != request.output_3mf.resolve():
        request.output_3mf.write_bytes(exported.read_bytes())
    if target.repair_3mf:
        repair_bambu_3mf(request.output_3mf)

    plan["returncode"] = slice_result.returncode
    plan["stdout"] = slice_result.stdout
    plan["stderr"] = slice_result.stderr
    plan["output_3mf"] = str(request.output_3mf)
    plan["output_project_3mf"] = str(project)
    plan["output_size_bytes"] = request.output_3mf.stat().st_size
    plan["project_size_bytes"] = project.stat().st_size
    return plan
