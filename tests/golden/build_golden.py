#!/usr/bin/env python3
"""Build the golden .vsdx files used to test the measurement tool and its extractor.

TEST-ONLY. These files live under `tests/golden/`, outside `plugins/`, so they are not in
`manifest.json` and never ship (skills ship text only). Run this to regenerate them:

    python tests/golden/build_golden.py

The goldens are DETERMINISTIC (fixed zip timestamps, sorted parts), and
`test_vsdx_to_page_read.py` asserts the committed files equal a fresh build, so a golden
cannot drift from the geometry written down here.

THE GEOMETRY IS KNOWN, NOT MEASURED. Every shape is placed by hand in Visio's own
convention (inches, origin bottom-left, y up, pin at `LocPinX`/`LocPinY`) on an 11 x 8.5
page, and the tests state the contract-convention numbers they expect from first
principles in comments (`y = 8.5 - (pin_y + height / 2)`), not from the extractor.

NOT YET OPENED IN VISIO. These parts follow the structure of the templates Microsoft ships
(content types, relationships, masters, page, `Connects`), but no copy has been opened in
Visio; that was not possible while another job held the application. Whether Visio opens
them without a repair prompt is APV-2026-0106. Until then they prove the READER, not the
files' fitness for Visio.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

NS = "http://schemas.microsoft.com/office/visio/2012/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
REL_BASE = "http://schemas.microsoft.com/visio/2010/relationships"

# A fixed timestamp keeps the archive byte-identical from run to run.
EPOCH = (1980, 1, 1, 0, 0, 0)


def cell(name, value, formula=None) -> str:
    f = f" F='{escape(formula)}'" if formula else ""
    return f"<Cell N='{name}' V='{value}'{f}/>"


def cells(**kw) -> str:
    return "".join(cell(k, v) for k, v in kw.items())


def user_row(name, value) -> str:
    return (f"<Section N='User'><Row N='{name}'><Cell N='Value' V='{value}' U='STR'/></Row>"
            "</Section>")


def geometry(rows: list[tuple]) -> str:
    """A Geometry section from `(type, x, y)` rows (a row may leave a coordinate out)."""
    out = ["<Section N='Geometry' IX='0'>"]
    for ix, (kind, x, y) in enumerate(rows, 1):
        out.append(f"<Row T='{kind}' IX='{ix}'>")
        if x is not None:
            out.append(cell("X", x))
        if y is not None:
            out.append(cell("Y", y))
        out.append("</Row>")
    out.append("</Section>")
    return "".join(out)


def master_xml(shape_cells: str, extra: str = "") -> str:
    return (f"<?xml version='1.0' encoding='utf-8' ?><MasterContents xmlns='{NS}' "
            f"xmlns:r='{R}' xml:space='preserve'><Shapes><Shape ID='1' Type='Shape' "
            f"NameU='Master'>{shape_cells}{extra}</Shape></Shapes></MasterContents>")


def box_master(width: float, height: float, structure: str = "") -> str:
    cs = (cell("Width", width) + cell("Height", height)
          + cell("LocPinX", width / 2, "Width*0.5") + cell("LocPinY", height / 2, "Height*0.5")
          + cell("TxtPinX", width / 2, "Width*0.5") + cell("TxtPinY", height / 2, "Height*0.5")
          + cell("TxtWidth", width, "Width*1") + cell("TxtHeight", height, "Height*1")
          + cell("TxtLocPinX", width / 2, "TxtWidth*0.5") + cell("TxtLocPinY", height / 2, "TxtHeight*0.5"))
    return master_xml(cs, user_row("msvStructureType", structure) if structure else "")


def connector_master() -> str:
    cs = cells(Width=1, Height=0, LocPinX=0.5, LocPinY=0, BeginX=0, BeginY=0, EndX=1, EndY=0)
    return master_xml(cs, geometry([("MoveTo", 0, 0), ("LineTo", 1, 0)]))


# (id, NameU, UniqueID, master xml)
MASTERS = {
    "Process": (1, "{11111111-0001-0000-8E40-00608CF305B2}", lambda: box_master(1.5, 0.75)),
    "Decision": (2, "{11111111-0002-0000-8E40-00608CF305B2}", lambda: box_master(1.25, 1.0)),
    "Dynamic connector": (3, "{11111111-0003-0000-8E40-00608CF305B2}", connector_master),
    "Legend": (4, "{11111111-0004-0000-8E40-00608CF305B2}", lambda: box_master(2.0, 1.0)),
    "Container": (5, "{11111111-0005-0000-8E40-00608CF305B2}", lambda: box_master(1.0, 1.0, "Container")),
    "Swimlane": (6, "{11111111-0006-0000-8E40-00608CF305B2}", lambda: box_master(1.0, 1.0, "Container")),
}


def masters_xml(names: list[str]) -> tuple[str, str]:
    items = []
    rels = []
    for n, name in enumerate(names, 1):
        mid, uid, _ = MASTERS[name]
        items.append(f"<Master ID='{mid}' NameU='{escape(name)}' Name='{escape(name)}' "
                     f"UniqueID='{uid}' BaseID='{uid}'><Rel r:id='rId{mid}'/></Master>")
        rels.append(f"<Relationship Id='rId{mid}' Type='{REL_BASE}/master' Target='master{mid}.xml'/>")
    return (f"<?xml version='1.0' encoding='utf-8' ?><Masters xmlns='{NS}' xmlns:r='{R}' "
            f"xml:space='preserve'>{''.join(items)}</Masters>",
            f"<?xml version='1.0' encoding='UTF-8' standalone='yes'?><Relationships xmlns='{PKG}'>"
            f"{''.join(rels)}</Relationships>")


def shape(sid, *, master=None, kind="Shape", name=None, cs="", children="", text=None,
          formula_relationships=None, master_shape=None) -> str:
    m = f" Master='{MASTERS[master][0]}'" if master else ""
    ms = f" MasterShape='{master_shape}'" if master_shape else ""
    n = f" NameU='{escape(name)}'" if name else ""
    rel = cell("Relationships", 0, formula_relationships) if formula_relationships else ""
    body = f"<Text>{escape(text)}</Text>" if text is not None else ""
    kids = f"<Shapes>{children}</Shapes>" if children else ""
    return f"<Shape ID='{sid}' Type='{kind}'{n}{m}{ms}>{cs}{rel}{kids}{body}</Shape>"


def refs(code: int, ids: list[int]) -> str:
    return f"DEPENDSON({code}," + ",".join(f"Sheet.{i}!SheetRef()" for i in ids) + ")"


def connector(sid, begin, end, glue_begin, glue_end, rows, text=None, label=None) -> tuple:
    """A 1-D connector from `begin` to `end` (page points, y up) drawn as `rows`.

    The pin is the midpoint of the ends, `Width`/`Height` are the signed extents (as Visio
    stores a connector), and `rows` are `(type, x, y)` in the connector's local frame.
    """
    (bx, by), (ex, ey) = begin, end
    w, h = ex - bx, ey - by
    cs = cells(PinX=(bx + ex) / 2, PinY=(by + ey) / 2, Width=w, Height=h,
               LocPinX=w / 2, LocPinY=h / 2, BeginX=bx, BeginY=by, EndX=ex, EndY=ey)
    if label:
        cs += cells(TxtPinX=label[0], TxtPinY=label[1], TxtWidth=label[2], TxtHeight=label[3],
                    TxtLocPinX=label[2] / 2, TxtLocPinY=label[3] / 2)
    xml = shape(sid, master="Dynamic connector", cs=cs + geometry(rows), text=text)
    connects = []
    if glue_begin:
        connects.append((sid, "BeginX", glue_begin))
    if glue_end:
        connects.append((sid, "EndX", glue_end))
    return xml, connects


def package(masters: list[str], page_cells: str, shapes_xml: str, connects: list[tuple],
            template: bool = False) -> bytes:
    mx, mrels = masters_xml(masters)
    conn = "".join(f"<Connect FromSheet='{a}' FromCell='{b}' ToSheet='{c}' ToCell='PinX'/>"
                   for a, b, c in connects)
    page = (f"<?xml version='1.0' encoding='utf-8' ?><PageContents xmlns='{NS}' xmlns:r='{R}' "
            f"xml:space='preserve'><Shapes>{shapes_xml}</Shapes>"
            f"{'<Connects>' + conn + '</Connects>' if conn else ''}</PageContents>")
    pages = (f"<?xml version='1.0' encoding='utf-8' ?><Pages xmlns='{NS}' xmlns:r='{R}' "
             f"xml:space='preserve'><Page ID='0' NameU='Page-1' Name='Page-1'>"
             f"<PageSheet>{page_cells}</PageSheet><Rel r:id='rId1'/></Page></Pages>")
    main_ct = "application/vnd.ms-visio.drawing.main+xml"
    parts = {
        "[Content_Types].xml": (
            "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
            "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>"
            "<Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>"
            "<Default Extension='xml' ContentType='application/xml'/>"
            f"<Override PartName='/visio/document.xml' ContentType='{main_ct}'/>"
            "<Override PartName='/visio/masters/masters.xml' ContentType='application/vnd.ms-visio.masters+xml'/>"
            + "".join(f"<Override PartName='/visio/masters/master{MASTERS[m][0]}.xml' "
                      "ContentType='application/vnd.ms-visio.master+xml'/>" for m in masters)
            + "<Override PartName='/visio/pages/pages.xml' ContentType='application/vnd.ms-visio.pages+xml'/>"
            "<Override PartName='/visio/pages/page1.xml' ContentType='application/vnd.ms-visio.page+xml'/>"
            "</Types>"),
        "_rels/.rels": (
            f"<?xml version='1.0' encoding='UTF-8' standalone='yes'?><Relationships xmlns='{PKG}'>"
            f"<Relationship Id='rId1' Type='{REL_BASE}/document' Target='visio/document.xml'/></Relationships>"),
        "visio/document.xml": (
            f"<?xml version='1.0' encoding='utf-8' ?><VisioDocument xmlns='{NS}' xmlns:r='{R}' "
            "xml:space='preserve'><DocumentSettings/><Colors/><FaceNames/><StyleSheets>"
            "<StyleSheet ID='0' NameU='No Style' Name='No Style'/></StyleSheets></VisioDocument>"),
        "visio/_rels/document.xml.rels": (
            f"<?xml version='1.0' encoding='UTF-8' standalone='yes'?><Relationships xmlns='{PKG}'>"
            f"<Relationship Id='rId1' Type='{REL_BASE}/masters' Target='masters/masters.xml'/>"
            f"<Relationship Id='rId2' Type='{REL_BASE}/pages' Target='pages/pages.xml'/></Relationships>"),
        "visio/masters/masters.xml": mx,
        "visio/masters/_rels/masters.xml.rels": mrels,
        "visio/pages/pages.xml": pages,
        "visio/pages/_rels/pages.xml.rels": (
            f"<?xml version='1.0' encoding='UTF-8' standalone='yes'?><Relationships xmlns='{PKG}'>"
            f"<Relationship Id='rId1' Type='{REL_BASE}/page' Target='page1.xml'/></Relationships>"),
        "visio/pages/page1.xml": page,
    }
    for m in masters:
        parts[f"visio/masters/master{MASTERS[m][0]}.xml"] = MASTERS[m][2]()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(parts):
            info = zipfile.ZipInfo(name, EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, parts[name])
    return buf.getvalue()


def page_sheet(width=11, height=8.5, page_scale=1, drawing_scale=1) -> str:
    return cells(PageWidth=width, PageHeight=height, PageScale=page_scale,
                 DrawingScale=drawing_scale)


# --------------------------------------------------------------------------
# golden-flow.vsdx
# --------------------------------------------------------------------------

def build_flow(page_scale=1, drawing_scale=1) -> bytes:
    """Seven boxes, a legend, a title, four connectors; every number is stated below.

    Visio coordinates (y up), page 11 x 8.5. `Process` is 1.5 x 0.75 by default,
    `Decision` 1.25 x 1.0, `Legend` 2.0 x 1.0; a center pin unless a shape says otherwise.

      id  master    pin (x, y)  note
       1  Process   (2.0, 6.0)  inherits its size
       2  Process   (5.0, 6.0)
       3  Process   (7.5, 6.0)
       4  Decision  (2.0, 4.0)  states Width 1.0; LocPinX is NOT stated, so it must be
                                 Width * 0.5 = 0.5 and not the master's 0.625
       5  Process   (9.0, 7.0)  LocPinX 0, LocPinY 0.375: the pin is the left-middle edge
       6  Process   (5.0, 1.5)  rotated 90 degrees
       7  Process   (9.5, 1.5)  text block 0.1 below the shape
       8  Legend    (1.5, 0.75)
       9  (none)    (5.5, 8.0)  6.0 x 0.5 text box: the title
    """
    shapes = [
        shape(1, master="Process", name="P1", cs=cells(PinX=2.0, PinY=6.0), text="Receive"),
        shape(2, master="Process", cs=cells(PinX=5.0, PinY=6.0), text="Validate"),
        shape(3, master="Process", cs=cells(PinX=7.5, PinY=6.0), text="Post"),
        shape(4, master="Decision", cs=cells(PinX=2.0, PinY=4.0, Width=1.0), text="OK?"),
        shape(5, master="Process", cs=cells(PinX=9.0, PinY=7.0, LocPinX=0, LocPinY=0.375)),
        shape(6, master="Process", cs=cells(PinX=5.0, PinY=1.5, Angle=1.5707963267948966)),
        shape(7, master="Process",
              cs=cells(PinX=9.5, PinY=1.5, TxtPinX=0.75, TxtPinY=-0.25, TxtWidth=1.5,
                       TxtHeight=0.3, TxtLocPinX=0.75, TxtLocPinY=0.15), text="Archive"),
        shape(8, master="Legend", cs=cells(PinX=1.5, PinY=0.75)),
        shape(9, cs=cells(PinX=5.5, PinY=8.0, Width=6.0, Height=0.5), text="Westbrook Payments"),
    ]
    c10, k10 = connector(10, (2.75, 6.0), (4.25, 6.0), 1, 2,
                         [("MoveTo", 0, 0), ("LineTo", 1.5, 0)], text="yes",
                         label=(0.75, 0.25, 0.5, 0.2))
    c11, k11 = connector(11, (7.5, 5.625), (8.75, 1.5), 3, 7,
                         [("MoveTo", 0, 0), ("LineTo", 0, -4.125), ("LineTo", 1.25, -4.125)])
    c12, k12 = connector(12, (2.0, 5.625), (2.0, 4.5), 1, 4,
                         [("MoveTo", 0, 0), ("LineTo", 0, -1.125)])
    c13, k13 = connector(13, (3.0, 1.0), (4.0, 0.5), None, None,
                         [("MoveTo", 0, 0), ("EllipticalArcTo", 1, -0.5)])
    xml = "".join(shapes) + c10 + c11 + c12 + c13
    return package(["Process", "Decision", "Dynamic connector", "Legend"],
                   page_sheet(page_scale=page_scale, drawing_scale=drawing_scale), xml,
                   k10 + k11 + k12 + k13)


# --------------------------------------------------------------------------
# golden-lanes.vsdx
# --------------------------------------------------------------------------

def build_lanes() -> bytes:
    """A container with a heading band, two stacked lanes with left headings, four steps.

    Visio coordinates (y up), page 11 x 8.5.

      id 1  Container   pin (5.5, 4.5)   10 x 6   -> x 0.5..10.5, y 1.5..7.5 (bottom-left)
         heading part: 10 x 0.5 at the top of the container, text "Branch"
      id 2  Swimlane    pin (5.5, 5.75)  10 x 2.5 -> y 4.5..7.0; heading part 0.5 x 2.5 at left
      id 3  Swimlane    pin (5.5, 3.25)  10 x 2.5 -> y 2.0..4.5
      id 4  Process     pin (3.0, 5.75)  in lane 2     id 6  Process  pin (7.0, 5.75) in lane 2
      id 5  Process     pin (3.0, 3.25)  in lane 3     id 7  Process  pin (7.0, 3.25) in lane 3

    A shape lists the sheets that hold it in `Relationships` as `DEPENDSON(4, ...)`; a
    lane is held by the container and a step by the container and its lane, and the
    INNERMOST (smallest) is its parent.
    """
    head = shape(8, cs=cells(PinX=5, PinY=5.75, Width=10, Height=0.5), text="Branch")
    lane_head_a = shape(9, cs=cells(PinX=0.25, PinY=1.25, Width=0.5, Height=2.5), text="Teller")
    lane_head_b = shape(10, cs=cells(PinX=0.25, PinY=1.25, Width=0.5, Height=2.5), text="Manager")
    container = shape(
        1, master="Container", kind="Group", name="Branch Container",
        cs=cells(PinX=5.5, PinY=4.5, Width=10, Height=6, LocPinX=5, LocPinY=3),
        children=head,
        formula_relationships="SUM(" + refs(1, [2, 3, 4, 5, 6, 7]) + ")")
    lane1 = shape(
        2, master="Swimlane", kind="Group",
        cs=cells(PinX=5.5, PinY=5.75, Width=10, Height=2.5, LocPinX=5, LocPinY=1.25),
        children=lane_head_a,
        formula_relationships="SUM(" + refs(5, [1]) + "," + refs(1, [4, 6]) + ")")
    lane2 = shape(
        3, master="Swimlane", kind="Group",
        cs=cells(PinX=5.5, PinY=3.25, Width=10, Height=2.5, LocPinX=5, LocPinY=1.25),
        children=lane_head_b,
        formula_relationships="SUM(" + refs(5, [1]) + "," + refs(1, [5, 7]) + ")")
    steps = [
        shape(4, master="Process", cs=cells(PinX=3.0, PinY=5.75),
              formula_relationships="SUM(" + refs(4, [1, 2]) + ")"),
        shape(5, master="Process", cs=cells(PinX=3.0, PinY=3.25),
              formula_relationships="SUM(" + refs(4, [1, 3]) + ")"),
        shape(6, master="Process", cs=cells(PinX=7.0, PinY=5.75),
              formula_relationships="SUM(" + refs(4, [1, 2]) + ")"),
        shape(7, master="Process", cs=cells(PinX=7.0, PinY=3.25),
              formula_relationships="SUM(" + refs(4, [1, 3]) + ")"),
    ]
    c11, k11 = connector(11, (3.75, 5.75), (6.25, 5.75), 4, 6,
                         [("MoveTo", 0, 0), ("LineTo", 2.5, 0)])
    return package(["Process", "Container", "Swimlane", "Dynamic connector"],
                   page_sheet(), container + lane1 + lane2 + "".join(steps) + c11, k11)


# --------------------------------------------------------------------------
# golden-scaffold.vsdx
# --------------------------------------------------------------------------

def build_scaffold() -> bytes:
    """One step, and a template's instruction panel left at the page foot.

      id 1  Process   pin (2.0, 6.0)         -> x 1.25, y 2.125, 1.5 x 0.75
      id 2  (none)    pin (5.5, 1.0), 10 x 1.2 group; its part says to delete it
                                              -> x 0.5, y 6.9, 10.0 x 1.2
    """
    part = shape(3, cs=cells(PinX=5, PinY=0.6, Width=9, Height=1.0),
                 text="Select the Tip Pane and press Delete")
    panel = shape(2, kind="Group", cs=cells(PinX=5.5, PinY=1.0, Width=10, Height=1.2),
                  children=part)
    one = shape(1, master="Process", cs=cells(PinX=2.0, PinY=6.0), text="Receive")
    return package(["Process"], page_sheet(), one + panel, [])


GOLDEN = {
    "golden-flow.vsdx": build_flow,
    "golden-lanes.vsdx": build_lanes,
    "golden-scaled.vsdx": lambda: build_flow(page_scale=0.25, drawing_scale=12),
    "golden-scaffold.vsdx": build_scaffold,
}


def main(argv=None) -> int:
    out = Path(__file__).resolve().parent
    for name, build in GOLDEN.items():
        (out / name).write_bytes(build())
        print(f"wrote {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
