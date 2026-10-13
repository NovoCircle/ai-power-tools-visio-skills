"""Tests for the fidelity comparison.

The fixture is a SYNTHETIC reading with the character of a hand-placed diagram:
three classes down the left, each with a note to its right on a dashed link, plus
a heading and a banner note across the top. Its boxes are deliberately NOT
aligned and NOT evenly spaced - widths differ by a few units, left edges differ,
vertical gaps differ - because that raggedness is the property this whole module
exists to preserve, and a tidy fixture would let the conflict with the linter go
untested.

Synthetic on purpose. Readings taken off the reference corpus are measurements of
somebody else's copyrighted images, and these test files ship; the corpus
readings live with the corpus, in the private benchmark, and this file must stay
free of them.
"""
from __future__ import annotations

import math

import pytest

import fidelity

# PORT NOTE (the only difference between this file and its source): the source imports
# the EA skill's linter, and this library has none yet. Only
# `test_a_faithful_reproduction_of_a_hand_placed_diagram_fails_the_linter` uses
# it; that test skips, with its reason, until a linter is importable here.
try:
    import lint
except ImportError:  # no linter in this library yet
    lint = None


# The reading. Image coordinates, y downward, on a notional 1069x764 canvas.
#
# Precision 5px stands for what a reading off a screen export can honestly claim:
# a box with a 1px border and a drop shadow has an outer edge legible to within a
# few pixels, and claiming better would be claiming to have read the shadow.
READING = {
    "source": "three-classes-with-notes",
    "canvas": {"width": 1069, "height": 764},
    "precision": 5,
    "elements": [
        {"id": "heading", "kind": "text", "name": "Perspective heading",
         "rect": [380, 60, 740, 86]},
        {"id": "banner", "kind": "note", "name": "Explanatory banner",
         "rect": [40, 115, 1000, 220]},
        {"id": "class_a", "kind": "class", "name": "Asset",
         "rect": [310, 320, 500, 445], "features": 3},
        {"id": "class_b", "kind": "class", "name": "Business Entities",
         "rect": [320, 470, 498, 572], "features": 2},
        {"id": "class_c", "kind": "class", "name": "Human Resources",
         "rect": [320, 610, 512, 714], "features": 2},
        {"id": "note_a", "kind": "note", "name": "Asset note",
         "rect": [630, 300, 848, 440]},
        {"id": "note_b", "kind": "note", "name": "Entities note",
         "rect": [630, 495, 848, 578]},
        {"id": "note_c", "kind": "note", "name": "Resources note",
         "rect": [630, 630, 848, 716]},
    ],
    "links": [
        {"from": "class_a", "to": "note_a", "style": "dashed"},
        {"from": "class_b", "to": "note_b", "style": "dashed"},
        {"from": "class_c", "to": "note_c", "style": "dashed"},
    ],
}

LINKS = [{"from": e["from"], "to": e["to"]} for e in READING["links"]]


def drawn(scale: float = 1.0, dx: float = 0.0, dy: float = 0.0,
          scale_y: float | None = None, moved: dict | None = None,
          drop: tuple = (), features: dict | None = None) -> list:
    """The reading rendered back out as EA objects.

    EA stores top and bottom NEGATIVE with top > bottom, so the conversion is a
    negation - and doing it here in the test fixture as well as in the module
    means a sign error in one of them shows up as a failure rather than as two
    mistakes agreeing with each other.
    """
    scale_y = scale if scale_y is None else scale_y
    moved = moved or {}
    features = features or {}
    out = []
    for entry in READING["elements"]:
        ident = entry["id"]
        if ident in drop:
            continue
        left, top, right, bottom = entry["rect"]
        mx, my = moved.get(ident, (0.0, 0.0))
        obj = {
            "ref": ident,
            # `element_id` is what the LINTER keys findings on. Carried here so
            # the same objects can be handed to both, which is the point of the
            # test that runs them side by side.
            "element_id": ident,
            "name": entry["name"],
            "left": left * scale + dx + mx,
            "right": right * scale + dx + mx,
            "top": -(top * scale_y + dy + my),
            "bottom": -(bottom * scale_y + dy + my),
        }
        if "features" in entry:
            obj["features"] = features.get(ident, entry["features"])
        out.append(obj)
    return out


# ---------------------------------------------------------------------------
# The property the module exists for
# ---------------------------------------------------------------------------
def test_an_exact_reproduction_is_faithful():
    report = fidelity.compare(READING, drawn(), LINKS)
    assert report.faithful
    assert report.findings == []
    assert report.not_run == []
    assert report.metrics["matched"] == 8


def test_the_same_diagram_drawn_bigger_and_elsewhere_is_the_same_diagram():
    """Similarity, not equality. A reader would not notice and need not."""
    report = fidelity.compare(READING, drawn(scale=2.5, dx=400, dy=-90), LINKS)
    assert report.faithful
    assert report.findings == []
    # The fit reports the difference as one number rather than smearing it over
    # every element as a drift the caller would have to spot was systematic.
    assert report.metrics["scale"] == pytest.approx(0.4, abs=1e-6)


def test_a_faithful_reproduction_of_a_hand_placed_diagram_fails_the_linter():
    """The conflict this module exists to settle, pinned as a test.

    The three classes in the reference are 193, 180 and 192 wide and start at
    x 316, 324 and 324. Reproducing that faithfully means reproducing the
    raggedness, and the linter is right to report it - so `LintReport.clean` is
    the wrong gate for a transcription, and this fails the day somebody makes
    the two agree by loosening one of them.
    """
    if lint is None:
        pytest.skip("no linter in the Visio skills library yet (see PORT NOTE)")
    objects = drawn()
    report = fidelity.compare(READING, objects, LINKS)
    assert report.faithful

    classes = [o for o in objects if o["ref"].startswith("class_")]
    lint_report = lint.LintReport()
    lint.check_uniform_sizing({"class": classes}, lint_report)
    assert not lint_report.clean
    assert [f.rule for f in lint_report.errors] == ["uniform-sizing"]


# ---------------------------------------------------------------------------
# Each way it can fail
# ---------------------------------------------------------------------------
def test_a_missing_element_is_an_error():
    report = fidelity.compare(READING, drawn(drop=("note_b",)), LINKS)
    assert not report.faithful
    missing = [f for f in report.findings if f.rule == "missing-element"]
    assert [f.subjects for f in missing] == [("note_b",)]


def test_a_link_to_a_missing_element_is_not_reported_as_a_missing_link():
    """Reporting the consequence as well as the cause buries the cause."""
    report = fidelity.compare(READING, drawn(drop=("note_b",)), LINKS)
    assert not any(f.rule == "missing-link" for f in report.findings)
    # and the denominator says only two of the three links could be judged
    assert report.metrics["links_judged"] == 2


def test_an_element_standing_for_nothing_is_an_error():
    objects = drawn() + [{"ref": "", "name": "Stray", "left": 10, "right": 60,
                          "top": -10, "bottom": -40}]
    report = fidelity.compare(READING, objects, LINKS)
    assert [f.rule for f in report.findings] == ["extra-element"]


def test_two_objects_cannot_both_be_the_one_box():
    """The second claim is an extra, not a silent overwrite."""
    objects = drawn()
    twin = dict(objects[2])
    objects.append(twin)
    report = fidelity.compare(READING, objects, LINKS)
    extra = [f for f in report.findings if f.rule == "extra-element"]
    assert [f.subjects for f in extra] == [("class_a",)]


def test_moving_one_box_past_the_reading_precision_is_reported():
    report = fidelity.compare(READING, drawn(moved={"note_b": (9.0, 0.0)}),
                              LINKS)
    drift = [f for f in report.findings if f.rule == "position-drift"]
    assert [f.subjects for f in drift] == [("note_b",)]
    assert drift[0].severity == "warning"


def test_moving_a_box_far_enough_is_an_error_rather_than_a_warning():
    report = fidelity.compare(READING, drawn(moved={"note_b": (60.0, 0.0)}),
                              LINKS)
    drift = [f for f in report.findings if f.rule == "position-drift"]
    assert drift and drift[0].severity == "error"


def test_a_shift_within_the_readings_precision_is_not_a_finding():
    """The tolerance IS the precision, so this is quiet by construction."""
    report = fidelity.compare(READING, drawn(moved={"note_b": (3.0, 0.0)}),
                              LINKS)
    assert report.findings == []


def test_swapping_two_boxes_inverts_an_ordering_and_is_an_error():
    a = next(e for e in READING["elements"] if e["id"] == "class_a")["rect"]
    c = next(e for e in READING["elements"] if e["id"] == "class_c")["rect"]
    swap = {"class_a": (0.0, c[1] - a[1]), "class_c": (0.0, a[1] - c[1])}
    report = fidelity.compare(READING, drawn(moved=swap), LINKS)
    inverted = [f for f in report.findings if f.rule == "order-inverted"]
    assert inverted
    assert all(f.severity == "error" for f in inverted)
    assert ("class_a", "class_c") in {f.subjects for f in inverted}


def test_stretching_one_axis_is_an_error_and_a_uniform_scale_is_not():
    stretched = fidelity.compare(READING, drawn(scale=2.0, scale_y=1.0), LINKS)
    assert [f.rule for f in stretched.findings if f.rule == "aspect-distorted"]
    assert not stretched.faithful

    uniform = fidelity.compare(READING, drawn(scale=2.0, scale_y=2.0), LINKS)
    assert uniform.faithful


def test_resizing_a_box_is_reported_against_twice_the_precision():
    """A width is a difference of two readings and carries both their errors."""
    objects = drawn()
    box = next(o for o in objects if o["ref"] == "note_a")
    box["right"] += 14
    report = fidelity.compare(READING, objects, LINKS)
    sized = [f for f in report.findings if f.rule == "size-drift"]
    assert sized and sized[0].subjects == ("note_a",)
    assert "width" in sized[0].message


def test_a_width_within_twice_the_precision_is_quiet():
    objects = drawn()
    box = next(o for o in objects if o["ref"] == "note_a")
    box["right"] += 6
    report = fidelity.compare(READING, objects, LINKS)
    assert not [f for f in report.findings if f.rule == "size-drift"]


def test_a_missing_connector_is_an_error():
    report = fidelity.compare(READING, drawn(), LINKS[:2])
    assert [f.subjects for f in report.findings
            if f.rule == "missing-link"] == [("class_c", "note_c")]


def test_a_connector_nobody_drew_is_an_error():
    report = fidelity.compare(READING, drawn(),
                              LINKS + [{"from": "class_a", "to": "class_b"}])
    assert [f.rule for f in report.findings] == ["extra-link"]


def test_a_reversed_connector_is_a_warning_not_a_missing_one():
    reversed_links = [{"from": "note_a", "to": "class_a"}] + LINKS[1:]
    report = fidelity.compare(READING, drawn(), reversed_links)
    assert [f.rule for f in report.findings] == ["link-direction-reversed"]
    assert report.faithful


def test_a_class_drawn_with_the_wrong_number_of_features_is_reported():
    report = fidelity.compare(READING, drawn(features={"class_a": 2}), LINKS)
    assert [f.subjects for f in report.findings
            if f.rule == "feature-count"] == [("class_a",)]


# ---------------------------------------------------------------------------
# What it refuses to claim
# ---------------------------------------------------------------------------
def test_a_reading_without_a_precision_is_refused():
    reading = {k: v for k, v in READING.items() if k != "precision"}
    with pytest.raises(ValueError, match="precision"):
        fidelity.compare(reading, drawn(), LINKS)


def test_a_reading_claiming_to_be_exact_is_refused():
    with pytest.raises(ValueError, match="positive"):
        fidelity.compare({**READING, "precision": 0}, drawn(), LINKS)


def test_one_matched_element_reports_that_it_measured_nothing():
    """A clean report here would be a report of a comparison that never ran."""
    report = fidelity.compare(READING, drawn()[:1], LINKS)
    assert report.fit is None
    assert any("at least two" in entry for entry in report.not_run)
    assert "worst_position_drift" not in report.metrics


def test_links_absent_from_the_reading_are_unanswered_not_clean():
    reading = {k: v for k, v in READING.items() if k != "links"}
    report = fidelity.compare(reading, drawn(), LINKS)
    assert any("declares no `links`" in entry for entry in report.not_run)
    assert "links_judged" not in report.metrics


def test_links_absent_from_the_reproduction_are_unanswered_not_clean():
    report = fidelity.compare(READING, drawn(), None)
    assert any("no links were supplied" in entry for entry in report.not_run)


def test_matching_by_name_says_so_because_it_is_a_guess():
    objects = [{k: v for k, v in obj.items() if k != "ref"}
               for obj in drawn()]
    report = fidelity.compare(READING, objects, LINKS)
    assert report.metrics["matched_by"] == "name"
    assert any("inferred from element names" in e for e in report.not_run)
    # It still compares - the guess is usable, it is just not quiet.
    assert report.metrics["matched"] == 8


def test_a_pair_the_reference_cannot_separate_is_not_judged():
    """Excluded from the denominator rather than passed.

    Two boxes whose centers sit within the reading precision are, as far as the
    reading knows, level - so requiring the reproduction to pick the same side
    would be requiring it to reproduce noise.
    """
    reading = {
        "precision": 5,
        "elements": [
            {"id": "a", "rect": [0, 0, 100, 50]},
            {"id": "b", "rect": [0, 200, 102, 250]},   # centers 1px apart in x
        ],
        "links": [],
    }
    objects = [
        {"ref": "a", "left": 0, "right": 100, "top": 0, "bottom": -50},
        # drawn the other way round in x, by more than the precision
        {"ref": "b", "left": -40, "right": 62, "top": -200, "bottom": -250},
    ]
    report = fidelity.compare(reading, objects, [])
    assert not [f for f in report.findings if f.rule == "order-inverted"]
    # one pair judged: the vertical one. The horizontal one could not be.
    assert report.metrics["ordering_pairs_judged"] == 1


def test_a_degenerate_reproduction_fits_nothing_and_says_so():
    reading = {
        "precision": 2,
        "elements": [{"id": "a", "rect": [0, 0, 10, 10]},
                     {"id": "b", "rect": [100, 100, 110, 110]}],
    }
    stacked = [
        {"ref": "a", "left": 0, "right": 10, "top": 0, "bottom": -10},
        {"ref": "b", "left": 0, "right": 10, "top": 0, "bottom": -10},
    ]
    report = fidelity.compare(reading, stacked, [])
    assert report.fit is None
    assert any("no scale could be fitted" in e for e in report.not_run)


def test_fit_similarity_needs_two_points_and_some_spread():
    assert fidelity.fit_similarity([]) is None
    assert fidelity.fit_similarity([((0, 0), (0, 0))]) is None
    assert fidelity.fit_similarity([((5, 5), (0, 0)), ((5, 5), (9, 9))]) is None


def test_rotation_is_not_fitted_because_a_turned_diagram_is_a_different_one():
    objects = []
    for entry in READING["elements"]:
        left, top, right, bottom = entry["rect"]
        # quarter turn: (x, y) -> (y, x), which preserves every distance
        objects.append({"ref": entry["id"],
                        "left": top, "right": bottom,
                        "top": -left, "bottom": -right})
    report = fidelity.compare(READING, objects, LINKS)
    assert not report.faithful
    assert any(f.rule in ("position-drift", "order-inverted")
               for f in report.errors)


# ---------------------------------------------------------------------------
# The coordinate conversion, which is where a sign error would live
# ---------------------------------------------------------------------------
def test_ea_coordinates_are_converted_rather_than_assumed():
    """`top` and `bottom` are negative in EA, with `top > bottom`."""
    obj = {"ref": "x", "left": 10, "right": 110, "top": -20, "bottom": -70}
    assert fidelity._produced_rect(obj, "x") == (10.0, 20.0, 110.0, 70.0)


def test_an_object_in_the_wrong_sign_convention_is_refused_not_measured():
    obj = {"ref": "x", "left": 10, "right": 110, "top": 70, "bottom": 20}
    with pytest.raises(ValueError, match="EA stores"):
        fidelity._produced_rect(obj, "x")


def test_an_inverted_reference_rect_is_refused():
    with pytest.raises(ValueError, match="y increases downward"):
        fidelity._reading_rect({"rect": [0, 100, 50, 10]}, "r")


def test_a_reference_element_without_an_id_is_refused():
    with pytest.raises(ValueError, match="no id"):
        fidelity.reference_rects({"elements": [{"rect": [0, 0, 1, 1]}]})


def test_a_duplicated_reference_id_is_refused():
    with pytest.raises(ValueError, match="twice"):
        fidelity.reference_rects({"elements": [
            {"id": "a", "rect": [0, 0, 1, 1]},
            {"id": "a", "rect": [2, 2, 3, 3]},
        ]})


def test_the_residual_is_measured_in_reference_pixels():
    """So it is comparable to the precision, which is declared in them.

    Drawn at a quarter scale with one box 20 EA units out of place: on the
    reference that is 80px, which is what the finding must say, not 20.
    """
    report = fidelity.compare(READING,
                              drawn(scale=0.25, moved={"note_b": (20.0, 0.0)}),
                              LINKS)
    drift = [f for f in report.findings if f.rule == "position-drift"][0]
    assert "80px" in drift.message
    assert report.metrics["worst_position_drift"] == pytest.approx(80, abs=1.5)


def test_every_finding_says_what_to_do_about_it():
    reports = [
        fidelity.compare(READING, drawn(drop=("note_b",)), LINKS),
        fidelity.compare(READING, drawn(moved={"note_b": (60.0, 0.0)}), LINKS),
        fidelity.compare(READING, drawn(scale=2.0, scale_y=1.0), LINKS),
        fidelity.compare(READING, drawn(features={"class_a": 9}), LINKS),
        fidelity.compare(READING, drawn(), LINKS[:2]),
    ]
    findings = [f for r in reports for f in r.findings]
    assert findings
    assert all(f.correction for f in findings)
    assert all(f.severity in ("error", "warning", "info") for f in findings)


def test_the_fixture_keeps_the_raggedness_it_exists_to_carry():
    """Guards the fixture itself.

    Every interesting assertion above rests on this being a diagram no layout
    rule would produce. If somebody tidies a rect to make a test pass, the
    fixture stops representing a hand-placed diagram and the suite stops meaning
    anything - so the properties are asserted rather than left to inspection.
    """
    rects = fidelity.reference_rects(READING)
    ids = ("class_a", "class_b", "class_c")
    widths = {i: rects[i][2] - rects[i][0] for i in ids}
    # three different widths: no uniform-sizing rule would draw these
    assert len(set(widths.values())) == 3
    # two different left edges: not a stack anything aligned
    assert len({rects[i][0] for i in ids}) == 2
    # and uneven vertical gaps: no pitch rule would space these
    gaps = (rects["class_b"][1] - rects["class_a"][3],
            rects["class_c"][1] - rects["class_b"][3])
    assert gaps[0] != gaps[1]
    assert all(g > 0 for g in gaps)


# ---------------------------------------------------------------------------
# The robust fit: one wrong box must not accuse seven right ones
# ---------------------------------------------------------------------------
def test_one_displaced_box_is_the_only_one_reported():
    """The reason the fit trims at all.

    A plain least-squares fit splits the difference: the displaced box absorbs
    most of its own error and every other box picks up a share of the rest, so
    the report names elements that are exactly where they should be and a
    caller following it moves the wrong ones.
    """
    report = fidelity.compare(READING, drawn(moved={"note_b": (60.0, 0.0)}),
                              LINKS)
    drift = [f for f in report.findings if f.rule == "position-drift"]
    assert [f.subjects for f in drift] == [("note_b",)]
    assert drift[0].severity == "error"
    assert report.metrics["fit_trimmed"] == ["note_b"]
    # and the residual is the WHOLE displacement, not seven eighths of it
    assert report.metrics["worst_position_drift"] == pytest.approx(60, abs=1.0)


def test_a_clean_reproduction_trims_nothing():
    report = fidelity.compare(READING, drawn(scale=1.7, dx=12, dy=-40), LINKS)
    assert report.metrics["fit_trimmed"] == []


def test_trimming_stops_at_half_and_does_not_chase_a_majority_away():
    """With no agreeing majority the diagram is simply different.

    Five of eight boxes scattered: there is no frame left that most of them
    share, so the check stops removing elements and reports what it sees rather
    than trimming until some arbitrary four agree.
    """
    scattered = {"class_a": (150.0, 40.0), "class_b": (-120.0, 90.0),
                 "class_c": (200.0, -70.0), "note_a": (-160.0, 130.0),
                 "note_b": (90.0, -110.0)}
    report = fidelity.compare(READING, drawn(moved=scattered), LINKS)
    assert not report.faithful
    assert len(report.metrics["fit_trimmed"]) <= 4
    assert report.metrics["elements_placed"] == 8


def test_every_element_is_measured_even_when_it_was_trimmed():
    """Trimmed means "not allowed to define the frame", not "not checked"."""
    report = fidelity.compare(READING, drawn(moved={"note_b": (60.0, 0.0)}),
                              LINKS)
    assert "note_b" in report.metrics["fit_trimmed"]
    assert any(f.subjects == ("note_b",) for f in report.findings)


# ---------------------------------------------------------------------------
# Content and color, which geometry alone cannot see
# ---------------------------------------------------------------------------
# The same reading, now recording that the notes carry body text and that the
# three classes share a fill. Geometry is unchanged, so anything that fails
# below fails for a reason the earlier tests cannot see.
VISIBLE = {
    **READING,
    "color_precision": 4,
    "elements": [
        {**e,
         **({"text": True} if e["id"].startswith("note") else {}),
         **({"fill": "#FFECD9"} if e["id"].startswith("class") else {})}
        for e in READING["elements"]
    ],
}


def _with(objects, **per_ref):
    for obj in objects:
        for key, value in per_ref.get(obj["ref"], {}).items():
            obj[key] = value
    return objects


def _filled(text="something"):
    return _with(drawn(), **{
        e["id"]: ({"text": text} if e.get("text") else {})
        | ({"fill": e["fill"]} if e.get("fill") else {})
        for e in VISIBLE["elements"]})


def test_a_box_in_the_right_place_and_empty_is_not_faithful():
    """The failure that motivated this check, pinned.

    Eight boxes at the right coordinates at the right sizes on the right links,
    and the notes rendered blank because a Note draws its documentation rather
    than its name. A reader saw it instantly; the geometry-only comparison
    called it faithful.
    """
    objects = _with(_filled(), note_b={"text": "   "})
    report = fidelity.compare(VISIBLE, objects, LINKS)
    assert not report.faithful
    assert [f.subjects for f in report.findings
            if f.rule == "empty-content"] == [("note_b",)]


def test_content_that_is_present_passes_whatever_it_says():
    """Presence, not wording - the words are expected to differ."""
    report = fidelity.compare(VISIBLE, _filled("entirely different words"),
                              LINKS)
    assert report.faithful
    assert report.metrics["content_judged"] == 3


def test_a_reproduction_that_reports_no_text_is_unanswered_not_clean():
    objects = _filled()
    for obj in objects:
        obj.pop("text", None)
    report = fidelity.compare(VISIBLE, objects, LINKS)
    assert report.metrics["content_judged"] == 0
    assert sum("content for" in e for e in report.not_run) == 3


def test_a_box_filled_the_wrong_color_is_reported():
    report = fidelity.compare(VISIBLE, _with(_filled(),
                                             class_b={"fill": "#C0FFC0"}),
                              LINKS)
    assert [f.subjects for f in report.findings
            if f.rule == "fill-differs"] == [("class_b",)]


def test_a_fill_within_the_readings_color_precision_is_quiet():
    """A renderer rounds a gradient; the reading says how much that is worth."""
    report = fidelity.compare(VISIBLE, _with(_filled(),
                                             class_b={"fill": "#FDEAD7"}),
                              LINKS)
    assert report.faithful
    assert report.metrics["worst_fill_delta"] <= 4


def test_an_element_left_at_the_tool_default_is_not_thereby_correct():
    objects = _filled()
    next(o for o in objects if o["ref"] == "class_c").pop("fill")
    report = fidelity.compare(VISIBLE, objects, LINKS)
    assert report.metrics["fills_judged"] == 2
    assert any("fill for 'class_c'" in e for e in report.not_run)


def test_declaring_fills_without_a_color_precision_is_refused():
    reading = {k: v for k, v in VISIBLE.items() if k != "color_precision"}
    with pytest.raises(ValueError, match="color_precision"):
        fidelity.compare(reading, _filled(), LINKS)


def test_a_reading_that_records_neither_says_nothing_about_them():
    """The original fixture records no text and no fills, so those two checks
    contribute nothing rather than passing vacuously."""
    report = fidelity.compare(READING, drawn(), LINKS)
    assert report.metrics["content_judged"] == 0
    assert "fills_judged" not in report.metrics


def test_a_reading_says_what_it_did_not_read():
    """Partial is allowed; partial and SILENT is not.

    A comparison only knows about what it was told, so a reading that skipped a
    whole category of element would otherwise report a perfect score for a
    diagram missing every one of them. That is the same failure as the blank
    notes, one level up.
    """
    reading = {**READING, "not_read": ["ports on block borders"]}
    report = fidelity.compare(reading, drawn(), LINKS)
    assert report.faithful
    assert report.metrics["not_read"] == ["ports on block borders"]
    assert any("ports on block borders" in e for e in report.not_run)


def test_a_reading_that_read_everything_says_nothing_extra():
    report = fidelity.compare(READING, drawn(), LINKS)
    assert report.metrics["not_read"] == []
