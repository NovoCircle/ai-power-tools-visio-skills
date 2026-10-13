"""Tests for measure_visio.py.

Three kinds of input, kept apart on purpose:

* SYNTHETIC page reads built in this file (`page`, `shp`) exercise one rule at a time.
  They are inputs to the measurement, not fixtures of the page-read contract.
* The GOLDEN .vsdx files of known geometry, read by the development extractor, exercise the
  whole path. They live in the skills repository (`tests/golden/`) and are not installed
  with the skills, so those tests skip when run from an install.
* The EA tool, when it can be found, as a parity check that this is the same method.

Expected numbers are derived by hand from the placement in `tests/golden/build_golden.py`.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections import Counter
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import measure_visio as M  # noqa: E402


def _find_repo_root() -> Path | None:
    for parent in HERE.parents:
        if (parent / "tests" / "golden" / "build_golden.py").is_file() \
                and (parent / "tools" / "dev" / "vsdx_to_page_read.py").is_file():
            return parent
    return None


REPO = _find_repo_root()
needs_repo = pytest.mark.skipif(
    REPO is None, reason="the golden files and the development extractor live in the skills "
                         "repository, not in an install")


def _extractor():
    sys.path.insert(0, str(REPO / "tools" / "dev"))
    import vsdx_to_page_read
    return vsdx_to_page_read


def golden(name: str) -> dict:
    (doc,) = _extractor().extract(str(REPO / "tests" / "golden" / name))
    return doc


# --------------------------------------------------------------------------
# Synthetic page reads
# --------------------------------------------------------------------------

def shp(ref, x, y, w, h, master="Process", text=None, **extra):
    rec = {"ref": ref, "x": x, "y": y, "width": w, "height": h}
    if master:
        rec["master"] = {"name": master, "universal_name": master, "unique_id": "{" + master + "}"}
    if text is not None:
        rec["text"] = text
    rec.update(extra)
    return rec


def page(shapes=(), containers=(), connectors=(), width=11.0, height=8.5, **extra):
    doc = {"contract": "apt-page-read", "contract_version": "0.1", "engine": "file",
           "unit": "in", "origin": "top-left",
           "page": {"page_id": "1", "width": width, "height": height,
                    "orientation": "landscape"},
           "containers": list(containers), "shapes": list(shapes),
           "connectors": list(connectors), "unavailable": []}
    doc.update(extra)
    return doc


def gaps(doc, axis="horizontal"):
    return M.measure_page(doc)["gaps"][axis]["values"]


# ---- the input contract ----------------------------------------------------

@pytest.mark.parametrize("change", [
    {"contract": "apt-render-plan"}, {"contract_version": "9.9"}, {"unit": "mm"},
    {"origin": "bottom-left"}, {"shapes": None},
])
def test_input_that_is_not_a_page_read_is_refused(change):
    doc = page()
    doc.update(change)
    with pytest.raises(M.MeasureError):
        M.measure_page(doc)


def test_a_page_without_a_size_is_refused():
    doc = page()
    del doc["page"]["width"]
    with pytest.raises(M.MeasureError, match="width"):
        M.measure_page(doc)


# ---- rounding and the axis ---------------------------------------------------

def test_q_removes_dust_and_breaks_ties_the_same_way_every_time():
    assert M.q(0.7500000000000043) == 0.75
    assert M.q(2.0625) == M.q(2.0624999999999) == 2.063      # one answer for one value
    assert M.q(-0.0) == 0.0 and str(M.q(-0.0)) == "0.0"


def test_vertical_gap_points_down():
    a = M.Box.make(0, 0, 1, 1)
    b = M.Box.make(0, 3, 1, 1)
    assert M.vertical_gap(a, b)[0] == 2.0          # b is two inches below a
    assert M.vertical_gap(b, a)[0] == -4.0         # a is above b: not a gap in this direction


def test_horizontal_gap_and_overlap():
    a = M.Box.make(0, 0, 1, 1)
    b = M.Box.make(3, 0.5, 1, 1)
    gap, overlap = M.horizontal_gap(a, b)
    assert gap == 2.0 and overlap == pytest.approx(0.5)


# ---- the adjacency rule (the EA tool's, restated) ---------------------------

def test_a_gap_is_the_distance_to_the_nearest_neighbor_in_the_row():
    doc = page([shp("a", 0, 0, 1, 1), shp("b", 2, 0, 1, 1), shp("c", 5, 0, 1, 1)])
    assert gaps(doc) == {"1": 1, "2": 1}      # a-b and b-c; a-c is not nearest


def test_each_element_contributes_at_most_one_gap_per_axis():
    doc = page([shp("a", 0, 0, 1, 1), shp("b", 2, 0, 1, 1), shp("c", 2, 5, 1, 1)])
    m = M.measure_page(doc)
    assert m["gaps"]["horizontal"]["n"] == 1 and m["gaps"]["vertical"]["n"] == 1


def test_a_pair_separated_by_a_non_endpoint_is_not_a_measurement():
    """The nearer object is unmastered, so the pair loses and is dropped, not reassigned."""
    doc = page([shp("a", 0, 0, 1, 1), shp("wall", 2, 0, 1, 1, master=None),
                shp("c", 4, 0, 1, 1)])
    assert gaps(doc) == {}


def test_a_pair_in_different_containers_is_not_a_measurement():
    lane1 = shp("L1", 0, 0, 3, 3, master="Swimlane", kind="lane", members=[])
    lane2 = shp("L2", 4, 0, 3, 3, master="Swimlane", kind="lane", members=[])
    doc = page([shp("a", 1, 1, 1, 1), shp("b", 5, 1, 1, 1)], containers=[lane1, lane2])
    assert gaps(doc) == {}
    same = page([shp("a", 0.2, 1, 1, 1), shp("b", 1.7, 1, 1, 1)], containers=[lane1])
    assert gaps(same) == {"0.5": 1}


def test_touching_shapes_are_counted_and_excluded():
    m = M.measure_page(page([shp("a", 0, 0, 1, 1), shp("b", 1, 0, 1, 1)]))
    assert m["gaps"]["horizontal"]["n"] == 0
    assert m["gaps"]["excluded_touching"]["horizontal"] == 1


def test_furniture_is_never_an_endpoint_but_does_intervene():
    legend = shp("lg", 2, 0, 1, 1, master="Legend")
    doc = page([shp("a", 0, 0, 1, 1), legend, shp("c", 4, 0, 1, 1)])
    m = M.measure_page(doc)
    assert m["gaps"]["horizontal"]["n"] == 0
    assert m["counts"]["furniture"] == 1 and m["counts"]["endpoints"] == 2


def test_pitch_is_center_to_center_next_to_the_gap():
    m = M.measure_page(page([shp("a", 0, 0, 1, 1), shp("b", 3, 0, 2, 1)]))
    assert m["gaps"]["horizontal"]["values"] == {"2": 1}
    assert m["pitch"]["horizontal"]["values"] == {"3.5": 1}      # 4.0 - 0.5


# ---- statistics ---------------------------------------------------------------

def test_the_mode_is_absent_on_a_tie():
    s = M.size_json(Counter({(1.0, 1.0): 2, (2.0, 1.0): 2}))
    assert s["mode"] is None and s["tied_modes"] == [[1.0, 1.0], [2.0, 1.0]]
    d = M.dist_json(Counter({1.0: 3, 2.0: 3}))
    assert d["mode"] is None and d["tied_modes"] == [1.0, 2.0]


def test_a_dominant_size_carries_its_count_and_share():
    s = M.size_json(Counter({(1.5, 0.75): 9, (2.0, 1.0): 1}))
    assert s["mode"] == [1.5, 0.75] and s["mode_count"] == 9 and s["mode_share"] == 0.9
    assert s["distinct"] == 2 and s["n"] == 10 and s["low_n"] is False


def test_low_n_and_thin_median():
    assert M.dist_json(Counter({1.0: 3}))["low_n"] is True
    g = M.gap_json({"d1": Counter({1.0: 12}), "d2": Counter({1.0: 12})})
    assert g["low_n"] is False and g["thin_median"] is True and g["n"] == 24
    wide = M.gap_json({f"d{i}": Counter({1.0: 1}) for i in range(M.MIN_SAMPLE_GAP)})
    assert wide["thin_median"] is False


def test_concentration_is_more_than_half_and_exactly_half_is_not():
    over = M.gap_json({"big": Counter({1.0: 6}), "small": Counter({2.0: 4})})
    assert over["concentrated"] is True and over["top_diagram"] == "big"
    assert over["top_count"] == 6 and over["top_share"] == 0.6 and over["diagrams"] == 2
    half = M.gap_json({"a": Counter({1.0: 5}), "b": Counter({2.0: 5})})
    assert half["concentrated"] is False


def test_the_constants_are_the_ea_tools():
    assert (M.MIN_SAMPLE, M.MIN_SAMPLE_GAP, M.MAX_DIAGRAM_SHARE, M.FIXED_SHAPE_SHARE) == \
        (10, 38, 0.5, 0.9)


# ---- furniture and title ----------------------------------------------------

@pytest.mark.parametrize("name,kind", [
    ("Title block", "title-block"), ("Page Title", "title-block"), ("Legend", "legend"),
    ("Border", "border"), ("Logo", "logo"), ("Text Callout", "note"), ("Note", "note"),
    ("Process", None), ("Decision", None), ("", None),
])
def test_furniture_is_recognized_from_the_master_name(name, kind):
    assert M.furniture_for(name) == kind


def test_a_stated_role_wins():
    doc = page([shp("x", 0, 0, 1, 1, role="furniture", furniture_kind="logo")])
    assert M.measure_page(doc)["furniture"]["logo"][0]["box"]["width"] == 1.0


def test_title_by_master():
    doc = page([shp("t", 3, 0.2, 5, 0.5, master="Title block", text="Westbrook")])
    t = M.measure_page(doc)["title"]
    assert t["source"] == "title-master" and t["align"] == "center"
    assert t["top_margin"] == 0.2 and t["left_margin"] == 3.0 and t["right_margin"] == 3.0
    assert t["text_length"] == 9


def test_title_by_a_wide_text_box_near_the_top():
    doc = page([shp("t", 0.5, 0.3, 4.0, 0.5, master=None, text="Westbrook")])
    t = M.measure_page(doc)["title"]
    assert t["source"] == "text-box" and t["align"] == "left"
    low = page([shp("t", 0.5, 5.0, 4.0, 0.5, master=None, text="Westbrook")])
    assert M.measure_page(low)["title"] is None


def test_title_falls_back_to_the_root_container_heading():
    c = shp("c", 0.5, 0.5, 10, 6, master="Container", kind="container", members=[],
            heading_box={"x": 0.5, "y": 0.5, "width": 10, "height": 0.5}, text="Branch")
    assert M.measure_page(page(containers=[c]))["title"]["source"] == "container-heading"


def test_text_is_never_copied_to_the_output():
    secret = "CONFIDENTIAL-SENTINEL-4471"
    doc = page([shp("a", 0, 0, 1, 1, text=secret, label_box={"x": 0, "y": 1, "width": 1, "height": 0.3})],
               connectors=[{"ref": "c", "text": secret, "path": [{"x": 0, "y": 0}, {"x": 1, "y": 0}],
                            "label_box": {"x": 0, "y": 0, "width": 1, "height": 1}}])
    doc["page"]["name"] = secret
    out = json.dumps(M.pool([M.measure_page(doc, label="x")]))
    out += json.dumps(M.measure_page(doc))
    assert secret not in out


# ---- labels -----------------------------------------------------------------

@pytest.mark.parametrize("label,expected", [
    ((0, 0, 2, 1), ("inside:middle-center", None)),
    ((0, 0, 2, 0.2), ("inside:top-center", None)),
    ((0, 0.8, 2, 0.2), ("inside:bottom-center", None)),
    ((0, 1.1, 2, 0.3), ("below", 0.1)),
    ((0, -0.4, 2, 0.3), ("above", 0.1)),
    ((2.5, 0.2, 1, 0.5), ("right", 0.5)),
    ((-1.5, 0.2, 1, 0.5), ("left", 0.5)),
])
def test_label_relation(label, expected):
    assert M.label_relation(M.Box.make(0, 0, 2, 1), M.Box.make(*label)) == expected


def test_labels_are_tallied_per_master_and_missing_boxes_are_reported():
    boxed = shp("a", 0, 0, 2, 1, text="t", label_box={"x": 0, "y": 1.1, "width": 2, "height": 0.3})
    bare = shp("b", 4, 0, 2, 1, text="t")
    m = M.measure_page(page([boxed, bare]))
    assert m["labels"]["by_master"] == {"Process": {"below": 1}}
    assert m["labels"]["no_label_box"] == 1
    assert m["labels"]["outside_gap"]["values"] == {"0.1": 1}
    assert "shapes[].label_box" not in M.measure_page(page([boxed]))["unavailable"]


def test_missing_label_boxes_are_listed_as_unavailable():
    assert "shapes[].label_box" in M.measure_page(page([shp("b", 0, 0, 1, 1, text="t")]))["unavailable"]


# ---- connectors ---------------------------------------------------------------

def test_attachment_sides_and_routes():
    a, b = shp("a", 0, 0, 2, 1), shp("b", 4, 0, 2, 1)
    conn = {"ref": "c", "route": "straight", "from_ref": "a", "to_ref": "b",
            "glued_begin": True, "glued_end": True,
            "path": [{"x": 2, "y": 0.5}, {"x": 4, "y": 0.5}]}
    bent = {"ref": "d", "route": "orthogonal", "from_ref": "a", "to_ref": "b",
            "path": [{"x": 1, "y": 1}, {"x": 1, "y": 2}, {"x": 5, "y": 2}, {"x": 5, "y": 1}]}
    m = M.measure_page(page([a, b], connectors=[conn, bent]))["connectors"]
    assert m["routes"] == {"orthogonal": 1, "straight": 1}
    assert m["begin_side"] == {"bottom": 1, "right": 1} and m["end_side"] == {"left": 1, "bottom": 1}
    assert m["glued_begin"] == 1 and m["bends"]["values"] == {"0": 1, "2": 1}


def test_a_connector_end_far_from_its_shape_is_off_and_one_inside_is_inside():
    box = M.Box.make(0, 0, 2, 2)
    assert M._side({"x": 1, "y": 1}, box) == "inside"
    assert M._side({"x": 5, "y": 5}, box) == "off"
    assert M._side({"x": 2.04, "y": 1}, box) == "right"          # within SIDE_TOL


def test_connector_label_offset_from_the_path_midpoint():
    path = [{"x": 0, "y": 0}, {"x": 4, "y": 0}]
    conn = {"ref": "c", "route": "straight", "text": "x", "path": path,
            "label_box": {"x": 1.5, "y": -0.8, "width": 1, "height": 0.6}}
    off = M.measure_page(page(connectors=[conn]))["connectors"]["label_offset_from_midpoint"]
    assert off["values"] == {"0.5": 1}           # center (2, -0.5) against midpoint (2, 0)


def test_midpoint_of_an_l_shaped_path_is_by_length():
    assert M._polyline_midpoint([{"x": 0, "y": 0}, {"x": 2, "y": 0}, {"x": 2, "y": 2}]) == (2.0, 0.0)


# ---- alignment ----------------------------------------------------------------

def test_alignment_counts_endpoints_with_a_mate():
    shapes = [shp("a", 0, 0, 1, 1), shp("b", 3, 0, 1, 1), shp("c", 0, 3, 1.4, 1),
              shp("d", 7, 0.5, 1, 2)]
    al = M.measure_page(page(shapes))["alignment"]
    assert al["n"] == 4
    assert al["center_row"] == 2          # a and b share cy 0.5; d's cy is 1.5
    assert al["left_edge"] == 2           # a and c start at 0
    assert al["top_edge"] == 2
    assert al["any"] == 3                 # d has no mate


# ---- containers and lanes ------------------------------------------------------

def test_heading_sides_and_thickness():
    def heading(box, h):
        c = shp("c", 0, 0, 10, 4, master="Container", kind="container", members=[],
                heading_box=h)
        return M._containers(M._items(page(containers=[c])))[0][0]["heading"]
    assert heading(None, {"x": 0, "y": 0, "width": 10, "height": 0.5})["side"] == "top"
    assert heading(None, {"x": 0, "y": 3.5, "width": 10, "height": 0.5})["side"] == "bottom"
    left = heading(None, {"x": 0, "y": 0, "width": 0.5, "height": 4})
    assert left["side"] == "left" and left["thickness"] == 0.5 and left["span"] == 4.0
    assert heading(None, {"x": 9.5, "y": 0, "width": 0.5, "height": 4})["side"] == "right"


def test_insets_are_measured_from_the_members_that_are_shapes():
    lane = shp("L", 0, 0, 10, 4, master="Swimlane", kind="lane", members=["a", "b"])
    a, b = shp("a", 1, 0.5, 2, 1), shp("b", 5, 1, 2, 1.5)
    rec = M._containers(M._items(page([a, b], containers=[lane])))[0][0]
    assert rec["insets"] == {"left": 1.0, "top": 0.5, "right": 3.0, "bottom": 1.5}
    assert rec["members"] == 2 and rec["member_shapes"] == 2


def test_lane_stack_axis_follows_how_the_centers_spread():
    stacked = [shp(f"L{i}", 0, i * 2, 10, 2, master="Swimlane", kind="lane", members=[])
               for i in range(3)]
    (v,) = M._containers(M._items(page(containers=stacked)))[1]
    assert v["axis"] == "vertical" and v["lanes"] == 3 and v["gap"]["values"] == {"0": 2}
    side = [shp(f"L{i}", i * 2.5, 0, 2, 6, master="Swimlane", kind="lane", members=[])
            for i in range(2)]
    (h,) = M._containers(M._items(page(containers=side)))[1]
    assert h["axis"] == "horizontal" and h["gap"]["values"] == {"0.5": 1}


# ---- sizes and defaults ---------------------------------------------------------

def test_sizes_per_master_with_a_default_size():
    defaults = {"{Process}": {"name": "Process", "width": 1.5, "height": 0.75, "source": "capture:x"}}
    shapes = [shp("a", 0, 0, 1.5, 0.75), shp("b", 3, 0, 1.5, 0.75), shp("c", 6, 0, 2, 1)]
    s = M.measure_page(page(shapes), master_defaults=defaults)["sizes"]["Process"]
    assert s["mode"] == [1.5, 0.75] and s["n"] == 3 and s["at_default"] == 2
    assert s["default"] == {"width": 1.5, "height": 0.75, "source": "capture:x"}


def test_a_rotated_shape_is_left_out_of_sizes():
    m = M.measure_page(page([shp("a", 0, 0, 1.5, 0.75), shp("r", 3, 0, 0.75, 1.5, angle=90.0)]))
    assert m["sizes"]["Process"]["n"] == 1
    assert any("rotated" in w for w in m["warnings"])


def test_unmastered_shapes_are_counted_not_sized():
    m = M.measure_page(page([shp("a", 0, 0, 1, 1, master=None, text="t"), shp("b", 3, 0, 1, 1)]))
    assert m["unmastered"] == {"shapes": 1, "with_text": 1} and list(m["sizes"]) == ["Process"]


def _capture(path, masters, key="basic-flowchart"):
    path.write_text(json.dumps({
        "schema": "apv-microsoft-template-capture/1", "template_key": key,
        "embedded_masters": {"masters": []},
        "stencils": [{"file": "S.VSSX", "masters": masters}]}), encoding="utf-8")


def test_master_defaults_load_from_a_template_capture(tmp_path):
    f = tmp_path / "cap.json"
    _capture(f, [
        {"unique_id": "{A}", "name_universal": "Process", "width_in": 1.0, "height_in": 0.75,
         "is_one_d": False},
        {"unique_id": "{B}", "name_universal": "Dynamic connector", "width_in": 1.0,
         "height_in": -0.5, "is_one_d": True},
        {"unique_id": "{C}", "name_universal": "X", "width_in": 1.0, "height_in": 1.0},
        {"unique_id": "{C}", "name_universal": "X", "width_in": 2.0, "height_in": 1.0}])
    d = M.load_master_defaults([str(f)])
    assert d == {"{A}": {"name": "Process", "width": 1.0, "height": 0.75,
                         "source": "capture:basic-flowchart"}}     # 1-D skipped, ambiguous dropped


def test_a_file_that_is_not_a_capture_is_refused(tmp_path):
    f = tmp_path / "x.json"
    f.write_text("{}", encoding="utf-8")
    with pytest.raises(M.MeasureError, match="not a template capture"):
        M.load_master_defaults([str(f)])


# ---- pooling --------------------------------------------------------------------

def test_scaled_and_background_diagrams_are_set_aside():
    normal = M.measure_page(page([shp("a", 0, 0, 1, 1), shp("b", 2, 0, 1, 1)]), label="n")
    scaled_doc = page([shp("a", 0, 0, 10, 10), shp("b", 20, 0, 10, 10)])
    scaled_doc["page"]["drawing_scale"] = {"page": 0.25, "drawing": 12}
    scaled = M.measure_page(scaled_doc, label="s")
    back_doc = page([shp("a", 0, 0, 1, 1), shp("b", 2, 0, 1, 1)])
    back_doc["page"]["background"] = True
    back = M.measure_page(back_doc, label="b")
    pooled = M.pool([normal, scaled, back])
    assert pooled["pooled"] == 1 and pooled["set_aside"] == {"scaled": 1, "background": 1}
    assert pooled["sizes"]["Process"]["n"] == 2
    assert pooled["gaps"]["horizontal"]["values"] == {"1": 1}


def test_pooled_gap_names_the_diagram_that_dominates():
    def row(n):
        return page([shp(f"s{i}", i * 2, 0, 1, 1) for i in range(n)])
    big = M.measure_page(row(8), label="big")        # 7 gaps
    small = M.measure_page(row(3), label="small")    # 2 gaps
    g = M.pool([big, small])["gaps"]["horizontal"]
    assert g["n"] == 9 and g["top_diagram"] == "big" and g["concentrated"] is True


def test_pooled_defaults_that_disagree_are_not_picked():
    def doc(w):
        d = M.measure_page(page([shp("a", 0, 0, 1, 1)]), label=str(w),
                           master_defaults={"{Process}": {"width": w, "height": 1, "source": "c"}})
        return d
    pooled = M.pool([doc(1.0), doc(2.0)])["sizes"]["Process"]
    assert pooled["default"] is None and pooled["defaults_disagree"] == [[1.0, 1], [2.0, 1]]


# ---- command line -----------------------------------------------------------------

def test_cli_measures_a_file_holding_a_list_of_page_reads(tmp_path, capsys):
    f = tmp_path / "reads.json"
    f.write_text(json.dumps([page([shp("a", 0, 0, 1, 1), shp("b", 2, 0, 1, 1)]),
                             page([shp("a", 0, 0, 1, 1)])]), encoding="utf-8")
    assert M.main([str(f)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["tool"] == "measure_visio" and out["unit"] == "in"
    assert [d["label"] for d in out["diagrams"]] == ["reads#1", "reads#2"]
    assert out["pooled"]["pooled"] == 2


def test_cli_reports_bad_input(tmp_path, capsys):
    f = tmp_path / "bad.json"
    f.write_text(json.dumps({"contract": "nope"}), encoding="utf-8")
    assert M.main([str(f)]) == 1
    assert "not a page read" in capsys.readouterr().err
    assert M.main([str(tmp_path / "missing.json")]) == 1


def test_the_module_states_where_it_differs_from_the_ea_tool():
    doc = M.__doc__
    for needle in ("measure_binding.py", "WHERE IT DIFFERS", "THE CONVERSION, STATED ONCE",
                   "TEXT IS NEVER COPIED"):
        assert needle in doc


# --------------------------------------------------------------------------
# The goldens, end to end
# --------------------------------------------------------------------------

@needs_repo
def test_flow_golden_gaps_and_pitch():
    m = M.measure_page(golden("golden-flow.vsdx"))
    # rows: 1-2 gap 1.5, 2-3 gap 1.0, rotated 6 to 7 gap 3.375; the legend sits between
    # decision 4 and nothing below it, so 4 has no vertical gap (nearest object is furniture)
    assert m["gaps"]["horizontal"]["values"] == {"1": 1, "1.5": 1, "3.375": 1}
    assert m["gaps"]["vertical"]["values"] == {"1.125": 1, "3.375": 1, "4.75": 1}
    assert m["pitch"]["horizontal"]["values"] == {"2.5": 1, "3": 1, "4.5": 1}
    assert m["pitch"]["vertical"]["values"] == {"2": 1, "4.5": 1, "5.5": 1}
    assert m["gaps"]["horizontal"]["mode"] is None          # three different gaps: no mode
    assert m["gaps"]["horizontal"]["median"] == 1.5


@needs_repo
def test_flow_golden_sizes_alignment_and_counts():
    m = M.measure_page(golden("golden-flow.vsdx"))
    assert m["counts"] == {"containers": 0, "shapes": 9, "connectors": 4, "scaffold_excluded": 0,
                           "furniture": 1, "endpoints": 7}
    proc = m["sizes"]["Process"]
    assert proc["n"] == 5 and proc["mode"] == [1.5, 0.75]       # the rotated one is left out
    assert m["sizes"]["Decision"]["mode"] == [1.0, 1.0]
    assert m["sizes"]["Legend"]["role"] == "furniture"
    al = m["alignment"]
    assert (al["n"], al["center_row"], al["center_column"], al["top_edge"], al["bottom_edge"],
            al["left_edge"], al["right_edge"], al["any"]) == (7, 5, 4, 3, 3, 0, 0, 6)


@needs_repo
def test_flow_golden_connectors_labels_title_furniture_margins():
    m = M.measure_page(golden("golden-flow.vsdx"))
    c = m["connectors"]
    assert c["routes"] == {"curved": 1, "orthogonal": 1, "straight": 2}
    assert (c["glued_begin"], c["glued_end"]) == (3, 3)
    assert c["bends"]["values"] == {"0": 2, "1": 1}
    assert c["begin_side"] == {"bottom": 2, "right": 1}
    assert c["end_side"] == {"left": 2, "top": 1}
    assert c["label_offset_from_midpoint"]["values"] == {"0.25": 1}
    lab = m["labels"]
    assert lab["n"] == 6 and lab["outside_gap"]["values"] == {"0.1": 1}
    assert lab["by_master"]["Process"] == {"below": 1, "inside:middle-center": 3}
    t = m["title"]
    assert (t["source"], t["align"], t["top_margin"], t["left_margin"], t["right_margin"],
            t["text_length"]) == ("text-box", "center", 0.25, 2.5, 2.5, 18)
    assert m["furniture"]["legend"] == [{"master": "Legend", "text_length": 0,
                                         "box": {"x": 0.5, "y": 7.25, "width": 2.0, "height": 1.0}}]
    assert m["margins"] == {"left": 0.5, "top": 0.25, "right": 0.5, "bottom": 0.25}
    assert m["unmastered"] == {"shapes": 1, "with_text": 1}


@needs_repo
def test_lanes_golden_containers_and_the_context_rule():
    m = M.measure_page(golden("golden-lanes.vsdx"))
    # the two steps in each lane are 2.5 apart; the steps in DIFFERENT lanes are vertical
    # neighbors, and that distance is a fact about the lanes, not a gap
    assert m["gaps"]["horizontal"]["values"] == {"2.5": 2}
    assert m["gaps"]["vertical"]["n"] == 0
    box, lane1, lane2 = m["containers"]
    assert box["heading"] == {"side": "top", "thickness": 0.5, "span": 10.0, "span_share": 1.0}
    assert lane1["heading"] == {"side": "left", "thickness": 0.5, "span": 2.5, "span_share": 1.0}
    # lane 1 spans x 0.5..10.5, y 1.5..4.0; its steps span x 2.25..7.75, y 2.375..3.125
    assert lane1["insets"] == {"left": 1.75, "top": 0.875, "right": 2.75, "bottom": 0.875}
    (stack,) = m["lane_stacks"]
    assert stack["axis"] == "vertical" and stack["lanes"] == 2
    assert stack["thickness"]["values"] == {"2.5": 2} and stack["gap"]["values"] == {"0": 1}
    assert m["title"]["source"] == "container-heading"


@needs_repo
def test_the_scaled_golden_is_set_aside_from_the_pool():
    flow = M.measure_page(golden("golden-flow.vsdx"), label="flow")
    scaled = M.measure_page(golden("golden-scaled.vsdx"), label="scaled")
    assert scaled["page"]["scaled"] is True and flow["page"]["scaled"] is False
    pooled = M.pool([flow, scaled])
    assert pooled["pooled"] == 1 and pooled["set_aside"]["scaled"] == 1


def test_scaffold_shapes_are_left_out_and_counted():
    doc = page([shp("a", 0, 0, 1, 1), shp("tips", 0, 7, 10, 1.2, master=None, scaffold=True)])
    m = M.measure_page(doc)
    assert m["counts"]["shapes"] == 1 and m["counts"]["scaffold_excluded"] == 1
    assert m["margins"]["bottom"] == 7.5          # measured from the one real shape
    assert m["unmastered"]["shapes"] == 0


@needs_repo
def test_scaffold_golden_end_to_end():
    pages = _extractor().extract(str(REPO / "tests" / "golden" / "golden-scaffold.vsdx"),
                                 scaffold_pattern=r"\btip pane\b")
    m = M.measure_page(pages[0])
    assert m["counts"]["scaffold_excluded"] == 1
    # the step spans y 2.125..2.875 on an 8.5 page; without the panel the bottom margin is 5.625
    assert m["margins"] == {"left": 1.25, "top": 2.125, "right": 8.25, "bottom": 5.625}


@needs_repo
def test_cli_end_to_end_over_extractor_output(tmp_path, capsys):
    pages = _extractor().extract(str(REPO / "tests" / "golden" / "golden-flow.vsdx"))
    f = tmp_path / "flow.json"
    f.write_text(json.dumps(pages), encoding="utf-8")
    assert M.main([str(f), "--no-pool"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "pooled" not in out and out["diagrams"][0]["gaps"]["horizontal"]["median"] == 1.5


# --------------------------------------------------------------------------
# Parity with the EA tool
# --------------------------------------------------------------------------

def _ea_module():
    candidates = [os.environ.get("EA_MEASURE_BINDING")]
    for parent in HERE.parents:
        candidates.append(str(parent / "ai-power-tools-skills" / "plugins" / "ai-power-tools"
                              / "skills" / "ea-diagram-composition" / "tools" / "measure_binding.py"))
    for c in candidates:
        if c and Path(c).is_file():
            spec = importlib.util.spec_from_file_location("ea_measure_binding", c)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["ea_measure_binding"] = mod
            spec.loader.exec_module(mod)
            return mod
    return None


@needs_repo
def test_gaps_agree_with_the_ea_tool_on_the_same_geometry():
    """The same rectangles, in EA's y-up negative integers (thousandths of an inch)."""
    ea = _ea_module()
    if ea is None:
        pytest.skip("the EA skills library's measure_binding.py was not found "
                    "(set EA_MEASURE_BINDING)")
    doc = golden("golden-flow.vsdx")
    items = []
    for n, s in enumerate(doc["shapes"]):
        master = (s.get("master") or {}).get("universal_name", "")
        left, right = round(s["x"] * 1000), round((s["x"] + s["width"]) * 1000)
        top, bottom = -round(s["y"] * 1000), -round((s["y"] + s["height"]) * 1000)
        otype = "Note" if master == "Legend" else "Class"
        items.append(ea.Item(n, master, otype, ea.Rect(left, top, right, bottom)))
    mine = M.measure_page(doc)
    for axis, key in (("h", "horizontal"), ("v", "vertical")):
        theirs, _ = ea.nearest_neighbor_gaps(items, axis, rule="strict")
        assert sorted(g / 1000 for g in theirs) == sorted(
            float(v) for v, c in mine["gaps"][key]["values"].items() for _ in range(c))


# --------------------------------------------------------------------------
# The corpus catalog schema
# --------------------------------------------------------------------------

def catalog(**over):
    doc = {
        "schema": M.CATALOG_SCHEMA,
        "corpus": {"name": "microsoft-visio-content", "root": M.ROOT_TOKEN},
        "visio": {"build": "16.0.20430.20146", "content_locale": "1033"},
        "measured_on": "2026-10-12",
        "tool": {"name": "measure_visio", "version": 1},
        "entries": [{"id": "ms-example-u", "file": "1033/EXAMPLE_U.VSTX", "kind": "template-sample",
                     "template_name": "Example", "size_bytes": 1234, "sha256": "a" * 64,
                     "pages_measured": 1, "counts": {"containers": 1, "shapes": 2, "connectors": 3}}],
        "examined_not_measured": [{"file": "1033/BLANK_U.VSTX", "reason": "no placed shapes"}],
    }
    doc.update(over)
    return doc


def test_a_sound_catalog_has_no_errors():
    assert M.validate_catalog(catalog()) == []


def _entry(**over):
    e = dict(catalog()["entries"][0])
    e.update(over)
    return e


@pytest.mark.parametrize("doc,needle", [
    (catalog(schema="other"), "schema"),
    (catalog(corpus={"name": "x", "root": "C:\\Program Files\\Microsoft Office"}), "corpus.root"),
    (catalog(visio={"build": "16.0", "content_locale": "1033"}), "visio.build"),
    (catalog(measured_on="12 October"), "measured_on"),
    (catalog(tool={"name": "other", "version": 1}), "tool.name"),
    (catalog(entries=[_entry(file="C:\\Program Files\\x.vstx")]), "relative"),
    (catalog(entries=[_entry(file="/usr/x.vstx")]), "relative"),
    (catalog(entries=[_entry(file="..\\x.vstx")]), "relative"),
    (catalog(entries=[_entry(sha256="xyz")]), "sha256"),
    (catalog(entries=[_entry(kind="mystery")]), "kind"),
    (catalog(entries=[_entry(id="Has Space")]), "id"),
    (catalog(entries=[_entry(), _entry()]), "duplicate"),
    (catalog(entries=[_entry(counts={"containers": 1})]), "counts"),
    (catalog(entries=[_entry(size_bytes=True)]), "size_bytes"),
    (catalog(examined_not_measured=[{"file": "D:\\x", "reason": "r"}]), "relative"),
])
def test_catalog_problems_are_reported(doc, needle):
    errors = M.validate_catalog(doc)
    assert errors and any(needle in e for e in errors), errors


def test_a_missing_template_name_is_an_error_but_null_is_fine():
    e = _entry()
    del e["template_name"]
    assert any("template_name" in x for x in M.validate_catalog(catalog(entries=[e])))
    assert M.validate_catalog(catalog(entries=[_entry(template_name=None)])) == []


def test_every_measurement_row_must_cite_a_catalog_entry():
    cat = catalog()
    good = {"schema": M.MEASUREMENTS_SCHEMA, "diagrams": [{"catalog_id": "ms-example-u", "label": "x"}]}
    assert M.validate_measurements(good, cat) == []
    bad = {"schema": M.MEASUREMENTS_SCHEMA, "diagrams": [{"catalog_id": "nope", "label": "x"}]}
    errors = M.validate_measurements(bad, cat)
    assert any("not in the catalog" in e for e in errors)
    assert any("has no measurement row" in e for e in errors)


def test_the_committed_corpus_catalog_is_sound():
    root = REPO
    if root is None or not (root / "corpus" / "microsoft-catalog.json").is_file():
        pytest.skip("the committed corpus catalog is in the skills repository, not in an install")
    cat = json.loads((root / "corpus" / "microsoft-catalog.json").read_text(encoding="utf-8"))
    assert M.validate_catalog(cat) == []
    meas = json.loads((root / "corpus" / "microsoft-measurements.json").read_text(encoding="utf-8"))
    assert M.validate_measurements(meas, cat) == []
    text = json.dumps(cat) + json.dumps(meas)
    assert "C:\\" not in text and "Program Files" not in text and "\\\\Users" not in text
