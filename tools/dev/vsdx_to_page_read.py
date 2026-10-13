#!/usr/bin/env python3
"""DEVELOPMENT ONLY. Read a .vsdx / .vstx directly (zip + XML) into page-read shape.

NOT SHIPPED. This file lives under `tools/dev/`, outside `plugins/`, so it is not in
`manifest.json` and never reaches a customer. It exists so that `measure_visio.py`
(which consumes page-read-shaped documents and nothing else) can be run and tested
before the server's page read (D5, APV-2026-0015) exists. When D5 lands, the measurement
tool is fed D5's output instead and this file is retired; the measurement tool does not
change.

    python tools/dev/vsdx_to_page_read.py <file.vsdx> [--page N] > page-read.json

READ-ONLY, NO VISIO
-------------------
The file is opened with `zipfile` and parsed with `xml.etree`. There is no COM, Visio is
never started, nothing is written next to the input, and nothing is extracted to disk.
It is a tool for TRUSTED files (Microsoft's installed templates, files we generate). It
refuses a DOCTYPE or entity declaration and caps member count and size, but the full
hardening (APV-2026-0009) belongs to the server's OPC reader, not to this script.

THE COORDINATE CONVERSION - STATED ONCE
---------------------------------------
Visio stores a shape's position as its PIN (`PinX`, `PinY`) in inches on an axis that
points UP with the origin at the bottom-left of the page, and the pin sits at
(`LocPinX`, `LocPinY`) inside the shape's own box (the center, unless the shape says
otherwise). The page-read contract (DESIGN-visio-v2-contracts, section 4, "Two
coordinate conventions") is inches, origin TOP-LEFT, y DOWN, a rectangle by its top-left
corner. For an unrotated shape this module computes

    x = pin_x - loc_pin_x
    y = page_height - (pin_y - loc_pin_y + height)

which for a center pin is the contract's `x = pin_x - width / 2`,
`y = page_height - (pin_y + height / 2)`. A rotated shape is reported as the axis-aligned
bounding box of the rotated rectangle, with `angle` (degrees) added. Every other point
(connector paths, text blocks) goes through `to_top_left`, the one function that turns a
bottom-left point into a top-left one. Nothing else in this file or in
`measure_visio.py` flips an axis.

Length cells are inches in the file whatever unit the document displays (APV-2026-0004
verified this against a metric template). A page whose drawing scale is not 1:1 stores
shape sizes in drawing units, not paper inches; such a page is read as stored and carries
`page.drawing_scale` so the measurement can set it aside instead of mixing scales.

WHAT IS READ, AND WHAT IS NOT
-----------------------------
A shape inherits any cell it does not state from its master. The size, the pin location
and the text block are resolved: the instance's value if it has one, else the master
shape's, and where the master states a cell as a multiple of the shape's own size
(`Width*0.5`, `TxtWidth*0.5`) the multiple is applied to THIS shape's size rather than copying the
master's cached value, which belongs to the master's size. Only TOP-LEVEL page shapes are
read; the parts of a group are not shapes of the page. Container membership comes from
the `Relationships` cell (`DEPENDSON(4, Sheet.N ...)` = "I am inside sheet N"), never from
geometry. Connector ends come from the page's `Connects`. Text is read verbatim.

Not read, and listed in `unavailable`: `shapes[].role`, `shapes[].style`,
`shapes[].shape_data`, `shapes[].hyperlinks`, `connectors[].style`, `image`. Fields beyond
revision 2.1 of the contract, added because the measurement needs them and named here so
D5 can decide whether to carry them (APV-2026-0107): `shapes[].label_box` and
`connectors[].label_box` (the text block, in contract coordinates),
`containers[].heading_box` (the heading band, taken from the container's parts),
`shapes[].angle`, `page.background`, `page.drawing_scale`, `shapes[].master.base_id`, and
`shapes[].scaffold` (only when the caller passes a pattern for a template's instruction
text, which the template leaves on its sample page for the author to delete).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Optional
import xml.etree.ElementTree as ET

NS = "http://schemas.microsoft.com/office/visio/2012/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
V = "{%s}" % NS

CONTRACT = "apt-page-read"
CONTRACT_VERSION = "0.1"

#: Limits for a trusted-file reader. Microsoft's largest template part measured here is
#: well under a megabyte; these are an order of magnitude above that, not a security
#: boundary (see the module docstring).
MAX_MEMBERS = 5000
MAX_MEMBER_BYTES = 64 * 1024 * 1024

#: Tolerance for deciding that a connector segment is axis-aligned, in inches.
AXIS_TOL = 1e-3

UNAVAILABLE = [
    "image", "shapes[].role", "shapes[].style", "shapes[].shape_data",
    "shapes[].hyperlinks", "containers[].style", "containers[].shape_data",
    "connectors[].style", "connectors[].shape_data",
    "shapes[].text_extent", "containers[].text_extent",
]


class ReadError(Exception):
    """The file cannot be read as a Visio package."""


def to_top_left(x: float, y: float, page_height: float) -> tuple[float, float]:
    """A point on Visio's bottom-left, y-up page as a contract point (top-left, y-down).

    THE ONLY PLACE AN AXIS IS FLIPPED. See the module docstring.
    """
    return x, page_height - y


# --------------------------------------------------------------------------
# Package access
# --------------------------------------------------------------------------

class Package:
    """A read-only view of an OPC package: parts by name, relationships by source."""

    def __init__(self, path: str):
        try:
            self.zf = zipfile.ZipFile(path, "r")
        except (zipfile.BadZipFile, OSError) as exc:
            raise ReadError(f"not a readable package: {exc}") from exc
        infos = self.zf.infolist()
        if len(infos) > MAX_MEMBERS:
            raise ReadError(f"{len(infos)} members is over the limit of {MAX_MEMBERS}")
        self.names = {i.filename for i in infos}
        self.sizes = {i.filename: i.file_size for i in infos}

    def close(self) -> None:
        self.zf.close()

    def has(self, name: str) -> bool:
        return name in self.names

    def xml(self, name: str) -> ET.Element:
        if name not in self.names:
            raise ReadError(f"part missing: {name}")
        if self.sizes[name] > MAX_MEMBER_BYTES:
            raise ReadError(f"{name} is {self.sizes[name]} bytes, over the limit")
        raw = self.zf.read(name)
        head = raw[:4096].upper()
        if b"<!DOCTYPE" in head or b"<!ENTITY" in raw.upper():
            raise ReadError(f"{name} declares a DOCTYPE or entity; refusing to parse")
        try:
            return ET.fromstring(raw)
        except ET.ParseError as exc:
            raise ReadError(f"{name} is not well-formed XML: {exc}") from exc

    def rels(self, part: str) -> dict[str, str]:
        """`{relationship id: resolved part name}` for the part's `.rels` file."""
        p = PurePosixPath(part)
        rels_name = str(p.parent / "_rels" / (p.name + ".rels"))
        if rels_name not in self.names:
            return {}
        out = {}
        for rel in self.xml(rels_name):
            if rel.get("TargetMode") == "External":
                continue
            out[rel.get("Id")] = resolve_part(p.parent, rel.get("Target", ""))
        return out


def resolve_part(base: PurePosixPath, target: str) -> str:
    """A relationship target as a package part name, kept inside the package."""
    if target.startswith("/"):
        parts = target.lstrip("/").split("/")
    else:
        parts = list(base.parts) + target.split("/")
    out: list[str] = []
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not out:
                raise ReadError(f"relationship target escapes the package: {target}")
            out.pop()
        else:
            out.append(part)
    return "/".join(out)


# --------------------------------------------------------------------------
# Cells and master inheritance
# --------------------------------------------------------------------------

@dataclass
class Cell:
    value: Optional[str]
    formula: Optional[str]


def _cells(shape: ET.Element) -> dict[str, Cell]:
    return {c.get("N"): Cell(c.get("V"), c.get("F")) for c in shape.findall(V + "Cell")}


def _num(text: Optional[str]) -> Optional[float]:
    if text is None or text == "":
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _user_rows(shape: ET.Element) -> dict[str, str]:
    out = {}
    for sec in shape.findall(V + "Section"):
        if sec.get("N") != "User":
            continue
        for row in sec.findall(V + "Row"):
            for cell in row.findall(V + "Cell"):
                if cell.get("N") == "Value":
                    out[row.get("N")] = cell.get("V") or ""
    return out


def _geometry(shape: ET.Element) -> dict[int, dict]:
    """`{section IX: {"flags": {...}, "rows": {row IX: {"T": type, cell: value}}}}`."""
    out: dict[int, dict] = {}
    for sec in shape.findall(V + "Section"):
        if sec.get("N") != "Geometry":
            continue
        ix = int(sec.get("IX", "0"))
        section = {"flags": {}, "rows": {}, "del": sec.get("Del") == "1"}
        for cell in sec.findall(V + "Cell"):
            section["flags"][cell.get("N")] = cell.get("V")
        for row in sec.findall(V + "Row"):
            if row.get("IX") is None:
                continue
            r = {"T": row.get("T"), "del": row.get("Del") == "1"}
            for cell in row.findall(V + "Cell"):
                r[cell.get("N")] = cell.get("V")
            section["rows"][int(row.get("IX"))] = r
        out[ix] = section
    return out


@dataclass
class Source:
    """The cells, User rows and geometry one master shape offers for inheritance."""
    cells: dict[str, Cell] = field(default_factory=dict)
    user: dict[str, str] = field(default_factory=dict)
    geometry: dict[int, dict] = field(default_factory=dict)


def _source(shape: ET.Element) -> Source:
    return Source(_cells(shape), _user_rows(shape), _geometry(shape))


@dataclass
class MasterShape:
    """A master: its identity, its top-level shape, and every shape in its tree by ID.

    A sub-shape of a page group names the master shape it inherits from with
    `MasterShape="<id>"`, and that id is always an id in the tree of the TOP-LEVEL
    instance's master, however deeply the sub-shape is nested.
    """
    master_id: str
    name: str
    universal_name: str
    unique_id: str
    base_id: str
    cells: dict[str, Cell] = field(default_factory=dict)
    user: dict[str, str] = field(default_factory=dict)
    geometry: dict[int, dict] = field(default_factory=dict)
    by_id: dict[str, Source] = field(default_factory=dict)

    @property
    def top(self) -> Source:
        return Source(self.cells, self.user, self.geometry)


def read_masters(pkg: Package) -> dict[str, MasterShape]:
    """`{master id: MasterShape}` from the package's own embedded masters."""
    if not pkg.has("visio/masters/masters.xml"):
        return {}
    root = pkg.xml("visio/masters/masters.xml")
    rels = pkg.rels("visio/masters/masters.xml")
    out: dict[str, MasterShape] = {}
    for m in root.findall(V + "Master"):
        rel = m.find(V + "Rel")
        target = rels.get(rel.get("{%s}id" % REL_NS)) if rel is not None else None
        ms = MasterShape(m.get("ID"), m.get("Name") or "", m.get("NameU") or m.get("Name") or "",
                         m.get("UniqueID") or "", m.get("BaseID") or "")
        if target and pkg.has(target):
            shapes = pkg.xml(target).find(V + "Shapes")
            top = shapes.find(V + "Shape") if shapes is not None else None
            if top is not None:
                ms.cells = _cells(top)
                ms.user = _user_rows(top)
                ms.geometry = _geometry(top)
                for el in top.iter(V + "Shape"):
                    ms.by_id[el.get("ID")] = _source(el)
        out[ms.master_id] = ms
    return out


_SIZE_MULTIPLE = re.compile(r"^\s*(Width|Height|TxtWidth|TxtHeight)\s*\*\s*([0-9.]+)\s*$")


class Resolved:
    """A shape with master inheritance applied to the cells the measurement needs.

    `master` is the `Source` it inherits from: its master's top shape for a page shape,
    or the named shape in that master's tree for a sub-shape; None when it has none.
    """

    def __init__(self, shape: ET.Element, master: Optional[Source]):
        self.shape = shape
        self.master = master
        self.own = _cells(shape)

    def cell(self, name: str) -> Optional[float]:
        """Numeric cell: this shape's value, else the master's (see the docstring)."""
        own = self.own.get(name)
        if own is not None and _num(own.value) is not None:
            return _num(own.value)
        if self.master is None:
            return None
        inherited = self.master.cells.get(name)
        if inherited is None:
            return None
        match = _SIZE_MULTIPLE.match(inherited.formula or "")
        if match and name != match.group(1):
            basis = self.cell(match.group(1))
            if basis is not None:
                return basis * float(match.group(2))
        return _num(inherited.value)

    def has_cell(self, name: str) -> bool:
        return name in self.own or (self.master is not None and name in self.master.cells)

    def user_row(self, name: str) -> Optional[str]:
        own = _user_rows(self.shape)
        if name in own:
            return own[name]
        return self.master.user.get(name) if self.master is not None else None

    def geometry(self) -> dict[int, dict]:
        """The master's geometry with this shape's overrides laid over it."""
        merged: dict[int, dict] = {}
        if self.master is not None:
            for ix, sec in self.master.geometry.items():
                merged[ix] = {"flags": dict(sec["flags"]), "del": sec["del"],
                              "rows": {r: dict(row) for r, row in sec["rows"].items()}}
        for ix, sec in _geometry(self.shape).items():
            into = merged.setdefault(ix, {"flags": {}, "rows": {}, "del": False})
            into["flags"].update(sec["flags"])
            into["del"] = sec["del"] or into["del"]
            for r, row in sec["rows"].items():
                into["rows"].setdefault(r, {"T": row["T"], "del": False}).update(row)
        return merged


def _text(shape: ET.Element) -> Optional[str]:
    node = shape.find(V + "Text")
    if node is None:
        return None
    return "".join(node.itertext()).strip()


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------

@dataclass
class Frame:
    """A shape's local frame: pin, size and rotation, in its OUTER frame's coordinates.

    For a page shape the outer frame is the page (bottom-left, y up); for a sub-shape it
    is the parent group's local frame.
    """
    pin_x: float
    pin_y: float
    width: float
    height: float
    loc_x: float
    loc_y: float
    angle: float = 0.0
    flip_x: bool = False
    flip_y: bool = False

    def to_outer(self, lx: float, ly: float) -> tuple[float, float]:
        """A point in the shape's local frame, in the outer frame's coordinates."""
        if self.flip_x:
            lx = self.width - lx
        if self.flip_y:
            ly = self.height - ly
        dx, dy = lx - self.loc_x, ly - self.loc_y
        c, s = math.cos(self.angle), math.sin(self.angle)
        return self.pin_x + dx * c - dy * s, self.pin_y + dx * s + dy * c

    def bbox(self) -> tuple[float, float, float, float]:
        """`(left, bottom, right, top)` of the shape's rectangle on the page (y up)."""
        corners = [self.to_outer(x, y) for x, y in
                   ((0, 0), (self.width, 0), (self.width, self.height), (0, self.height))]
        xs, ys = [p[0] for p in corners], [p[1] for p in corners]
        return min(xs), min(ys), max(xs), max(ys)


def _frame(r: Resolved) -> Optional[Frame]:
    pin_x, pin_y = r.cell("PinX"), r.cell("PinY")
    width, height = r.cell("Width"), r.cell("Height")
    if None in (pin_x, pin_y, width, height):
        return None
    loc_x, loc_y = r.cell("LocPinX"), r.cell("LocPinY")
    return Frame(pin_x, pin_y, width, height,
                 width / 2 if loc_x is None else loc_x,
                 height / 2 if loc_y is None else loc_y,
                 r.cell("Angle") or 0.0,
                 bool(r.cell("FlipX")), bool(r.cell("FlipY")))


def _rect(left: float, bottom: float, right: float, top: float, page_h: float) -> dict:
    x, y = to_top_left(left, top, page_h)
    return {"x": round(x, 6), "y": round(y, 6),
            "width": round(right - left, 6), "height": round(top - bottom, 6)}


def _label_box(r: Resolved, frame: Frame, page_h: float) -> Optional[dict]:
    """The text block as a contract rectangle, or None when the shape states none.

    The block is `TxtWidth` x `TxtHeight` with its own pin (`TxtPinX`, `TxtPinY`) at
    (`TxtLocPinX`, `TxtLocPinY`), all in the SHAPE's local frame. Each is resolved like
    any inherited cell; a block that states no size is the shape's own box.
    """
    tw = r.cell("TxtWidth") if r.has_cell("TxtWidth") else frame.width
    th = r.cell("TxtHeight") if r.has_cell("TxtHeight") else frame.height
    if tw is None:
        tw = frame.width
    if th is None:
        th = frame.height
    tpx = r.cell("TxtPinX") if r.has_cell("TxtPinX") else frame.width / 2
    tpy = r.cell("TxtPinY") if r.has_cell("TxtPinY") else frame.height / 2
    tlx = r.cell("TxtLocPinX") if r.has_cell("TxtLocPinX") else tw / 2
    tly = r.cell("TxtLocPinY") if r.has_cell("TxtLocPinY") else th / 2
    if None in (tpx, tpy, tlx, tly):
        return None
    left, bottom = tpx - tlx, tpy - tly
    corners = [frame.to_outer(x, y) for x, y in
               ((left, bottom), (left + tw, bottom), (left + tw, bottom + th), (left, bottom + th))]
    xs, ys = [p[0] for p in corners], [p[1] for p in corners]
    return _rect(min(xs), min(ys), max(xs), max(ys), page_h)


def _path(r: Resolved, frame: Frame, page_h: float) -> tuple[list[dict], bool]:
    """`(points, curved)`: the drawn polyline of a 1-D shape in contract coordinates.

    Rows are merged over the master's (an instance usually states only the cells that
    differ). Arcs and splines contribute their end vertex and set `curved`.
    """
    sections = [(ix, s) for ix, s in sorted(r.geometry().items())
                if not s["del"] and s["flags"].get("NoShow") != "1"]
    points: list[tuple[float, float]] = []
    curved = False
    if sections:
        _, section = sections[0]
        for _, row in sorted(section["rows"].items()):
            if row["del"]:
                continue
            kind = row["T"] or ""
            x, y = _num(row.get("X")), _num(row.get("Y"))
            if kind in ("RelMoveTo", "RelLineTo"):
                if x is None or y is None:
                    continue
                x, y = x * frame.width, y * frame.height
            elif kind in ("MoveTo", "LineTo"):
                x = 0.0 if x is None else x
                y = 0.0 if y is None else y
            elif kind in ("ArcTo", "EllipticalArcTo", "NURBSTo", "SplineStart", "SplineKnot",
                          "RelCubBezTo", "RelQuadBezTo", "RelEllipticalArcTo"):
                curved = True
                if x is None or y is None:
                    continue
                if kind.startswith("Rel"):
                    x, y = x * frame.width, y * frame.height
            else:
                continue
            points.append(frame.to_outer(x, y))
    if len(points) < 2:
        bx, by, ex, ey = (r.cell("BeginX"), r.cell("BeginY"), r.cell("EndX"), r.cell("EndY"))
        if None in (bx, by, ex, ey):
            return [], curved
        points = [(bx, by), (ex, ey)]
    out = []
    for x, y in points:
        tx, ty = to_top_left(x, y, page_h)
        point = {"x": round(tx, 6), "y": round(ty, 6)}
        if not out or out[-1] != point:
            out.append(point)
    return out, curved


def classify_route(path: list[dict], curved: bool, ext: Optional[float]) -> Optional[str]:
    """`straight`, `orthogonal` or `curved`; None when a diagonal polyline fits none.

    Taken from the DRAWN path, not from the connector's route-style cell: the enumeration
    of that cell was not verified, and the path is what a reader sees.
    """
    if curved or ext == 2:
        return "curved"
    if len(path) < 2:
        return None
    if len(path) == 2:
        return "straight"
    for a, b in zip(path, path[1:]):
        if abs(a["x"] - b["x"]) > AXIS_TOL and abs(a["y"] - b["y"]) > AXIS_TOL:
            return None
    return "orthogonal"


def _heading(r: Resolved, master: Optional[MasterShape], frame: Frame,
             page_h: float) -> Optional[tuple[str, dict]]:
    """`(text, box)` of a container's heading, taken from its parts, or None.

    A container group usually carries no text of its own; its heading is the first
    part (depth first) that has a text element, even an empty one (an unnamed phase
    still has its band). The part's box is mapped out through every enclosing frame to
    the page. Parts get their size and pin from the master shape they name.
    """
    def walk(el: ET.Element, chain: list[Frame]):
        children = el.find(V + "Shapes")
        for child in (children.findall(V + "Shape") if children is not None else []):
            ref = child.get("MasterShape")
            own_master = master.by_id.get(ref) if (master and ref) else None
            cr = Resolved(child, own_master)
            cf = _frame(cr)
            if cf is not None:
                text = _text(child)
                if text is not None:
                    corners = [cf.to_outer(x, y) for x, y in
                               ((0, 0), (cf.width, 0), (cf.width, cf.height), (0, cf.height))]
                    for outer in chain:
                        corners = [outer.to_outer(x, y) for x, y in corners]
                    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
                    return text, _rect(min(xs), min(ys), max(xs), max(ys), page_h)
                found = walk(child, [cf] + chain)
                if found:
                    return found
        return None
    return walk(r.shape, [frame])


# --------------------------------------------------------------------------
# Page read
# --------------------------------------------------------------------------

_SHEET_REF = re.compile(r"Sheet\.(\d+)!SheetRef\(\)")
_DEPENDSON = re.compile(r"DEPENDSON\(\s*(\d+)((?:\s*,\s*Sheet\.\d+!SheetRef\(\))*)\s*\)")


def memberships(formula: Optional[str]) -> list[int]:
    """Sheet ids a shape says it is INSIDE: the `DEPENDSON(4 ...)` groups of `Relationships`.

    Verified on the cross-functional sample: a lane lists its list as code 5, a shape in
    a lane lists the list, the lane and the phase separator as code 4. Bit 4 means "the
    sheets that follow contain me"; the other bits are not interpreted.
    """
    out: list[int] = []
    for m in _DEPENDSON.finditer(formula or ""):
        if int(m.group(1)) & 4:
            out += [int(s) for s in _SHEET_REF.findall(m.group(2))]
    return out


_KIND_WORDS = (("pool", "pool"), ("swimlane", "lane"), ("lane", "lane"),
               ("phase", "phase"), ("separator", "phase"))


def container_kind(structure: str, name: str) -> str:
    """Contract container `kind` from Visio's structure type and the master name."""
    lowered = (name or "").lower()
    if structure == "List":
        return "list"
    for word, kind in _KIND_WORDS:
        if re.search(r"\b" + word, lowered):
            return kind
    return "container"


def _orientation(width: float, height: float) -> str:
    return "landscape" if width >= height else "portrait"


def page_parts(pkg: Package) -> list[dict]:
    """Pages in document order: `{"id", "name", "background", "part", "sheet": Element}`."""
    rels = pkg.rels("visio/pages/pages.xml")
    out = []
    for page in pkg.xml("visio/pages/pages.xml").findall(V + "Page"):
        rel = page.find(V + "Rel")
        part = rels.get(rel.get("{%s}id" % REL_NS)) if rel is not None else None
        out.append({"id": page.get("ID"), "name": page.get("NameU") or page.get("Name") or "",
                    "background": page.get("Background") == "1", "part": part,
                    "sheet": page.find(V + "PageSheet")})
    return out


def _page_cell(sheet: Optional[ET.Element], name: str) -> Optional[float]:
    if sheet is None:
        return None
    for c in sheet.findall(V + "Cell"):
        if c.get("N") == name:
            return _num(c.get("V"))
    return None


def read_page(pkg: Package, masters: dict[str, MasterShape], page: dict,
              document_path: str, document_name: str,
              scaffold: Optional[re.Pattern] = None) -> dict:
    """One page as an `apt-page-read` document.

    `scaffold`, when given, is a pattern for the instructional text a template leaves on
    its sample page for the author to delete ("Select the Tip Pane and press Delete").
    A top-level shape whose parts' text matches it is emitted with `scaffold: true`, an
    extension to the contract, so a measurement can leave it out: it is not the diagram.
    """
    width = _page_cell(page["sheet"], "PageWidth") or 0.0
    height = _page_cell(page["sheet"], "PageHeight") or 0.0
    scale_paper = _page_cell(page["sheet"], "PageScale") or 1.0
    scale_drawing = _page_cell(page["sheet"], "DrawingScale") or 1.0
    warnings: list[str] = []
    containers, shapes, connectors = [], [], []
    root = pkg.xml(page["part"]) if page["part"] else None
    top = root.find(V + "Shapes") if root is not None else None

    resolved: dict[str, Resolved] = {}
    master_of: dict[str, Optional[MasterShape]] = {}
    order: list[str] = []
    for sh in (top.findall(V + "Shape") if top is not None else []):
        sid = sh.get("ID")
        master = masters.get(sh.get("Master") or "")
        master_of[sid] = master
        resolved[sid] = Resolved(sh, master.top if master else None)
        order.append(sid)

    # Container structure first: a shape's parent is the innermost sheet it says holds it.
    frames = {sid: _frame(r) for sid, r in resolved.items()}
    structure = {sid: (r.user_row("msvStructureType") or "") for sid, r in resolved.items()}
    container_ids = {sid for sid, s in structure.items() if s in ("Container", "List")}

    def area(sid: str) -> float:
        f = frames.get(sid)
        return f.width * f.height if f else math.inf

    parent: dict[str, str] = {}
    for sid, r in resolved.items():
        inside = [str(i) for i in memberships(r.own["Relationships"].formula
                                              if "Relationships" in r.own else None)
                  if str(i) in container_ids and str(i) != sid]
        if inside:
            parent[sid] = min(inside, key=area)

    def ref(sid: str) -> str:
        return "id:" + sid

    members: dict[str, list[str]] = {}
    for child, par in parent.items():
        members.setdefault(par, []).append(ref(child))

    connects: dict[tuple[str, str], str] = {}
    cn = root.find(V + "Connects") if root is not None else None
    for c in (cn if cn is not None else []):
        end = "begin" if (c.get("FromCell") or "").startswith("Begin") else \
              "end" if (c.get("FromCell") or "").startswith("End") else None
        if end:
            connects[(c.get("FromSheet"), end)] = c.get("ToSheet")

    for sid in order:
        r = resolved[sid]
        frame = frames[sid]
        m = master_of[sid]
        sh = r.shape
        master_obj = None
        if m is not None:
            master_obj = {"name": m.name or m.universal_name, "universal_name": m.universal_name,
                          "unique_id": m.unique_id}
            if m.base_id:
                master_obj["base_id"] = m.base_id
        if frame is None:
            warnings.append(f"shape {sid}: no resolvable position or size; skipped")
            continue
        text = _text(sh)
        one_d = r.has_cell("BeginX") and r.has_cell("EndX")
        rec: dict = {"ref": ref(sid), "shape_id": int(sid)}
        if sh.get("UniqueID"):
            rec["unique_id"] = sh.get("UniqueID")
        if master_obj:
            rec["master"] = master_obj
        if text is not None:
            rec["text"] = text
        lb = _label_box(r, frame, height)
        if lb and text:
            rec["label_box"] = lb
        if sid in parent:
            rec["parent_ref"] = ref(parent[sid])
        if scaffold is not None and not one_d and scaffold.search(
                " ".join("".join(t.itertext()) for t in sh.iter(V + "Text"))):
            rec["scaffold"] = True

        if one_d:
            path, curved = _path(r, frame, height)
            rec["glued_begin"] = (sid, "begin") in connects
            rec["glued_end"] = (sid, "end") in connects
            if rec["glued_begin"]:
                rec["from_ref"] = ref(connects[(sid, "begin")])
            if rec["glued_end"]:
                rec["to_ref"] = ref(connects[(sid, "end")])
            route = classify_route(path, curved, r.cell("ConLineRouteExt"))
            if route:
                rec["route"] = route
            rec["path"] = path
            connectors.append(rec)
            continue

        left, bottom, right, top_y = frame.bbox()
        rec.update(_rect(left, bottom, right, top_y, height))
        if abs(frame.angle) > 1e-9:
            rec["angle"] = round(math.degrees(frame.angle), 4)
        if sid in container_ids:
            rec["kind"] = container_kind(structure[sid], (m.universal_name if m else "") or "")
            rec["members"] = members.get(sid, [])
            if not rec.get("text"):
                heading = _heading(r, m, frame, height)
                if heading:
                    rec["text"], rec["heading_box"] = heading
            elif "label_box" in rec:
                rec["heading_box"] = rec["label_box"]
            containers.append(rec)
        else:
            shapes.append(rec)

    doc = {
        "contract": CONTRACT, "contract_version": CONTRACT_VERSION, "engine": "file",
        "unit": "in", "origin": "top-left",
        "document": {"path": document_path, "name": document_name},
        "page": {"page_id": page["id"], "name": page["name"], "width": round(width, 6),
                 "height": round(height, 6), "orientation": _orientation(width, height),
                 "background": page["background"]},
        "containers": containers, "shapes": shapes, "connectors": connectors,
        "counts": {"containers": len(containers), "shapes": len(shapes),
                   "connectors": len(connectors), "keyed": 0,
                   "unkeyed": len(containers) + len(shapes) + len(connectors),
                   "duplicate_keys": 0},
        "unavailable": list(UNAVAILABLE),
    }
    if abs(scale_paper - scale_drawing) > 1e-9:
        doc["page"]["drawing_scale"] = {"page": scale_paper, "drawing": scale_drawing}
        warnings.append(f"drawing scale {scale_paper}:{scale_drawing}; sizes are in drawing "
                        "units, not paper inches")
    if warnings:
        doc["warnings"] = warnings
    return doc


def extract(path: str, *, path_label: Optional[str] = None,
            include_background: bool = True,
            scaffold_pattern: Optional[str] = None) -> list[dict]:
    """Every page of a .vsdx / .vstx as an `apt-page-read` document, in page order.

    `path_label` replaces the path recorded in `document.path`: pass a path relative to
    a stated root (`<visio-content>\\1033\\NAME.VSTX`) so no absolute path is carried
    into anything that is kept. Background pages are included, flagged
    `page.background`, unless `include_background` is false. `scaffold_pattern` is a
    regular expression for template instruction text (see `read_page`).
    """
    pkg = Package(path)
    try:
        masters = read_masters(pkg)
        name = PurePosixPath(path.replace("\\", "/")).name
        label = path_label if path_label is not None else path
        pattern = re.compile(scaffold_pattern, re.I) if scaffold_pattern else None
        return [read_page(pkg, masters, p, label, name, pattern) for p in page_parts(pkg)
                if include_background or not p["background"]]
    finally:
        pkg.close()


def master_defaults(path: str) -> list[dict]:
    """Default size of each master EMBEDDED in the package, read from the file itself.

    `{"name", "universal_name", "unique_id", "width_in", "height_in"}`; used by the
    corpus runner to add defaults the template-capture fixtures do not cover.
    """
    pkg = Package(path)
    try:
        out = []
        for m in read_masters(pkg).values():
            w, h = _num(m.cells["Width"].value) if "Width" in m.cells else None, \
                   _num(m.cells["Height"].value) if "Height" in m.cells else None
            out.append({"name": m.name, "universal_name": m.universal_name,
                        "unique_id": m.unique_id, "width_in": w, "height_in": h})
        return out
    finally:
        pkg.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("file")
    parser.add_argument("--page", type=int, help="1-based page number; default: all pages")
    args = parser.parse_args(argv)
    try:
        pages = extract(args.file)
    except ReadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.page is not None:
        pages = pages[args.page - 1:args.page]
    json.dump(pages if args.page is None else (pages[0] if pages else None), sys.stdout, indent=1)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
