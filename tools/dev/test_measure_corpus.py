"""Tests for the development-only corpus runner, over a stand-in content folder of goldens.

Microsoft's files are not used here: the runner is pointed at a temporary folder holding
copies of the golden .vsdx files under the `*_U.VSTX` names it looks for.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
GOLDEN = ROOT / "tests" / "golden"
sys.path.insert(0, str(HERE))
import measure_corpus as C  # noqa: E402
import measure_visio as M  # noqa: E402


def _blank() -> bytes:
    spec = importlib.util.spec_from_file_location("build_golden", GOLDEN / "build_golden.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.package(["Process"], mod.page_sheet(), "", [])


@pytest.fixture()
def content(tmp_path) -> Path:
    folder = tmp_path / "Visio Content"
    (folder / "1033").mkdir(parents=True)
    for src, dst in (("golden-flow.vsdx", "FLOWGOLD_U.VSTX"), ("golden-lanes.vsdx", "LANEGOLD_U.VSTX"),
                     ("golden-scaffold.vsdx", "scaffold_gold_u.vstx")):
        shutil.copy(GOLDEN / src, folder / "1033" / dst)
    (folder / "1033" / "BLANK_U.VSTX").write_bytes(_blank())
    (folder / "1033" / "BROKEN_U.VSTX").write_bytes(b"not a zip")
    (folder / "1033" / "METRIC_M.VSTX").write_bytes(b"ignored: not a US-unit file")
    return folder


def run(content, out, date="2026-10-12"):
    return C.run(content, "--content", "16.0.1.2", [], out, date)


def test_entry_id():
    assert C.entry_id("CFF_SHAREDPROCESS_U") == "ms-cff-sharedprocess-u"
    assert C.entry_id("five_steps_of_risk_u") == "ms-five-steps-of-risk-u"


def test_the_runner_writes_a_sound_catalog_and_citing_measurements(content, tmp_path):
    out = tmp_path / "corpus"
    assert run(content, out) == 0
    cat = json.loads((out / "microsoft-catalog.json").read_text(encoding="utf-8"))
    meas = json.loads((out / "microsoft-measurements.json").read_text(encoding="utf-8"))
    assert M.validate_catalog(cat) == [] and M.validate_measurements(meas, cat) == []
    assert [e["file"] for e in cat["entries"]] == ["1033/FLOWGOLD_U.VSTX", "1033/LANEGOLD_U.VSTX",
                                                  "1033/scaffold_gold_u.vstx"]
    assert {s["file"]: s["reason"].split(":")[0] for s in cat["examined_not_measured"]} == {
        "1033/BLANK_U.VSTX": "no placed shapes", "1033/BROKEN_U.VSTX": "unreadable"}
    flow = cat["entries"][0]
    assert flow["counts"] == {"containers": 0, "shapes": 9, "connectors": 4}
    assert flow["pages_measured"] == 1 and len(flow["sha256"]) == 64
    assert flow["template_name"] is None             # the golden declares no title
    assert cat["visio"] == {"build": "16.0.1.2", "content_locale": "1033", "units": "U",
                            "install_found_by": "--content"}


def test_the_catalog_names_files_relative_to_the_root_never_absolutely(content, tmp_path):
    out = tmp_path / "corpus"
    run(content, out)
    text = (out / "microsoft-catalog.json").read_text(encoding="utf-8") + \
        (out / "microsoft-measurements.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in text and "Visio Content" not in text
    assert "\\\\Users" not in text and "C:\\\\" not in text


def test_the_scaffold_is_left_out_and_reported(content, tmp_path):
    out = tmp_path / "corpus"
    run(content, out)
    cat = json.loads((out / "microsoft-catalog.json").read_text(encoding="utf-8"))
    assert cat["scope"]["scaffold"]["files_with_scaffold"] == 1
    assert cat["scope"]["scaffold"]["shapes_excluded"] == 1


def test_embedded_master_sizes_supply_the_defaults(content, tmp_path):
    out = tmp_path / "corpus"
    run(content, out)
    meas = json.loads((out / "microsoft-measurements.json").read_text(encoding="utf-8"))
    flow = next(d for d in meas["diagrams"] if d["catalog_id"] == "ms-flowgold-u")
    assert flow["sizes"]["Process"]["default"] == {"width": 1.5, "height": 0.75, "source": "embedded"}
    assert flow["sizes"]["Process"]["at_default"] == 5
    assert meas["master_defaults"]["instances_by_source"] == {"embedded": sum(
        r["n"] for d in meas["diagrams"] for r in d["sizes"].values())}


def test_the_output_is_deterministic_lf_and_one_diagram_per_line(content, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    run(content, a)
    run(content, b)
    for name in ("microsoft-catalog.json", "microsoft-measurements.json"):
        raw = (a / name).read_bytes()
        assert raw == (b / name).read_bytes()
        assert b"\r" not in raw and not raw.startswith(b"\xef\xbb\xbf") and raw.endswith(b"\n")
    lines = (a / "microsoft-measurements.json").read_text(encoding="utf-8").splitlines()
    assert sum(1 for line in lines if line.startswith(' {"catalog_id"')) == 3


def test_missing_content_is_reported(tmp_path, capsys):
    assert C.main(["--content", str(tmp_path / "nowhere"), "--build", "16.0.1.2"]) == 2
    assert "not found" in capsys.readouterr().err
