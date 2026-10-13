#!/usr/bin/env python3
"""Measure the numbers a Visio diagram standard needs from diagrams already drawn.

A convention that was guessed is worse than one that is absent. This tool reads a
page read (the `apt-page-read` contract, section 4 of the Visio v2 contracts) and
states what the page does: how big each master is drawn, the gap and the pitch between
neighbors, what lines up, how connectors are routed and where they attach, where labels
sit, where the title and the furniture are, and how lanes and containers are built -
each figure with the sample it rests on, so a convention starts from a measurement and
not an estimate.

    python measure_visio.py page-read.json [more.json ...] [--master-catalog capture.json]

HOW A VSDX BECOMES INPUT
------------------------
This tool takes page-read-shaped JSON and nothing else. Until the server's page read
(D5, APV-2026-0015) exists, `tools/dev/vsdx_to_page_read.py` in the skills repository
reads a `.vsdx` directly (zip and XML, no COM, no Visio) into that shape. It is a
development tool and does not ship. When D5 lands this tool is fed D5's output and does
not change. A file may hold one page read or a list of them.

UNITS - THE CONVERSION, STATED ONCE
-----------------------------------
Input is the contract's inches, origin top-left, y increasing downward, a rectangle by
its top-left corner. This module adds NO conversion: every figure it emits is in
inches on that axis, rounded to 0.001 (`QUANTUM`) before anything is compared, so float
dust (0.7500000000000043) cannot split a mode. The one place Visio's own convention
(bottom-left origin, y up, shapes positioned by a center pin) is converted is the
extractor named above; it is documented there and nowhere else. Mapping inches to the
notation library's neutral unit, once that unit is decided, is a single factor applied
by the consumer of the catalog, not here.

THE APPROACH IS THE EA TOOL'S, NOT A SECOND ONE
-----------------------------------------------
`ea-diagram-composition/tools/measure_binding.py` mines Sparx-authored models for the
sizes and gaps a language binding needs. This tool keeps its method and its guards:

* The modal size per concept with its count, its share of the sample and n; the mode is
  ABSENT on a tie, because picking the first of ten different sizes presents an accident
  as a convention.
* A gap is measured between an element and its NEAREST neighbor in a direction (a row
  or column it shares, a positive gap), inside the SAME container context, and a pair
  with a nearer third element between them is not a measurement. Containers are never
  endpoints and never intervene; touching rectangles are counted and excluded.
* Each element contributes at most one horizontal and one vertical gap, so n counts
  elements that have a neighbor.
* A gap is a median AND a mode, each with n; a population under `MIN_SAMPLE` is `low_n`;
  under `MIN_SAMPLE_GAP` its median is `thin_median`; a pooled population in which one
  diagram supplies more than `MAX_DIAGRAM_SHARE` is `concentrated`, because that median
  measures the diagram and not the notation.
* Furniture is annotation, not content, and is never a gap endpoint.
* A fixed-shape concept (at least `MIN_SAMPLE` instances, `FIXED_SHAPE_SHARE` of one
  size) is reported as fixed rather than as a choice.

WHERE IT DIFFERS, AND WHY
-------------------------
1. Geometry is float inches, top-left, y down. EA stores integer pixels on a y-up axis
   with negative values, so its `Rect` is replaced by `Box`, which keeps the contract's
   axis; "A above B" is `B.y - A.bottom`.
2. The concept is the MASTER (`master.universal_name`), the Visio counterpart of EA's
   stereotype. There is no technology or diagram-type attribution: a Visio file carries
   no `MDGDgm` tag, so which diagrams belong together is the CALLER's statement (the
   corpus catalog), not something inferred here. A shape with no master is reported
   under `unmastered` and is an obstacle but never an endpoint or a sized concept.
3. Furniture is recognized from the master name and the page, not from an object type
   (EA has `Note`/`Text`/`Boundary`; Visio has masters). See `FURNITURE_MASTERS`. A
   `role: furniture` the input already states wins.
4. Container context is geometric enclosure, as in EA, although the page read also
   carries Visio's own membership. What is measured is what is DRAWN, and a shape that
   sits in a lane but is not a member of it is still in that lane on the page.
5. The "historical" rule is not carried over. It exists in EA to reproduce numbers
   recorded before the method was written; the Visio side has no such history.
6. Pitch (center to center along the axis) is reported next to the gap. EA left it to
   the binding author; a Visio standard states spacing both ways.
7. Quantities EA does not measure: alignment, connector routing and attachment sides,
   label placement, title and furniture position, and lane and container geometry.
8. `MIN_SAMPLE` and `MIN_SAMPLE_GAP` are ADOPTED from the EA tool, not re-derived. EA
   derived them from its own populations; they have not been re-measured on a Visio
   corpus, so they are provisional here (APV-2026-0105).
9. The tolerances and shares below (`ALIGN_TOL`, `SIDE_TOL`, `LABEL_INSIDE_SHARE`,
   `HEADING_BAND_SHARE`, `CENTER_TOL`, `TITLE_BAND`, `TITLE_MIN_WIDTH`) are chosen, not
   derived, and nobody has yet measured how far they move a figure (APV-2026-0108).

WHAT IS MEASURED
----------------
Per diagram (a page read): `sizes` per master with the default size when a master
catalog supplies one; `gaps` and `pitch` horizontal and vertical; `alignment` (the
share of elements that have a row-mate or column-mate on a center line or on an edge,
within `ALIGN_TOL`); `connectors` (route classes, glue, bends, the side of a shape each
end attaches to); `labels` (text block against its shape: inside with its anchor, or
above, below, left, right with the distance; connector labels against their path's
midpoint); `title` and `furniture`; `containers` (box, heading band, member insets) and
`lane_stacks`; `margins` (content against the page edge). Observations are kept as
value-to-count maps, so a pooled figure is recomputed from them exactly.

Across diagrams (`pool`): the same statistics over every non-scaled, non-background
diagram, with each gap statistic's concentration.

TEXT IS NEVER COPIED. The page read carries each shape's text; this tool records only
whether a shape has text and how long it is. Nothing of the text reaches the output, so
a catalog of measurements cannot republish the content of the diagrams it measured.

A shape the producer marks `scaffold: true` (a template's instruction text, left on its
sample page for the author to delete) is left out of every figure and counted in
`counts.scaffold_excluded`. It is not part of the contract; a page read without the field
measures everything it holds.

WHAT IT WILL NOT DO
-------------------
It does not read a `.vsdx`, it does not open Visio, and it does not infer a diagram's
language. When the input lacks a field (`label_box`, `heading_box`, `path`, `members`)
the figures that need it are absent and the field is listed in `unavailable`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Iterable, Optional, Sequence

TOOL = "measure_visio"
TOOL_VERSION = 1

UNIT = "in"

#: Every coordinate and size is rounded to this many inches before it is compared.
QUANTUM = 0.001

#: Below this many observations a figure is `low_n`. ADOPTED from the EA tool, which
#: derived it for a modal size (agreement of a subsample's mode with the population's
#: 95% of the time); not re-derived for Visio. See "WHERE IT DIFFERS", item 8.
MIN_SAMPLE = 10

#: Observations a gap MEDIAN needs before it is stable. ADOPTED from the EA tool (the
#: subsample median within 25% of the population's, 90% of the time); not re-derived.
MIN_SAMPLE_GAP = 38

#: A concept with at least `MIN_SAMPLE` instances of which this share are one size is
#: treated as fixed by the notation, not chosen by authors.
FIXED_SHAPE_SHARE = 0.9

#: A per-concept size is called dominant only if its mode covers at least this share.
DOMINANT_SHARE = 0.5

#: A pooled statistic is `concentrated` when ONE diagram supplies MORE than this share.
MAX_DIAGRAM_SHARE = 0.5

#: Two center lines or two edges are "aligned" when they differ by at most this, inches.
ALIGN_TOL = 0.02

#: A connector end is "on" a shape's edge when it lies within this of it, inches.
SIDE_TOL = 0.05

#: A label whose box has at least this share of its area inside its shape is INSIDE it.
LABEL_INSIDE_SHARE = 0.5

#: A title is a text-bearing shape whose top edge lies within this share of the page
#: height from the top, and which is at least `TITLE_MIN_WIDTH` of the page wide.
TITLE_BAND = 0.15
TITLE_MIN_WIDTH = 0.25

#: A container's heading is a BAND along one edge when it spans at least this share of
#: that edge's length; the side is then the edge it lies against.
HEADING_BAND_SHARE = 0.9

#: Share of the page's width within which a box's center counts as centered.
CENTER_TOL = 0.05

#: Contract furniture kinds, recognized from the master's name. First match wins. The
#: patterns were taken from the master names that occur in Microsoft's sample diagrams
#: and are deliberately few; a master that matches none is content.
FURNITURE_MASTERS: tuple[tuple[str, re.Pattern], ...] = (
    ("title-block", re.compile(r"\btitle\b", re.I)),
    ("legend", re.compile(r"\blegend\b", re.I)),
    ("border", re.compile(r"\b(border|frame)\b", re.I)),
    ("logo", re.compile(r"\blogo\b", re.I)),
    ("note", re.compile(r"\b(note|callout|annotation|comment)\b", re.I)),
)

FURNITURE_KINDS = ("title-block", "legend", "note", "logo", "border")

CONTRACT = "apt-page-read"
CONTRACT_VERSIONS = ("0.1",)


class MeasureError(Exception):
    """The input cannot be measured."""


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------

def q(value: float) -> float:
    """`value` rounded to `QUANTUM` (half up); never -0.0.

    Rounded to six places first, so the dust Visio leaves in a cached value
    (0.7500000000000043, 4.69e-15) cannot decide a tie, then to `QUANTUM` half up.
    Without the first step 2.0625 became 2.062 on one shape and 2.063 on another.
    """
    exact = Decimal(repr(round(float(value), 6)))
    return float(exact.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)) + 0.0


@dataclass(frozen=True)
class Box:
    """A rectangle in the contract's convention: top-left corner, y down, inches.

    Edges are held to six places - enough to remove float dust and no more - and are
    quantized to `QUANTUM` only where a figure is REPORTED (`q`), never between a
    subtraction and the next: quantizing 4.6875 and 2.625 first and subtracting gave
    2.063 for one pair and 2.062 for another that is identically 2.0625.
    """
    x: float
    y: float
    right: float
    bottom: float

    @classmethod
    def make(cls, x: float, y: float, width: float, height: float) -> "Box":
        return cls(round(x, 6) + 0.0, round(y, 6) + 0.0,
                   round(x + width, 6) + 0.0, round(y + height, 6) + 0.0)

    @property
    def width(self) -> float:
        return round(self.right - self.x, 6) + 0.0

    @property
    def height(self) -> float:
        return round(self.bottom - self.y, 6) + 0.0

    @property
    def cx(self) -> float:
        return (self.x + self.right) / 2

    @property
    def cy(self) -> float:
        return (self.y + self.bottom) / 2

    @property
    def area(self) -> float:
        return self.width * self.height

    def contains(self, other: "Box") -> bool:
        """True when `other` lies inside this box and is not identical to it."""
        return (self.x <= other.x and self.right >= other.right
                and self.y <= other.y and self.bottom >= other.bottom
                and self != other)

    def intersection_area(self, other: "Box") -> float:
        w = min(self.right, other.right) - max(self.x, other.x)
        h = min(self.bottom, other.bottom) - max(self.y, other.y)
        return w * h if w > 0 and h > 0 else 0.0

    def as_json(self) -> dict:
        return {"x": q(self.x), "y": q(self.y), "width": q(self.width),
                "height": q(self.height)}


def _box(obj: Optional[dict]) -> Optional[Box]:
    if not obj:
        return None
    try:
        return Box.make(float(obj["x"]), float(obj["y"]), float(obj["width"]), float(obj["height"]))
    except (KeyError, TypeError, ValueError):
        return None


def horizontal_gap(a: Box, b: Box) -> tuple[float, float]:
    """`(gap, overlap)` for B to the right of A; overlap is the rows they share."""
    return round(b.x - a.right, 6) + 0.0, min(a.bottom, b.bottom) - max(a.y, b.y)


def vertical_gap(a: Box, b: Box) -> tuple[float, float]:
    """`(gap, overlap)` for B below A; overlap is the columns they share.

    A is above B when A's bottom edge is a SMALLER number than B's top edge (y points
    down), so the gap is `B.y - A.bottom`.
    """
    return round(b.y - a.bottom, 6) + 0.0, min(a.right, b.right) - max(a.x, b.x)


_AXES = {"h": horizontal_gap, "v": vertical_gap}


# --------------------------------------------------------------------------
# The page, as items
# --------------------------------------------------------------------------

@dataclass
class Item:
    """One placed shape or container of a page read."""
    ref: str
    role: str                      # "shape" | "container"
    concept: str                   # master universal name; "" when unmastered
    box: Box
    has_text: bool = False
    text_length: int = 0
    furniture_kind: Optional[str] = None
    kind: str = ""                 # container kind
    label_box: Optional[Box] = None
    heading_box: Optional[Box] = None
    members: tuple[str, ...] = ()
    master_id: str = ""            # master unique id, for default sizes
    angle: float = 0.0
    container_geometric: bool = False   # set by `analyze` when it encloses another item

    @property
    def is_furniture(self) -> bool:
        return self.furniture_kind is not None

    @property
    def is_container(self) -> bool:
        return self.role == "container" or self.container_geometric


def furniture_for(concept: str) -> Optional[str]:
    for kind, pattern in FURNITURE_MASTERS:
        if concept and pattern.search(concept):
            return kind
    return None


def validate_page_read(doc: dict) -> None:
    """Refuse input that is not a page read this tool understands."""
    if not isinstance(doc, dict) or doc.get("contract") != CONTRACT:
        raise MeasureError(f"not a page read: `contract` must be {CONTRACT!r}")
    if doc.get("contract_version") not in CONTRACT_VERSIONS:
        raise MeasureError(
            f"page read contract_version {doc.get('contract_version')!r} is not one this "
            f"tool knows ({', '.join(CONTRACT_VERSIONS)})")
    if doc.get("unit") != "in" or doc.get("origin") != "top-left":
        raise MeasureError("a page read must be unit 'in' and origin 'top-left'; this "
                           "tool does not convert")
    page = doc.get("page") or {}
    for key in ("width", "height"):
        if not isinstance(page.get(key), (int, float)):
            raise MeasureError(f"page.{key} is missing")
    for key in ("containers", "shapes", "connectors"):
        if not isinstance(doc.get(key), list):
            raise MeasureError(f"`{key}` must be a list")


def _items(doc: dict) -> list[Item]:
    out: list[Item] = []
    for role, key in (("container", "containers"), ("shape", "shapes")):
        for s in doc[key]:
            if s.get("scaffold"):
                continue    # instruction text a template leaves to be deleted; not the diagram
            box = _box(s)
            if box is None:
                continue
            master = s.get("master") or {}
            concept = master.get("universal_name") or master.get("name") or ""
            text = s.get("text")
            furniture = None
            if s.get("role") == "furniture":
                furniture = s.get("furniture_kind") or "note"
            elif role == "shape":
                furniture = furniture_for(concept)
            out.append(Item(
                ref=str(s.get("ref", "")), role=role, concept=concept, box=box,
                has_text=bool(text), text_length=len(text) if text else 0,
                furniture_kind=furniture, kind=s.get("kind", "") if role == "container" else "",
                label_box=_box(s.get("label_box")), heading_box=_box(s.get("heading_box")),
                members=tuple(s.get("members") or ()),
                master_id=master.get("unique_id", ""),
                angle=float(s.get("angle") or 0.0)))
    return out


# --------------------------------------------------------------------------
# Distributions
# --------------------------------------------------------------------------

def _key(value) -> str:
    """The JSON key for a value-to-count map: `0.5`, or `1.5x0.75` for a size."""
    if isinstance(value, tuple):
        return "x".join(_key(v) for v in value)
    return format(value, "g") if isinstance(value, float) else str(value)


def _unquote(key: str):
    parts = key.split("x")
    nums = tuple(float(p) for p in parts)
    return nums if len(nums) > 1 else nums[0]


def _expand(counts: Counter) -> list:
    return sorted(v for v, c in counts.items() for _ in range(c))


def dist_json(counts: Counter, *, min_sample: int = MIN_SAMPLE) -> dict:
    """Median, unique mode and the value-to-count map of a one-dimensional population."""
    n = sum(counts.values())
    if not n:
        return {"n": 0, "median": None, "mode": None, "mode_count": 0, "low_n": True,
                "values": {}}
    top = max(counts.values())
    winners = sorted(v for v, c in counts.items() if c == top)
    out = {"n": n, "median": q(statistics.median(_expand(counts))),
           "mode": winners[0] if len(winners) == 1 else None, "mode_count": top,
           "low_n": n < min_sample,
           "values": {_key(v): c for v, c in sorted(counts.items())}}
    if len(winners) > 1:
        out["tied_modes"] = winners
    return out


def size_json(counts: Counter, *, min_sample: int = MIN_SAMPLE) -> dict:
    """The modal (width, height) with what it rests on; the mode is absent on a tie."""
    n = sum(counts.values())
    top = max(counts.values())
    winners = sorted(v for v, c in counts.items() if c == top)
    widths = sorted(w for (w, _), c in counts.items() for _ in range(c))
    heights = sorted(h for (_, h), c in counts.items() for _ in range(c))
    out = {"n": n,
           "mode": list(winners[0]) if len(winners) == 1 else None,
           "mode_count": top, "mode_share": round(top / n, 4),
           "distinct": len(counts),
           "median": [q(statistics.median(widths)), q(statistics.median(heights))],
           "low_n": n < min_sample,
           "values": {_key(v): c for v, c in sorted(counts.items())}}
    if len(winners) > 1:
        out["tied_modes"] = [list(w) for w in winners]
    return out


def gap_json(by_diagram: dict[str, Counter], *, max_share: float = MAX_DIAGRAM_SHARE) -> dict:
    """A pooled gap statistic with provenance: which diagram supplied the most.

    `by_diagram` maps a diagram label to its value-to-count map. `concentrated` is true
    when one diagram supplies MORE than `max_share` of the population; the median and
    mode stay on the result so the pooled figure is still inspectable, but they then
    describe that diagram and not the notation.
    """
    total: Counter = Counter()
    supplied: Counter = Counter()
    for label, counts in by_diagram.items():
        total.update(counts)
        supplied[label] = sum(counts.values())
    out = dist_json(total)
    n = out["n"]
    out["thin_median"] = n < MIN_SAMPLE_GAP
    out["diagrams"] = sum(1 for c in supplied.values() if c)
    if n:
        top_label, top_count = min(supplied.items(), key=lambda kv: (-kv[1], kv[0]))
        out["top_diagram"] = top_label
        out["top_count"] = top_count
        out["top_share"] = round(top_count / n, 4)
        out["concentrated"] = top_count > max_share * n
    return out


# --------------------------------------------------------------------------
# Master default sizes
# --------------------------------------------------------------------------

def load_master_defaults(capture_paths: Iterable[str]) -> dict[str, dict]:
    """`{master unique id: {name, width, height, source}}` from template-capture files.

    The files are the APV-2026-0004 captures (`schema` `apv-microsoft-template-capture/1`):
    stencil masters with `width_in` and `height_in`. 1-D masters have no default size
    and are skipped. A unique id that appears twice with different sizes is dropped as
    ambiguous rather than resolved.
    """
    found: dict[str, dict] = {}
    ambiguous: set[str] = set()
    for path in capture_paths:
        with open(path, encoding="utf-8") as fh:
            record = json.load(fh)
        if not str(record.get("schema", "")).startswith("apv-microsoft-template-capture/"):
            raise MeasureError(f"{Path(path).name}: not a template capture")
        masters = list(record.get("embedded_masters", {}).get("masters", []))
        for stencil in record.get("stencils", []):
            masters += stencil.get("masters", [])
        for m in masters:
            uid, w, h = m.get("unique_id"), m.get("width_in"), m.get("height_in")
            if not uid or m.get("is_one_d") or w is None or h is None:
                continue
            entry = {"name": m.get("name_universal", ""), "width": q(w), "height": q(h),
                     "source": "capture:" + record.get("template_key", Path(path).stem)}
            if uid in found and (found[uid]["width"], found[uid]["height"]) != \
                    (entry["width"], entry["height"]):
                ambiguous.add(uid)
            found.setdefault(uid, entry)
    for uid in ambiguous:
        found.pop(uid, None)
    return found


# --------------------------------------------------------------------------
# The measurement of one page
# --------------------------------------------------------------------------

def _context(items: list[Item]) -> list[frozenset[int]]:
    """For each item, the indices of the containers that enclose it."""
    return [frozenset(j for j, o in enumerate(items)
                      if j != i and o.is_container and o.box.contains(it.box))
            for i, it in enumerate(items)]


def nearest_neighbor_gaps(items: list[Item], axis: str,
                          context: list[frozenset[int]]) -> tuple[list[tuple[float, float]], int]:
    """`(pairs, non_positive)`: `(gap, pitch)` per element with a qualifying neighbor.

    The EA tool's strict rule, restated for floats: B is A's nearest neighbor in a
    direction when they share a row (horizontal) or column (vertical), B is on the far
    side, and no other object sits nearer; both must be endpoints (a mastered, non-
    container, non-furniture element) and sit in the same container context. A nearer
    object that is not an endpoint drops the pair. Touching pairs are counted, not used.
    """
    measure = _AXES[axis]

    def endpoint(i: int) -> bool:
        it = items[i]
        return not it.is_container and not it.is_furniture and bool(it.concept)

    pairs: list[tuple[float, float]] = []
    non_positive = 0
    for i, a in enumerate(items):
        if not endpoint(i):
            continue
        best: Optional[float] = None
        best_is_endpoint = False
        best_b = None
        for j, b in enumerate(items):
            if i == j or b.is_container or context[j] != context[i]:
                continue
            gap, overlap = measure(a.box, b.box)
            if overlap <= 0 or gap < 0:
                continue
            if best is None or gap < best:
                best, best_is_endpoint, best_b = gap, endpoint(j), b
            elif gap == best and endpoint(j):
                best_is_endpoint, best_b = True, b
        if best is None or not best_is_endpoint:
            continue
        if best <= 0:
            non_positive += 1
            continue
        pitch = (best_b.box.cx - a.box.cx) if axis == "h" else (best_b.box.cy - a.box.cy)
        pairs.append((q(best), q(pitch)))
    return pairs, non_positive


def _alignment(items: list[Item], context: list[frozenset[int]]) -> dict:
    """Share of endpoints with a mate on a shared center line or edge, within ALIGN_TOL."""
    idx = [i for i, it in enumerate(items)
           if not it.is_container and not it.is_furniture and it.concept]
    n = len(idx)
    out: dict = {"n": n, "tolerance": ALIGN_TOL}
    if not n:
        return out
    tests = {
        "center_row": lambda a, b: abs(a.cy - b.cy) <= ALIGN_TOL,
        "center_column": lambda a, b: abs(a.cx - b.cx) <= ALIGN_TOL,
        "left_edge": lambda a, b: abs(a.x - b.x) <= ALIGN_TOL,
        "right_edge": lambda a, b: abs(a.right - b.right) <= ALIGN_TOL,
        "top_edge": lambda a, b: abs(a.y - b.y) <= ALIGN_TOL,
        "bottom_edge": lambda a, b: abs(a.bottom - b.bottom) <= ALIGN_TOL,
    }
    hits = Counter()
    any_hit = 0
    for i in idx:
        mine = False
        for name, fn in tests.items():
            if any(j != i and context[j] == context[i] and fn(items[i].box, items[j].box)
                   for j in idx):
                hits[name] += 1
                mine = True
        any_hit += mine
    for name in tests:
        out[name] = hits[name]
    out["any"] = any_hit
    return out


def _side(point: dict, box: Box) -> str:
    """Which edge of `box` the point lies on; `inside`, `off` otherwise."""
    x, y = float(point["x"]), float(point["y"])
    dists = {"left": abs(x - box.x), "right": abs(x - box.right),
             "top": abs(y - box.y), "bottom": abs(y - box.bottom)}
    within_x = box.x - SIDE_TOL <= x <= box.right + SIDE_TOL
    within_y = box.y - SIDE_TOL <= y <= box.bottom + SIDE_TOL
    on = [s for s, d in dists.items()
          if d <= SIDE_TOL and (within_y if s in ("left", "right") else within_x)]
    if on:
        return min(on, key=lambda s: dists[s])
    return "inside" if box.x < x < box.right and box.y < y < box.bottom else "off"


def _polyline_midpoint(path: Sequence[dict]) -> Optional[tuple[float, float]]:
    pts = [(float(p["x"]), float(p["y"])) for p in path]
    if len(pts) < 2:
        return None
    lengths = [math.dist(a, b) for a, b in zip(pts, pts[1:])]
    total = sum(lengths)
    if total <= 0:
        return pts[0]
    half, run = total / 2, 0.0
    for (a, b), length in zip(zip(pts, pts[1:]), lengths):
        if run + length >= half and length > 0:
            t = (half - run) / length
            return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
        run += length
    return pts[-1]


def _connectors(doc: dict, items: list[Item]) -> dict:
    conns = doc["connectors"]
    by_ref = {it.ref: it for it in items}
    routes = Counter()
    bends = Counter()
    begin_sides, end_sides = Counter(), Counter()
    label_offset = Counter()
    glued = Counter()
    with_text = with_label_box = 0
    for c in conns:
        routes[c.get("route") or "unclassified"] += 1
        glued["begin"] += bool(c.get("glued_begin"))
        glued["end"] += bool(c.get("glued_end"))
        path = c.get("path") or []
        if len(path) >= 2 and (c.get("route") in ("orthogonal", "straight")):
            bends[len(path) - 2] += 1
        for end, key, sides in (("from_ref", 0, begin_sides), ("to_ref", -1, end_sides)):
            it = by_ref.get(c.get(end, ""))
            if it is not None and path:
                sides[_side(path[key], it.box)] += 1
        if c.get("text"):
            with_text += 1
            lb = _box(c.get("label_box"))
            mid = _polyline_midpoint(path)
            if lb is not None and mid is not None:
                with_label_box += 1
                label_offset[q(math.dist((lb.cx, lb.cy), mid))] += 1
    n = len(conns)
    return {"n": n, "routes": dict(sorted(routes.items())),
            "glued_begin": glued["begin"], "glued_end": glued["end"],
            "bends": dist_json(bends),
            "begin_side": dict(sorted(begin_sides.items())),
            "end_side": dict(sorted(end_sides.items())),
            "with_text": with_text,
            "label_offset_from_midpoint": dist_json(label_offset)}


def label_relation(shape: Box, label: Box) -> tuple[str, Optional[float]]:
    """`(relation, gap)`: where a text block sits against its shape.

    `inside:<vertical>-<horizontal>` when at least `LABEL_INSIDE_SHARE` of the block is
    inside the shape (the anchor is the block's center in thirds of the shape), else
    `above`, `below`, `left` or `right` with the distance between the nearest edges, else
    `overlap` when it straddles the shape and fits none of those.
    """
    inter = label.intersection_area(shape)
    if label.area > 0 and inter / label.area >= LABEL_INSIDE_SHARE:
        fy = (label.cy - shape.y) / shape.height if shape.height else 0.5
        fx = (label.cx - shape.x) / shape.width if shape.width else 0.5
        v = "top" if fy < 1 / 3 else "bottom" if fy > 2 / 3 else "middle"
        h = "left" if fx < 1 / 3 else "right" if fx > 2 / 3 else "center"
        return f"inside:{v}-{h}", None
    if label.bottom <= shape.y + SIDE_TOL:
        return "above", q(shape.y - label.bottom)
    if label.y >= shape.bottom - SIDE_TOL:
        return "below", q(label.y - shape.bottom)
    if label.right <= shape.x + SIDE_TOL:
        return "left", q(shape.x - label.right)
    if label.x >= shape.right - SIDE_TOL:
        return "right", q(label.x - shape.right)
    return "overlap", None


def _labels(items: list[Item]) -> dict:
    by_master: dict[str, Counter] = defaultdict(Counter)
    outside = Counter()
    n = missing = 0
    for it in items:
        if it.is_container or not it.has_text:
            continue
        if it.label_box is None:
            missing += 1
            continue
        relation, gap = label_relation(it.box, it.label_box)
        by_master[it.concept or "(unmastered)"][relation] += 1
        n += 1
        if gap is not None:
            outside[gap] += 1
    return {"n": n, "no_label_box": missing,
            "by_master": {m: dict(sorted(c.items())) for m, c in sorted(by_master.items())},
            "outside_gap": dist_json(outside)}


def _title(doc: dict, items: list[Item], page_w: float, page_h: float) -> Optional[dict]:
    """The page's title, by geometry and master; its text is never recorded."""
    def describe(box: Box, source: str, master: str, length: int) -> dict:
        offset = box.cx - page_w / 2
        align = "center" if abs(offset) <= CENTER_TOL * page_w else \
            "left" if offset < 0 else "right"
        return {"source": source, "master": master or None, "box": box.as_json(),
                "align": align, "top_margin": q(box.y), "left_margin": q(box.x),
                "right_margin": q(page_w - box.right),
                "width_share": round(box.width / page_w, 4) if page_w else None,
                "text_length": length}

    flagged = [it for it in items if it.furniture_kind == "title-block"
               and not it.is_container]
    if flagged:
        it = min(flagged, key=lambda i: (i.box.y, -i.box.width))
        return describe(it.box, "title-master", it.concept, it.text_length)
    texts = [it for it in items if not it.is_container and not it.concept and it.has_text
             and it.box.y <= TITLE_BAND * page_h and it.box.width >= TITLE_MIN_WIDTH * page_w]
    if texts:
        it = min(texts, key=lambda i: (i.box.y, -i.box.width))
        return describe(it.box, "text-box", "", it.text_length)
    roots = [it for it in items if it.role == "container" and it.heading_box is not None
             and not any(o is not it and o.role == "container" and o.box.contains(it.box)
                         for o in items)]
    if roots:
        root = max(roots, key=lambda i: i.box.area)
        return describe(root.heading_box, "container-heading", root.concept, root.text_length)
    return None


def _containers(items: list[Item]) -> tuple[list[dict], list[dict]]:
    by_ref = {it.ref: it for it in items}
    records: list[dict] = []
    for it in items:
        if it.role != "container":
            continue
        rec: dict = {"ref": it.ref, "kind": it.kind or "container", "master": it.concept or None,
                     "box": it.box.as_json()}
        direct = [by_ref[r] for r in it.members if r in by_ref
                  and by_ref[r].role == "shape" and not by_ref[r].is_furniture]
        rec["members"] = len(it.members)
        rec["member_shapes"] = len(direct)
        if it.heading_box is not None:
            h, b = it.heading_box, it.box
            band_wide = h.width >= HEADING_BAND_SHARE * b.width
            band_tall = h.height >= HEADING_BAND_SHARE * b.height
            if band_wide and not band_tall:
                side = "top" if (h.y - b.y) <= (b.bottom - h.bottom) else "bottom"
            elif band_tall and not band_wide:
                side = "left" if (h.x - b.x) <= (b.right - h.right) else "right"
            else:
                edges = {"top": abs(h.y - b.y), "bottom": abs(b.bottom - h.bottom),
                         "left": abs(h.x - b.x), "right": abs(b.right - h.right)}
                side = min(edges, key=lambda e: (edges[e], e))
            horizontal = side in ("top", "bottom")
            rec["heading"] = {
                "side": side,
                "thickness": q(h.height if horizontal else h.width),
                "span": q(h.width if horizontal else h.height),
                "span_share": round((h.width / b.width) if horizontal else
                                    (h.height / b.height), 4) if (b.width and b.height) else None}
        if direct:
            left = min(d.box.x for d in direct)
            top = min(d.box.y for d in direct)
            right = max(d.box.right for d in direct)
            bottom = max(d.box.bottom for d in direct)
            rec["insets"] = {"left": q(left - it.box.x), "top": q(top - it.box.y),
                             "right": q(it.box.right - right), "bottom": q(it.box.bottom - bottom)}
        records.append(rec)

    # Lane stacks: sibling lanes (same parent container by enclosure) laid end to end. The
    # stacking axis is the one along which their CENTERS spread.
    lanes = [it for it in items if it.role == "container" and it.kind in ("lane", "pool")]
    stacks: list[dict] = []
    groups: dict[Optional[int], list[Item]] = defaultdict(list)
    for lane in lanes:
        parents = [j for j, o in enumerate(items)
                   if o.role == "container" and o.kind not in ("lane", "pool")
                   and o.box.contains(lane.box)]
        parent = min(parents, key=lambda j: items[j].box.area) if parents else None
        groups[parent].append(lane)
    for parent, members in sorted(groups.items(), key=lambda kv: (kv[0] is None, kv[0] or 0)):
        if len(members) < 2:
            continue
        spread_x = max(m.box.cx for m in members) - min(m.box.cx for m in members)
        spread_y = max(m.box.cy for m in members) - min(m.box.cy for m in members)
        vertical = spread_y >= spread_x
        ordered = sorted(members, key=(lambda m: m.box.y) if vertical else (lambda m: m.box.x))
        gaps = Counter(q((b.box.y - a.box.bottom) if vertical else (b.box.x - a.box.right))
                       for a, b in zip(ordered, ordered[1:]))
        thickness = Counter(q(m.box.height if vertical else m.box.width) for m in ordered)
        length = Counter(q(m.box.width if vertical else m.box.height) for m in ordered)
        stacks.append({"axis": "vertical" if vertical else "horizontal", "lanes": len(ordered),
                       "thickness": dist_json(thickness), "length": dist_json(length),
                       "gap": dist_json(gaps)})
    return records, stacks


def measure_page(doc: dict, *, label: str = "",
                 master_defaults: Optional[dict[str, dict]] = None) -> dict:
    """Everything this tool measures on one page read; see the module docstring.

    `label` identifies the diagram in the output (a catalog id); `master_defaults` is
    `load_master_defaults`'s result. The result holds no shape text.
    """
    validate_page_read(doc)
    page = doc["page"]
    page_w, page_h = float(page["width"]), float(page["height"])
    items = _items(doc)
    # A shape that encloses another is a container for adjacency, whatever it is called.
    for it in items:
        if it.role == "shape" and any(o is not it and o.role == "shape" and it.box.contains(o.box)
                                      for o in items):
            it.container_geometric = True
    context = _context(items)
    defaults = master_defaults or {}

    # Sizes per master (every mastered item), roles noted.
    sized: dict[str, Counter] = defaultdict(Counter)
    roles: dict[str, set] = defaultdict(set)
    unit_ids: dict[str, str] = {}
    for it in items:
        if not it.concept:
            continue
        w, h = q(it.box.width), q(it.box.height)
        if abs(it.angle) > 1e-9:
            continue   # a rotated shape is a bounding box, not the master's size
        sized[it.concept][(w, h)] += 1
        roles[it.concept].add("container" if it.role == "container" else
                              "furniture" if it.is_furniture else "shape")
        unit_ids.setdefault(it.concept, it.master_id)
    sizes: dict = {}
    for concept, counts in sorted(sized.items()):
        rec = size_json(counts)
        rec["role"] = "/".join(sorted(roles[concept]))
        d = defaults.get(unit_ids.get(concept, ""))
        if d is not None:
            rec["default"] = {"width": d["width"], "height": d["height"], "source": d["source"]}
            rec["at_default"] = sum(c for (w, h), c in counts.items()
                                    if abs(w - d["width"]) <= QUANTUM * 1.5
                                    and abs(h - d["height"]) <= QUANTUM * 1.5)
        sizes[concept] = rec

    unmastered = {"shapes": sum(1 for it in items if it.role == "shape" and not it.concept),
                  "with_text": sum(1 for it in items if it.role == "shape" and not it.concept
                                   and it.has_text)}

    h_pairs, nph = nearest_neighbor_gaps(items, "h", context)
    v_pairs, npv = nearest_neighbor_gaps(items, "v", context)
    h_gap, v_gap = Counter(g for g, _ in h_pairs), Counter(g for g, _ in v_pairs)
    h_pitch, v_pitch = Counter(p for _, p in h_pairs), Counter(p for _, p in v_pairs)

    furniture: dict = defaultdict(list)
    for it in items:
        if it.is_furniture:
            furniture[it.furniture_kind].append(
                {"master": it.concept or None, "box": it.box.as_json(),
                 "text_length": it.text_length})
    content = [it for it in items if not it.is_furniture]
    margins = None
    if items:
        margins = {"left": q(min(i.box.x for i in items)),
                   "top": q(min(i.box.y for i in items)),
                   "right": q(page_w - max(i.box.right for i in items)),
                   "bottom": q(page_h - max(i.box.bottom for i in items))}

    containers, stacks = _containers(items)
    unavailable = list(doc.get("unavailable", []))
    if any(it.has_text for it in items) and not any(it.label_box for it in items):
        unavailable.append("shapes[].label_box")
    if any(it.role == "container" for it in items) and not any(it.heading_box for it in items
                                                                if it.role == "container"):
        unavailable.append("containers[].heading_box")
    if doc["connectors"] and not any(c.get("path") for c in doc["connectors"]):
        unavailable.append("connectors[].path")

    warnings: list[str] = []
    scaled = "drawing_scale" in page
    if scaled:
        warnings.append("drawing scale is not 1:1; sizes are in drawing units and this "
                        "diagram is set aside from pooled statistics")
    rotated = sum(1 for it in items if abs(it.angle) > 1e-9)
    if rotated:
        warnings.append(f"{rotated} rotated shape(s) excluded from sizes")

    return {
        "label": label,
        "page": {"page_id": page.get("page_id"), "width": page_w, "height": page_h,
                 "orientation": page.get("orientation"),
                 "background": bool(page.get("background")),
                 "drawing_scale": page.get("drawing_scale"), "scaled": scaled},
        "counts": {"containers": len([i for i in items if i.role == "container"]),
                   "shapes": len([i for i in items if i.role == "shape"]),
                   "connectors": len(doc["connectors"]),
                   "scaffold_excluded": sum(1 for k in ("containers", "shapes")
                                            for s in doc[k] if s.get("scaffold")),
                   "furniture": len([i for i in items if i.is_furniture]),
                   "endpoints": len([i for i in content if not i.is_container and i.concept])},
        "sizes": sizes,
        "unmastered": unmastered,
        "gaps": {"horizontal": dist_json(h_gap), "vertical": dist_json(v_gap),
                 "excluded_touching": {"horizontal": nph, "vertical": npv}},
        "pitch": {"horizontal": dist_json(h_pitch), "vertical": dist_json(v_pitch)},
        "alignment": _alignment(items, context),
        "connectors": _connectors(doc, items),
        "labels": _labels(items),
        "title": _title(doc, items, page_w, page_h),
        "furniture": {k: furniture[k] for k in FURNITURE_KINDS if k in furniture},
        "containers": containers,
        "lane_stacks": stacks,
        "margins": margins,
        "unavailable": sorted(set(unavailable)),
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# Across diagrams
# --------------------------------------------------------------------------

def _pool_counter(diagrams: Sequence[dict], getter) -> dict[str, Counter]:
    out: dict[str, Counter] = {}
    for d in diagrams:
        values = getter(d)
        if values:
            out[d["label"]] = Counter({_unquote(k): c for k, c in values.items()})
    return out


def pool(diagrams: Sequence[dict]) -> dict:
    """Pooled statistics over the diagrams that are comparable.

    Set aside, and counted: scaled diagrams (sizes in drawing units), background pages.
    """
    used = [d for d in diagrams if not d["page"]["scaled"] and not d["page"]["background"]]
    aside = {"scaled": sum(1 for d in diagrams if d["page"]["scaled"]),
             "background": sum(1 for d in diagrams if d["page"]["background"])}

    sizes: dict = {}
    names = sorted({m for d in used for m in d["sizes"]})
    for name in names:
        counts: Counter = Counter()
        diagrams_with = 0
        defaults, at_default = set(), 0
        roles = set()
        for d in used:
            rec = d["sizes"].get(name)
            if rec is None:
                continue
            diagrams_with += 1
            counts.update({_unquote(k): c for k, c in rec["values"].items()})
            roles.add(rec["role"])
            if "default" in rec:
                defaults.add((rec["default"]["width"], rec["default"]["height"],
                              rec["default"]["source"]))
                at_default += rec["at_default"]
        rec = size_json(counts)
        rec["diagrams"] = diagrams_with
        rec["role"] = "/".join(sorted(roles))
        rec["fixed_shape"] = (rec["n"] >= MIN_SAMPLE and rec["mode"] is not None
                              and rec["mode_share"] >= FIXED_SHAPE_SHARE)
        rec["dominant"] = rec["mode"] is not None and rec["mode_share"] >= DOMINANT_SHARE
        if len(defaults) == 1:
            w, h, source = next(iter(defaults))
            rec["default"] = {"width": w, "height": h, "source": source}
            rec["at_default"] = at_default
        elif len(defaults) > 1:
            rec["default"] = None
            rec["defaults_disagree"] = [list(d[:2]) for d in sorted(defaults)]
        sizes[name] = rec

    gaps = {"horizontal": gap_json(_pool_counter(used, lambda d: d["gaps"]["horizontal"]["values"])),
            "vertical": gap_json(_pool_counter(used, lambda d: d["gaps"]["vertical"]["values"]))}
    pitch = {"horizontal": gap_json(_pool_counter(used, lambda d: d["pitch"]["horizontal"]["values"])),
             "vertical": gap_json(_pool_counter(used, lambda d: d["pitch"]["vertical"]["values"]))}

    routes: Counter = Counter()
    sides = {"begin": Counter(), "end": Counter()}
    n_conn = 0
    for d in used:
        routes.update(d["connectors"]["routes"])
        sides["begin"].update(d["connectors"]["begin_side"])
        sides["end"].update(d["connectors"]["end_side"])
        n_conn += d["connectors"]["n"]
    align = Counter()
    align_n = 0
    for d in used:
        a = d["alignment"]
        align_n += a.get("n", 0)
        for k, v in a.items():
            if k not in ("n", "tolerance"):
                align[k] += v
    label_rel: dict[str, Counter] = defaultdict(Counter)
    for d in used:
        for m, c in d["labels"]["by_master"].items():
            label_rel[m].update(c)

    titles = Counter((d["title"]["source"], d["title"]["align"]) for d in used if d["title"])
    kinds: dict[str, Counter] = defaultdict(Counter)
    for d in used:
        for rec in d["containers"]:
            kinds[rec["kind"]][_key((rec["box"]["width"], rec["box"]["height"]))] += 1
    container_sizes = {k: size_json(Counter({_unquote(s): c for s, c in v.items()}))
                       for k, v in sorted(kinds.items())}
    headings: dict[str, Counter] = defaultdict(Counter)
    for d in used:
        for rec in d["containers"]:
            if "heading" in rec:
                headings[rec["kind"]][(rec["heading"]["side"], rec["heading"]["thickness"])] += 1
    heading_stats = {k: {f"{s}:{t:g}": c for (s, t), c in sorted(v.items())}
                     for k, v in sorted(headings.items())}

    return {
        "diagrams": len(diagrams), "pooled": len(used), "set_aside": aside,
        "sizes": sizes, "gaps": gaps, "pitch": pitch,
        "connectors": {"n": n_conn, "routes": dict(sorted(routes.items())),
                       "begin_side": dict(sorted(sides["begin"].items())),
                       "end_side": dict(sorted(sides["end"].items()))},
        "alignment": {"n": align_n, **{k: align[k] for k in sorted(align)}},
        "label_relations": {m: dict(sorted(c.items())) for m, c in sorted(label_rel.items())},
        "titles": {f"{s}:{a}": c for (s, a), c in sorted(titles.items())},
        "container_sizes": container_sizes,
        "container_headings": heading_stats,
    }


# --------------------------------------------------------------------------
# The corpus catalog
# --------------------------------------------------------------------------

CATALOG_SCHEMA = "apv-visio-corpus-catalog/1"
MEASUREMENTS_SCHEMA = "apv-visio-corpus-measurements/1"
ENTRY_KINDS = ("template-sample", "sample", "customer-example")
ROOT_TOKEN = "<visio-content>"

_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BUILD = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ABSOLUTE = re.compile(r"^([A-Za-z]:|[\\/])|(^|[\\/])\.\.([\\/]|$)")


def validate_catalog(doc: dict) -> list[str]:
    """Problems with a corpus catalog; empty when it is sound.

    A catalog says WHICH files were measured, WHERE they came from and WHEN. It names a
    file relative to a stated root and never by an absolute path, and it never holds the
    file's content: a Microsoft file is read in place and not copied.
    """
    errors: list[str] = []

    def need(obj, key, kind, where):
        if not isinstance(obj, dict) or key not in obj:
            errors.append(f"{where}: `{key}` is missing")
            return None
        value = obj[key]
        if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
            errors.append(f"{where}: `{key}` must be {kind.__name__}")
            return None
        return obj[key]

    if not isinstance(doc, dict):
        return ["catalog must be an object"]
    if doc.get("schema") != CATALOG_SCHEMA:
        errors.append(f"schema must be {CATALOG_SCHEMA!r}")
    corpus = need(doc, "corpus", dict, "catalog")
    if corpus is not None:
        need(corpus, "name", str, "corpus")
        if corpus.get("root") != ROOT_TOKEN:
            errors.append(f"corpus.root must be {ROOT_TOKEN!r}: files are named relative to a "
                          "stated root, never by an absolute path")
    visio = need(doc, "visio", dict, "catalog")
    if visio is not None:
        build = need(visio, "build", str, "visio")
        if build is not None and not _BUILD.match(build):
            errors.append("visio.build must look like 16.0.20430.20146")
        need(visio, "content_locale", str, "visio")
    measured = need(doc, "measured_on", str, "catalog")
    if measured is not None and not _DATE.match(measured):
        errors.append("measured_on must be YYYY-MM-DD")
    tool = need(doc, "tool", dict, "catalog")
    if tool is not None:
        if tool.get("name") != TOOL:
            errors.append(f"tool.name must be {TOOL!r}")
        need(tool, "version", int, "tool")
    entries = need(doc, "entries", list, "catalog")
    seen: set[str] = set()
    for n, e in enumerate(entries or []):
        where = f"entries[{n}]"
        eid = need(e, "id", str, where)
        if eid is not None:
            if not _ID.match(eid):
                errors.append(f"{where}: id {eid!r} must be lowercase letters, digits, . _ -")
            if eid in seen:
                errors.append(f"{where}: duplicate id {eid!r}")
            seen.add(eid)
        f = need(e, "file", str, where)
        if f is not None and (_ABSOLUTE.search(f) or not f.strip()):
            errors.append(f"{where}: file {f!r} must be relative to {ROOT_TOKEN}, "
                          "with no drive, no leading separator and no '..'")
        if need(e, "kind", str, where) not in (*ENTRY_KINDS, None):
            errors.append(f"{where}: kind must be one of {', '.join(ENTRY_KINDS)}")
        name = e.get("template_name") if isinstance(e, dict) else None
        if name is not None and not isinstance(name, str):
            errors.append(f"{where}: template_name must be a string or null")
        elif isinstance(e, dict) and "template_name" not in e:
            errors.append(f"{where}: `template_name` is missing (null when the file has none)")
        need(e, "size_bytes", int, where)
        sha = need(e, "sha256", str, where)
        if sha is not None and not _SHA.match(sha):
            errors.append(f"{where}: sha256 must be 64 lowercase hex digits")
        need(e, "pages_measured", int, where)
        c = need(e, "counts", dict, where)
        if c is not None:
            for k in ("containers", "shapes", "connectors"):
                need(c, k, int, f"{where}.counts")
    skipped = doc.get("examined_not_measured", [])
    if not isinstance(skipped, list):
        errors.append("examined_not_measured must be a list")
    else:
        for n, s in enumerate(skipped):
            where = f"examined_not_measured[{n}]"
            f = need(s, "file", str, where)
            if f is not None and _ABSOLUTE.search(f):
                errors.append(f"{where}: file {f!r} must be relative")
            need(s, "reason", str, where)
    return errors


def validate_measurements(doc: dict, catalog: dict) -> list[str]:
    """Problems with a measurements file: every row must cite a catalog entry."""
    errors: list[str] = []
    if doc.get("schema") != MEASUREMENTS_SCHEMA:
        errors.append(f"schema must be {MEASUREMENTS_SCHEMA!r}")
    ids = {e.get("id") for e in catalog.get("entries", [])}
    cited: set[str] = set()
    for n, d in enumerate(doc.get("diagrams", [])):
        cid = d.get("catalog_id")
        if cid not in ids:
            errors.append(f"diagrams[{n}]: catalog_id {cid!r} is not in the catalog")
        else:
            cited.add(cid)
        if not d.get("label"):
            errors.append(f"diagrams[{n}]: `label` is missing")
    for missing in sorted(ids - cited):
        errors.append(f"catalog entry {missing!r} has no measurement row")
    return errors


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------

def load_page_reads(path: str) -> list[dict]:
    """A JSON file holding one page read or a list of them."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, list) else [data]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("page_reads", nargs="+", metavar="page-read.json",
                        help="file(s) holding an apt-page-read document or a list of them")
    parser.add_argument("--master-catalog", action="append", default=[], metavar="capture.json",
                        help="a template-capture file giving master default sizes; repeatable")
    parser.add_argument("--no-pool", action="store_true", help="per-diagram results only")
    args = parser.parse_args(argv)
    try:
        defaults = load_master_defaults(args.master_catalog)
        diagrams = []
        for path in args.page_reads:
            for i, doc in enumerate(load_page_reads(path), 1):
                stem = Path(path).stem
                diagrams.append(measure_page(doc, label=f"{stem}#{i}", master_defaults=defaults))
    except (MeasureError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    result = {"tool": TOOL, "tool_version": TOOL_VERSION, "unit": UNIT, "diagrams": diagrams}
    if not args.no_pool:
        result["pooled"] = pool(diagrams)
    json.dump(result, sys.stdout, indent=1)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
