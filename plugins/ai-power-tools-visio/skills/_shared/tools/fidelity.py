"""Does the diagram we produced look like the one we were shown?

`lint.py` answers a different question, and the difference matters enough to
state first. The linter judges a diagram against ITSELF: nothing overlaps, peers
are the same size, spacing is even, labels fit. That is INTRINSIC quality, and it
is the right question when we are composing a layout from structure, because then
nobody has said where anything goes and the only standard available is whether
the result reads well.

This module judges a diagram against a REFERENCE. That is EXTRINSIC fidelity, and
it is the right question when we are reproducing a picture - a diagram drawn in
some other tool, of which all that survives is the image. There the standard is
not "does it read well" but "is it the same diagram".

THE TWO WILL DISAGREE, AND ON A REPRODUCTION THIS ONE WINS.

That is not a wrinkle, it is the central fact. A hand-placed diagram is hand
placed: its boxes are a few units out of alignment, its gaps are irregular, its
widths differ by ten units for no reason. `check_stack_alignment` and
`check_pitch_consistency` will report every one of those, correctly, as defects -
and "fixing" them produces a tidier diagram that is no longer the one we were
asked to reproduce. So a transcription is NOT required to lint clean, and a
caller who gates on `LintReport.clean` for a transcribed diagram has gated on the
wrong thing.

WHAT "ESSENTIALLY THE SAME" IS TAKEN TO MEAN

Similarity, not equality. The same diagram drawn at twice the scale, or shifted
across the canvas, is the same diagram; a reader would not notice and should not
have to. So the comparison fits a single uniform scale and an offset between the
two, and judges what is left over. Three consequences worth being explicit about:

  * A systematic difference - everything 1.4x bigger, everything 30 units right -
    is absorbed by the fit and is not a finding. It shows up as one number
    (`scale`) that a caller can read, rather than being smeared across every
    element as a drift they would have to recognize as systematic themselves.
  * The scale is UNIFORM. Stretching x and y differently changes proportions, and
    that is visible, so it is reported (`aspect-distorted`) rather than absorbed.
  * Rotation is not fitted. A diagram turned on its side is not the same diagram.

THERE IS NO TOLERANCE CONSTANT IN THIS MODULE, DELIBERATELY

Every other threshold in this toolchain is a calibrated constant, and each one is
a small standing debt: it was measured once, against a population that can move.
Here there is nothing to calibrate, because the uncertainty has a single source
and the reading itself knows it.

The produced geometry is exact - we placed it, to the unit. The reference
geometry is read off a picture by eye, and is good to some number of pixels. So
the tolerance IS the reading's precision, declared by the reading (`precision`),
and a difference larger than the reading's own precision is a real difference.
Nothing else is added.

The practical effect is that a reading which cannot be made precisely must SAY so
by declaring a larger precision, which is honest, and every check then loosens
together. A reading that declares a precision it cannot support is the one way to
get a wrong answer here, and that is a property of the reading rather than a
constant somebody has to maintain.

CORRESPONDENCE IS DECLARED, NEVER GUESSED

Each produced object states which reference element it stands for (`ref`). It is
not inferred from the name, because on our own corpus the names deliberately do
not survive: a Sparx sample reproduced as reference content has different element
names by design, and a matcher keyed on names would fail on exactly the diagrams
this exists to check. Name matching is available as an explicit fallback and the
report says when it was used, because "we guessed the correspondence" and "we
were told it" are different confidences and only one of them should be quiet.

An unmatched element on either side is a finding, never a skipped comparison.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence

__all__ = [
    "Finding",
    "FidelityReport",
    "Fit",
    "SEVERE_MULTIPLE",
    "compare",
    "fit_similarity",
    "fit_robustly",
    "match_elements",
    "reference_rects",
    "produced_rects",
    "check_inventory",
    "check_placement",
    "check_ordering",
    "check_sizing",
    "check_links",
    "check_features",
    "check_content",
    "check_fill",
]

# A drift is a warning until it is this many times the reading's precision, and
# an error beyond it. Not a tolerance - the tolerance is the precision itself,
# and everything past it is already a real difference. This only separates "a
# reader would have to look twice" from "a reader would see it at a glance", and
# a factor of three is the point at which a box has moved by most of its own
# width on the readings this corpus produces.
SEVERE_MULTIPLE = 3.0


@dataclass(frozen=True)
class Finding:
    """One way the reproduction differs from its reference.

    Deliberately the same shape as `lint.Finding` - a caller that already knows
    how to render, sort and act on one should not need a second vocabulary for
    the other, and the two reports are read side by side.
    """

    rule: str
    severity: str            # "error" | "warning" | "info"
    message: str
    subjects: tuple = ()     # reference element ids involved
    correction: str = ""     # what to do about it

    def __str__(self) -> str:
        where = f" {list(self.subjects)}" if self.subjects else ""
        return f"[{self.severity}] {self.rule}{where}: {self.message}"


@dataclass(frozen=True)
class Fit:
    """The uniform scale and offset that best maps produced onto reference.

    `scale` is how much bigger the reference is than what we produced, so 2.0
    means we drew it at half size - which is not a defect, only a fact a caller
    may want. `residuals` are what is left per element AFTER that mapping, in
    reference pixels, which is the unit the precision is declared in so the two
    are directly comparable.
    """

    scale: float
    offset_x: float
    offset_y: float
    residuals: dict = field(default_factory=dict)
    scale_x: float = 0.0
    scale_y: float = 0.0

    def apply(self, x: float, y: float) -> tuple:
        return (self.scale * x + self.offset_x, self.scale * y + self.offset_y)


@dataclass
class FidelityReport:
    findings: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    # A check that wanted to run and lacked its input, with the reason. Same
    # contract as `lint.LintReport.not_run`, and the same hazard it exists to
    # close: a check that did not run reports exactly what a clean one does, so
    # a report with entries here has compared less than it looks.
    not_run: list = field(default_factory=list)
    fit: Optional[Fit] = None
    matched: dict = field(default_factory=dict)

    @property
    def errors(self) -> list:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def faithful(self) -> bool:
        """No errors. Warnings are differences a reader might notice, reported.

        Named for what it claims rather than `clean`, because `clean` already
        means something else one import away and the two are not the same
        judgment: a transcription can be faithful and lint badly, and a
        composed diagram can lint perfectly and be faithful to nothing.
        """
        return not self.errors

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
def _reading_rect(entry: Mapping[str, Any], where: str) -> tuple:
    """`[left, top, right, bottom]` as read off an image: y increases DOWNWARD.

    Image coordinates, because that is what a reading is taken in and asking a
    reader to negate what they measured is asking for a sign error.
    """
    rect = entry.get("rect")
    if rect is None:
        raise ValueError(f"{where}: no rect. A reference element without "
                         f"geometry cannot take part in a comparison of "
                         f"geometry; leave it out, or read it.")
    try:
        left, top, right, bottom = (float(v) for v in rect)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{where}: rect must be four numbers "
                         f"[left, top, right, bottom], got {rect!r}") from exc
    if right <= left or bottom <= top:
        raise ValueError(
            f"{where}: rect {rect!r} is empty or inverted. In image "
            f"coordinates y increases downward, so bottom must exceed top.")
    return (left, top, right, bottom)


def _produced_rect(obj: Mapping[str, Any], where: str) -> tuple:
    """The same rect from an EA object, converted out of EA's convention.

    EA stores `top` and `bottom` NEGATIVE with `top > bottom`, so a height is
    `top - bottom`. Negating both puts the rect in the same y-down frame the
    reading uses, which is the only frame the two can be compared in. Doing it
    here, once, is the difference between one conversion and a sign error in
    every check.
    """
    try:
        left = float(obj["left"])
        right = float(obj["right"])
        raw_top = float(obj["top"])
        raw_bottom = float(obj["bottom"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{where}: needs numeric left/top/right/bottom, "
                         f"got {obj!r}") from exc
    # Checked on the RAW values, before negating, and this is the whole reason
    # the check is here. A rect handed over in the y-down convention by mistake
    # - top 70, bottom 20 - negates to a perfectly well-formed rect, just
    # mirrored, so validating after the conversion accepts it silently and
    # every measurement downstream is of a diagram flipped about the x axis.
    # EA's own values are never positive, so the sign is the tell.
    if raw_top > 0 or raw_bottom > 0:
        raise ValueError(
            f"{where}: top={raw_top:g} bottom={raw_bottom:g}. EA stores both "
            f"negative with top > bottom, so a positive value means these are "
            f"already in image coordinates. Negating them would silently "
            f"mirror the element rather than convert it.")
    if raw_top <= raw_bottom:
        raise ValueError(
            f"{where}: top={raw_top:g} is not above bottom={raw_bottom:g}. EA "
            f"stores both negative with top > bottom, so a height is "
            f"top - bottom.")
    top, bottom = -raw_top, -raw_bottom
    if right <= left:
        raise ValueError(
            f"{where}: left={left:g} right={right:g} is empty or inverted.")
    return (left, top, right, bottom)


def reference_rects(reading: Mapping[str, Any]) -> dict:
    """`{element id: rect}` for a reading, validated."""
    out: dict = {}
    for index, entry in enumerate(reading.get("elements") or []):
        ident = str(entry.get("id") or "").strip()
        if not ident:
            raise ValueError(
                f"reference element {index}: no id. Ids are how a produced "
                f"object declares what it stands for, so an element without "
                f"one can never be matched to anything.")
        if ident in out:
            raise ValueError(
                f"reference element {index}: id {ident!r} is used twice. A "
                f"produced object naming it would match two elements, and "
                f"which one it meant is exactly what cannot be recovered.")
        out[ident] = _reading_rect(entry, f"reference element {ident!r}")
    return out


def produced_rects(objects: Iterable[Mapping[str, Any]]) -> list:
    """`[(object, rect)]`, validated, preserving the caller's order."""
    return [(obj, _produced_rect(obj, f"produced object {index}"))
            for index, obj in enumerate(objects)]


def _center(rect: Sequence[float]) -> tuple:
    return ((rect[0] + rect[2]) / 2.0, (rect[1] + rect[3]) / 2.0)


def _size(rect: Sequence[float]) -> tuple:
    return (rect[2] - rect[0], rect[3] - rect[1])


def _precision(reading: Mapping[str, Any]) -> float:
    """The reading's declared precision, which IS every tolerance here.

    Refused rather than defaulted. A default would be a tolerance constant
    wearing a disguise, and it would be applied to readings whose author never
    considered the question - which is precisely when it would be wrong.
    """
    if "precision" not in reading:
        raise ValueError(
            "the reading declares no `precision`. It is the number of pixels "
            "the geometry was read to, and every tolerance in this comparison "
            "derives from it, so there is no safe value to assume: a reading "
            "taken off a crisp 1000px export and one taken off a photograph "
            "of a whiteboard need different answers and only their author "
            "knows which this is.")
    try:
        precision = float(reading["precision"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"precision must be a number of pixels, got "
                         f"{reading['precision']!r}") from exc
    if precision <= 0:
        raise ValueError(
            f"precision must be positive, got {precision}. A reading claiming "
            f"to be exact would make every rounding difference a defect.")
    return precision


# ---------------------------------------------------------------------------
# Correspondence
# ---------------------------------------------------------------------------
def match_elements(reading: Mapping[str, Any],
                   objects: Sequence[Mapping[str, Any]]) -> tuple:
    """`(matched, missing, extra, how)` between a reading and what we drew.

    `matched` is `{reference id: object}`. `missing` are reference ids nothing
    claimed; `extra` are produced objects claiming nothing, or claiming an id
    the reading does not have. `how` is `"ref"` or `"name"` - see the module
    docstring on why the distinction is reported rather than smoothed over.

    A produced object claiming an id ANOTHER object already claimed is an
    `extra`, not a silent overwrite. Two boxes cannot both be the one box.
    """
    known = reference_rects(reading)
    by_name = {}
    for entry in reading.get("elements") or []:
        name = str(entry.get("name") or "").strip().casefold()
        if name:
            # A name used twice cannot identify anything, so it identifies
            # nothing rather than whichever came last.
            by_name[name] = None if name in by_name else str(entry["id"])

    declared = [obj for obj in objects if str(obj.get("ref") or "").strip()]
    how = "ref" if declared else "name"

    matched: dict = {}
    extra: list = []
    for obj in objects:
        ident = str(obj.get("ref") or "").strip()
        if not ident and how == "name":
            ident = by_name.get(
                str(obj.get("name") or "").strip().casefold()) or ""
        if ident and ident in known and ident not in matched:
            matched[ident] = obj
        else:
            extra.append(obj)

    missing = [ident for ident in known if ident not in matched]
    return (matched, missing, extra, how)


# ---------------------------------------------------------------------------
# The fit
# ---------------------------------------------------------------------------
def fit_similarity(pairs: Sequence[tuple]) -> Optional[Fit]:
    """Least-squares uniform scale and offset mapping produced onto reference.

    `pairs` is `[(produced_center, reference_center)]`. Closed form: with both
    sets centered, the scale that minimizes the squared error is the ratio of
    the cross term to the produced spread, and the offset follows from the
    centroids.

    Returns None when the produced centers have no spread at all - every box at
    one point - because then no scale is determined and any answer would be
    invented. Callers report that as a check that could not run.
    """
    if len(pairs) < 2:
        return None
    n = float(len(pairs))
    px = sum(p[0] for p, _ in pairs) / n
    py = sum(p[1] for p, _ in pairs) / n
    rx = sum(r[0] for _, r in pairs) / n
    ry = sum(r[1] for _, r in pairs) / n

    cross = sum((p[0] - px) * (r[0] - rx) + (p[1] - py) * (r[1] - ry)
                for p, r in pairs)
    spread = sum((p[0] - px) ** 2 + (p[1] - py) ** 2 for p, _ in pairs)
    if spread <= 0:
        return None
    scale = cross / spread

    # The per-axis scales are fitted separately and carried, not applied. They
    # are what `check_placement` needs to tell "drawn at a different size",
    # which is not a defect, from "stretched along one axis", which is.
    spread_x = sum((p[0] - px) ** 2 for p, _ in pairs)
    spread_y = sum((p[1] - py) ** 2 for p, _ in pairs)
    scale_x = (sum((p[0] - px) * (r[0] - rx) for p, r in pairs) / spread_x
               if spread_x > 0 else 0.0)
    scale_y = (sum((p[1] - py) * (r[1] - ry) for p, r in pairs) / spread_y
               if spread_y > 0 else 0.0)

    fit = Fit(scale=scale,
              offset_x=rx - scale * px,
              offset_y=ry - scale * py,
              scale_x=scale_x,
              scale_y=scale_y)
    return fit


def fit_robustly(centers: Mapping[str, tuple],
                 precision: float) -> tuple:
    """`(fit, trimmed)` - the frame set by the elements that AGREE.

    A plain least-squares fit is dragged by its outliers, and on this problem
    that is not a nuance, it is a wrong answer. Move one box in a diagram of
    eight and the best fit shifts and rescales to split the difference: the
    displaced box absorbs seven eighths of its own error, every other box picks
    up a share of the rest, and the report names innocent elements as drifting.
    A caller following it would move the wrong boxes.

    So the frame is defined by the agreeing majority. The worst element is
    dropped and the fit retaken while anything still exceeds the reading's
    precision, down to a floor of half the elements - at which point no
    majority agrees about anything and the diagram is simply different, which
    is what gets reported. Every element is still MEASURED against the frame,
    including the dropped ones; being dropped only means it was not allowed to
    define where the diagram is.

    `trimmed` comes back so a caller can see the frame rested on a subset
    rather than having to infer it.
    """
    active = sorted(centers)
    floor = max(2, (len(centers) + 1) // 2)
    trimmed: list = []
    while True:
        fit = fit_similarity([centers[i] for i in active])
        if fit is None or fit.scale <= 0:
            return (None, tuple(trimmed))
        residuals = {i: math.dist(fit.apply(*p), r)
                     for i, (p, r) in centers.items()}
        worst = max(active, key=lambda i: residuals[i])
        if residuals[worst] <= precision or len(active) <= floor:
            return (fit, tuple(trimmed))
        active.remove(worst)
        trimmed.append(worst)


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------
def check_inventory(missing: Sequence[str], extra: Sequence[Mapping[str, Any]],
                    report: FidelityReport) -> None:
    """Everything in the reference is present, and nothing else is.

    First, and an error either way. A diagram missing a box is not a diagram
    that is slightly out of position, and there is no point measuring the
    geometry of a reproduction that is not of the same content.
    """
    for ident in missing:
        report.add(Finding(
            "missing-element", "error",
            f"the reference has {ident!r} and the reproduction has nothing "
            f"standing for it",
            subjects=(ident,),
            correction="draw it, or - if it was deliberately left out - remove "
                       "it from the reading, because a reading is what we are "
                       "claiming to reproduce"))
    for obj in extra:
        claimed = str(obj.get("ref") or "").strip()
        name = str(obj.get("name") or "").strip()
        if claimed:
            why = (f"claims reference element {claimed!r}, which the reading "
                   f"does not have or which another object already claimed")
        else:
            why = "stands for nothing in the reference"
        report.add(Finding(
            "extra-element", "error",
            f"the reproduction has {name or '<unnamed>'!r}, which {why}",
            subjects=(claimed or name,),
            correction="remove it, or give it the `ref` of the reference "
                       "element it reproduces"))


def check_ordering(matched: Mapping[str, Mapping[str, Any]],
                   ref_rects: Mapping[str, Sequence[float]],
                   prod_rects: Mapping[str, Sequence[float]],
                   precision: float, report: FidelityReport) -> None:
    """Whatever was left of, or above, what, still is.

    The scale-invariant core of "looks the same", and the check that survives a
    reader describing the diagram out loud: this box is above that one, these
    three run down the left. Get the ordering wrong and no amount of accurate
    positioning saves it.

    A pair the REFERENCE cannot separate is not judged. Two boxes whose centers
    differ by less than the reading precision are, as far as the reading knows,
    level - so requiring the reproduction to pick the same side would be
    requiring it to reproduce noise. Those pairs are excluded from the
    denominator rather than passed, which is the difference between "we checked
    and it held" and "we could not check".
    """
    idents = sorted(matched)
    judged = 0
    for i, a in enumerate(idents):
        for b in idents[i + 1:]:
            ra, rb = ref_rects[a], ref_rects[b]
            pa, pb = prod_rects[a], prod_rects[b]
            for axis, index, words in ((0, 0, ("left of", "right of")),
                                       (1, 1, ("above", "below"))):
                ref_delta = _center(ra)[index] - _center(rb)[index]
                if abs(ref_delta) <= precision:
                    continue
                judged += 1
                prod_delta = _center(pa)[index] - _center(pb)[index]
                if prod_delta == 0 or (prod_delta > 0) != (ref_delta > 0):
                    was = words[0] if ref_delta < 0 else words[1]
                    now = ("level with" if prod_delta == 0
                           else words[0] if prod_delta < 0 else words[1])
                    report.add(Finding(
                        "order-inverted", "error",
                        f"{a!r} is {was} {b!r} in the reference and {now} it "
                        f"in the reproduction",
                        subjects=(a, b),
                        correction=f"the reading separates them by "
                                   f"{abs(ref_delta):.0f}px, which is more "
                                   f"than its {precision:.0f}px precision, so "
                                   f"this is a real inversion rather than two "
                                   f"boxes that were always level"))
    report.metrics["ordering_pairs_judged"] = judged


def check_placement(matched: Mapping[str, Mapping[str, Any]],
                    ref_rects: Mapping[str, Sequence[float]],
                    prod_rects: Mapping[str, Sequence[float]],
                    precision: float, fit: Fit,
                    report: FidelityReport) -> None:
    """Every box lands where the reference puts it, once scale is allowed for.

    The residual after the fit, in reference pixels, against the reading's own
    precision. Systematic scale and offset are already gone, so what is left is
    this element being in the wrong place relative to the others - which is the
    only sense in which a single element can be misplaced at all.
    """
    residuals: dict = {}
    worst = 0.0
    for ident, rect in prod_rects.items():
        want = _center(ref_rects[ident])
        got = fit.apply(*_center(rect))
        drift = math.dist(got, want)
        residuals[ident] = drift
        worst = max(worst, drift)
        if drift <= precision:
            continue
        severity = "error" if drift > precision * SEVERE_MULTIPLE else "warning"
        report.add(Finding(
            "position-drift", severity,
            f"{ident!r} sits {drift:.0f}px from where the reference puts it, "
            f"against a reading precision of {precision:.0f}px",
            subjects=(ident,),
            correction="move it; the offset is measured after the overall "
                       "scale and position of the diagram have been fitted "
                       "out, so it is this element relative to the others"))
    report.metrics["worst_position_drift"] = round(worst, 1)
    report.metrics["elements_placed"] = len(prod_rects)

    # Aspect. Only meaningful when the diagram has extent on both axes to fit
    # against; a single row of boxes determines no vertical scale, and dividing
    # by it would manufacture a finding out of nothing.
    if fit.scale_x > 0 and fit.scale_y > 0:
        ratio = max(fit.scale_x, fit.scale_y) / min(fit.scale_x, fit.scale_y)
        report.metrics["aspect_ratio"] = round(ratio, 3)
        # The tolerance again comes from the reading rather than from a
        # constant: a distortion small enough to be explained by the precision
        # over the diagram's own extent is not distinguishable from a clean
        # reading of an undistorted diagram.
        extent = _reading_extent(ref_rects)
        allowed = 1.0 + (2.0 * precision / extent if extent > 0 else 0.0)
        if ratio > allowed:
            report.add(Finding(
                "aspect-distorted", "error",
                f"the reproduction is stretched: it needs a horizontal scale "
                f"{fit.scale_x:.3f} and a vertical scale {fit.scale_y:.3f} to "
                f"fit the reference, a ratio of {ratio:.3f}",
                correction="scale both axes together; proportions are visible "
                           "and a uniformly larger diagram is the same "
                           "diagram while a stretched one is not"))


def _reading_extent(ref_rects: Mapping[str, Sequence[float]]) -> float:
    """The diagonal of everything the reading holds, for scaling a tolerance."""
    if not ref_rects:
        return 0.0
    lefts = [r[0] for r in ref_rects.values()]
    tops = [r[1] for r in ref_rects.values()]
    rights = [r[2] for r in ref_rects.values()]
    bottoms = [r[3] for r in ref_rects.values()]
    return math.hypot(max(rights) - min(lefts), max(bottoms) - min(tops))


def check_sizing(matched: Mapping[str, Mapping[str, Any]],
                 ref_rects: Mapping[str, Sequence[float]],
                 prod_rects: Mapping[str, Sequence[float]],
                 precision: float, fit: Fit,
                 report: FidelityReport) -> None:
    """Every box is the size the reference draws it, at the fitted scale.

    Two edges are read per axis, so the tolerance is twice the precision: a
    width is a difference of two readings and carries both their errors.
    """
    worst = 0.0
    tolerance = 2.0 * precision
    for ident, rect in prod_rects.items():
        want_w, want_h = _size(ref_rects[ident])
        got_w, got_h = (v * fit.scale for v in _size(rect))
        for axis, want, got in (("width", want_w, got_w),
                                ("height", want_h, got_h)):
            delta = abs(got - want)
            worst = max(worst, delta)
            if delta <= tolerance:
                continue
            severity = ("error" if delta > tolerance * SEVERE_MULTIPLE
                        else "warning")
            report.add(Finding(
                "size-drift", severity,
                f"{ident!r} is {got:.0f}px {axis} where the reference draws "
                f"it {want:.0f}px, a difference of {delta:.0f}px against a "
                f"tolerance of {tolerance:.0f}px",
                subjects=(ident,),
                correction="resize it; the comparison is at the fitted scale, "
                           "so drawing the whole diagram bigger has already "
                           "been allowed for"))
    report.metrics["worst_size_drift"] = round(worst, 1)
    report.metrics["elements_sized"] = len(prod_rects)


def check_links(reading: Mapping[str, Any], links: Optional[Sequence],
                matched: Mapping[str, Mapping[str, Any]],
                report: FidelityReport) -> None:
    """The same things are joined to the same things.

    Compared as unordered pairs, with direction reported separately. A
    connector drawn the other way round is a different statement about the
    model and worth saying, but it is not the same defect as an absent one, and
    on a note link - which is most of what a transcription carries - direction
    is not meaningful at all.

    A link touching an element that was never matched is not reported as a
    missing link. Its absence is already `missing-element`, and reporting the
    consequence as well buries the cause.
    """
    wanted = reading.get("links")
    if wanted is None:
        report.not_run.append(
            "link comparison: the reading declares no `links`. Absent is not "
            "the same as none - a reading that simply did not record the "
            "connectors cannot be used to say the reproduction has the right "
            "ones.")
        return
    if links is None:
        report.not_run.append(
            "link comparison: no links were supplied for the reproduction. "
            "The reading has them, so this is an unanswered question rather "
            "than a clean one.")
        return

    def pair(entry: Mapping[str, Any], a: str, b: str) -> Optional[tuple]:
        source = str(entry.get(a) or "").strip()
        target = str(entry.get(b) or "").strip()
        return (source, target) if source and target else None

    ref_pairs = [p for p in (pair(e, "from", "to") for e in wanted) if p]
    got_pairs = [p for p in (pair(e, "from", "to") for e in links) if p]
    got_unordered = {frozenset(p) for p in got_pairs}
    ref_unordered = {frozenset(p) for p in ref_pairs}

    judged = 0
    for source, target in ref_pairs:
        if source not in matched or target not in matched:
            continue
        judged += 1
        key = frozenset((source, target))
        if key not in got_unordered:
            report.add(Finding(
                "missing-link", "error",
                f"the reference joins {source!r} to {target!r} and the "
                f"reproduction does not",
                subjects=(source, target),
                correction="draw the connector"))
        elif (source, target) not in got_pairs:
            report.add(Finding(
                "link-direction-reversed", "warning",
                f"the reference draws {source!r} -> {target!r} and the "
                f"reproduction draws it the other way round",
                subjects=(source, target),
                correction="reverse it, unless the connector is one whose "
                           "direction carries no meaning"))
    for key in got_unordered - ref_unordered:
        ends = tuple(sorted(key))
        report.add(Finding(
            "extra-link", "error",
            f"the reproduction joins {ends[0]!r} to {ends[-1]!r} and the "
            f"reference does not",
            subjects=ends,
            correction="remove it; a connector nobody drew is a claim about "
                       "the model that the source does not make"))
    report.metrics["links_judged"] = judged


def check_features(reading: Mapping[str, Any],
                   matched: Mapping[str, Mapping[str, Any]],
                   report: FidelityReport) -> None:
    """Boxes carrying a visible list carry the same number of entries.

    Attributes and operations are content, they are legible in the picture, and
    a class drawn with three of them and reproduced with two is visibly not the
    same box however well it is placed. Counted rather than compared by name,
    because the names are expected to differ - the reproduction is reference
    content, not a copy of somebody else's model.

    Only elements whose reading STATES a count are judged, and the denominator
    says how many that was.
    """
    judged = 0
    for entry in reading.get("elements") or []:
        ident = str(entry.get("id") or "").strip()
        if "features" not in entry or ident not in matched:
            continue
        want = int(entry["features"])
        obj = matched[ident]
        if "features" not in obj:
            report.not_run.append(
                f"feature count for {ident!r}: the reading states {want} but "
                f"the reproduction reports none, so the two cannot be "
                f"compared.")
            continue
        judged += 1
        got = int(obj["features"])
        if got != want:
            report.add(Finding(
                "feature-count", "warning",
                f"{ident!r} shows {got} feature(s) where the reference shows "
                f"{want}",
                subjects=(ident,),
                correction="add or remove features; the count is visible in "
                           "the box and a reader compares it directly"))
    report.metrics["features_judged"] = judged


def check_content(reading: Mapping[str, Any],
                  matched: Mapping[str, Mapping[str, Any]],
                  report: FidelityReport) -> None:
    """A box whose content IS text is not empty.

    THIS CHECK EXISTS BECAUSE ITS ABSENCE ALREADY PASSED A BAD DIAGRAM. The
    first reproduction of a reference put eight boxes at the right coordinates
    at the right sizes on the right links - and every note and the heading
    rendered BLANK, because a note draws its documentation rather than its name.
    A reader saw it instantly. A geometry-only comparison called it faithful.

    Presence, not wording. The words legitimately differ - the reproduction is
    reference content, not a copy of somebody else's model - so comparing them
    would fail on every correct diagram. What cannot differ is that there is
    something there.
    """
    judged = 0
    for entry in reading.get("elements") or []:
        ident = str(entry.get("id") or "").strip()
        if not entry.get("text") or ident not in matched:
            continue
        obj = matched[ident]
        if "text" not in obj:
            report.not_run.append(
                f"content for {ident!r}: the reading says this element's "
                f"visible content is text, and the reproduction reports no "
                f"`text` at all - so whether it is blank is unanswered, which "
                f"is not the same as answered well.")
            continue
        judged += 1
        if not str(obj["text"]).strip():
            report.add(Finding(
                "empty-content", "error",
                f"{ident!r} is drawn in the right place and is EMPTY; the "
                f"reference has text in it",
                subjects=(ident,),
                correction="a Note draws its documentation, not its name - "
                           "set the body text rather than only naming the "
                           "element"))
    report.metrics["content_judged"] = judged


def _rgb(value: Any, where: str) -> tuple:
    text = str(value).strip().lstrip("#")
    if len(text) != 6:
        raise ValueError(f"{where}: expected a color as #RRGGBB, got {value!r}")
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError as exc:
        raise ValueError(f"{where}: {value!r} is not hexadecimal") from exc


def check_fill(reading: Mapping[str, Any],
               matched: Mapping[str, Mapping[str, Any]],
               report: FidelityReport) -> None:
    """Boxes are the color the reference draws them.

    Color is not decoration on these diagrams - a pale band groups three
    categories and distinguishes them from the notes beside them, and losing it
    loses the grouping. Compared per channel against the reading's declared
    `color_precision`, for the same reason the geometry is compared against its
    `precision`: the uncertainty belongs to the reading, not to a constant here.
    """
    declared = [e for e in (reading.get("elements") or []) if e.get("fill")]
    if not declared:
        return
    if "color_precision" not in reading:
        raise ValueError(
            "the reading declares fills but no `color_precision`. A renderer "
            "draws a gradient and rounds it, so an exact match is the wrong "
            "test and there is no safe value to assume - the reading knows "
            "how well it sampled the color and nothing else does.")
    tolerance = float(reading["color_precision"])
    judged = 0
    worst = 0
    for entry in declared:
        ident = str(entry.get("id") or "").strip()
        if ident not in matched:
            continue
        obj = matched[ident]
        if not obj.get("fill"):
            report.not_run.append(
                f"fill for {ident!r}: the reading records {entry['fill']} and "
                f"the reproduction reports no fill, so they cannot be "
                f"compared. An element left at the tool default reports "
                f"nothing here and is not thereby correct.")
            continue
        judged += 1
        want = _rgb(entry["fill"], f"reading {ident!r}")
        got = _rgb(obj["fill"], f"reproduction {ident!r}")
        delta = max(abs(a - b) for a, b in zip(want, got))
        worst = max(worst, delta)
        if delta > tolerance:
            report.add(Finding(
                "fill-differs", "warning" if delta <= tolerance * SEVERE_MULTIPLE
                else "error",
                f"{ident!r} is filled {obj['fill']} where the reference draws "
                f"it {entry['fill']}, a difference of {delta} in one channel "
                f"against a tolerance of {tolerance:.0f}",
                subjects=(ident,),
                correction="set the fill; on these diagrams a shared color is "
                           "what groups boxes, so losing it loses the "
                           "grouping rather than only the decoration"))
    report.metrics["fills_judged"] = judged
    report.metrics["worst_fill_delta"] = worst


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def compare(reading: Mapping[str, Any],
            objects: Sequence[Mapping[str, Any]],
            links: Optional[Sequence] = None) -> FidelityReport:
    """Compare a reproduction against a reading taken off the reference.

    `reading` is what was read from the picture: a `precision`, an `elements`
    list of `{id, rect: [left, top, right, bottom], name?, features?}` in image
    coordinates, and optionally `links` of `{from, to}` naming element ids.

    `objects` are what we drew, in EA coordinates, each carrying `ref` - the
    reference element id it stands for. `links` are the connectors drawn,
    `{from, to}` in reference ids.

    The report is faithful when it holds no errors. It is not required to hold
    no warnings, and it is not required to lint clean - see the module
    docstring, because on a hand-placed reference those two requirements are in
    direct conflict and this is the one that decides.
    """
    report = FidelityReport()
    precision = _precision(reading)
    report.metrics["precision"] = precision

    # A READING IS ALLOWED TO BE PARTIAL. It is not allowed to be partial
    # SILENTLY, which is a different thing and is the failure this whole module
    # keeps rediscovering: a comparison that only knows about what it was told
    # reports a perfect score for a diagram missing everything it was not told
    # about. So a reading names what it deliberately did not read, and those
    # names come out as unanswered questions rather than as nothing at all.
    for omission in reading.get("not_read") or []:
        report.not_run.append(
            f"not read from the reference: {omission}. Anything in that "
            f"category is outside this comparison entirely - it is neither "
            f"checked nor counted, and a faithful verdict says nothing "
            f"about it.")
    report.metrics["not_read"] = list(reading.get("not_read") or [])

    ref_rects = reference_rects(reading)
    report.metrics["reference_elements"] = len(ref_rects)

    matched, missing, extra, how = match_elements(reading, objects)
    report.matched = dict(matched)
    report.metrics["matched"] = len(matched)
    report.metrics["matched_by"] = how
    if how == "name" and matched:
        report.not_run.append(
            "correspondence was inferred from element names, because no "
            "produced object declared a `ref`. That is a guess: it is wrong "
            "wherever the reproduction renames things, which on this corpus "
            "is by design.")

    check_inventory(missing, extra, report)

    prod_rects = {}
    for ident, obj in matched.items():
        prod_rects[ident] = _produced_rect(obj, f"produced object {ident!r}")

    if len(prod_rects) < 2:
        report.not_run.append(
            f"geometry comparison: {len(prod_rects)} element(s) matched, and "
            f"at least two are needed before there is any relative position "
            f"or scale to compare. Everything below position is unmeasured.")
        return report

    centers = {i: (_center(prod_rects[i]), _center(ref_rects[i]))
               for i in prod_rects}
    fit, trimmed = fit_robustly(centers, precision)
    if fit is None or fit.scale <= 0:
        report.not_run.append(
            "geometry comparison: no scale could be fitted between the two. "
            "Either every box we drew is at the same point, or the "
            "correspondence is so scrambled that the best fit is degenerate; "
            "in both cases a residual would be meaningless.")
        return report
    report.fit = fit
    report.metrics["scale"] = round(fit.scale, 4)
    # Visible rather than inferred: a frame set by six of eight elements is a
    # different claim from one every element agreed on, and the findings read
    # differently in the two cases.
    report.metrics["fit_trimmed"] = list(trimmed)

    check_ordering(matched, ref_rects, prod_rects, precision, report)
    check_placement(matched, ref_rects, prod_rects, precision, fit, report)
    check_sizing(matched, ref_rects, prod_rects, precision, fit, report)
    check_links(reading, links, matched, report)
    check_features(reading, matched, report)
    check_content(reading, matched, report)
    check_fill(reading, matched, report)
    return report
