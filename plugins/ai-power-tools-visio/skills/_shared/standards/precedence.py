#!/usr/bin/env python3
"""Precedence: the notation, the house standards and a per-diagram instruction.

Three layers, in this order, and the order is enforced by this module rather than
described in a document:

    notation      what a thing IS, and what a diagram type admits. Never overridden.
    standards     how it is PAINTED and FRAMED: color, lines, type, furniture, page,
                  Shape Data set. The customer's, from the standards file.
    per-diagram   an instruction for ONE diagram. Wins over the standards for that
                  diagram only, and is recorded as {path, value, reason}.

What each layer may decide:

    | Field                                          | Owner       |
    |------------------------------------------------|-------------|
    | a thing's kind, metaclass, qualified kind      | notation    |
    | what a notation diagram type admits            | notation    |
    | grammar, sizing, spacing of a notation type    | notation    |
    | fill, outline, font, line paint, arrowheads    | standards   |
    | routing preference                             | standards   |
    | page, furniture, Shape Data set                | standards   |
    | a practice's own diagram type                  | standards   |
    | any paint-or-frame field, for one diagram      | per-diagram |

A house standard that tries to decide a row owned by the notation is REFUSED, with
a reason, not quietly ignored: `resolve` raises `PrecedenceRefused` carrying every
finding. A per-diagram override that reaches outside paint and frame is refused the
same way. Nothing a refusal leaves behind is half applied.

The notation is passed in as a small view of the library (`Notation`). Its shape is
a draft: the notation library's schema is not settled, so `Notation.from_dict` is
the one place that will change when it lands.

Units. A notation's sizing and spacing are only inherited by a practice's own
diagram type when both are declared in the same unit; otherwise they are not
inherited and a warning says so. The library's unit conversion is not settled, and
guessing one would put boxes of the wrong size on the page.
"""
from __future__ import annotations

import copy
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_standards as vs  # noqa: E402
from validate_standards import Finding  # noqa: E402

LAYERS = ("notation", "standards", "per-diagram")

#: Style fields that carry a color and may be written `$name`.
_COLOR_FIELDS = ("fill_color", "line_color", "font_color")

#: Which visual channel a style field writes, for the notation's claimed channels.
#: A proposal of this draft (soft): the library names the channels, not the fields.
THING_CHANNEL = {"fill_color": "fill", "line_color": "border", "line_pattern": "border",
                 "line_weight": "border_width", "font_color": "font_color"}
CONNECTOR_CHANNEL = {"line_color": "line_color", "line_pattern": "line_style",
                     "line_weight": "line_style", "font_color": "font_color"}

DEFAULT_OVERRIDE_REASON = "per-diagram instruction"


class PrecedenceRefused(ValueError):
    """The standards file or an override tried to decide something it does not own."""

    def __init__(self, findings: Iterable[Finding]):
        self.findings = tuple(findings)
        super().__init__("; ".join(str(f) for f in self.findings))

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(f.code for f in self.findings)


# --------------------------------------------------------------------------
# The notation, as this module needs to see it
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Concept:
    kind: str
    language: str
    category: str                      # "thing" or "relationship"
    metaclass: str | None = None
    qualified_kind: str | None = None


@dataclass(frozen=True)
class NotationDiagramType:
    name: str
    language: str
    admits: tuple[str, ...] | None     # None: the notation states no restriction
    conventions: Mapping[str, Any]     # grammar, title, sizing, spacing, routing, channels, unit


class Notation:
    """One language of the notation library, reduced to what precedence needs.

    Soft: the library schema is not settled. Expected shape of `from_dict`:

        language: WestbrookBankArchitecture
        concepts:
          WBABusinessApplication: {category: thing, metaclass: Component,
                                   qualified_kind: "WBA::WBABusinessApplication"}
        diagram_types:
          WBAApplicationView:
            admits: [WBABusinessApplication, ...]
            conventions: {unit: in, grammar: layered-bands, title: drawn, sizing: {...},
                          spacing: {...}, routing: {default: orthogonal}, channels: {fill: ~}}
        defaults:                      # the tool's rendering defaults, the bottom layer
          style: {font_family: Calibri}
          shape_data: {WBABusinessApplication: [{name: criticality, label: Criticality}]}
    """

    def __init__(self, language: str, concepts: Mapping[str, Concept],
                 diagram_types: Mapping[str, NotationDiagramType],
                 default_style: Mapping[str, Any] | None = None,
                 default_shape_data: Mapping[str, Sequence[Mapping[str, Any]]] | None = None):
        self.language = language
        self.concepts = dict(concepts)
        self.diagram_types = dict(diagram_types)
        self.default_style = dict(default_style or {})
        self.default_shape_data = {k: [dict(r) for r in v]
                                   for k, v in (default_shape_data or {}).items()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Notation":
        language = data.get("language")
        if not isinstance(language, str) or not language:
            raise ValueError("notation: `language` is required")
        concepts: dict[str, Concept] = {}
        for kind, body in (data.get("concepts") or {}).items():
            body = body or {}
            if body.get("category") not in ("thing", "relationship"):
                raise ValueError(f"notation.concepts.{kind}.category must be thing or relationship")
            concepts[kind] = Concept(kind, language, body["category"], body.get("metaclass"),
                                     body.get("qualified_kind"))
        types: dict[str, NotationDiagramType] = {}
        for name, body in (data.get("diagram_types") or {}).items():
            body = body or {}
            admits = body.get("admits")
            unknown = [a for a in admits or [] if a not in concepts]
            if unknown:
                raise ValueError(f"notation.diagram_types.{name}.admits names unknown concepts: {unknown}")
            types[name] = NotationDiagramType(name, language, tuple(admits) if admits is not None else None,
                                              dict(body.get("conventions") or {}))
        defaults = data.get("defaults") or {}
        return cls(language, concepts, types, defaults.get("style"), defaults.get("shape_data"))


def _as_notations(notations: Notation | Mapping[str, Notation] | Iterable[Notation] | None) -> dict[str, Notation]:
    if notations is None:
        return {}
    if isinstance(notations, Notation):
        return {notations.language: notations}
    if isinstance(notations, Mapping):
        return dict(notations)
    return {n.language: n for n in notations}


# --------------------------------------------------------------------------
# Checks of a standards file against the notation
# --------------------------------------------------------------------------
def _find_concept(notations: Mapping[str, Notation], name: str,
                  language: str | None = None) -> Concept | None:
    for lang, n in notations.items():
        if language and lang != language:
            continue
        if name in n.concepts:
            return n.concepts[name]
        for c in n.concepts.values():
            if c.qualified_kind == name:
                return c
    return None


def check_against_notation(doc: Mapping[str, Any], notations: Mapping[str, Notation]) -> list[Finding]:
    """What a validated standards document may not do to the notation.

    Errors are refusals. Warnings (a selector that names a kind no notation has)
    do not stop anything: painting nothing is harmless, but it is worth saying.
    """
    out: list[Finding] = []
    types = doc.get("diagram_types") or {}
    all_notation_types = {t for n in notations.values() for t in n.diagram_types}
    for name, t in types.items():
        here = f"diagram_types.{name}"
        if name in all_notation_types:
            out.append(Finding(here, "redefines-notation-type",
                               f"{name!r} is a diagram type of the notation. A house standard cannot "
                               f"redefine it. Give the practice's type its own name and set "
                               f"`refines` to draw it on {name!r}."))
            continue
        base: NotationDiagramType | None = None
        language = None
        ref = t.get("refines")
        if ref:
            language = ref["language"]
            n = notations.get(language)
            if n is None:
                out.append(Finding(f"{here}.refines.language", "unknown-language",
                                   f"no notation named {language!r} is loaded"))
                continue
            base = n.diagram_types.get(ref["type"])
            if base is None:
                out.append(Finding(f"{here}.refines.type", "unknown-diagram-type",
                                   f"{language!r} has no diagram type {ref['type']!r}; it has "
                                   f"{sorted(n.diagram_types)}"))
                continue
        for kind in t.get("admits") or []:
            concept = _find_concept(notations, kind, language)
            if concept is None:
                out.append(Finding(f"{here}.admits", "unknown-concept",
                                   f"{kind!r} is not a concept of "
                                   f"{language or 'any loaded notation'}. A house standard cannot "
                                   f"introduce a concept."))
            elif base is not None and base.admits is not None and concept.kind not in base.admits:
                out.append(Finding(f"{here}.admits", "admits-widened",
                                   f"{base.name!r} does not admit {kind!r}. A practice's type may "
                                   f"admit a subset of what the type it refines admits, never more."))

    def warn_unknown(kinds: Iterable[str], where: str) -> None:
        if not notations:
            return
        for k in kinds:
            if _find_concept(notations, k) is None:
                out.append(Finding(where, "unknown-kind",
                                   f"{k!r} is not a concept of any loaded notation, so this selects "
                                   f"nothing", "warning"))

    for rule in doc.get("paint") or []:
        warn_unknown((rule.get("when") or {}).get("kinds") or [], f"paint.{rule['id']}.when.kinds")
    for kind in (doc.get("lines") or {}).get("by_kind") or {}:
        warn_unknown([kind], f"lines.by_kind.{kind}")
    for s in doc.get("shape_data") or []:
        warn_unknown((s.get("when") or {}).get("kinds") or [], f"shape_data.{s['id']}.when.kinds")
    return out


# --------------------------------------------------------------------------
# Per-diagram overrides
# --------------------------------------------------------------------------
def _normalize_overrides(overrides: Any) -> list[dict[str, Any]]:
    if overrides is None or overrides == {} or overrides == []:
        return []
    if isinstance(overrides, Mapping):          # {path: value}
        return [{"path": p, "value": v, "reason": DEFAULT_OVERRIDE_REASON} for p, v in overrides.items()]
    out = []
    for o in overrides:
        if not isinstance(o, Mapping) or "path" not in o or "value" not in o:
            raise PrecedenceRefused([Finding("overrides", "override-invalid",
                                             f"an override is {{path, value, reason}}; got {o!r}")])
        out.append({"path": o["path"], "value": o["value"],
                    "reason": o.get("reason") or DEFAULT_OVERRIDE_REASON})
    return out


def _step(cur: Any, seg: str) -> Any:
    """One path segment: a mapping key, or a list item addressed by its `id` or `name`."""
    if isinstance(cur, dict):
        return cur[seg] if seg in cur else _MISSING
    if isinstance(cur, list):
        for item in cur:
            if isinstance(item, dict) and seg in (item.get("id"), item.get("name")):
                return item
    return _MISSING


_MISSING = object()


def apply_overrides(doc: Mapping[str, Any], overrides: Any) -> tuple[dict, list[dict[str, Any]]]:
    """Apply per-diagram overrides to a COPY of the standards. Returns (copy, recorded).

    `recorded` is the list the render plan's `provenance.overrides` carries:
    `{path, value, reason}` per override, in the order given. The input document
    is never changed, so the next diagram starts from the standards again.
    """
    items = _normalize_overrides(overrides)
    effective = copy.deepcopy(dict(doc))
    findings: list[Finding] = []
    seen: set[str] = set()
    for o in items:
        path = o["path"]
        if not isinstance(path, str) or not path.strip():
            findings.append(Finding("overrides", "override-invalid", f"path must be a non-empty string, got {path!r}"))
            continue
        if path in seen:
            findings.append(Finding(path, "override-duplicate-path",
                                    "this path is overridden twice; give one instruction per path"))
            continue
        seen.add(path)
        segs = path.split(".")
        if segs[0] not in vs.OVERRIDABLE_SECTIONS:
            findings.append(Finding(path, "override-outside-paint-and-frame",
                                    f"a per-diagram instruction changes paint and frame only "
                                    f"({', '.join(vs.OVERRIDABLE_SECTIONS)}). {segs[0]!r} is "
                                    + ("a diagram type's definition, which belongs to the standards file."
                                       if segs[0] == "diagram_types" else
                                       "identity of the standards file or of the notation.")))
            continue
        cur: Any = effective
        for seg in segs[:-1]:
            cur = _step(cur, seg)
            if cur is _MISSING:
                break
        if cur is _MISSING or not isinstance(cur, (dict, list)):
            findings.append(Finding(path, "override-path-not-found",
                                    "no such place in the standards. Paths are the ones the validator "
                                    "prints; list items are addressed by their `id` or `name`."))
            continue
        last = segs[-1]
        if isinstance(cur, dict):
            cur[last] = copy.deepcopy(o["value"])
        else:
            target = _step(cur, last)
            if target is _MISSING:
                findings.append(Finding(path, "override-path-not-found", f"no list item {last!r}"))
                continue
            cur[cur.index(target)] = copy.deepcopy(o["value"])
    if findings:
        raise PrecedenceRefused(findings)
    if items:
        report = vs.validate(effective)
        if not report.ok:
            raise PrecedenceRefused(
                Finding(f.path, "notation-owned" if f.code == "notation-owned" else "override-invalid",
                        f.message if f.code == "notation-owned" else f"{f.code}: {f.message}")
                for f in report.errors)
    recorded = [{"path": o["path"], "value": copy.deepcopy(o["value"]), "reason": o["reason"]}
                for o in items]
    return effective, recorded


# --------------------------------------------------------------------------
# The resolved result
# --------------------------------------------------------------------------
class ResolvedDiagramType:
    """A diagram type with its conventions merged. Plain data, read-only by convention."""

    def __init__(self, name: str, owner: str, language: str | None, refines: Mapping[str, str] | None,
                 admits: tuple[str, ...] | None, conventions: Mapping[str, Any],
                 routing_source: str):
        self.name, self.owner, self.language, self.refines = name, owner, language, refines
        self.admits = admits
        self.grammar = conventions.get("grammar")
        self.title = conventions.get("title")
        self.sizing = dict(conventions.get("sizing") or {})
        self.spacing = dict(conventions.get("spacing") or {})
        self.routing = dict(conventions.get("routing") or {})
        self.channels = dict(conventions.get("channels") or {})
        self.unit = conventions.get("unit")
        self.routing_source = routing_source


class Resolved:
    """The standards as they apply to one diagram. Build with `resolve`."""

    def __init__(self, doc: dict, base_doc: Mapping[str, Any], notations: dict[str, Notation],
                 overrides: list[dict[str, Any]], findings: list[Finding], ref: str,
                 diagram_type: ResolvedDiagramType | None, page: dict, furniture: dict):
        self.doc = doc
        self._base_doc = base_doc
        self.notations = notations
        self.overrides = overrides
        self.findings = tuple(findings)
        self.standards_ref = ref
        self.diagram_type = diagram_type
        self.page = page
        self.furniture = furniture
        self._override_paths = {o["path"] for o in overrides}

    # ---- identity: always the notation's ---------------------------------
    def concept(self, kind: str, language: str | None = None) -> Concept | None:
        """What a kind IS. Read from the notation; no standards or override reaches it."""
        return _find_concept(self.notations, kind, language)

    # ---- provenance ------------------------------------------------------
    def provenance(self) -> dict[str, Any]:
        """The render plan's `provenance.standards_ref` and `provenance.overrides`."""
        return {"standards_ref": self.standards_ref,
                "overrides": [dict(o) for o in self.overrides]}

    @property
    def unit(self) -> str:
        return self.doc.get("unit", "in")

    @property
    def routing(self) -> dict[str, Any]:
        """Effective routing: the practice type's, else the standards', else the notation's."""
        dt = self.diagram_type
        if dt and dt.routing_source == "practice-type":
            return {**dt.routing, "source": "practice-type"}
        pref = (self.doc.get("lines") or {}).get("routing")
        if pref:
            return {**(dt.routing if dt else {}), "default": pref, "source": "standards"}
        if dt and dt.routing:
            return {**dt.routing, "source": "notation"}
        return {}

    # ---- styles ----------------------------------------------------------
    def _color(self, value: Any) -> Any:
        if isinstance(value, str) and value.startswith("$"):
            return self.doc["colors"][value[1:]]
        return value

    def _finish(self, style: dict[str, Any]) -> dict[str, Any]:
        return {k: (self._color(v) if k in _COLOR_FIELDS else v) for k, v in style.items()}

    def _layer(self, path: str) -> str:
        return "per-diagram" if path in self._override_paths else "standards"

    def thing_style_trace(self, thing: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
        """(style, trace). `trace` says, per field, which layer and path decided it."""
        style: dict[str, Any] = {}
        trace: dict[str, dict[str, str]] = {}

        def put(layer: str, path: str, values: Mapping[str, Any]) -> None:
            for k, v in values.items():
                style[k] = v
                trace[k] = {"layer": layer, "path": f"{path}.{k}" if path else k}

        for n in self.notations.values():
            put("notation", "defaults.style", n.default_style)
        t = self.doc.get("type") or {}
        for f, p in (("font_family", "type.font_family"), ("font_color", "type.font_color")):
            if f in t:
                style[f] = t[f]
                trace[f] = {"layer": self._layer(p), "path": p}
        if "sizes" in t:
            p = "type.sizes.shape_label"
            style["font_size"] = t["sizes"]["shape_label"]
            trace["font_size"] = {"layer": self._layer(p), "path": p}
        for rule in self.doc.get("paint") or []:
            if self._matches(rule["when"], thing):
                for k, v in rule["style"].items():
                    p = f"paint.{rule['id']}.style.{k}"
                    style[k] = v
                    trace[k] = {"layer": self._layer(p), "path": p}
        return self._finish(style), trace

    def thing_style(self, thing: Mapping[str, Any]) -> dict[str, Any]:
        """The render plan's `style` for a thing (contract 3.8), colors resolved to #RRGGBB."""
        return self.thing_style_trace(thing)[0]

    def connector_style(self, relationship: Mapping[str, Any]) -> dict[str, Any]:
        """The render plan's `style` for a connector."""
        style: dict[str, Any] = {}
        t = self.doc.get("type") or {}
        if "font_family" in t:
            style["font_family"] = t["font_family"]
        if "sizes" in t:
            style["font_size"] = t["sizes"]["connector_label"]
        lines = self.doc.get("lines") or {}
        style.update(lines.get("default") or {})
        names = {relationship.get("kind"), relationship.get("qualified_kind")}
        concept = self.concept(relationship.get("qualified_kind") or relationship.get("kind") or "")
        if concept and concept.qualified_kind:
            names.add(concept.qualified_kind)
        for kind, entry in (lines.get("by_kind") or {}).items():
            if kind in names:
                style.update(entry["style"])
        return self._finish(style)

    # ---- selectors -------------------------------------------------------
    def _attrs(self, item: Mapping[str, Any]) -> dict[str, Any]:
        kind = item.get("kind")
        concept = self.concept(item.get("qualified_kind") or kind or "", item.get("language"))
        names = {n for n in (kind, item.get("qualified_kind")) if n}
        if concept and concept.qualified_kind:
            names.add(concept.qualified_kind)
        return {"names": names,
                "metaclass": item.get("metaclass") or (concept.metaclass if concept else None),
                "language": item.get("language") or (concept.language if concept else None),
                "properties": item.get("properties") or {}}

    def _matches(self, when: Mapping[str, Any], item: Mapping[str, Any]) -> bool:
        a = self._attrs(item)
        if "kinds" in when and not (set(when["kinds"]) & a["names"]):
            return False
        if "metaclasses" in when and a["metaclass"] not in when["metaclasses"]:
            return False
        if "language" in when and a["language"] != when["language"]:
            return False
        for name, expected in (when.get("properties") or {}).items():
            wanted = expected if isinstance(expected, list) else [expected]
            if name not in a["properties"] or a["properties"][name] not in wanted:
                return False
        return True

    def matches(self, when: Mapping[str, Any], item: Mapping[str, Any]) -> bool:
        """Whether a selector (`when`) selects a thing or relationship."""
        return self._matches(when, item)

    # ---- Shape Data ------------------------------------------------------
    def shape_data_rows(self, item: Mapping[str, Any], target: str = "shape") -> list[dict[str, Any]]:
        """The Shape Data rows an item carries: the tool's defaults, then the standards' sets.

        A standards row with the same `name` as a default replaces it in place; a
        new name is appended. Row names starting `APT_` are never produced here.
        """
        rows: dict[str, dict[str, Any]] = {}
        concept = self.concept(item.get("qualified_kind") or item.get("kind") or "")
        if concept:
            for n in self.notations.values():
                for r in n.default_shape_data.get(concept.kind, []):
                    rows[r["name"]] = {**r, "layer": "notation"}
        for s in self.doc.get("shape_data") or []:
            if s.get("target", "shape") == target and self._matches(s["when"], item):
                for r in s["rows"]:
                    rows[r["name"]] = {**r, "layer": "standards", "set": s["id"]}
        out = []
        for r in rows.values():
            r = dict(r)
            r.setdefault("from_property", r["name"])
            r.setdefault("invisible", False)
            r.setdefault("show_on_shape", False)
            out.append(r)
        return out

    # ---- furniture -------------------------------------------------------
    def legend_entries(self, things: Sequence[Mapping[str, Any]],
                       relationships: Sequence[Mapping[str, Any]] = ()) -> list[dict[str, Any]]:
        """What the legend explains on a diagram that draws these things and relationships."""
        legend = self.furniture.get("legend")
        if not legend or not legend.get("enabled"):
            return []
        if legend.get("mode", "derived") == "explicit":
            return [{"source": f"furniture.legend.entries[{i}]", "label": e["label"],
                     "swatch": e["swatch"], "style": self._finish(e["style"])}
                    for i, e in enumerate(legend.get("entries") or [])]
        only_used = legend.get("only_used", True)
        out: list[dict[str, Any]] = []
        for rule in self.doc.get("paint") or []:
            if not rule.get("legend"):
                continue
            if only_used and not any(self._matches(rule["when"], t) for t in things):
                continue
            keep = {k: v for k, v in rule["style"].items()
                    if k in ("fill_color", "line_color", "line_weight", "line_pattern")}
            out.append({"source": f"paint.{rule['id']}", "label": rule["legend"],
                        "swatch": "shape", "style": self._finish(keep)})
        for kind, entry in ((self.doc.get("lines") or {}).get("by_kind") or {}).items():
            if not entry.get("legend"):
                continue
            used = any(kind in {r.get("kind"), r.get("qualified_kind")} for r in relationships)
            if only_used and not used:
                continue
            style = {**((self.doc.get("lines") or {}).get("default") or {}), **entry["style"]}
            out.append({"source": f"lines.by_kind.{kind}", "label": entry["legend"],
                        "swatch": "line", "style": self._finish(style)})
        return out

    def title_block_values(self, view: Mapping[str, Any], generated_at: str | None = None
                           ) -> tuple[list[dict[str, Any]], list[Finding]]:
        """Values for the title block's fields, and a finding for each required one missing."""
        tb = self.furniture.get("title-block")
        if not tb or not tb.get("enabled"):
            return [], []
        values, findings = [], []
        for f in tb.get("fields") or []:
            src = f["source"]
            value = {"view.title": view.get("title") or view.get("name"),
                     "view.revision": view.get("revision"),
                     "view.description": view.get("description"),
                     "generated_at": generated_at,
                     "constant": f.get("value")}[src]
            if value is None or value == "":
                if f.get("required"):
                    findings.append(Finding(f"furniture.title-block.fields.{f['name']}",
                                            "title-block-missing-value",
                                            f"the title block needs {f['label']!r} ({src}) and the view "
                                            f"has none"))
                continue
            values.append({"name": f["name"], "label": f["label"], "value": value})
        return values, findings


# --------------------------------------------------------------------------
# resolve
# --------------------------------------------------------------------------
def _merge(base: Mapping[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(dict(base))
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, Mapping) and isinstance(out.get(k), Mapping) \
            else copy.deepcopy(v)
    return out


def _channel_warnings(doc: Mapping[str, Any], base: NotationDiagramType | None,
                      type_name: str) -> list[Finding]:
    """Paint that lands on a channel the notation already uses for something else."""
    if base is None:
        return []
    ch = base.conventions.get("channels") or {}
    claimed = dict(ch.get("claimed") or {})
    if ch.get("fill"):
        claimed["fill"] = ch["fill"]
    out: list[Finding] = []

    def scan(style: Mapping[str, Any], mapping: Mapping[str, str], path: str) -> None:
        for field_name in style:
            channel = mapping.get(field_name)
            if channel in claimed:
                out.append(Finding(f"{path}.{field_name}", "channel-claimed",
                                   f"{channel} is already used by {type_name!r} to mean: "
                                   f"{claimed[channel]}. The standards paint it anyway; a reader "
                                   f"may misread the diagram.", "warning"))

    for rule in doc.get("paint") or []:
        scan(rule["style"], THING_CHANNEL, f"paint.{rule['id']}.style")
    lines = doc.get("lines") or {}
    scan(lines.get("default") or {}, CONNECTOR_CHANNEL, "lines.default")
    for kind, entry in (lines.get("by_kind") or {}).items():
        scan(entry["style"], CONNECTOR_CHANNEL, f"lines.by_kind.{kind}.style")
    return out


def _resolve_diagram_type(doc: Mapping[str, Any], notations: Mapping[str, Notation], name: str
                          ) -> tuple[ResolvedDiagramType, NotationDiagramType | None, list[Finding]]:
    findings: list[Finding] = []
    practice = (doc.get("diagram_types") or {}).get(name)
    if practice is not None:
        ref = practice.get("refines")
        base = notations[ref["language"]].diagram_types[ref["type"]] if ref else None
        conv: dict[str, Any] = {}
        if base is not None:
            conv = copy.deepcopy(dict(base.conventions))
            base_unit = conv.get("unit")
            if base_unit is not None and base_unit != doc.get("unit", "in"):
                findings.append(Finding(f"diagram_types.{name}", "unit-not-converted",
                                        f"{ref['type']!r} is declared in {base_unit!r} and the standards "
                                        f"in {doc.get('unit', 'in')!r}; its sizing and spacing are not "
                                        f"inherited until the library states the conversion", "warning"))
                conv["sizing"], conv["spacing"] = {}, {}
        for key in ("grammar", "title", "routing", "channels"):
            conv[key] = copy.deepcopy(practice[key])
        conv["sizing"] = _merge(conv.get("sizing") or {}, practice.get("sizing") or {})
        conv["spacing"] = _merge(conv.get("spacing") or {}, practice.get("spacing") or {})
        conv["unit"] = doc.get("unit", "in")
        admits = tuple(practice["admits"]) if practice.get("admits") else (base.admits if base else None)
        return (ResolvedDiagramType(name, "practice", ref["language"] if ref else None, ref, admits,
                                    conv, "practice-type"), base, findings)
    for n in notations.values():
        if name in n.diagram_types:
            nt = n.diagram_types[name]
            return (ResolvedDiagramType(name, "notation", n.language, None, nt.admits,
                                        nt.conventions, "notation"), nt, findings)
    raise PrecedenceRefused([Finding("diagram_type", "unknown-diagram-type",
                                     f"{name!r} is neither a diagram type of a loaded notation nor "
                                     f"one of the standards' own")])


def resolve(standards: Mapping[str, Any],
            notations: Notation | Mapping[str, Notation] | Iterable[Notation] | None,
            *, diagram_type: str | None = None, overrides: Any = None,
            ref: str | None = None) -> Resolved:
    """Merge notation, standards and per-diagram overrides for one diagram.

    `standards` is a parsed standards document; `notations` the languages in play;
    `diagram_type` the type being drawn (the notation's or the practice's own);
    `overrides` a list of `{path, value, reason}` for this diagram only; `ref` the
    name to record as `provenance.standards_ref` (default: the standards' `id`).

    Raises `PrecedenceRefused` when the standards file is invalid, tries to decide
    something the notation owns, or an override reaches outside paint and frame.
    """
    notes = _as_notations(notations)
    report = vs.validate(standards)
    if not report.ok:
        raise PrecedenceRefused(report.errors)
    findings: list[Finding] = list(report.warnings)

    against = check_against_notation(standards, notes)
    refusals = [f for f in against if f.severity == "error"]
    if refusals:
        raise PrecedenceRefused(refusals)
    findings += [f for f in against if f.severity == "warning"]

    effective, recorded = apply_overrides(standards, overrides)
    # An override can change a selector or add an admits-like field: check again.
    if recorded:
        again = [f for f in check_against_notation(effective, notes) if f.severity == "error"]
        if again:
            raise PrecedenceRefused(again)

    rdt: ResolvedDiagramType | None = None
    page = copy.deepcopy(effective.get("page") or {})
    furniture = copy.deepcopy(effective.get("furniture") or {})
    if diagram_type is not None:
        rdt, base, more = _resolve_diagram_type(effective, notes, diagram_type)
        findings += more
        findings += _channel_warnings(effective, base, base.name if base else diagram_type)
        practice = (effective.get("diagram_types") or {}).get(diagram_type)
        if practice:
            page = _merge(page, practice.get("page") or {})
            furniture = _merge(furniture, practice.get("furniture") or {})
    return Resolved(effective, standards, notes, recorded, findings,
                    ref or effective.get("id", ""), rdt, page, furniture)
