"""Precedence tests: notation, standards, per-diagram override.

The notation below is a HAND-WRITTEN STUB. The notation library's schema is not
settled, so there is no library entry to capture; the values are the Westbrook
canon's (stereotypes, base types, qualified names) and the conventions are
placeholders that make the merge testable. When the library lands, this stub is
replaced by a loader over a real entry (see the README's change list).

Run from the repository root:  python -m pytest plugins -q
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

import precedence as pr
import validate_standards as vs

HERE = Path(__file__).resolve().parent
LANG = "WestbrookBankArchitecture"

_ELEMENTS = {
    "WBABusinessApplication": "Component", "WBABusinessService": "Component",
    "WBAVendorSystem": "Component", "WBARegulatedFunction": "Component",
    "WBASystemOfRecord": "Component", "WBAAIGateway": "Component", "WBAAIService": "Component",
    "WBAAIModel": "Class", "WBADataAsset": "Class", "WBADataEntity": "Class",
    "WBAGovernedElement": "Class", "WBARegulatedActivity": "Activity",
    "WBACustomerTouchpoint": "Activity", "WBAExternalCall": "Activity", "WBATechnologyNode": "Node",
}
_CONNECTORS = {"Uses": "Association", "Flows": "InformationFlow", "realizes": "Realisation"}

STUB = {
    "language": LANG,
    "concepts": {
        **{k: {"category": "thing", "metaclass": m, "qualified_kind": f"WBA::{k}"}
           for k, m in _ELEMENTS.items()},
        **{k: {"category": "relationship", "metaclass": m} for k, m in _CONNECTORS.items()},
    },
    "diagram_types": {
        "WBAApplicationView": {
            "admits": ["WBABusinessApplication", "WBABusinessService", "WBAVendorSystem",
                       "WBASystemOfRecord", "WBAAIGateway", "WBAAIService", "WBATechnologyNode"],
            "conventions": {
                "unit": "in", "grammar": "layered-bands", "title": "drawn",
                "sizing": {"default": {"w": 1.5, "h": 0.8}, "WBAVendorSystem": {"w": 1.5, "h": 0.6}},
                "spacing": {"item_gap_x": 0.5, "band_gap": 0.5},
                "routing": {"default": "straight"},
                "channels": {"fill": None, "claimed": {}},
            },
        },
        "WBAProcessView": {"admits": ["WBARegulatedActivity", "WBACustomerTouchpoint", "WBAExternalCall"],
                           "conventions": {"unit": "in", "grammar": "lanes", "title": "drawn"}},
        "WBADataModelView": {"admits": ["WBADataAsset", "WBADataEntity"], "conventions": {}},
    },
    "defaults": {
        "style": {"font_family": "Calibri", "line_weight": 0.5},
        "shape_data": {"WBABusinessApplication": [
            {"name": "criticality", "label": "Criticality (default)", "type": "string"},
            {"name": "tool_default_row", "label": "Tool default"}]},
    },
}

APP = {"key": "{A1}", "name": "Retail Payments Hub", "kind": "WBABusinessApplication",
       "properties": {"criticality": "Mission-Critical", "lifecycle": "Current"}}
LEDGER = {"key": "{A2}", "name": "Core Banking Ledger", "kind": "WBASystemOfRecord"}
VENDOR = {"key": "{A3}", "name": "Card Network Gateway", "kind": "WBAVendorSystem",
          "qualified_kind": "WBA::WBAVendorSystem"}
NODE = {"key": "{A4}", "name": "Payments Cluster", "kind": "WBATechnologyNode"}
PERSON = {"key": "{A5}", "name": "Branch Touchpoint", "kind": "WBACustomerTouchpoint"}
USES = {"key": "{B1}", "kind": "Uses", "source_key": "{A1}", "target_key": "{A2}"}
FLOWS = {"key": "{B2}", "kind": "Flows", "source_key": "{A1}", "target_key": "{A3}"}

STYLE_FIELDS_3_8 = {"fill_color", "line_color", "line_weight", "line_pattern", "rounding",
                    "font_family", "font_size", "font_color", "bold", "italic", "text_align",
                    "begin_arrow", "end_arrow"}
FURNITURE_KINDS_3_5 = {"title-block", "legend", "note", "logo", "border"}


@pytest.fixture()
def std():
    return copy.deepcopy(vs.load(HERE / "westbrook-standards.yaml"))


@pytest.fixture()
def notation():
    return pr.Notation.from_dict(copy.deepcopy(STUB))


def refused(std, notation, **kw):
    with pytest.raises(pr.PrecedenceRefused) as exc:
        pr.resolve(std, notation, **kw)
    return exc.value


# ---------------------------------------------------------------------------
# Standards decide paint
# ---------------------------------------------------------------------------
def test_applications_are_blue_infrastructure_gray_external_dashed(std, notation):
    r = pr.resolve(std, notation)
    assert r.thing_style(APP)["fill_color"] == "#DCE9F7"
    assert r.thing_style(NODE)["fill_color"] == "#E7E6E6"
    vendor = r.thing_style(VENDOR)
    assert vendor["fill_color"] == "#DCE9F7", "external adds a dash, it does not remove the blue"
    assert vendor["line_pattern"] == "dash"
    assert "line_pattern" not in r.thing_style(APP)


def test_a_thing_no_rule_selects_gets_type_and_tool_defaults_only(std, notation):
    style = pr.resolve(std, notation).thing_style(PERSON)
    assert style == {"font_family": "Segoe UI", "font_size": 10, "font_color": "#1F1F1F",
                     "line_weight": 0.5}


def test_standards_type_wins_over_the_tools_default_font(std, notation):
    r = pr.resolve(std, notation)
    style, trace = r.thing_style_trace(APP)
    assert style["font_family"] == "Segoe UI"
    assert trace["font_family"] == {"layer": "standards", "path": "type.font_family"}
    assert trace["line_weight"]["path"] == "paint.application.style.line_weight"


def test_tool_default_survives_where_standards_are_silent(std, notation):
    style, trace = pr.resolve(std, notation).thing_style_trace(PERSON)
    assert trace["line_weight"]["layer"] == "notation"


def test_qualified_kind_selects(std, notation):
    std["paint"][0]["when"] = {"kinds": ["WBA::WBABusinessApplication"]}
    r = pr.resolve(std, notation)
    assert r.thing_style(APP)["fill_color"] == "#DCE9F7"
    assert "fill_color" not in r.thing_style(LEDGER)


def test_qualified_kind_selects_a_thing_that_carries_only_the_bare_kind(std, notation):
    std["paint"][0]["when"] = {"kinds": ["WBA::WBASystemOfRecord"]}
    assert pr.resolve(std, notation).thing_style(LEDGER)["fill_color"] == "#DCE9F7"


def test_selector_by_metaclass_and_property(std, notation):
    std["paint"].append({"id": "heavy", "when": {"metaclasses": ["Component"],
                                                  "properties": {"criticality": ["Mission-Critical"]}},
                         "style": {"line_weight": 2.25}, "legend": "Heavy outline: mission-critical"})
    r = pr.resolve(std, notation)
    assert r.thing_style(APP)["line_weight"] == 2.25
    assert r.thing_style(LEDGER)["line_weight"] == 1.0      # no criticality property
    assert r.thing_style(NODE)["line_weight"] == 1.0        # a Node, not a Component


def test_connector_style_layers_default_then_kind(std, notation):
    r = pr.resolve(std, notation)
    uses, flows = r.connector_style(USES), r.connector_style(FLOWS)
    assert uses["end_arrow"] == "open-arrow" and flows["end_arrow"] == "filled-triangle"
    assert uses["line_color"] == flows["line_color"] == "#404040"
    assert uses["font_size"] == 9 and uses["font_family"] == "Segoe UI"
    assert r.connector_style({"kind": "realizes"})["line_pattern"] == "dot"


def test_style_keys_are_the_render_plans_style_fields(std, notation):
    r = pr.resolve(std, notation)
    for item in (APP, VENDOR, NODE, PERSON):
        assert set(r.thing_style(item)) <= STYLE_FIELDS_3_8
    for item in (USES, FLOWS):
        assert set(r.connector_style(item)) <= STYLE_FIELDS_3_8


def test_furniture_keys_are_the_render_plans_furniture_kinds(std, notation):
    assert set(pr.resolve(std, notation).furniture) == FURNITURE_KINDS_3_5


def test_no_color_reference_survives_resolution(std, notation):
    r = pr.resolve(std, notation)
    for item in (APP, VENDOR, NODE):
        assert all(not str(v).startswith("$") for v in r.thing_style(item).values())


# ---------------------------------------------------------------------------
# The notation decides what a thing is: a standards file that tries is refused
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("key", ["kind", "metaclass", "stereotype", "retype"])
def test_standards_that_change_what_a_thing_is_are_refused_with_a_reason(std, notation, key):
    std["paint"][0][key] = "WBATechnologyNode"
    err = refused(std, notation)
    assert err.codes == ("notation-owned",)
    assert "notation standard" in str(err.findings[0].message)
    assert err.findings[0].path == f"paint.application.{key}"


def test_nothing_is_half_applied_when_a_file_is_refused(std, notation):
    std["paint"][0]["kind"] = "WBATechnologyNode"
    with pytest.raises(pr.PrecedenceRefused):
        pr.resolve(std, notation, diagram_type="WestbrookContextView")


def test_resolved_concepts_come_from_the_notation_whatever_the_standards_say(std, notation):
    r = pr.resolve(std, notation, diagram_type="WestbrookContextView")
    c = r.concept("WBABusinessApplication")
    assert (c.metaclass, c.category, c.qualified_kind) == ("Component", "thing", "WBA::WBABusinessApplication")
    assert r.concept("WBA::WBATechnologyNode").kind == "WBATechnologyNode"
    assert r.concept("NotAConcept") is None


def test_painting_never_alters_the_item_it_styles(std, notation):
    item = copy.deepcopy(APP)
    pr.resolve(std, notation).thing_style(item)
    assert item == APP


def test_a_practice_type_cannot_redefine_a_notation_diagram_type(std, notation):
    std["diagram_types"]["WBAApplicationView"] = std["diagram_types"].pop("WestbrookDeploymentView")
    err = refused(std, notation)
    assert err.codes == ("redefines-notation-type",)
    assert "refines" in err.findings[0].message


def test_a_practice_type_cannot_admit_what_the_type_it_refines_does_not(std, notation):
    std["diagram_types"]["WestbrookContextView"]["admits"].append("WBARegulatedActivity")
    err = refused(std, notation)
    assert err.codes == ("admits-widened",)
    assert "WBAApplicationView" in err.findings[0].message


def test_a_practice_type_may_admit_a_subset(std, notation):
    r = pr.resolve(std, notation, diagram_type="WestbrookContextView")
    assert r.diagram_type.admits == ("WBABusinessApplication", "WBASystemOfRecord", "WBAVendorSystem")


def test_a_practice_type_cannot_introduce_a_concept(std, notation):
    std["diagram_types"]["WestbrookDeploymentView"]["admits"].append("WBAInvented")
    err = refused(std, notation)
    assert err.codes == ("unknown-concept",)
    assert "cannot introduce a concept" in err.findings[0].message


def test_refining_an_unknown_type_or_language_is_refused(std, notation):
    std["diagram_types"]["WestbrookContextView"]["refines"]["type"] = "Nope"
    assert refused(std, notation).codes == ("unknown-diagram-type",)
    std["diagram_types"]["WestbrookContextView"]["refines"] = {"language": "Other", "type": "X"}
    assert refused(std, notation).codes == ("unknown-language",)


def test_refinement_with_no_notation_loaded_is_refused_not_skipped(std):
    assert refused(std, None).codes[0] == "unknown-language"


def test_selector_naming_an_unknown_kind_warns_but_does_not_refuse(std, notation):
    std["paint"][0]["when"]["kinds"].append("WBAInvented")
    r = pr.resolve(std, notation)
    assert [f.code for f in r.findings] == ["unknown-kind"]


def test_invalid_standards_are_refused_through_the_same_door(std, notation):
    std["paint"][0]["style"]["fill_color"] = "blue"
    assert refused(std, notation).codes == ("format",)


# ---------------------------------------------------------------------------
# A per-diagram override wins, for that diagram only, and is recorded
# ---------------------------------------------------------------------------
AMBER = {"path": "paint.application.style.fill_color", "value": "#FFE699",
         "reason": "Reviewer asked for amber on this page"}


def test_a_per_diagram_override_wins(std, notation):
    r = pr.resolve(std, notation, overrides=[AMBER])
    assert r.thing_style(APP)["fill_color"] == "#FFE699"
    assert r.thing_style(VENDOR)["fill_color"] == "#FFE699"     # same rule, same diagram
    assert r.thing_style(NODE)["fill_color"] == "#E7E6E6"       # other rules untouched


def test_the_override_is_recorded_as_path_value_reason(std, notation):
    r = pr.resolve(std, notation, overrides=[AMBER], ref="westbrook-standards.yaml")
    assert r.provenance() == {"standards_ref": "westbrook-standards.yaml", "overrides": [AMBER]}
    assert r.overrides[0].keys() == {"path", "value", "reason"}


def test_the_trace_names_the_layer_that_won(std, notation):
    r = pr.resolve(std, notation, overrides=[AMBER])
    _, trace = r.thing_style_trace(APP)
    assert trace["fill_color"] == {"layer": "per-diagram", "path": "paint.application.style.fill_color"}
    assert trace["line_color"]["layer"] == "standards"


def test_the_override_is_for_that_diagram_only(std, notation):
    before = copy.deepcopy(std)
    pr.resolve(std, notation, overrides=[AMBER])
    assert std == before, "the standards document passed in is never changed"
    again = pr.resolve(std, notation)
    assert again.thing_style(APP)["fill_color"] == "#DCE9F7"
    assert again.provenance()["overrides"] == []


def test_override_of_a_named_color_cascades_and_is_recorded(std, notation):
    o = {"path": "colors.application_fill", "value": "#CCFFCC", "reason": "print on a green template"}
    r = pr.resolve(std, notation, overrides=[o])
    assert r.thing_style(APP)["fill_color"] == "#CCFFCC"
    assert r.provenance()["overrides"] == [o]


def test_override_may_use_a_color_name(std, notation):
    r = pr.resolve(std, notation, overrides=[
        {"path": "paint.application.style.fill_color", "value": "$infrastructure_fill",
         "reason": "monochrome pack"}])
    assert r.thing_style(APP)["fill_color"] == "#E7E6E6"


def test_override_of_frame_and_type_and_furniture(std, notation):
    r = pr.resolve(std, notation, overrides=[
        {"path": "page.orientation", "value": "portrait", "reason": "fits the memo"},
        {"path": "furniture.legend.enabled", "value": False, "reason": "single color page"},
        {"path": "type.sizes.shape_label", "value": 12, "reason": "projected"},
        {"path": "furniture.title-block.fields.author_role.value", "value": "Solution Architecture",
         "reason": "authored by the solution team"}])
    assert r.page["orientation"] == "portrait"
    assert r.furniture["legend"]["enabled"] is False
    assert r.legend_entries([APP]) == []
    assert r.thing_style(APP)["font_size"] == 12
    assert [o["path"] for o in r.provenance()["overrides"]] == [
        "page.orientation", "furniture.legend.enabled", "type.sizes.shape_label",
        "furniture.title-block.fields.author_role.value"]
    values, _ = r.title_block_values({"title": "T", "revision": 1})
    assert {"name": "author_role", "label": "Author role", "value": "Solution Architecture"} in values


def test_override_without_a_reason_records_a_default_reason(std, notation):
    r = pr.resolve(std, notation, overrides=[{"path": AMBER["path"], "value": "#FFE699"}])
    assert r.provenance()["overrides"][0]["reason"] == pr.DEFAULT_OVERRIDE_REASON


def test_override_mapping_form_is_accepted_and_empty_means_none(std, notation):
    r = pr.resolve(std, notation, overrides={AMBER["path"]: "#FFE699"})
    assert r.provenance()["overrides"] == [
        {"path": AMBER["path"], "value": "#FFE699", "reason": pr.DEFAULT_OVERRIDE_REASON}]
    assert pr.resolve(std, notation, overrides={}).provenance()["overrides"] == []
    assert pr.resolve(std, notation, overrides=None).provenance()["overrides"] == []


def test_recorded_value_is_a_copy(std, notation):
    value = {"fill_color": "#FFE699"}
    r = pr.resolve(std, notation, overrides=[{"path": "paint.application.style", "value": value,
                                              "reason": "whole-style swap"}])
    value["fill_color"] = "#000000"
    assert r.provenance()["overrides"][0]["value"] == {"fill_color": "#FFE699"}
    assert r.thing_style(APP)["fill_color"] == "#FFE699"


# ---------------------------------------------------------------------------
# ... and cannot reach what the notation, or the standards' definitions, own
# ---------------------------------------------------------------------------
def test_an_override_cannot_change_what_a_thing_is(std, notation):
    err = refused(std, notation, overrides=[
        {"path": "paint.application.kind", "value": "WBATechnologyNode", "reason": "make it a node"}])
    assert err.codes == ("notation-owned",)
    assert "notation standard" in err.findings[0].message


def test_an_override_cannot_widen_what_a_diagram_type_admits(std, notation):
    err = refused(std, notation, overrides=[
        {"path": "diagram_types.WestbrookContextView.admits", "value": ["WBARegulatedActivity"],
         "reason": "just this once"}])
    assert err.codes == ("override-outside-paint-and-frame",)
    assert "diagram type's definition" in err.findings[0].message


def test_an_override_cannot_touch_identity(std, notation):
    for path in ("id", "contract", "unit", "owner"):
        err = refused(std, notation, overrides=[{"path": path, "value": "x", "reason": "r"}])
        assert err.codes == ("override-outside-paint-and-frame",), path


def test_an_override_with_an_invalid_value_is_refused(std, notation):
    err = refused(std, notation, overrides=[
        {"path": "paint.application.style.fill_color", "value": "amber", "reason": "r"}])
    assert err.codes == ("override-invalid",)


def test_an_override_naming_an_unknown_path_is_refused(std, notation):
    err = refused(std, notation, overrides=[
        {"path": "paint.nothing.style.fill_color", "value": "#FFFFFF", "reason": "r"}])
    assert err.codes == ("override-path-not-found",)


def test_one_instruction_per_path(std, notation):
    err = refused(std, notation, overrides=[AMBER, dict(AMBER, value="#FFFFFF")])
    assert err.codes == ("override-duplicate-path",)


def test_malformed_override_entries_are_refused(std, notation):
    assert refused(std, notation, overrides=["paint"]).codes == ("override-invalid",)


# ---------------------------------------------------------------------------
# Diagram types, routing, channels, units
# ---------------------------------------------------------------------------
def test_practice_type_inherits_sizing_and_spacing_it_does_not_state(std, notation):
    dt = pr.resolve(std, notation, diagram_type="WestbrookContextView").diagram_type
    assert dt.owner == "practice" and dt.refines == {"language": LANG, "type": "WBAApplicationView"}
    assert dt.sizing["default"] == {"w": 1.75, "h": 0.9}                 # the practice's wins
    assert dt.sizing["WBAVendorSystem"] == {"w": 1.5, "h": 0.6}          # inherited
    assert dt.spacing["item_gap_x"] == 0.4 and dt.spacing["band_gap"] == 0.3   # the practice's wins


def test_units_that_differ_are_not_inherited_and_say_so(std, notation):
    notation.diagram_types["WBAApplicationView"].conventions["unit"] = "px"
    r = pr.resolve(std, notation, diagram_type="WestbrookContextView")
    assert [f.code for f in r.findings] == ["unit-not-converted"]
    assert "WBAVendorSystem" not in r.diagram_type.sizing
    assert r.diagram_type.sizing["default"] == {"w": 1.75, "h": 0.9}


def test_notation_type_keeps_its_own_grammar_sizing_and_spacing(std, notation):
    dt = pr.resolve(std, notation, diagram_type="WBAApplicationView").diagram_type
    assert dt.owner == "notation" and dt.grammar == "layered-bands"
    assert dt.sizing["default"] == {"w": 1.5, "h": 0.8} and dt.spacing == {"item_gap_x": 0.5, "band_gap": 0.5}


def test_routing_precedence_practice_type_then_standards_then_notation(std, notation):
    assert pr.resolve(std, notation, diagram_type="WestbrookContextView").routing == \
        {"default": "orthogonal", "source": "practice-type"}
    assert pr.resolve(std, notation, diagram_type="WBAApplicationView").routing["source"] == "standards"
    assert pr.resolve(std, notation, diagram_type="WBAApplicationView").routing["default"] == "orthogonal"
    del std["lines"]["routing"]
    assert pr.resolve(std, notation, diagram_type="WBAApplicationView").routing == \
        {"default": "straight", "source": "notation"}


def test_page_and_furniture_changes_of_a_practice_type_merge_over_the_file(std, notation):
    r = pr.resolve(std, notation, diagram_type="WestbrookDeploymentView")
    assert (r.page["size"], r.page["orientation"], r.page["margin"]) == ("A3", "landscape", 0.5)
    assert r.furniture["note"]["enabled"] is False
    assert r.furniture["note"]["title"] == "Notes"            # merged, not replaced
    assert r.furniture["legend"]["enabled"] is True


def test_unknown_diagram_type_is_refused(std, notation):
    assert refused(std, notation, diagram_type="Nope").codes == ("unknown-diagram-type",)


def test_painting_a_channel_the_notation_claims_warns_with_its_meaning(std, notation):
    notation.diagram_types["WBAApplicationView"].conventions["channels"] = {
        "fill": "Layer: business, application, technology", "claimed": {"border": "Flow type"}}
    r = pr.resolve(std, notation, diagram_type="WBAApplicationView")
    by_path = {f.path: f for f in r.findings if f.code == "channel-claimed"}
    assert "paint.application.style.fill_color" in by_path
    assert "Layer: business" in by_path["paint.application.style.fill_color"].message
    assert "paint.external.style.line_pattern" in by_path
    assert all(f.severity == "warning" for f in by_path.values())
    assert r.thing_style(APP)["fill_color"] == "#DCE9F7", "a warning, not a refusal: paint is the practice's call"


def test_unclaimed_channels_do_not_warn(std, notation):
    r = pr.resolve(std, notation, diagram_type="WBAApplicationView")
    assert not [f for f in r.findings if f.code == "channel-claimed"]


# ---------------------------------------------------------------------------
# Shape Data, legend, title block
# ---------------------------------------------------------------------------
def test_shape_data_standards_replace_tool_defaults_by_name_and_extend(std, notation):
    rows = {r["name"]: r for r in pr.resolve(std, notation).shape_data_rows(APP)}
    assert rows["criticality"]["label"] == "Criticality" and rows["criticality"]["layer"] == "standards"
    assert rows["criticality"]["type"] == "list" and rows["criticality"]["show_on_shape"] is True
    assert rows["tool_default_row"]["layer"] == "notation"
    assert rows["businessOwner"]["from_property"] == "businessOwner"
    assert rows["lifecycle"]["show_on_shape"] is False and rows["lifecycle"]["invisible"] is False
    assert list(rows)[:2] == ["criticality", "tool_default_row"], "a replaced row keeps its position"


def test_shape_data_for_connectors_uses_target_connector(std, notation):
    r = pr.resolve(std, notation)
    assert [x["name"] for x in r.shape_data_rows(USES, target="connector")] == ["integrationPattern", "slaTier"]
    assert r.shape_data_rows(USES) == []                      # shape sets do not apply to a connector
    assert r.shape_data_rows(PERSON) == []


def test_identity_rows_are_never_produced_by_the_merge(std, notation):
    r = pr.resolve(std, notation)
    for item in (APP, VENDOR, NODE):
        assert not [x for x in r.shape_data_rows(item) if x["name"].upper().startswith("APT_")]


def test_derived_legend_lists_only_what_the_page_uses(std, notation):
    r = pr.resolve(std, notation)
    entries = r.legend_entries([APP, LEDGER], [USES])
    assert [e["source"] for e in entries] == ["paint.application", "lines.by_kind.Uses"]
    assert entries[0]["style"]["fill_color"] == "#DCE9F7" and entries[0]["swatch"] == "shape"
    assert entries[1]["swatch"] == "line" and entries[1]["style"]["end_arrow"] == "open-arrow"
    full = r.legend_entries([APP, NODE, VENDOR], [USES, FLOWS])
    assert [e["source"] for e in full] == [
        "paint.application", "paint.infrastructure", "paint.external",
        "lines.by_kind.Uses", "lines.by_kind.Flows"]
    assert [e["label"] for e in full][0].startswith("Blue")


def test_legend_lists_everything_when_only_used_is_off(std, notation):
    std["furniture"]["legend"]["only_used"] = False
    assert len(pr.resolve(std, notation).legend_entries([])) == 6


def test_explicit_legend_returns_its_entries_with_colors_resolved(std, notation):
    std["furniture"]["legend"].update(mode="explicit", entries=[
        {"label": "Application", "swatch": "shape", "style": {"fill_color": "$application_fill"}}])
    entries = pr.resolve(std, notation).legend_entries([APP])
    assert entries == [{"source": "furniture.legend.entries[0]", "label": "Application",
                        "swatch": "shape", "style": {"fill_color": "#DCE9F7"}}]


def test_title_block_carries_revision_and_author_role(std, notation):
    r = pr.resolve(std, notation)
    values, findings = r.title_block_values(
        {"id": "v", "name": "Payments context", "title": "Retail Payments: application context",
         "revision": 3}, generated_at="2026-10-12")
    assert findings == []
    assert [(v["name"], v["value"]) for v in values] == [
        ("title", "Retail Payments: application context"), ("revision", 3),
        ("author_role", "Enterprise Architecture"), ("date", "2026-10-12")]


def test_title_block_without_a_revision_is_reported_and_zero_is_a_revision(std, notation):
    r = pr.resolve(std, notation)
    _, findings = r.title_block_values({"name": "Payments context"})
    assert [(f.code, f.path) for f in findings] == [
        ("title-block-missing-value", "furniture.title-block.fields.revision")]
    _, none = r.title_block_values({"name": "Payments context", "revision": 0})
    assert none == []


def test_title_defaults_to_the_view_name(std, notation):
    values, _ = pr.resolve(std, notation).title_block_values({"name": "Payments context", "revision": 1})
    assert values[0]["value"] == "Payments context"


# ---------------------------------------------------------------------------
# Notation input
# ---------------------------------------------------------------------------
def test_notation_from_dict_rejects_a_diagram_type_that_admits_an_unknown_concept():
    bad = copy.deepcopy(STUB)
    bad["diagram_types"]["WBAApplicationView"]["admits"].append("Ghost")
    with pytest.raises(ValueError, match="Ghost"):
        pr.Notation.from_dict(bad)


def test_notation_from_dict_needs_a_category():
    bad = copy.deepcopy(STUB)
    bad["concepts"]["WBAAIModel"]["category"] = "node"
    with pytest.raises(ValueError, match="category"):
        pr.Notation.from_dict(bad)


def test_several_notations_may_be_passed_as_a_list_or_mapping(std, notation):
    assert pr.resolve(std, [notation]).thing_style(APP)["fill_color"] == "#DCE9F7"
    assert pr.resolve(std, {LANG: notation}).thing_style(APP)["fill_color"] == "#DCE9F7"
