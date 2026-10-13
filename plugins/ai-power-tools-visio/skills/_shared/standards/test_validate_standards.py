"""Schema tests for the house standards file (validate_standards.py).

Run from the repository root:  python -m pytest plugins -q
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest

import validate_standards as vs

HERE = Path(__file__).resolve().parent
WESTBROOK = HERE / "westbrook-standards.yaml"
README = HERE / "README.md"


@pytest.fixture()
def doc():
    """A fresh copy of the Westbrook standards, parsed."""
    return copy.deepcopy(vs.load(WESTBROOK))


def errors(d):
    return vs.validate(d).errors


def codes(d):
    return [f.code for f in errors(d)]


def only(d, code):
    found = [f for f in errors(d) if f.code == code]
    assert found, f"expected a {code!r} finding, got {[str(f) for f in errors(d)]}"
    return found


# ---------------------------------------------------------------------------
# The worked example is valid
# ---------------------------------------------------------------------------
def test_westbrook_example_is_valid_and_clean(doc):
    report = vs.validate(doc)
    assert report.errors == []
    assert report.warnings == []


def test_cli_validates_the_example(capsys):
    assert vs.main([str(WESTBROOK)]) == 0
    assert "OK" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Every bullet of scope section 3 is expressible, and the example uses each
# ---------------------------------------------------------------------------
SCOPE_BULLETS = {
    "palette and meaning: fill, line and font color per concept or category, with legend text":
        lambda d: all("legend" in r and "fill_color" in r["style"] or "line_pattern" in r["style"]
                      for r in d["paint"]) and "colors" in d,
    "lines: weight, pattern, arrowheads per relationship kind; routing preference":
        lambda d: d["lines"]["routing"] and all(
            {"end_arrow"} <= set(e["style"]) for e in d["lines"]["by_kind"].values())
        and "line_weight" in d["lines"]["default"] and "line_pattern" in d["lines"]["default"],
    "type: font family and sizes for labels, connector labels, titles, notes":
        lambda d: d["type"]["font_family"] and {"shape_label", "connector_label", "title", "note"}
        <= set(d["type"]["sizes"]),
    "furniture: title block, legend, notes panel, border, page, logo, revision and author fields":
        lambda d: {"title-block", "legend", "note", "border", "logo"} <= set(d["furniture"])
        and {"size", "orientation"} <= set(d["page"])
        and {"revision", "author_role"} <= {f["name"] for f in d["furniture"]["title-block"]["fields"]}
        and all("position" in d["furniture"][k] for k in ("title-block", "legend", "note")),
    "Shape Data set: which attributes a kind carries and which are shown as data graphics":
        lambda d: any(r.get("show_on_shape") and "graphic" in r
                      for s in d["shape_data"] for r in s["rows"])
        and any(not r.get("show_on_shape") for s in d["shape_data"] for r in s["rows"]),
    "the practice's own diagram types, in the library's form":
        lambda d: any("refines" in t for t in d["diagram_types"].values())
        and any("refines" not in t for t in d["diagram_types"].values())
        and all({"grammar", "title", "routing", "channels"} <= set(t) for t in d["diagram_types"].values()),
}


@pytest.mark.parametrize("bullet", list(SCOPE_BULLETS), ids=lambda b: b.split(":")[0])
def test_example_uses_every_scope_bullet(doc, bullet):
    assert SCOPE_BULLETS[bullet](doc), bullet


def test_the_three_house_rules_of_the_example(doc):
    """Applications blue, infrastructure gray, external dashed."""
    paint = {r["id"]: r for r in doc["paint"]}
    assert doc["colors"][paint["application"]["style"]["fill_color"][1:]].upper() == "#DCE9F7"
    assert paint["external"]["style"]["line_pattern"] == "dash"
    fill = doc["colors"][paint["infrastructure"]["style"]["fill_color"][1:]]
    r, g, b = (int(fill[i:i + 2], 16) for i in (1, 3, 5))
    assert abs(r - g) < 8 and abs(g - b) < 8, "infrastructure fill is gray"


def test_title_block_carries_revision_and_author_role(doc):
    fields = {f["name"]: f for f in doc["furniture"]["title-block"]["fields"]}
    assert fields["revision"]["source"] == "view.revision" and fields["revision"]["required"]
    assert fields["author_role"]["source"] == "constant" and fields["author_role"]["value"]


# ---------------------------------------------------------------------------
# Contract, version, YAML
# ---------------------------------------------------------------------------
def test_wrong_contract_name_is_refused(doc):
    doc["contract"] = "apt-view"
    assert codes(doc) == ["wrong-contract"]


@pytest.mark.parametrize("version", ["9.9", 0.1, None])
def test_unknown_version_is_refused_not_guessed(doc, version):
    doc["contract_version"] = version
    assert codes(doc) == ["unknown-version"]


def test_unquoted_version_gets_a_quote_hint(doc):
    doc["contract_version"] = 0.1
    assert "quote" in only(doc, "unknown-version")[0].message


def test_not_a_mapping_is_refused():
    assert [f.code for f in vs.validate(["a"]).errors] == ["type"]


def test_duplicate_yaml_key_is_refused_rather_than_last_one_winning():
    text = WESTBROOK.read_text(encoding="utf-8").replace(
        "unit: in\n", "unit: in\nunit: mm\n", 1)
    with pytest.raises(vs.StandardsError) as exc:
        vs.load_text(text, "dup.yaml")
    assert "duplicate key 'unit'" in str(exc.value)


def test_yaml_syntax_error_is_a_standards_error():
    with pytest.raises(vs.StandardsError):
        vs.load_text("a: [unclosed", "bad.yaml")


def test_loader_is_safe():
    with pytest.raises(vs.StandardsError):
        vs.load_text("contract: !!python/object/apply:os.getcwd []", "unsafe.yaml")


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------
def test_missing_required_top_level_keys_are_named(doc):
    del doc["owner"]
    f = only(doc, "required")[0]
    assert f.path == "owner"


def test_unknown_key_gets_did_you_mean(doc):
    doc["paint"][0]["style"]["fill_colour"] = "#FFFFFF"
    f = only(doc, "unknown-key")[0]
    assert f.path == "paint.application.style.fill_colour"
    assert "fill_color" in f.message


def test_arrowheads_are_not_paint_for_shapes(doc):
    doc["paint"][0]["style"]["end_arrow"] = "open-arrow"
    assert codes(doc) == ["unknown-key"]


def test_fill_is_not_a_line_field(doc):
    doc["lines"]["default"]["fill_color"] = "#FFFFFF"
    assert codes(doc) == ["unknown-key"]


@pytest.mark.parametrize("bad", ["blue", "#12345", "#GGGGGG", 12, "$"])
def test_bad_color_is_refused(doc, bad):
    doc["paint"][0]["style"]["fill_color"] = bad
    assert errors(doc)


def test_unknown_color_name_suggests_the_close_one(doc):
    doc["paint"][0]["style"]["fill_color"] = "$aplication_fill"
    f = only(doc, "unknown-color-name")[0]
    assert "$application_fill" in f.message


def test_palette_holds_literal_colors_only(doc):
    doc["colors"]["alias"] = "$text"
    assert errors(doc)


def test_enums_are_checked_with_a_suggestion(doc):
    doc["paint"][0]["style"]["line_pattern"] = "dashed"
    assert "dash" in only(doc, "enum")[0].message


def test_numbers_must_be_positive_and_not_booleans(doc):
    doc["type"]["sizes"]["title"] = 0
    doc["type"]["sizes"]["note"] = True
    assert sorted(codes(doc)) == ["range", "type"]


def test_duplicate_paint_id_is_refused(doc):
    doc["paint"].append(copy.deepcopy(doc["paint"][0]))
    assert "duplicate-id" in codes(doc)


def test_selector_needs_at_least_one_criterion(doc):
    doc["paint"][0]["when"] = {}
    assert "required" in codes(doc)


def test_empty_selector_lists_are_refused(doc):
    doc["paint"][0]["when"] = {"kinds": []}
    assert errors(doc)


def test_qualified_kinds_are_accepted_in_selectors(doc):
    doc["paint"][0]["when"] = {"kinds": ["WBA::WBABusinessApplication"]}
    assert errors(doc) == []


def test_findings_paths_are_addressable_by_id_not_position(doc):
    doc["paint"][1]["style"]["line_weight"] = -1
    assert only(doc, "range")[0].path == "paint.infrastructure.style.line_weight"


# ---------------------------------------------------------------------------
# A house standard cannot say what a thing is
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("where, key", [
    ("paint_rule", "kind"),
    ("paint_rule", "metaclass"),
    ("paint_rule", "stereotype"),
    ("paint_rule", "retype"),
    ("paint_rule", "as_kind"),
    ("when", "kind"),
    ("when", "qualified_kind"),
    ("top", "stereotype_prefix"),
    ("top", "concepts"),
    ("top", "kinds"),
    ("top", "admits"),
    ("row", "base_type"),
    ("diagram_type", "concepts"),
    ("lines_entry", "allowed_ends"),
])
def test_notation_owned_keys_are_refused_with_a_reason(doc, where, key):
    target = {
        "paint_rule": doc["paint"][0],
        "when": doc["paint"][0]["when"],
        "top": doc,
        "row": doc["shape_data"][0]["rows"][0],
        "diagram_type": doc["diagram_types"]["WestbrookDeploymentView"],
        "lines_entry": doc["lines"]["by_kind"]["Uses"],
    }[where]
    target[key] = "WBATechnologyNode"
    f = only(doc, "notation-owned")[0]
    assert f.path.endswith(key)
    assert "notation standard" in f.message and "cannot set it" in f.message


def test_admits_outside_a_diagram_type_points_at_where_it_is_allowed(doc):
    doc["paint"][0]["admits"] = ["WBATechnologyNode"]
    msg = only(doc, "notation-owned")[0].message
    assert "diagram_types" in msg


def test_kind_refusal_tells_the_author_what_to_use_instead(doc):
    doc["paint"][0]["kind"] = "WBATechnologyNode"
    assert "when.kinds" in only(doc, "notation-owned")[0].message


# ---------------------------------------------------------------------------
# Furniture, page, Shape Data
# ---------------------------------------------------------------------------
def test_custom_page_needs_dimensions(doc):
    doc["page"] = {"size": "custom", "orientation": "landscape"}
    assert codes(doc).count("required") == 2


def test_constant_title_field_needs_a_value(doc):
    del doc["furniture"]["title-block"]["fields"][2]["value"]
    assert only(doc, "required")[0].path == "furniture.title-block.fields.author_role"


def test_value_on_a_non_constant_field_is_only_a_warning(doc):
    doc["furniture"]["title-block"]["fields"][1]["value"] = "ignored"
    report = vs.validate(doc)
    assert report.ok and [w.code for w in report.warnings] == ["ignored"]


def test_explicit_legend_needs_entries(doc):
    doc["furniture"]["legend"]["mode"] = "explicit"
    assert only(doc, "required")[0].path == "furniture.legend.entries"


def test_explicit_legend_with_entries_is_valid(doc):
    doc["furniture"]["legend"].update(mode="explicit", entries=[
        {"label": "Application", "swatch": "shape", "style": {"fill_color": "$application_fill"}},
        {"label": "Uses", "swatch": "line", "style": {"line_color": "$line", "end_arrow": "open-arrow"}}])
    assert errors(doc) == []


def test_furniture_keys_are_the_render_plan_furniture_kinds(doc):
    assert set(doc["furniture"]) == {"border", "title-block", "legend", "note", "logo"}
    doc["furniture"]["title_block"] = {"enabled": True}
    assert "unknown-key" in codes(doc)


def test_furniture_item_must_say_whether_it_is_enabled(doc):
    del doc["furniture"]["legend"]["enabled"]
    assert only(doc, "required")[0].path == "furniture.legend.enabled"


def test_shape_data_row_names_starting_apt_are_reserved(doc):
    doc["shape_data"][0]["rows"].append({"name": "APT_Key"})
    assert "reserved-name" in codes(doc)


def test_reserved_prefix_check_is_case_insensitive(doc):
    doc["shape_data"][0]["rows"].append({"name": "apt_view"})
    assert "reserved-name" in codes(doc)


def test_list_row_needs_values_and_values_need_list(doc):
    doc["shape_data"][0]["rows"].append({"name": "tier", "type": "list"})
    doc["shape_data"][0]["rows"].append({"name": "owner2", "type": "string", "values": ["a"]})
    assert sorted(codes(doc)) == ["conflict", "required"]


def test_duplicate_row_name_in_a_set_is_refused(doc):
    doc["shape_data"][0]["rows"].append({"name": "criticality"})
    assert "duplicate-id" in codes(doc)


def test_graphic_needs_show_on_shape(doc):
    doc["shape_data"][0]["rows"][1]["graphic"] = {"type": "text"}
    assert "conflict" in codes(doc)


def test_row_name_must_be_a_valid_shape_data_name(doc):
    doc["shape_data"][0]["rows"][2]["name"] = "business owner"
    assert "format" in codes(doc)


# ---------------------------------------------------------------------------
# The practice's own diagram types
# ---------------------------------------------------------------------------
def test_own_type_without_refines_needs_a_default_size(doc):
    del doc["diagram_types"]["WestbrookDeploymentView"]["sizing"]
    assert only(doc, "required")[0].path == "diagram_types.WestbrookDeploymentView.sizing"


def test_refining_type_may_leave_sizing_to_inheritance(doc):
    del doc["diagram_types"]["WestbrookContextView"]["sizing"]
    assert errors(doc) == []


def test_sizing_uses_w_and_h_like_the_library(doc):
    doc["diagram_types"]["WestbrookDeploymentView"]["sizing"]["default"] = {"width": 1, "height": 1}
    found = [f for f in errors(doc) if f.code == "unknown-key"]
    assert any("Use `w`" in f.message for f in found)


def test_type_requires_the_four_mandatory_blocks_the_library_requires(doc):
    t = doc["diagram_types"]["WestbrookDeploymentView"]
    for k in ("grammar", "title", "routing", "channels"):
        del t[k]
    assert sorted(f.path.rsplit(".", 1)[1] for f in only(doc, "required")) == \
        ["channels", "grammar", "routing", "title"]


def test_grammar_is_checked_against_the_library_vocabulary(doc):
    doc["diagram_types"]["WestbrookDeploymentView"]["grammar"] = "nested_grid"
    assert "nested-grid" in only(doc, "enum")[0].message


def test_channels_claimed_and_free_cannot_overlap(doc):
    doc["diagram_types"]["WestbrookContextView"]["channels"]["free"] = ["border"]
    assert "conflict" in codes(doc)


def test_channels_fill_is_required_even_when_unclaimed(doc):
    t = doc["diagram_types"]["WestbrookDeploymentView"]
    t["channels"] = {}
    assert only(doc, "required")[0].path.endswith("channels.fill")
    t["channels"] = {"fill": None}
    assert errors(doc) == []


def test_unexplained_color_is_a_warning_naming_the_rule(doc):
    del doc["paint"][1]["legend"]
    report = vs.validate(doc)
    assert report.ok
    assert [(w.code, w.path) for w in report.warnings] == [("unexplained-color", "paint.infrastructure")]


def test_unexplained_line_is_a_warning(doc):
    del doc["lines"]["by_kind"]["Flows"]["legend"]
    assert [w.code for w in vs.validate(doc).warnings] == ["unexplained-line"]


def test_derived_legend_with_nothing_to_say_is_a_warning(doc):
    for r in doc["paint"]:
        r.pop("legend")
    for e in doc["lines"]["by_kind"].values():
        e.pop("legend")
    assert "legend-will-be-empty" in [w.code for w in vs.validate(doc).warnings]


# ---------------------------------------------------------------------------
# Soft fields and the README stay in step with the schema
# ---------------------------------------------------------------------------
def test_soft_fields_are_declared_and_each_names_what_it_depends_on():
    soft = vs.soft_fields()
    assert soft, "the draft depends on a library schema that is not settled"
    for pattern, depends, note in soft:
        assert depends in {"library", "data-graphics"}, (pattern, depends)
        assert note, f"{pattern} is soft but says nothing about what will need aligning"


def test_every_soft_field_the_example_uses_is_in_the_soft_list(doc):
    patterns = [re.escape(p).replace(r"\*", r"[^.]+").replace(r"\[\]", r"(\[\d+\]|\.[^.]+)")
                for p, _, _ in vs.soft_fields()]
    for path, _ in vs.validate(doc).soft_used:
        assert any(re.fullmatch(p, path) for p in patterns), path


def test_example_marks_soft_fields_with_comments(doc):
    text = WESTBROOK.read_text(encoding="utf-8")
    assert text.count("# soft:") >= 10


def test_readme_reference_is_generated_from_the_schema():
    text = README.read_text(encoding="utf-8")
    head, sep, rest = text.partition(vs.REFERENCE_START)
    assert sep, "README.md is missing the reference start marker"
    body, sep2, _ = rest.partition(vs.REFERENCE_END)
    assert sep2, "README.md is missing the reference end marker"
    assert body.strip() == vs.reference_markdown(), \
        "README reference is stale: run  python validate_standards.py --write-readme"


def test_readme_lists_every_soft_field_in_the_change_list():
    text = README.read_text(encoding="utf-8")
    section = text.split("## Alignment change list", 1)[1].split("\n## ", 1)[0]
    for pattern, _, _ in vs.soft_fields():
        assert f"`{pattern}`" in section, f"{pattern} is soft but not in the alignment change list"


def test_every_schema_key_has_documentation():
    missing = [p for p, n, _ in vs.walk() if p and not p.endswith(("[]", ".*")) and not n.doc]
    assert missing == [], f"undocumented keys (the README reference would be blank): {missing}"


def test_readme_minimal_example_is_valid():
    text = README.read_text(encoding="utf-8")
    block = text.split("## A minimal file", 1)[1].split("```yaml", 1)[1].split("```", 1)[0]
    report = vs.validate(vs.load_text(block, "README minimal example"))
    assert report.errors == [] and report.warnings == []


def test_shipped_files_are_lf_without_bom():
    for p in HERE.iterdir():
        if p.suffix in {".py", ".yaml", ".md"}:
            raw = p.read_bytes()
            assert b"\r\n" not in raw, f"{p.name} has CRLF"
            assert not raw.startswith(b"\xef\xbb\xbf"), f"{p.name} has a BOM"
