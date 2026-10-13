"""Tests for the page-read adapter in front of the fidelity checker.

THE INPUT HERE IS DERIVED, NOT CAPTURED. No page read exists yet to capture: the
operation that produces one is not built. So every page read below is written
out of the ported checker's own reading (`test_fidelity.READING`, a synthetic,
hand-placed, deliberately ragged diagram) by one stated formula, and none of it
is a measurement of a real Visio file. When a real read can be captured, a
captured fixture replaces these (the backlog item that tracks it says so); until
then these tests prove the adapter's reshaping and its refusals, not that it
agrees with what Visio will actually return.

THE FORMULA. The reading is in image pixels, top-left origin, y down. A page read
is in inches, top-left origin, y down, a rectangle by its top-left corner. With
`PX_PER_IN` pixels to the inch, for a reading rect `[left, top, right, bottom]`:

    x = left / PX_PER_IN            width  = (right - left) / PX_PER_IN
    y = top  / PX_PER_IN            height = (bottom - top) / PX_PER_IN

`PX_PER_IN` is 96 here only because it is a round number; it is a test constant,
not a measured export scale, and the checker must not care what it is (it fits a
scale). The page is the reading's canvas divided by the same number.
"""
from __future__ import annotations

import copy

import pytest

import fidelity
import fidelity_page_read as adapter
from test_fidelity import LINKS, READING, VISIBLE, drawn

PX_PER_IN = 96.0


def page_read(reading=READING, *, scale: float = 1.0, dx: float = 0.0,
              dy: float = 0.0, scale_y: float | None = None,
              moved: dict | None = None, drop: tuple = (),
              containers: tuple = ("banner",), key=lambda ident: ident,
              text: dict | None = None, fill: dict | None = None) -> dict:
    """The reading as a page read, by the formula in the module docstring.

    `scale`, `scale_y`, `dx`, `dy` (inches) and `moved` (reading pixels) mirror
    the knobs on `test_fidelity.drawn`, so a perturbation reads the same on both
    sides of the adapter.
    """
    scale_y = scale if scale_y is None else scale_y
    moved = moved or {}
    text = text or {}
    fill = fill or {}
    containers_out, shapes_out, ids = [], [], {}
    for number, entry in enumerate(reading["elements"], start=1):
        ident = entry["id"]
        if ident in drop:
            continue
        left, top, right, bottom = entry["rect"]
        mx, my = moved.get(ident, (0.0, 0.0))
        item = {
            "ref": key(ident),
            "shape_id": number,
            "identity": {"key": key(ident), "source": "westbrook-example",
                         "view": "wba-example-view"},
            "x": (left + mx) * scale / PX_PER_IN + dx,
            "y": (top + my) * scale_y / PX_PER_IN + dy,
            "width": (right - left) * scale / PX_PER_IN,
            "height": (bottom - top) * scale_y / PX_PER_IN,
            "text": text.get(ident, entry["name"]),
        }
        if ident in fill:
            item["style"] = {"fill_color": fill[ident]}
        if ident in containers:
            containers_out.append(item)
        else:
            shapes_out.append(item)
        ids[ident] = number
    connectors = []
    for index, link in enumerate(reading.get("links") or [], start=100):
        if link["from"] in drop or link["to"] in drop:
            continue
        connectors.append({
            "ref": f"link-{index}", "shape_id": index,
            "from_ref": key(link["from"]), "to_ref": key(link["to"]),
            "glued_begin": True, "glued_end": True})
    canvas = reading["canvas"]
    return {
        "contract": "apt-page-read", "contract_version": "0.1",
        "engine": "file", "unit": "in", "origin": "top-left",
        "document": {"path": "<output-dir>\\Westbrook Example.vsdx",
                     "name": "Westbrook Example.vsdx"},
        "page": {"page_id": "1", "name": "Example",
                 "width": canvas["width"] / PX_PER_IN,
                 "height": canvas["height"] / PX_PER_IN,
                 "orientation": "landscape"},
        "containers": containers_out, "shapes": shapes_out,
        "connectors": connectors,
        "counts": {"containers": len(containers_out), "shapes": len(shapes_out),
                   "connectors": len(connectors), "keyed": len(ids),
                   "unkeyed": 0, "duplicate_keys": 0},
        "unavailable": ["image", "shapes[].text_extent"],
    }


def rules(report) -> list:
    return [f.rule for f in report.findings]


# A reading with the features counts removed: the page read states none, so the
# reading's own `features` would (correctly) leave three unanswered questions.
NO_FEATURES = {**READING, "elements": [
    {k: v for k, v in e.items() if k != "features"} for e in READING["elements"]]}


# ---------------------------------------------------------------------------
# The property the adapter exists for
# ---------------------------------------------------------------------------
def test_a_page_read_of_the_same_diagram_is_faithful():
    report = adapter.compare_page_read(NO_FEATURES, page_read())
    assert report.faithful
    assert report.findings == []
    assert report.not_run == []
    assert report.metrics["matched"] == 8
    # inches to pixels is the fitted scale, not a finding
    assert report.metrics["scale"] == pytest.approx(PX_PER_IN, rel=1e-6)


def test_the_conversion_agrees_with_the_originals_own_fixture():
    """Two independent writings of the same sign convention must agree.

    `test_fidelity.drawn` negates image coordinates to EA's convention by itself;
    the adapter negates a top-left page read. Fed the same diagram, they must
    produce the same rects, or one of them has a sign error.
    """
    from_adapter = {o["ref"]: o for o in
                    adapter.to_fidelity_input(page_read()).objects}
    from_fixture = {o["ref"]: o for o in drawn(scale=1 / PX_PER_IN)}
    assert set(from_adapter) == set(from_fixture)
    for ref, want in from_fixture.items():
        for side in ("left", "right", "top", "bottom"):
            assert from_adapter[ref][side] == pytest.approx(want[side], abs=1e-9)


def test_a_bigger_page_and_elsewhere_is_the_same_diagram():
    report = adapter.compare_page_read(
        NO_FEATURES, page_read(scale=2.5, dx=4.0, dy=-0.9))
    assert report.faithful
    assert report.findings == []
    assert report.metrics["scale"] == pytest.approx(PX_PER_IN / 2.5, rel=1e-6)


def test_a_shape_above_the_top_of_the_page_changes_nothing():
    """A negative y would be refused by the checker as a mirrored rect.

    The adapter shifts the whole page down by one amount; the fit removes a
    translation, so the findings must be the ones an unshifted page gives.
    """
    above = page_read(dy=-3.0)
    assert min(s["y"] for s in above["shapes"] + above["containers"]) < 0
    report = adapter.compare_page_read(NO_FEATURES, above)
    assert report.faithful and report.findings == []
    assert report.metrics["page_read"]["y_shift"] > 0

    # and a perturbation is reported the same way with or without the shift
    plain = adapter.compare_page_read(NO_FEATURES,
                                      page_read(moved={"note_b": (60.0, 0.0)}))
    shifted = adapter.compare_page_read(
        NO_FEATURES, page_read(dy=-3.0, moved={"note_b": (60.0, 0.0)}))
    assert [(f.rule, f.subjects, f.severity) for f in plain.findings] == \
           [(f.rule, f.subjects, f.severity) for f in shifted.findings]


def test_a_vertically_mirrored_page_is_never_a_clean_comparison():
    """The sign convention, pinned from the other side.

    A page read of the diagram flipped top to bottom is a perfectly well-formed
    top-left read. If the adapter ever treated y as pointing up, the flip would
    be undone and this would compare clean. As it is, the checker finds no
    positive scale to fit and says the geometry went unmeasured. (`faithful` is
    True there, as it is for the original's degenerate case: it means "no
    errors", and the entry in `not_run` is what says nothing was compared.)
    """
    flipped = page_read()
    height = flipped["page"]["height"]
    for item in flipped["shapes"] + flipped["containers"]:
        item["y"] = height - (item["y"] + item["height"])
    report = adapter.compare_page_read(NO_FEATURES, flipped)
    assert report.fit is None
    assert any("no scale could be fitted" in e for e in report.not_run)
    assert "worst_position_drift" not in report.metrics


# ---------------------------------------------------------------------------
# Each way it can fail, through the adapter
# ---------------------------------------------------------------------------
def test_a_missing_shape_is_an_error_and_its_link_is_not_blamed():
    report = adapter.compare_page_read(NO_FEATURES, page_read(drop=("note_b",)))
    assert [f.subjects for f in report.findings
            if f.rule == "missing-element"] == [("note_b",)]
    assert "missing-link" not in rules(report)
    assert report.metrics["links_judged"] == 2


def test_a_hand_drawn_shape_stands_for_nothing():
    drawn_by_hand = page_read()
    drawn_by_hand["shapes"].append(
        {"ref": "id:12", "shape_id": 12, "x": 8.2, "y": 6.9, "width": 1.5,
         "height": 0.6, "text": "Fraud review (draft)"})
    report = adapter.compare_page_read(NO_FEATURES, drawn_by_hand)
    extra = [f for f in report.findings if f.rule == "extra-element"]
    assert len(extra) == 1
    assert "stands for nothing" in extra[0].message
    assert "Fraud review (draft)" in extra[0].message


def test_moving_one_shape_past_the_precision_names_only_that_shape():
    report = adapter.compare_page_read(
        NO_FEATURES, page_read(moved={"note_b": (9.0, 0.0)}))
    drift = [f for f in report.findings if f.rule == "position-drift"]
    assert [f.subjects for f in drift] == [("note_b",)]
    assert drift[0].severity == "warning"


def test_a_shift_inside_the_readings_precision_is_quiet():
    report = adapter.compare_page_read(
        NO_FEATURES, page_read(moved={"note_b": (3.0, 0.0)}))
    assert report.findings == []


def test_a_stretched_page_is_reported():
    stretched = adapter.compare_page_read(NO_FEATURES,
                                          page_read(scale=2.0, scale_y=1.0))
    assert "aspect-distorted" in rules(stretched)


def test_the_residual_is_in_reading_pixels_whatever_the_page_unit():
    """Inches in, pixels out: 20 reading-px of error at a quarter scale is 20."""
    report = adapter.compare_page_read(
        NO_FEATURES, page_read(scale=0.25, moved={"note_b": (80.0, 0.0)}))
    drift = [f for f in report.findings if f.rule == "position-drift"][0]
    assert "80px" in drift.message


# ---------------------------------------------------------------------------
# Correspondence is declared
# ---------------------------------------------------------------------------
def test_keys_that_differ_from_the_readings_ids_need_a_map():
    order = [e["id"] for e in READING["elements"]]
    guid = lambda ident: ("{A1B2C3D4-0001-4E5F-8A9B-"
                          + format(order.index(ident) + 1, "012d") + "}")
    read = page_read(key=guid)
    ref_map = {guid(e["id"]): e["id"] for e in READING["elements"]}

    unmapped = adapter.compare_page_read(NO_FEATURES, read)
    assert not unmapped.faithful
    assert "missing-element" in rules(unmapped)

    mapped = adapter.compare_page_read(NO_FEATURES, read, ref_map)
    assert mapped.faithful and mapped.findings == []
    assert mapped.metrics["matched_by"] == "ref"


def test_two_shapes_mapped_to_one_element_cannot_both_be_it():
    read = page_read()
    twin = copy.deepcopy(read["shapes"][0])
    twin["ref"] = twin["identity"]["key"] = "second"
    twin["shape_id"] = 99
    read["shapes"].append(twin)
    ref_map = {"second": read["shapes"][0]["ref"]}
    report = adapter.compare_page_read(NO_FEATURES, read, ref_map)
    assert [f.rule for f in report.findings] == ["extra-element"]


# ---------------------------------------------------------------------------
# Connectors
# ---------------------------------------------------------------------------
def test_a_page_with_no_connectors_answers_the_link_question_with_missing():
    read = page_read()
    read["connectors"] = []
    report = adapter.compare_page_read(NO_FEATURES, read)
    assert sorted(f.subjects for f in report.findings
                  if f.rule == "missing-link") == [
        ("class_a", "note_a"), ("class_b", "note_b"), ("class_c", "note_c")]
    assert not any("no links were supplied" in e for e in report.not_run)


def test_an_unglued_connector_joins_nothing_and_says_so():
    read = page_read()
    del read["connectors"][2]["to_ref"]
    report = adapter.compare_page_read(NO_FEATURES, read)
    assert [f.subjects for f in report.findings
            if f.rule == "missing-link"] == [("class_c", "note_c")]
    assert any("'link-102'" in e and "not glued" in e for e in report.not_run)


def test_a_connector_drawn_backwards_is_a_warning_through_the_adapter():
    read = page_read()
    c = read["connectors"][0]
    c["from_ref"], c["to_ref"] = c["to_ref"], c["from_ref"]
    report = adapter.compare_page_read(NO_FEATURES, read)
    assert rules(report) == ["link-direction-reversed"]
    assert report.faithful


# ---------------------------------------------------------------------------
# What the page read cannot say is said
# ---------------------------------------------------------------------------
def test_a_reading_that_counts_features_gets_an_unanswered_question():
    """The page read carries no feature count, and must not invent one."""
    report = adapter.compare_page_read(READING, page_read())
    assert report.faithful
    assert sum("feature count for" in e for e in report.not_run) == 3


def test_a_shape_with_no_extent_is_set_aside_and_reported():
    read = page_read()
    read["shapes"][0]["width"] = 0
    report = adapter.compare_page_read(NO_FEATURES, read)
    ident = read["shapes"][0]["ref"]
    assert any(ident in e and "no usable extent" in e for e in report.not_run)
    assert [f.subjects for f in report.findings
            if f.rule == "missing-element"] == [(ident,)]


def test_blank_text_is_caught_and_absent_text_is_unanswered():
    blank = adapter.compare_page_read(
        VISIBLE, page_read(VISIBLE, text={"note_b": "   "},
                           fill={"class_a": "#FFECD9", "class_b": "#FFECD9",
                                 "class_c": "#FFECD9"}))
    assert [f.subjects for f in blank.findings
            if f.rule == "empty-content"] == [("note_b",)]

    absent = page_read(VISIBLE, fill={"class_a": "#FFECD9", "class_b": "#FFECD9",
                                      "class_c": "#FFECD9"})
    for item in absent["shapes"] + absent["containers"]:
        del item["text"]
    unanswered = adapter.compare_page_read(VISIBLE, absent)
    assert unanswered.metrics["content_judged"] == 0
    assert sum("content for" in e for e in unanswered.not_run) == 3


def test_a_wrong_fill_is_reported_and_a_near_one_is_not():
    fills = {"class_a": "#FFECD9", "class_b": "#FFECD9", "class_c": "#FFECD9"}
    wrong = adapter.compare_page_read(
        VISIBLE, page_read(VISIBLE, fill={**fills, "class_b": "#C0FFC0"}))
    assert [f.subjects for f in wrong.findings
            if f.rule == "fill-differs"] == [("class_b",)]

    near = adapter.compare_page_read(
        VISIBLE, page_read(VISIBLE, fill={**fills, "class_b": "#FDEAD7"}))
    assert near.faithful


def test_a_fill_that_is_not_a_color_is_set_aside_and_reported():
    fills = {"class_a": "#FFECD9", "class_b": "theme:accent1",
             "class_c": "#FFECD9"}
    report = adapter.compare_page_read(VISIBLE, page_read(VISIBLE, fill=fills))
    assert any("'theme:accent1' is not a #RRGGBB color" in e
               for e in report.not_run)
    assert report.metrics["fills_judged"] == 2


def test_a_reading_with_no_precision_is_still_refused():
    reading = {k: v for k, v in NO_FEATURES.items() if k != "precision"}
    with pytest.raises(ValueError, match="precision"):
        adapter.compare_page_read(reading, page_read())


def test_the_adapter_introduces_no_tolerance_of_its_own():
    """Precision comes from the reading. Doubling it must loosen the result.

    A move of 8 reading-px is a warning at precision 5 and invisible at 10; if
    the adapter carried its own threshold, the second would not follow the
    reading.
    """
    moved = page_read(moved={"note_b": (8.0, 0.0)})
    tight = adapter.compare_page_read({**NO_FEATURES, "precision": 5}, moved)
    loose = adapter.compare_page_read({**NO_FEATURES, "precision": 10}, moved)
    assert "position-drift" in rules(tight)
    assert loose.findings == []


# ---------------------------------------------------------------------------
# What the adapter refuses to read
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("change, match", [
    ({"contract": "apt-render-plan"}, "not a page read"),
    ({"contract_version": "9.9"}, "contract_version"),
    ({"unit": "mm"}, "unit"),
    ({"origin": "bottom-left"}, "origin"),
    ({"shapes": None}, "no `shapes` list"),
    ({"connectors": None}, "no `connectors` list"),
    ({"containers": None}, "no `containers` list"),
])
def test_a_document_that_is_not_a_page_read_this_adapter_knows_is_refused(
        change, match):
    read = {**page_read(), **change}
    if read.get(next(iter(change))) is None:
        del read[next(iter(change))]
    with pytest.raises(ValueError, match=match):
        adapter.to_fidelity_input(read)
