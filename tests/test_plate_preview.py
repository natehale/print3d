"""Reading an ElegooSlicer slice back: its numbers, and the plate preview it never draws.

ElegooSlicer writes the same 3mf layout as Bambu Studio, so these tests build a
minimal .3mf by hand and exercise what actually differs: the weight line's
spelling, a time that lives in slice_info.config rather than the gcode header,
and a plate preview drawn from plate_N.json because the CLI emits no PNG.
"""

import json
import zipfile
from pathlib import Path

from PIL import Image

from print3d.plate_preview import draw_plate
from print3d.printability import analyze_slice
from print3d.project import prediction_seconds, read_plate_json

GOLDEN = Path(__file__).parent / "fixtures" / "cube_20mm.gcode.3mf"

# ElegooSlicer 1.5.3.5: no `total estimated time:` line, and `used [g]` not `weight [g]`.
ELEGOO_GCODE = """\
; HEADER_BLOCK_START
; ElegooSlicer 1.5.3.5
; total layer number: 50
; total filament used [g] = 4.01
; HEADER_BLOCK_END

; CONFIG_BLOCK_START
; layer_height = 0.2
; CONFIG_BLOCK_END
G1 Z0.2
G1 X10 Y10 E1.5
G1 X20 Y10 E1.5
"""

ELEGOO_SLICE_INFO = """\
<?xml version="1.0" encoding="UTF-8"?>
<config>
  <plate>
    <metadata key="index" value="1"/>
    <metadata key="prediction" value="637"/>
    <metadata key="weight" value="4.01"/>
  </plate>
</config>
"""

ELEGOO_PLATE_JSON = {
    "bbox_all": [128.0, 118.0, 170.0, 138.0],
    "bbox_objects": [
        {"id": 28, "name": "cube.stl", "bbox": [128.0, 118.0, 148.0, 138.0]},
        {"id": 29, "name": "cube2.stl", "bbox": [150.0, 118.0, 170.0, 138.0]},
    ],
    "filament_colors": ["#00AE42", "#FF0000"],
    "bed_type": "textured_plate",
}


def _write_3mf(path: Path, *, plate_json: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Metadata/plate_1.gcode", ELEGOO_GCODE)
        archive.writestr("Metadata/slice_info.config", ELEGOO_SLICE_INFO)
        if plate_json:
            archive.writestr("Metadata/plate_1.json", json.dumps(ELEGOO_PLATE_JSON))
    return path


def test_weight_line_matches_elegoos_spelling(tmp_path: Path):
    metrics = analyze_slice(_write_3mf(tmp_path / "elegoo.gcode.3mf"))
    assert metrics["filament_g"] == 4.01
    assert metrics["layer_count"] == 50


def test_missing_time_falls_back_to_the_slice_info_prediction(tmp_path: Path):
    metrics = analyze_slice(_write_3mf(tmp_path / "elegoo.gcode.3mf"))
    assert metrics["estimated_time"] == "10m 37s"
    assert metrics["estimated_minutes"] == 10.6


def test_bambu_header_still_parses_unchanged():
    """The header time wins where it exists; the old spelling still reads true."""
    metrics = analyze_slice(GOLDEN)
    assert metrics["estimated_time"] == "13m 52s"
    assert metrics["estimated_minutes"] == 13.9
    assert metrics["filament_g"] == 3.63
    assert metrics["layer_count"] == 100


def test_prediction_seconds_reads_the_named_plate(tmp_path: Path):
    project = _write_3mf(tmp_path / "elegoo.gcode.3mf")
    assert prediction_seconds(project) == 637
    assert prediction_seconds(project, plate=2) is None
    # Bambu Studio writes the same key, so the reader is not Elegoo-specific.
    assert prediction_seconds(GOLDEN) == 832


def test_read_plate_json_returns_the_summary(tmp_path: Path):
    data = read_plate_json(_write_3mf(tmp_path / "elegoo.gcode.3mf"))
    assert data is not None
    assert data["filament_colors"] == ["#00AE42", "#FF0000"]
    assert len(data["bbox_objects"]) == 2
    assert data["bed_type"] == "textured_plate"


def test_read_plate_json_is_none_when_absent(tmp_path: Path):
    project = _write_3mf(tmp_path / "bare.gcode.3mf", plate_json=False)
    assert read_plate_json(project) is None


def test_draw_plate_writes_a_512_png(tmp_path: Path):
    project = _write_3mf(tmp_path / "elegoo.gcode.3mf")
    dest = draw_plate(project, tmp_path / "out" / "plate.png", build_volume_mm=(256.0, 256.0, 256.0))
    assert dest is not None
    with Image.open(dest) as image:
        assert image.format == "PNG"
        assert image.size == (512, 512)


def test_draw_plate_returns_none_and_writes_nothing_without_plate_json(tmp_path: Path):
    project = _write_3mf(tmp_path / "bare.gcode.3mf", plate_json=False)
    dest = tmp_path / "out" / "plate.png"
    assert draw_plate(project, dest) is None
    assert not dest.exists()


def test_draw_plate_defaults_the_bed_to_the_active_target(tmp_path: Path):
    project = _write_3mf(tmp_path / "elegoo.gcode.3mf")
    dest = draw_plate(project, tmp_path / "plate.png")
    assert dest is not None and dest.is_file()


def test_draw_plate_previews_the_bambu_fixture_too(tmp_path: Path):
    # The existing fixture carries a plate_1.json, so the same code previews it.
    dest = draw_plate(GOLDEN, tmp_path / "bambu.png")
    assert dest is not None
    with Image.open(dest) as image:
        assert image.size == (512, 512)
