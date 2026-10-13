"""Tests for the development-only extractor, against golden .vsdx files of known geometry.

Every expected number is derived by hand from the placement written in
`tests/golden/build_golden.py` (Visio's bottom-left, center-pin convention), using the
contract's formula `x = pin_x - loc_pin_x`, `y = 8.5 - (pin_y - loc_pin_y + height)` -
never taken from the extractor's own output.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
GOLDEN = ROOT / "tests" / "golden"
sys.path.insert(0, str(HERE))
import vsdx_to_page_read as X  # noqa: E402


def _build_module():
    spec = importlib.util.spec_from_file_location("build_golden", GOLDEN / "build_golden.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def by_ref(page: dict) -> dict:
    return {s["ref"]: s for k in ("containers", "shapes", "connectors") for s in page[k]}


@pytest.fixture(scope="module")
def flow() -> dict:
    (page,) = X.extract(str(GOLDEN / "golden-flow.vsdx"))
    return page


@pytest.fixture(scope="module")
def lanes() -> dict:
    (page,) = X.extract(str(GOLDEN / "golden-lanes.vsdx"))
    return page


# ---- the goldens are what the builder says they are ------------------------

@pytest.mark.parametrize("name", ["golden-flow.vsdx", "golden-lanes.vsdx", "golden-scaled.vsdx",
                                  "golden-scaffold.vsdx"])
def test_committed_golden_equals_a_fresh_build(name):
    """A golden cannot drift from the geometry written down in the builder."""
    assert (GOLDEN / name).read_bytes() == _build_module().GOLDEN[name]()


# ---- the conversion, stated once ------------------------------------------

def test_to_top_left_is_the_only_flip():
    assert X.to_top_left(2.0, 6.0, 8.5) == (2.0, 2.5)
    assert X.to_top_left(0.0, 8.5, 8.5) == (0.0, 0.0)


def test_page_header_is_contract_shaped(flow):
    assert flow["contract"] == "apt-page-read" and flow["contract_version"] == "0.1"
    assert (flow["engine"], flow["unit"], flow["origin"]) == ("file", "in", "top-left")
    assert flow["page"]["width"] == 11.0 and flow["page"]["height"] == 8.5
    assert flow["page"]["orientation"] == "landscape" and flow["page"]["background"] is False
    assert "drawing_scale" not in flow["page"]
    assert flow["counts"] == {"containers": 0, "shapes": 9, "connectors": 4, "keyed": 0,
                              "unkeyed": 13, "duplicate_keys": 0}
    assert "shapes[].role" in flow["unavailable"] and "image" in flow["unavailable"]


def test_center_pin_shape_inherits_its_size_from_the_master(flow):
    s = by_ref(flow)["id:1"]
    # pin (2.0, 6.0), 1.5 x 0.75 from the master: x = 2.0 - 0.75, y = 8.5 - (6.0 + 0.375)
    assert (s["x"], s["y"], s["width"], s["height"]) == (1.25, 2.125, 1.5, 0.75)
    assert s["master"]["universal_name"] == "Process"
    assert s["master"]["unique_id"] == "{11111111-0001-0000-8E40-00608CF305B2}"


def test_a_stated_width_scales_the_inherited_pin_location(flow):
    """The master's LocPinX is `Width*0.5`; applying its cached 0.625 would shift the shape."""
    s = by_ref(flow)["id:4"]
    # Width 1.0 stated, Height 1.0 inherited, pin (2.0, 4.0): x = 2.0 - 0.5, y = 8.5 - 4.5
    assert (s["x"], s["y"], s["width"], s["height"]) == (1.5, 4.0, 1.0, 1.0)


def test_a_pin_that_is_not_the_center(flow):
    s = by_ref(flow)["id:5"]
    # pin (9.0, 7.0) at local (0, 0.375): left = 9.0, bottom = 6.625, top = 7.375
    assert (s["x"], s["y"], s["width"], s["height"]) == (9.0, 1.125, 1.5, 0.75)


def test_a_rotated_shape_is_its_bounding_box_with_the_angle(flow):
    s = by_ref(flow)["id:6"]
    # 1.5 x 0.75 turned 90 degrees about pin (5.0, 1.5): 0.75 wide, 1.5 tall
    assert (s["x"], s["y"], s["width"], s["height"]) == (4.625, 6.25, 0.75, 1.5)
    assert s["angle"] == 90.0


def test_label_box_follows_the_text_block_not_the_shape(flow):
    s = by_ref(flow)["id:7"]
    # shape bottom edge at page y 7.375; text block 0.3 tall starting 0.1 below it
    assert s["label_box"] == {"x": 8.75, "y": 7.475, "width": 1.5, "height": 0.3}
    inside = by_ref(flow)["id:1"]
    assert inside["label_box"] == {k: inside[k] for k in ("x", "y", "width", "height")}
    assert "label_box" not in by_ref(flow)["id:5"]      # no text, so no label


def test_text_is_carried_verbatim(flow):
    assert by_ref(flow)["id:9"]["text"] == "Westbrook Payments"


# ---- connectors -------------------------------------------------------------

def test_connector_paths_and_route_classes(flow):
    refs = by_ref(flow)
    assert refs["id:10"]["path"] == [{"x": 2.75, "y": 2.5}, {"x": 4.25, "y": 2.5}]
    assert refs["id:10"]["route"] == "straight"
    assert refs["id:11"]["path"] == [{"x": 7.5, "y": 2.875}, {"x": 7.5, "y": 7.0},
                                     {"x": 8.75, "y": 7.0}]
    assert refs["id:11"]["route"] == "orthogonal"
    assert refs["id:13"]["route"] == "curved"


def test_connector_glue_comes_from_connects(flow):
    refs = by_ref(flow)
    assert (refs["id:10"]["from_ref"], refs["id:10"]["to_ref"]) == ("id:1", "id:2")
    assert refs["id:10"]["glued_begin"] and refs["id:10"]["glued_end"]
    assert not refs["id:13"]["glued_begin"] and "from_ref" not in refs["id:13"]


def test_connector_label_box(flow):
    # label 0.5 x 0.2 centered 0.25 above the connector's midpoint (3.5, 2.5)
    assert by_ref(flow)["id:10"]["label_box"] == {"x": 3.25, "y": 2.15, "width": 0.5, "height": 0.2}


# ---- containers and lanes --------------------------------------------------

def test_container_membership_is_visios_and_innermost(lanes):
    refs = by_ref(lanes)
    assert [c["kind"] for c in lanes["containers"]] == ["container", "lane", "lane"]
    assert refs["id:2"]["parent_ref"] == "id:1"            # a lane sits in the container
    assert refs["id:4"]["parent_ref"] == "id:2"            # a step lists the container AND its lane
    assert refs["id:5"]["parent_ref"] == "id:3"
    assert refs["id:1"]["members"] == ["id:2", "id:3"]
    assert refs["id:2"]["members"] == ["id:4", "id:6"]


def test_container_geometry(lanes):
    refs = by_ref(lanes)
    # container pin (5.5, 4.5), 10 x 6: x 0.5..10.5, bottom-left y 1.5..7.5
    assert (refs["id:1"]["x"], refs["id:1"]["y"], refs["id:1"]["height"]) == (0.5, 1.0, 6.0)
    # lanes 2.5 tall, stacked at bottom-left y 4.5..7.0 and 2.0..4.5
    assert (refs["id:2"]["y"], refs["id:3"]["y"]) == (1.5, 4.0)


def test_container_headings_come_from_the_parts(lanes):
    refs = by_ref(lanes)
    assert refs["id:1"]["text"] == "Branch"
    assert refs["id:1"]["heading_box"] == {"x": 0.5, "y": 1.0, "width": 10.0, "height": 0.5}
    assert refs["id:2"]["text"] == "Teller"
    assert refs["id:2"]["heading_box"] == {"x": 0.5, "y": 1.5, "width": 0.5, "height": 2.5}


# ---- scale and refusals -----------------------------------------------------

def test_a_scaled_drawing_is_flagged():
    (page,) = X.extract(str(GOLDEN / "golden-scaled.vsdx"))
    assert page["page"]["drawing_scale"] == {"page": 0.25, "drawing": 12.0}
    assert any("drawing scale" in w for w in page["warnings"])


def test_path_label_replaces_the_path():
    (page,) = X.extract(str(GOLDEN / "golden-flow.vsdx"), path_label="<visio-content>\\1033\\X.VSTX")
    assert page["document"] == {"path": "<visio-content>\\1033\\X.VSTX", "name": "golden-flow.vsdx"}


def test_output_is_json_serializable(flow):
    assert json.loads(json.dumps(flow)) == flow


def test_not_a_package_is_refused(tmp_path):
    bad = tmp_path / "x.vsdx"
    bad.write_bytes(b"not a zip")
    with pytest.raises(X.ReadError):
        X.extract(str(bad))


def test_a_doctype_is_refused(tmp_path):
    bad = tmp_path / "x.vsdx"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("visio/pages/pages.xml", "<?xml version='1.0'?><!DOCTYPE a [<!ENTITY e 'x'>]><Pages/>")
    with pytest.raises(X.ReadError, match="DOCTYPE|entity"):
        X.extract(str(bad))


def test_relationship_targets_cannot_leave_the_package():
    from pathlib import PurePosixPath
    assert X.resolve_part(PurePosixPath("visio/pages"), "../masters/m.xml") == "visio/masters/m.xml"
    with pytest.raises(X.ReadError):
        X.resolve_part(PurePosixPath("visio"), "../../etc/passwd")


def test_master_defaults_are_read_from_the_embedded_masters():
    sizes = {m["universal_name"]: (m["width_in"], m["height_in"])
             for m in X.master_defaults(str(GOLDEN / "golden-flow.vsdx"))}
    assert sizes["Process"] == (1.5, 0.75) and sizes["Decision"] == (1.25, 1.0)


# ---- template instruction text ----------------------------------------------

def test_scaffold_is_marked_only_when_a_pattern_is_given():
    plain = X.extract(str(GOLDEN / "golden-scaffold.vsdx"))[0]
    assert not any("scaffold" in s for s in plain["shapes"])
    marked = X.extract(str(GOLDEN / "golden-scaffold.vsdx"), scaffold_pattern=r"\btip pane\b")[0]
    flags = {s["ref"]: s.get("scaffold", False) for s in marked["shapes"]}
    assert flags == {"id:1": False, "id:2": True}
    panel = by_ref(marked)["id:2"]
    # pin (5.5, 1.0), 10 x 1.2: x 0.5, bottom-left y 0.4..1.6, so y = 8.5 - 1.6
    assert (panel["x"], panel["y"], panel["width"], panel["height"]) == (0.5, 6.9, 10.0, 1.2)
