"""Feed a page read to the fidelity checker.

`fidelity.py` is a faithful copy of the checker in the Sparx EA skills library
(see `fidelity-source.md` beside it). It judges a reproduction against a
reference reading, and it takes the reproduction as a list of objects in EA's
coordinate convention: `left`, `right`, `top`, `bottom`, with `top` and `bottom`
NEGATIVE and `top` above `bottom`. A page read is a different shape in a
different convention - top-left origin, y increasing downward, a rectangle by
its top-left corner and size, in inches (`apt-page-read`, section 4 of the v2
contracts). This module is the whole of the difference, and nothing else: it
reshapes a page read into the checker's input and calls the checker.

It does not touch the checker's arithmetic and it adds no tolerance. The
tolerance is the reference reading's declared `precision`, exactly as in the
original; precision comes from the reading, not from here.

THE CONVERSION

For a shape with page-read fields `x, y, width, height` (inches, top-left, y
down) the checker's object is

    left = x            right  = x + width
    top  = -y           bottom = -(y + height)

which is the same negation the original's own fixtures apply to a reading in
image coordinates. The page read's unit (inches) is not converted to the
reading's unit (pixels): the checker fits one uniform scale and offset between
the two before it judges anything, so the unit difference is the fitted `scale`
and the report says so. A shape above the page's top edge (negative `y`) would
make `top` positive, which the checker refuses as a mirrored rect, so all `y`
values are first shifted down by a single amount that makes every one
non-negative. A uniform translation is exactly what the fit removes, so the
shift cannot change a finding; it is recorded in the metrics so it is not
silent.

CORRESPONDENCE IS DECLARED

The checker matches a produced object to a reference element by the `ref` the
object carries. A page read's `ref` is the shape's key, and a reading of an EA
diagram names its elements by the same key, so by default the key IS the
reference id. A reading transcribed from a picture has ids of its own; pass
`ref_map` ({page-read ref: reading element id}) to say which shape stands for
which element. A shape a person drew by hand has no key (its `ref` is
`id:<shape_id>`), so it stands for nothing, and the checker reports it as an
extra element.

READ BOTH `faithful` AND `not_run`

`faithful` means the report holds no errors, as in the original. A report whose
`not_run` is non-empty has compared less than it looks, and in one case compared
no geometry at all (no positive scale could be fitted, which is also what a
vertically mirrored page produces): `faithful` is still True there. A caller
treats a non-empty `not_run` as "not verified", not as "verified".

WHAT THE PAGE READ CANNOT SAY IS SAID

Anything that the adapter could not hand to the checker comes out of
`compare_page_read` as an entry in `report.not_run`, never as silence: a shape
with no usable extent, a connector with an unglued end, a fill that is not a
`#RRGGBB` color. The page read states a `features` count for no shape, so a
reading that records one gets the checker's own "cannot be compared" entry.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

import fidelity

__all__ = [
    "KNOWN_CONTRACT_VERSIONS",
    "PageReadInput",
    "to_fidelity_input",
    "compare_page_read",
]

#: The page-read contract versions this adapter was written against. A reader
#: refuses a version it does not know rather than guessing.
KNOWN_CONTRACT_VERSIONS = ("0.1",)

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass
class PageReadInput:
    """What the checker is handed, plus what the adapter could not hand over."""

    objects: list = field(default_factory=list)
    links: list = field(default_factory=list)
    #: Becomes `report.not_run`: things the page read held that the comparison
    #: could not use, each with the reason.
    notes: list = field(default_factory=list)
    #: The single downward shift applied to every `y`, in the page read's unit.
    y_shift: float = 0.0


def _check_contract(page_read: Mapping[str, Any]) -> None:
    if page_read.get("contract") != "apt-page-read":
        raise ValueError(
            f"not a page read: contract is {page_read.get('contract')!r}, "
            f"expected 'apt-page-read'.")
    version = page_read.get("contract_version")
    if version not in KNOWN_CONTRACT_VERSIONS:
        raise ValueError(
            f"page read contract_version {version!r} is not one this adapter "
            f"knows ({', '.join(KNOWN_CONTRACT_VERSIONS)}). Refusing rather than "
            f"guessing what the fields mean.")
    if page_read.get("unit") != "in":
        raise ValueError(
            f"page read unit is {page_read.get('unit')!r}; the page-read "
            f"contract is in inches ('in').")
    if page_read.get("origin") != "top-left":
        raise ValueError(
            f"page read origin is {page_read.get('origin')!r}; this adapter "
            f"converts from 'top-left' with y increasing downward and will not "
            f"assume it. A bottom-left, y-up read would be measured mirrored.")
    for name in ("containers", "shapes", "connectors"):
        if not isinstance(page_read.get(name), list):
            raise ValueError(f"page read has no `{name}` list; the contract "
                             f"requires it.")


def _ref_for(item: Mapping[str, Any], ref_map: Mapping[str, str]) -> str:
    """The reference id this page-read item claims to stand for, or ''."""
    identity = item.get("identity") or {}
    key = str(identity.get("key") or "").strip()
    ref = str(item.get("ref") or "").strip()
    if not key and ref.startswith("id:"):
        return ""   # drawn by hand: keyless, stands for nothing
    return ref_map.get(ref, ref)


def _extent(item: Mapping[str, Any]) -> Optional[tuple]:
    """`(x, y, width, height)` as floats, or None when it has no usable extent."""
    try:
        x, y, w, h = (float(item[k]) for k in ("x", "y", "width", "height"))
    except (KeyError, TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return (x, y, w, h)


def to_fidelity_input(page_read: Mapping[str, Any],
                      ref_map: Optional[Mapping[str, str]] = None
                      ) -> PageReadInput:
    """Reshape a page read into `fidelity.compare`'s `objects` and `links`.

    Containers and shapes both become objects: a lane or a group is drawn on the
    page and a reading may record it. Connectors become links, but only a
    connector glued at both ends has anything to say about which things are
    joined, so the others are reported in `notes` and offered as nothing.
    """
    _check_contract(page_read)
    ref_map = dict(ref_map or {})

    extents = []
    for kind, items in (("container", page_read["containers"]),
                        ("shape", page_read["shapes"])):
        for item in items:
            extents.append((kind, item, _extent(item)))
    usable = [e for _, _, e in extents if e is not None]
    # One shift for the whole page; see the module docstring.
    shift = max(0.0, -min(y for _, y, _, _ in usable)) if usable else 0.0

    result = PageReadInput(y_shift=shift)
    for kind, item, extent in extents:
        label = item.get("ref") or f"id:{item.get('shape_id', '?')}"
        if extent is None:
            result.notes.append(
                f"page read {kind} {label!r}: no usable extent (x, y, width and "
                f"height, with positive width and height), so it cannot take "
                f"part in a comparison of geometry. If the reading has an "
                f"element for it, that element is reported missing.")
            continue
        x, y, w, h = extent
        obj: dict = {
            "ref": _ref_for(item, ref_map),
            "left": x,
            "right": x + w,
            "top": -(y + shift),
            "bottom": -(y + shift + h),
        }
        # The checker reads `name` only to report and to match when no object
        # declares a `ref`. A page read has no name; its visible text is the
        # nearest thing, and name matching is flagged as a guess regardless.
        text = item.get("text")
        if text:
            obj["name"] = str(text)
        # `text` is passed when the page read states it (even as an empty
        # string, which means known-empty); absent stays absent, so the checker
        # reports the question as unanswered rather than clean.
        if "text" in item:
            obj["text"] = item["text"]
        fill = (item.get("style") or {}).get("fill_color")
        if fill:
            if _HEX_COLOR.match(str(fill)):
                obj["fill"] = str(fill)
            else:
                result.notes.append(
                    f"page read {kind} {label!r}: fill {fill!r} is not a "
                    f"#RRGGBB color, so it is not offered for the color "
                    f"comparison.")
        result.objects.append(obj)

    for connector in page_read["connectors"]:
        label = connector.get("ref") or f"id:{connector.get('shape_id', '?')}"
        begin = str(connector.get("from_ref") or "").strip()
        end = str(connector.get("to_ref") or "").strip()
        if not begin or not end:
            result.notes.append(
                f"page read connector {label!r}: not glued at "
                f"{'either end' if not begin and not end else 'one end'}, so "
                f"it joins nothing the comparison can name. A link in the "
                f"reading between those two things, if there is one, is "
                f"reported missing.")
            continue
        result.links.append({"from": ref_map.get(begin, begin),
                             "to": ref_map.get(end, end)})
    return result


def compare_page_read(reading: Mapping[str, Any],
                      page_read: Mapping[str, Any],
                      ref_map: Optional[Mapping[str, str]] = None
                      ) -> fidelity.FidelityReport:
    """Compare a page read against a reference reading.

    Same report, same rules and same precision as `fidelity.compare`; this only
    prepares the produced side. What the adapter set aside is appended to
    `report.not_run`, and the page-read facts the adapter introduced are under
    `report.metrics["page_read"]`.
    """
    prepared = to_fidelity_input(page_read, ref_map)
    report = fidelity.compare(reading, prepared.objects, prepared.links)
    report.not_run.extend(prepared.notes)
    report.metrics["page_read"] = {
        "objects_offered": len(prepared.objects),
        "links_offered": len(prepared.links),
        "y_shift": prepared.y_shift,
    }
    return report
