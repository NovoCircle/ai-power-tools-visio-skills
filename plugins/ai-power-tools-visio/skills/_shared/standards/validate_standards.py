#!/usr/bin/env python3
"""Validator for the house standards file (contract `apt-standards`, DRAFT 0.1).

A practice defines its look once - palette and meaning, lines, type, furniture,
Shape Data set, and its own diagram types - in one YAML file it edits. This
module is the schema for that file. It is a Python validator rather than a JSON
Schema because the checks that matter most here are not shape checks: a refusal
has to say WHY ("`kind` says which concept a thing is, and that belongs to the
notation standard"), unknown keys need did-you-mean hints, and a few rules cross
fields. The notation library's own loader works the same way, so the two read
alike.

The schema is DATA (the `SCHEMA` tree below). Three things are derived from it so
they cannot drift from the code: the validation itself, the key reference in the
README (`python validate_standards.py --reference`), and the list of fields that
depend on a schema that is not settled yet (`soft_fields()`).

Every path in a finding is also a valid per-diagram override path
(`paint.application.style.fill_color`): list items that carry an `id` or `name`
are addressed by it, not by position.

Usage:
    python validate_standards.py <file.yaml>        # validate, print findings
    python validate_standards.py --reference        # print the key reference
    python validate_standards.py --write-readme     # refresh the README's reference

Requires PyYAML. Files are read with a `safe_load` loader, always.
"""
from __future__ import annotations

import difflib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment guard
    raise ImportError(
        "validate_standards needs PyYAML. Install it with: pip install pyyaml") from exc

CONTRACT = "apt-standards"
#: A reader refuses a version it does not know rather than guessing.
KNOWN_VERSIONS = ("0.1",)

# --------------------------------------------------------------------------
# Vocabularies. Those marked soft in the schema depend on the notation library.
# --------------------------------------------------------------------------
PAGE_SIZES = ("Letter", "A4", "A3", "Tabloid", "custom")
ORIENTATIONS = ("portrait", "landscape")
UNITS = ("in", "mm", "pt")
LINE_PATTERNS = ("solid", "dash", "dot", "dash-dot", "none")
ARROWS = ("none", "filled-triangle", "open-arrow", "filled-diamond", "open-diamond", "circle")
TEXT_ALIGN = ("left", "center", "right")
ROUTES = ("straight", "orthogonal", "curved")
ANCHORS = ("top-left", "top-center", "top-right",
           "bottom-left", "bottom-center", "bottom-right")
SHAPE_DATA_TYPES = ("string", "number", "boolean", "date", "list", "currency")
GRAPHIC_TYPES = ("text", "icon", "bar", "color")
#: The grammar names the notation library's loader declares (hyphenated). The
#: contracts draft writes five of them with underscores; see README, soft list.
GRAMMARS = ("layered-bands", "lanes", "nested-grid", "radial", "two-column-cycle",
            "computed-geometry", "matrix", "radial-tree", "chevron-stack", "treemap",
            "graph", "ea-semantic")
#: The library's ten visual channels.
CHANNELS = ("fill", "border", "border_width", "line_color", "line_style",
            "font_color", "opacity", "icon", "size", "position")
#: Spacing keys, copied from the composition engine's spec (soft: unit and names).
SPACING_KEYS = ("item_gap_x", "item_gap_y", "item_gap_flow", "band_gap", "band_pad_x",
                "band_pad_y", "lane_gap", "lane_pad", "grid_pad", "label_height",
                "label_width", "wrap_width")

#: Keys that say what a concept IS. They belong to the notation standard, so a
#: house standard that carries one is refused, with the reason below - not just
#: reported as an unknown key.
NOTATION_OWNED: dict[str, str] = {
    "kind": "which concept a thing is",
    "kinds": "which concepts exist",
    "qualified_kind": "which concept a thing is",
    "concept": "which concepts exist",
    "concepts": "which concepts exist",
    "metaclass": "what base type a concept has",
    "base_type": "what base type a relationship has",
    "stereotype": "which concept a thing is",
    "stereotypes": "which concepts exist",
    "stereotype_prefix": "how a concept is named in the source",
    "retype": "which concept a thing is",
    "as_kind": "which concept a thing is",
    "maps_to": "which concept a thing is",
    "admits": "which concepts a notation diagram type admits",
    "allowed_ends": "which things a relationship may connect",
    "relationship_rules": "which things a relationship may connect",
}
_NOTATION_HINTS: dict[str, str] = {
    "kind": "To paint things of a kind, select them with `when.kinds`.",
    "kinds": "To paint things of a kind, select them with `when.kinds`.",
    "metaclass": "To select by base type, use `when.metaclasses`.",
    "admits": "A practice's own diagram type may list `admits` under `diagram_types`, "
              "and only a subset of what the diagram type it refines admits.",
}

_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_ROW_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_REF = re.compile(r"^\$([A-Za-z][A-Za-z0-9_-]*)$")
_ID_HINT = "Letters, digits, `_` and `-`; starts with a letter."


@dataclass(frozen=True)
class Finding:
    path: str
    code: str
    message: str
    severity: str = "error"

    def __str__(self) -> str:
        where = f"{self.path}: " if self.path else ""
        return f"{self.severity} [{self.code}] {where}{self.message}"


class StandardsError(ValueError):
    """The file is not a valid standards file. `.findings` holds every reason."""

    def __init__(self, findings: list[Finding]):
        self.findings = tuple(findings)
        super().__init__("; ".join(str(f) for f in findings if f.severity == "error")
                         or "invalid standards file")


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    #: (concrete path, depends-on note) for every soft field the document uses.
    soft_used: list[tuple[str, str]] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


class _Ctx:
    def __init__(self, colors: set[str]):
        self.report = Report()
        self.colors = colors

    def err(self, path: str, code: str, message: str) -> None:
        self.report.findings.append(Finding(path, code, message, "error"))

    def warn(self, path: str, code: str, message: str) -> None:
        self.report.findings.append(Finding(path, code, message, "warning"))


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _type_name(value: Any) -> str:
    return "null" if value is None else type(value).__name__


# --------------------------------------------------------------------------
# Schema nodes
# --------------------------------------------------------------------------
class Node:
    label = "value"

    def __init__(self, doc: str = "", soft: str | None = None):
        self.doc = doc
        #: None, or "<depends-on>: <what will need aligning>". `library:` means
        #: the notation library (APT-2026-0472); anything else names its own item.
        self.soft = soft

    def check(self, value: Any, path: str, ctx: _Ctx) -> None:  # pragma: no cover
        raise NotImplementedError


class Str(Node):
    label = "string"

    def __init__(self, doc="", soft=None, pattern: re.Pattern | None = None, hint: str = ""):
        super().__init__(doc, soft)
        self.pattern, self.hint = pattern, hint

    def check(self, value, path, ctx):
        if not isinstance(value, str) or not value.strip():
            ctx.err(path, "type", f"expected a non-empty string, got {value!r}"
                    + (" (quote it in YAML)" if isinstance(value, (int, float)) else ""))
        elif value.strip("\n") != value.strip():
            # A folded YAML block (`>`) legitimately ends with a newline.
            ctx.err(path, "format", f"has leading or trailing whitespace: {value!r}")
        elif self.pattern and not self.pattern.match(value):
            ctx.err(path, "format", f"{value!r} is not valid here. {self.hint}".strip())


class NullableStr(Str):
    label = "string or `~`"

    def check(self, value, path, ctx):
        if value is not None:
            super().check(value, path, ctx)


class Const(Node):
    label = "constant"

    def __init__(self, value: str, doc="", soft=None):
        super().__init__(doc, soft)
        self.value = value

    def check(self, value, path, ctx):
        if value != self.value:
            ctx.err(path, "wrong-contract", f"must be {self.value!r}, got {value!r}")


class Num(Node):
    label = "number"

    def __init__(self, doc="", soft=None, minimum: float = 0.0, exclusive: bool = True):
        super().__init__(doc, soft)
        self.minimum, self.exclusive = minimum, exclusive

    def check(self, value, path, ctx):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            ctx.err(path, "type", f"expected a number, got {value!r}")
        elif value < self.minimum or (self.exclusive and value == self.minimum):
            rel = "greater than" if self.exclusive else "at least"
            ctx.err(path, "range", f"must be {rel} {self.minimum:g}, got {value:g}")


class NumOr(Num):
    """A number, or one of a few named sizes (`auto`, `content`)."""

    def __init__(self, names: tuple[str, ...], doc="", soft=None):
        super().__init__(doc, soft)
        self.names = names
        self.label = "number or " + " / ".join(f"`{n}`" for n in names)

    def check(self, value, path, ctx):
        if isinstance(value, str):
            if value not in self.names:
                ctx.err(path, "enum", f"expected a number or one of {list(self.names)}, got {value!r}")
        else:
            super().check(value, path, ctx)


class Bool(Node):
    label = "boolean"

    def check(self, value, path, ctx):
        if not isinstance(value, bool):
            ctx.err(path, "type", f"expected true or false, got {value!r}")


class Enum(Node):
    def __init__(self, values: tuple[str, ...], doc="", soft=None):
        super().__init__(doc, soft)
        self.values = tuple(values)
        self.label = " / ".join(f"`{v}`" for v in self.values)

    def check(self, value, path, ctx):
        if not isinstance(value, str) or value not in self.values:
            near = difflib.get_close_matches(str(value), self.values, n=1)
            hint = f" Did you mean {near[0]!r}?" if near else ""
            ctx.err(path, "enum", f"{value!r} is not one of {list(self.values)}.{hint}")


class Color(Node):
    def __init__(self, doc="", soft=None, allow_ref: bool = True):
        super().__init__(doc, soft)
        self.allow_ref = allow_ref
        self.label = "color (`#RRGGBB` or `$name`)" if allow_ref else "color (`#RRGGBB`)"

    def check(self, value, path, ctx):
        if isinstance(value, str) and _HEX.match(value):
            return
        m = _REF.match(value) if isinstance(value, str) else None
        if m and self.allow_ref:
            if m.group(1) not in ctx.colors:
                near = difflib.get_close_matches(m.group(1), sorted(ctx.colors), n=1)
                hint = f" Did you mean ${near[0]}?" if near else ""
                ctx.err(path, "unknown-color-name",
                        f"{value!r} is not defined under `colors`.{hint}")
            return
        ctx.err(path, "format", "expected a color written #RRGGBB"
                + (" or a $name from `colors`" if self.allow_ref else "") + f", got {value!r}")


class Scalar(Node):
    label = "string, number or boolean"

    def check(self, value, path, ctx):
        if value is None or isinstance(value, (dict, list)):
            ctx.err(path, "type", f"expected a string, number or boolean, got {_type_name(value)}")


class ScalarOrList(Scalar):
    label = "scalar or list of scalars"

    def check(self, value, path, ctx):
        if isinstance(value, list):
            if not value:
                ctx.err(path, "empty", "a list of values must not be empty")
            for i, v in enumerate(value):
                super().check(v, f"{path}[{i}]", ctx)
        else:
            super().check(value, path, ctx)


class Map(Node):
    label = "mapping"

    def __init__(self, fields: Mapping[str, Node], required: tuple[str, ...] = (),
                 at_least_one: tuple[str, ...] = (), hints: Mapping[str, str] | None = None,
                 doc="", soft=None):
        super().__init__(doc, soft)
        self.fields = dict(fields)
        self.required = tuple(required)
        self.at_least_one = tuple(at_least_one)
        self.hints = dict(hints or {})

    def check(self, value, path, ctx):
        if not isinstance(value, dict):
            ctx.err(path, "type", f"expected a mapping, got {_type_name(value)}")
            return
        for key in value:
            if key not in self.fields:
                self._unknown(key, path, ctx)
        for req in self.required:
            if req not in value:
                ctx.err(_join(path, req), "required", "required key is missing")
        if self.at_least_one and not any(k in value for k in self.at_least_one):
            ctx.err(path, "required", f"needs at least one of: {', '.join(self.at_least_one)}")
        for key, node in self.fields.items():
            if key in value:
                sub = _join(path, key)
                if node.soft:
                    ctx.report.soft_used.append((sub, node.soft))
                node.check(value[key], sub, ctx)

    def _unknown(self, key: Any, path: str, ctx: _Ctx) -> None:
        here = _join(path, str(key))
        if key in NOTATION_OWNED:
            hint = self.hints.get(key) or _NOTATION_HINTS.get(key, "")
            ctx.err(here, "notation-owned",
                    f"`{key}` says {NOTATION_OWNED[key]}. That is owned by the notation "
                    f"standard and a house standard cannot set it. {hint}".strip())
            return
        if key in self.hints:
            ctx.err(here, "unknown-key", self.hints[key])
            return
        near = difflib.get_close_matches(str(key), list(self.fields), n=2)
        hint = (f" Did you mean {' or '.join(repr(n) for n in near)}?" if near
                else f" Known keys: {', '.join(self.fields)}.")
        ctx.err(here, "unknown-key", f"unknown key {key!r}.{hint}")


class Dict(Node):
    """A mapping of arbitrary keys to one kind of value."""
    label = "mapping"

    def __init__(self, value: Node, doc="", soft=None, key_pattern: re.Pattern | None = None,
                 key_hint: str = "", keys: tuple[str, ...] | None = None, min_items: int = 0):
        super().__init__(doc, soft)
        self.value, self.key_pattern, self.key_hint = value, key_pattern, key_hint
        self.keys, self.min_items = keys, min_items

    def check(self, value, path, ctx):
        if not isinstance(value, dict):
            ctx.err(path, "type", f"expected a mapping, got {_type_name(value)}")
            return
        if len(value) < self.min_items:
            ctx.err(path, "empty", "must not be empty")
        for key, sub in value.items():
            here = _join(path, str(key))
            if not isinstance(key, str) or not key.strip():
                ctx.err(here, "format", f"key {key!r} must be a non-empty string")
                continue
            if self.key_pattern and not self.key_pattern.match(key):
                ctx.err(here, "format", f"key {key!r} is not valid. {self.key_hint}".strip())
                continue
            if self.keys is not None and key not in self.keys:
                near = difflib.get_close_matches(key, self.keys, n=1)
                ctx.err(here, "unknown-key", f"unknown key {key!r}."
                        + (f" Did you mean {near[0]!r}?" if near else f" Known: {list(self.keys)}."))
                continue
            if self.value.soft:
                ctx.report.soft_used.append((here, self.value.soft))
            self.value.check(sub, here, ctx)


class List(Node):
    label = "list"

    def __init__(self, item: Node, doc="", soft=None, unique_by: str | None = None,
                 min_items: int = 0, unique: bool = False):
        super().__init__(doc, soft)
        self.item, self.unique_by, self.min_items, self.unique = item, unique_by, min_items, unique

    def check(self, value, path, ctx):
        if not isinstance(value, list):
            ctx.err(path, "type", f"expected a list, got {_type_name(value)}")
            return
        if len(value) < self.min_items:
            ctx.err(path, "empty", f"needs at least {self.min_items} item(s)")
        seen: set[Any] = set()
        for i, item in enumerate(value):
            sub = f"{path}[{i}]"
            if (self.unique_by and isinstance(item, dict)
                    and isinstance(item.get(self.unique_by), str) and item[self.unique_by].strip()):
                ident = item[self.unique_by]
                sub = _join(path, ident)
                if ident in seen:
                    ctx.err(sub, "duplicate-id", f"`{self.unique_by}` {ident!r} is used twice")
                seen.add(ident)
            elif self.unique and isinstance(item, str):
                if item in seen:
                    ctx.err(sub, "duplicate", f"{item!r} is listed twice")
                seen.add(item)
            if self.item.soft:
                ctx.report.soft_used.append((sub, self.item.soft))
            self.item.check(item, sub, ctx)


# --------------------------------------------------------------------------
# The schema
# --------------------------------------------------------------------------
_CLAIMED_ENUM = tuple(c for c in CHANNELS if c != "fill")

SHAPE_STYLE = ("fill_color", "line_color", "line_weight", "line_pattern", "rounding",
               "font_family", "font_size", "font_color", "bold", "italic", "text_align")
LINE_STYLE = ("line_color", "line_weight", "line_pattern", "begin_arrow", "end_arrow",
              "font_color", "bold", "italic")


def _style(allowed: tuple[str, ...], doc: str = "") -> Map:
    every: dict[str, Node] = {
        "fill_color": Color("Fill color of the shape."),
        "line_color": Color("Outline color of a shape, or the color of a connector."),
        "line_weight": Num("Line weight in points."),
        "line_pattern": Enum(LINE_PATTERNS, "Outline or connector pattern."),
        "rounding": Num("Corner rounding, in the file's `unit`.", minimum=0, exclusive=False),
        "font_family": Str("Font family for this element."),
        "font_size": Num("Font size in points."),
        "font_color": Color("Text color."),
        "bold": Bool("Bold text."),
        "italic": Bool("Italic text."),
        "text_align": Enum(TEXT_ALIGN, "Text alignment."),
        "begin_arrow": Enum(ARROWS, "Arrowhead at the source end."),
        "end_arrow": Enum(ARROWS, "Arrowhead at the target end."),
    }
    return Map({k: every[k] for k in allowed}, doc=doc)


def _selector(doc: str) -> Map:
    return Map({
        "kinds": List(Str(), unique=True, min_items=1,
                      soft="library: concept names - bare, qualified (`WBA::WBABusinessApplication`) "
                           "or as the notation writes them",
                      doc="Concept names to match, bare or qualified. A thing matches when its "
                          "`kind` or `qualified_kind` is listed."),
        "metaclasses": List(Str(), unique=True, min_items=1,
                            soft="library: where a concept's base type is recorded",
                            doc="Base types to match (`Component`, `Node`)."),
        "language": Str(soft="library: language ids", doc="Match only things of this language."),
        "properties": Dict(ScalarOrList(), min_items=1,
                           doc="Property name to a value, or a list of values (any of). "
                               "`external: true` selects things whose `external` property is true."),
    }, at_least_one=("kinds", "metaclasses", "language", "properties"), doc=doc)


def _position() -> Map:
    return Map({
        "anchor": Enum(ANCHORS, "Page corner or edge the item hangs from, inside the page margin."),
        "offset_x": Num("Distance inward from the anchor along the page's width, in `unit`.",
                        minimum=0, exclusive=False),
        "offset_y": Num("Distance inward from the anchor along the page's height, in `unit`.",
                        minimum=0, exclusive=False),
    }, required=("anchor",), doc="Where the item sits on the page.")


def _page(partial: bool) -> Map:
    return Map({
        "size": Enum(PAGE_SIZES, "Named page size, or `custom` with `width` and `height`."),
        "orientation": Enum(ORIENTATIONS, "Page orientation."),
        "width": Num("Page width in `unit`; with `height`, required when `size` is `custom`."),
        "height": Num("Page height in `unit`."),
        "margin": Num("Margin inside the page edge, in `unit`.", minimum=0, exclusive=False),
    }, required=() if partial else ("size", "orientation"),
        doc="Page changes for this diagram type." if partial else "Page size and orientation.")


def _furniture(partial: bool) -> Map:
    req = () if partial else ("enabled",)
    common: dict[str, Node] = {
        "enabled": Bool("Whether diagrams carry this item."),
        "position": _position(),
        "width": NumOr(("auto", "content"), "Width in `unit`; `content` spans the page inside "
                       "the margins, `auto` fits the text."),
        "height": NumOr(("auto",), "Height in `unit`, or `auto` to fit the text."),
        "style": _style(SHAPE_STYLE, "Paint for the item's frame and text."),
        "master": Map({"stencil": Str(doc="Stencil that holds the master."),
                       "name": Str(doc="Master name in that stencil.")}, required=("stencil", "name"),
                      soft="library: the Visio rendering section decides which masters draw furniture",
                      doc="Visio master that draws the item. Absent: the composition skill's default."),
    }

    def with_extra(extra: dict[str, Node], doc: str) -> Map:
        return Map({**common, **extra}, required=req, doc=doc)

    field_node = Map({
        "name": Str(pattern=_ID, hint=_ID_HINT, doc="Field id; how an override addresses the field."),
        "label": Str(doc="Label printed beside the value."),
        "source": Enum(("view.title", "view.revision", "view.description", "generated_at",
                        "constant"), "Where the value comes from."),
        "value": Str(doc="The value, when `source` is `constant` (an author role, never a person)."),
        "required": Bool("A diagram without this value fails verification."),
    }, required=("name", "label", "source"))
    legend_entry = Map({
        "label": Str(doc="Text beside the sample."),
        "swatch": Enum(("shape", "line"), "Draw a shape sample or a line sample."),
        "style": _style(SHAPE_STYLE + ("begin_arrow", "end_arrow"), "Paint of the sample."),
    }, required=("label", "swatch", "style"))
    return Map({
        "border": with_extra({"margin": Num("Gap between the page edge and the border, in `unit`.",
                                            minimum=0, exclusive=False)}, "Page border."),
        "title-block": with_extra({
            "format": Enum(("line", "table"), "One line of text, or a labeled table."),
            "separator": Str("Text between fields in `line` format."),
            "show_labels": Bool("Print each field's label in `line` format."),
            "fields": List(field_node, unique_by="name", min_items=1,
                           doc="Fields in order. The review board expects the revision and the "
                               "author role; list them here."),
        }, "Title block."),
        "legend": with_extra({
            "mode": Enum(("derived", "explicit"), "`derived`: built from the `legend` text of the "
                         "paint and line rules in use. `explicit`: the `entries` below."),
            "title": Str("Legend heading."),
            "only_used": Bool("Derived mode: list only rules that matched something on the page."),
            "entries": List(legend_entry, doc="Entries for `explicit` mode."),
        }, "Legend."),
        "note": with_extra({
            "title": Str("Panel heading."),
            "source": Enum(("view.description", "constant"), "Where the panel's text comes from."),
            "text": Str("Fixed text, when `source` is `constant`."),
        }, "Notes panel."),
        "logo": with_extra({
            "asset": Str("Image file, relative to the standards file."),
            "alt": Str("Alternative text for the image."),
        }, "Logo."),
    }, doc=("Furniture changes for this diagram type, merged over the file's `furniture`." if partial
            else "Page furniture. Keys are the render plan's `furniture_kind` values."))


def _diagram_type() -> Map:
    size = Map({"w": Num(doc="Width, in `unit`."), "h": Num(doc="Height, in `unit`.")},
               required=("w", "h"),
               hints={"width": "unknown key 'width'. Use `w`.", "height": "unknown key 'height'. Use `h`."})
    return Map({
        "display_name": Str("Name shown to people."),
        "description": Str("What the diagram is for."),
        "refines": Map({"language": Str(doc="Notation language id."),
                        "type": Str(doc="That language's diagram type name.")},
                       required=("language", "type"),
                       soft="library: language and diagram type ids",
                       doc="The notation's diagram type this one is drawn on. Sizing and spacing it "
                           "does not state are inherited. Absent: a type of the practice's own."),
        "admits": List(Str(), unique=True, min_items=1,
                       soft="library: concept names, and whether `admits` sits on the diagram type "
                            "or on a viewpoint",
                       doc="Concepts this diagram admits. When the type refines a notation type, "
                           "only a subset of what that type admits."),
        "grammar": Enum(GRAMMARS, soft="library: grammar vocabulary (hyphenated here; the contracts "
                        "draft writes underscores)", doc="Layout grammar."),
        "title": Enum(("drawn",), soft="library: the library also has `frame-header`, which has no "
                      "Visio meaning",
                      doc="Title convention. Visio has no diagram frame, so the title is drawn."),
        "sizing": Dict(size, min_items=1,
                       soft="library: integer EA pixels today; the declared unit is undecided",
                       doc="Concept name to `{w, h}` in `unit`. `default` is the fallback box."),
        "spacing": Map({**{k: Num(f"`{k}`, in `unit`.", minimum=0, exclusive=False)
                           for k in SPACING_KEYS},
                        "align": Enum(TEXT_ALIGN, "Alignment of items within a band or lane.")},
                       soft="library: key names (the composition engine's) and unit",
                       doc="Gaps and padding, in `unit`, named as the composition engine names them."),
        "routing": Map({
            "default": Enum(ROUTES, "Default connector route."),
            "trunk_for": List(Str(), unique=True, doc="Relationship kinds drawn as a shared trunk."),
            "trunk_route": Enum(ROUTES, "Route for a trunk."),
        }, required=("default",),
            soft="library: the library names EA's ten routes; Visio's are three",
            doc="Connector routing for this type."),
        "channels": Map({
            "fill": NullableStr("What fill means in this diagram type, or `~` if unclaimed."),
            "claimed": Dict(Str(), keys=_CLAIMED_ENUM,
                            doc="Channel to the meaning it already carries."),
            "free": List(Enum(CHANNELS), unique=True, doc="Channels a second variable may use."),
            "notes": Str("Free text."),
        }, required=("fill",),
            soft="library: channel names; the style-field to channel map is this draft's proposal",
            doc="Which visual channels this type already uses, as the library does."),
        "page": _page(partial=True),
        "furniture": _furniture(partial=True),
        "notes": Str("Free text."),
    }, required=("grammar", "title", "routing", "channels"),
        doc="A diagram type of the practice, in the library's form.")


def _build_schema() -> Map:
    paint_rule = Map({
        "id": Str(pattern=_ID, hint=_ID_HINT,
                  doc="Rule id; also how a per-diagram override addresses the rule."),
        "label": Str("Name of the category, for people."),
        "when": _selector("Which things this rule paints."),
        "style": _style(SHAPE_STYLE, "Paint applied to matching things."),
        "legend": Str("Text that explains this paint in the legend. A rule that sets a color or "
                      "pattern without it is an unexplained color."),
    }, required=("id", "when", "style"))
    line_rule = Map({
        "style": _style(LINE_STYLE, "Paint for connectors of this kind."),
        "legend": Str("Text that explains this line in the legend."),
    }, required=("style",))
    row = Map({
        "name": Str(pattern=_ROW_NAME, hint="Letters, digits and `_`.",
                    doc="Shape Data row name; letters, digits and `_`. `APT_` names are reserved."),
        "label": Str("Label in the Shape Data window."),
        "type": Enum(SHAPE_DATA_TYPES, "Row type. Absent: the content's declaration, else `string`."),
        "values": List(Scalar(), min_items=1, doc="Permitted choices; only for `type: list`."),
        "from_property": Str("Content property that supplies the value. Absent: the row's `name`."),
        "invisible": Bool("Hide the row from the Shape Data window."),
        "show_on_shape": Bool("Show the value on the shape as a data graphic."),
        "graphic": Map({
            "type": Enum(GRAPHIC_TYPES, "How the value is drawn."),
            "position": Enum(ANCHORS, "Where on the shape."),
        }, required=("type",),
            soft="data-graphics: how a shown row is drawn (text, icon, bar, color) until the "
                 "data graphics model is fixed",
            doc="How a shown value is drawn."),
    }, required=("name",))
    data_set = Map({
        "id": Str(pattern=_ID, hint=_ID_HINT, doc="Set id; also how an override addresses the set."),
        "target": Enum(("shape", "connector"), "What carries the rows. Absent: `shape`."),
        "when": _selector("Which things or relationships carry these rows."),
        "rows": List(row, min_items=1, doc="Rows in order. Names starting `APT_` are reserved."),
    }, required=("id", "when", "rows"))
    sizes = Map({k: Num(f"Font size in points for {what}.") for k, what in (
        ("shape_label", "shape labels"), ("connector_label", "connector labels"),
        ("title", "the title"), ("note", "notes"), ("legend", "the legend"))},
        required=("shape_label", "connector_label", "title", "note", "legend"),
        doc="Font sizes by role, in points.")
    return Map({
        "contract": Const(CONTRACT, "Contract name."),
        "contract_version": Enum(KNOWN_VERSIONS, "Contract version; quote it. A reader refuses a "
                                 "version it does not know."),
        "id": Str(pattern=_ID, hint=_ID_HINT, doc="Stable id of this standards definition."),
        "name": Str("Name of the definition, for people."),
        "owner": Str("The practice that owns the file."),
        "description": Str("What the standards are for."),
        "unit": Enum(UNITS, "Unit of every length in the file. Absent: `in`."),
        "colors": Dict(Color(allow_ref=False), key_pattern=_ID, key_hint=_ID_HINT,
                       doc="Named colors, used as `$name` elsewhere. Change one here, change it everywhere."),
        "type": Map({
            "font_family": Str("Font for every label."),
            "font_color": Color("Default text color."),
            "sizes": sizes,
        }, required=("font_family", "sizes"), doc="Type."),
        "page": _page(partial=False),
        "paint": List(paint_rule, unique_by="id",
                      doc="Palette and meaning. Every rule whose `when` matches a thing applies, in "
                          "order; later rules win per field. A thing's concept is never changed."),
        "lines": Map({
            "routing": Enum(ROUTES, soft="library: the notation's routing convention uses EA's "
                            "route names", doc="Routing preference, over the notation's default."),
            "default": _style(LINE_STYLE, "Paint for every connector."),
            "by_kind": Dict(line_rule, soft="library: relationship names",
                            doc="Relationship kind (bare or qualified) to line paint and legend."),
        }, doc="Lines."),
        "furniture": _furniture(partial=False),
        "shape_data": List(data_set, unique_by="id",
                           doc="Shape Data set: which rows a shape (or connector) of a kind carries, "
                               "and which are shown on it."),
        "diagram_types": Dict(_diagram_type(), doc="The practice's own diagram types, keyed by name.",
                              key_pattern=re.compile(r"^\S(.*\S)?$"),
                              key_hint="No leading or trailing whitespace."),
        "notes": Str("Free text."),
    }, required=("contract", "contract_version", "id", "name", "owner"),
        doc="The house standards file.")


SCHEMA = _build_schema()

#: Sections a per-diagram override may touch. Everything else is identity or the
#: practice's type definitions, which an override cannot change.
OVERRIDABLE_SECTIONS = ("colors", "type", "page", "paint", "lines", "furniture", "shape_data")


# --------------------------------------------------------------------------
# Walking the schema (documentation and the soft list are derived from it)
# --------------------------------------------------------------------------
def walk(node: Node = SCHEMA, pattern: str = "", required: bool = True
         ) -> Iterator[tuple[str, Node, bool]]:
    yield pattern, node, required
    if isinstance(node, Map):
        for key, child in node.fields.items():
            yield from walk(child, _join(pattern, key), key in node.required)
    elif isinstance(node, Dict):
        yield from walk(node.value, _join(pattern, "*"), False)
    elif isinstance(node, List):
        yield from walk(node.item, pattern + "[]", False)


def soft_fields() -> list[tuple[str, str, str]]:
    """Every field that depends on a schema not yet settled: (pattern, depends-on, note)."""
    out = []
    for pattern, node, _ in walk():
        if node.soft:
            depends, _, note = node.soft.partition(":")
            out.append((pattern, depends.strip(), note.strip()))
    return out


REFERENCE_START = "<!-- reference:start (generated: python validate_standards.py --write-readme) -->"
REFERENCE_END = "<!-- reference:end -->"
SOFT_START = "<!-- soft:start (generated: python validate_standards.py --write-readme) -->"
SOFT_END = "<!-- soft:end -->"


def reference_markdown() -> str:
    rows = ["| Path | Type | Required | Soft | Meaning |", "|---|---|---|---|---|"]
    for pattern, node, required in walk():
        if not pattern:
            continue
        soft = "soft" if node.soft else ""
        meaning = node.doc.replace("|", "\\|")
        rows.append(f"| `{pattern}` | {node.label} | {'yes' if required else ''} | {soft} | {meaning} |")
    return "\n".join(rows)


def soft_markdown() -> str:
    rows = ["| Field | Depends on | What will need aligning | Status |", "|---|---|---|---|"]
    for pattern, depends, note in soft_fields():
        item = "notation library (APT-2026-0472)" if depends == "library" else (
            "typed Shape Data and data graphics (APV-2026-0013)" if depends == "data-graphics" else depends)
        rows.append(f"| `{pattern}` | {item} | {note[:1].upper() + note[1:]} | open |")
    return "\n".join(rows)


def _replace_block(text: str, start: str, end: str, body: str) -> str | None:
    head, sep, rest = text.partition(start)
    if not sep:
        return None
    _, _, tail = rest.partition(end)
    return f"{head}{start}\n\n{body}\n\n{end}{tail}"


# --------------------------------------------------------------------------
# Loading and validating
# --------------------------------------------------------------------------
class _UniqueKeyLoader(yaml.SafeLoader):
    """`safe_load` that refuses a duplicate key instead of silently keeping the last."""


def _construct_unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False):
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"duplicate key {key!r}", key_node.start_mark)
            seen.add(key)
        except TypeError:
            pass
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
                                 _construct_unique_mapping)


def load_text(text: str, source: str = "<memory>") -> Any:
    """Parse YAML safely. A syntax error or a duplicate key raises StandardsError."""
    try:
        return yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506 - SafeLoader subclass
    except yaml.YAMLError as exc:
        raise StandardsError([Finding(source, "yaml", str(exc).replace("\n", " "))]) from exc


def load(path: str | Path) -> Any:
    p = Path(path)
    return load_text(p.read_text(encoding="utf-8"), p.name)


def validate(doc: Any) -> Report:
    """Validate a parsed standards document. Never raises on a bad document."""
    colors = (set(c for c in doc["colors"] if isinstance(c, str))
              if isinstance(doc, dict) and isinstance(doc.get("colors"), dict) else set())
    ctx = _Ctx(colors)
    if not isinstance(doc, dict):
        ctx.err("", "type", f"a standards file is a mapping, got {_type_name(doc)}")
        return ctx.report
    # The contract and its version come first: a document that is not this
    # contract at this version is not read further.
    if doc.get("contract") != CONTRACT:
        ctx.err("contract", "wrong-contract", f"must be {CONTRACT!r}, got {doc.get('contract')!r}")
        return ctx.report
    if doc.get("contract_version") not in KNOWN_VERSIONS:
        ctx.err("contract_version", "unknown-version",
                f"this reader knows {list(KNOWN_VERSIONS)}, got {doc.get('contract_version')!r}"
                + (" (quote the version in YAML)"
                   if isinstance(doc.get("contract_version"), (int, float)) else ""))
        return ctx.report
    SCHEMA.check(doc, "", ctx)
    _semantic(doc, ctx)
    return ctx.report


def check(doc: Any) -> Report:
    """Validate, raising StandardsError when there is any error."""
    report = validate(doc)
    if not report.ok:
        raise StandardsError(report.findings)
    return report


def _is_map(v: Any) -> bool:
    return isinstance(v, dict)


def _semantic(doc: dict, ctx: _Ctx) -> None:
    """Rules that cross fields. Each guards its inputs: the structural pass has
    already reported a wrong type, so a wrong type here is skipped, not repeated."""
    _page_rules(doc.get("page"), "page", ctx)

    paint = doc.get("paint") if isinstance(doc.get("paint"), list) else []
    for rule in paint:
        if _is_map(rule) and _is_map(rule.get("style")) and "legend" not in rule:
            if any(k in rule["style"] for k in ("fill_color", "line_color", "line_pattern", "font_color")):
                ctx.warn(_join("paint", str(rule.get("id", "?"))), "unexplained-color",
                         "sets a color or pattern but has no `legend`, so a reader cannot tell "
                         "what it means")
    lines = doc.get("lines")
    by_kind = lines.get("by_kind") if _is_map(lines) and _is_map(lines.get("by_kind")) else {}
    for kind, entry in by_kind.items():
        if _is_map(entry) and "legend" not in entry:
            ctx.warn(_join("lines.by_kind", str(kind)), "unexplained-line",
                     "has no `legend`, so a reader cannot tell what the line means")

    fur = doc.get("furniture")
    if _is_map(fur):
        _furniture_rules(fur, "furniture", ctx)
        legend = fur.get("legend")
        if _is_map(legend) and legend.get("enabled") and legend.get("mode", "derived") == "derived":
            has_text = (any(_is_map(r) and r.get("legend") for r in paint)
                        or any(_is_map(e) and e.get("legend") for e in by_kind.values()))
            if not has_text:
                ctx.warn("furniture.legend", "legend-will-be-empty",
                         "the legend is derived but no paint or line rule has `legend` text")

    for s in doc.get("shape_data") if isinstance(doc.get("shape_data"), list) else []:
        if not _is_map(s) or not isinstance(s.get("rows"), list):
            continue
        base = _join("shape_data", str(s.get("id", "?")))
        names: set[str] = set()
        for r in s["rows"]:
            if not _is_map(r) or not isinstance(r.get("name"), str):
                continue
            where = _join(base, f"rows.{r['name']}")
            if r["name"] in names:
                ctx.err(where, "duplicate-id", f"row name {r['name']!r} is used twice in this set")
            names.add(r["name"])
            if r["name"].upper().startswith("APT_"):
                ctx.err(where, "reserved-name",
                        "names starting `APT_` carry shape identity and are written by the "
                        "tool; a house standard cannot define them")
            if r.get("type") == "list" and "values" not in r:
                ctx.err(where, "required", "a `list` row needs `values`")
            if "values" in r and r.get("type") != "list":
                ctx.err(where, "conflict", "`values` is only for `type: list`")
            if "graphic" in r and not r.get("show_on_shape"):
                ctx.err(where, "conflict", "`graphic` needs `show_on_shape: true`")

    types = doc.get("diagram_types")
    if _is_map(types):
        for name, t in types.items():
            if not _is_map(t):
                continue
            here = _join("diagram_types", str(name))
            if "refines" not in t:
                sizing = t.get("sizing")
                if not _is_map(sizing) or "default" not in sizing:
                    ctx.err(_join(here, "sizing"), "required",
                            "a type that refines nothing needs `sizing` with a `default` box")
            _page_rules(t.get("page"), _join(here, "page"), ctx)
            if _is_map(t.get("furniture")):
                _furniture_rules(t["furniture"], _join(here, "furniture"), ctx)
            ch = t.get("channels")
            if _is_map(ch) and isinstance(ch.get("free"), list) and _is_map(ch.get("claimed") or {}):
                spoken = set(ch.get("claimed") or {}) | ({"fill"} if ch.get("fill") else set())
                clash = sorted(spoken & {x for x in ch["free"] if isinstance(x, str)})
                if clash:
                    ctx.err(_join(here, "channels.free"), "conflict",
                            f"{clash} are already claimed, so listing them as free says it is safe "
                            f"to overwrite their meaning")


def _page_rules(page: Any, where: str, ctx: _Ctx) -> None:
    if _is_map(page) and page.get("size") == "custom":
        for k in ("width", "height"):
            if k not in page:
                ctx.err(_join(where, k), "required", "`size: custom` needs `width` and `height`")


def _furniture_rules(fur: dict, where: str, ctx: _Ctx) -> None:
    tb = fur.get("title-block")
    if _is_map(tb) and isinstance(tb.get("fields"), list):
        for f in tb["fields"]:
            if not _is_map(f) or not isinstance(f.get("name"), str):
                continue
            here = _join(where, f"title-block.fields.{f['name']}")
            if f.get("source") == "constant" and "value" not in f:
                ctx.err(here, "required", "`source: constant` needs `value`")
            elif f.get("source") != "constant" and "value" in f:
                ctx.warn(here, "ignored", "`value` is only read when `source` is `constant`")
    lg = fur.get("legend")
    if _is_map(lg):
        if lg.get("mode") == "explicit" and not lg.get("entries"):
            ctx.err(_join(where, "legend.entries"), "required", "`mode: explicit` needs `entries`")
        if lg.get("mode", "derived") == "derived" and lg.get("entries"):
            ctx.warn(_join(where, "legend.entries"), "ignored",
                     "`entries` are only read in `explicit` mode")
    note = fur.get("note")
    if _is_map(note) and note.get("source") == "constant" and "text" not in note:
        ctx.err(_join(where, "note.text"), "required", "`source: constant` needs `text`")


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    if argv[:1] == ["--reference"]:
        print(reference_markdown())
        return 0
    if argv[:1] == ["--write-readme"]:
        readme = Path(__file__).with_name("README.md")
        text = readme.read_text(encoding="utf-8")
        for start, end, body in ((REFERENCE_START, REFERENCE_END, reference_markdown()),
                                 (SOFT_START, SOFT_END, soft_markdown())):
            text = _replace_block(text, start, end, body)
            if text is None:
                print(f"README.md has no marker {start!r}")
                return 1
        with readme.open("w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        print("README.md generated blocks refreshed")
        return 0
    if len(argv) != 1:
        print(__doc__)
        return 2
    try:
        report = validate(load(argv[0]))
    except StandardsError as exc:
        report = Report(list(exc.findings))
    for f in report.findings:
        print(f)
    print("OK" if report.ok else f"{len(report.errors)} error(s)")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
