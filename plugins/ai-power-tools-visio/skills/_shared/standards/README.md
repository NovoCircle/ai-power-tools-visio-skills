# The house standards file

A practice decides how its diagrams look once, in one file it edits, and every diagram drawn
afterward follows it. This directory holds the format of that file, a checker for it, the rule
that decides who wins when the notation, the file and a single request disagree, and the
Westbrook Bank file as a worked example.

## Status: a draft, not a settled format

This is a customer-visible shape and it is proposed, not decided. Three things are not settled
and the file is written to be easy to align when they are:

- **The notation library's schema** (APT-2026-0472). Every field that borrows the library's
  vocabulary is marked **soft** below, with what will need aligning. Until the library lands the
  file follows the library's current form (the composition skill's bindings) and the render
  plan's field names.
- **Typed Shape Data and data graphics** (APV-2026-0013). The `graphic` block is provisional.
- **The names and layout of the file itself.** Section names, the `when` selector, `$name`
  colors, the title block's field list and `furniture` keys are this draft's proposal.

Westbrook Bank is an illustration. A real practice uses its own technology, stereotypes and
firm; nothing in the format or the checker assumes the Westbrook model.

## What it holds

| Section | What the practice decides |
|---|---|
| `colors`, `paint` | Palette and meaning: fill, line and font color per concept or category, and the legend text that explains each |
| `lines` | Weight, pattern and arrowheads per relationship kind, and a routing preference |
| `type` | Font family and the sizes of shape labels, connector labels, titles, notes and the legend |
| `page`, `furniture` | Page size and orientation, border, title block (with revision and author role), legend, notes panel, logo, and where each sits |
| `shape_data` | Which Shape Data rows a shape or connector of a kind carries, and which are shown on it |
| `diagram_types` | The practice's own diagram types ("our context diagram"), written the way the notation library writes a diagram type |

A standards file is not a Visio template. A template is one thing the product can write from it.
The file is the source, so it can also drive checking and restyling a whole folder.

## Who wins

Three layers, in this order. The order is enforced by `precedence.py`, not just described here.

1. **The notation decides what a thing is.** Its kind, its base type, which concepts a diagram
   type admits. A standards file cannot change any of it, and neither can a per-diagram
   instruction. A file that tries is refused, with a reason.
2. **The practice's standards decide how it is painted and framed.** Color, lines, type, page,
   furniture, Shape Data set, and the practice's own diagram types.
3. **A per-diagram instruction wins for that one diagram.** "Make this one amber" overrides the
   standards for this diagram only, and the diagram records that it did: the render plan's
   `provenance.overrides` carries `{path, value, reason}` for each.

| Field | Decided by | Can a standards file change it? | Can a per-diagram instruction? |
|---|---|---|---|
| A thing's kind, base type, qualified kind | Notation | No: refused (`notation-owned`) | No |
| What a notation diagram type admits | Notation | No: a name that is already a notation type is refused (`redefines-notation-type`) | No |
| Grammar, sizing and spacing of a notation diagram type | Notation conventions | No (set them in the practice's own type, which refines it) | No |
| A practice type's `admits` | Standards | Yes, but only a subset of what the type it refines admits (`admits-widened`), and only concepts the notation has (`unknown-concept`) | No (`override-outside-paint-and-frame`) |
| Fill, outline, font, line paint, arrowheads | Standards | Yes | Yes |
| Routing preference | Standards | Yes | Yes |
| Page, furniture, Shape Data set | Standards | Yes | Yes |
| The file's own identity and the practice's type definitions | Standards | Yes | No |

If a notation already uses a visual channel for something (a fill that means a layer, a dashed
outline that means a kind of flow), the standards may still paint it, because paint is the
practice's call, but the merge returns a `channel-claimed` warning naming the notation's meaning.

## A minimal file

```yaml
contract: apt-standards
contract_version: "0.1"
id: example-standards
name: Example standards
owner: Example Practice
type:
  font_family: Segoe UI
  sizes: {shape_label: 10, connector_label: 9, title: 16, note: 9, legend: 9}
page: {size: Letter, orientation: landscape}
paint:
  - id: application
    when: {kinds: [WBABusinessApplication]}
    style: {fill_color: "#DCE9F7", line_color: "#1F4E79"}
    legend: "Blue: an application"
```

Every section is optional apart from the five identity keys, so a practice can start with paint
and add the rest. `westbrook-standards.yaml` uses every section.

Points worth knowing while editing:

- Rules in `paint` all apply, in order, and a later rule wins per field. That is how "external is
  dashed" adds a dashed outline to a blue vendor system without taking away its blue.
- Colors can be written `#RRGGBB` or `$name` from `colors`. Change a color once and every rule
  using it follows.
- A rule that sets a color or pattern without `legend` text is an unexplained color. The checker
  warns about it, and a derived legend leaves it out.
- `selector` keys under `when` are `kinds`, `metaclasses`, `language` and `properties`. A rule
  selects things; it never says what they are. `kind: ...` in a rule is refused.
- The title block's `author_role` is a role (for example `Enterprise Architecture`), never a
  person's name. The format cannot check that; the file's owner does.
- Furniture keys (`title-block`, `legend`, `note`, `logo`, `border`) are the render plan's
  `furniture_kind` values, so nothing translates between the file and the plan.
- Lengths are in the file's `unit` (default `in`).

## Using it from code

```python
import validate_standards as vs
import precedence

doc = vs.load("westbrook-standards.yaml")          # parsed with a safe loader; duplicate keys refused
report = vs.validate(doc)                          # report.errors, report.warnings, report.soft_used

notation = precedence.Notation.from_dict(...)      # see the Notation docstring: a draft view of the library
resolved = precedence.resolve(
    doc, notation,
    diagram_type="WestbrookContextView",
    overrides=[{"path": "paint.application.style.fill_color", "value": "#FFE699",
                "reason": "Reviewer asked for amber on this page"}],
    ref="westbrook-standards.yaml")

resolved.thing_style(thing)            # the render plan's `style`, colors resolved to #RRGGBB
resolved.connector_style(relationship)
resolved.shape_data_rows(thing)        # the notation's defaults, then the standards' sets
resolved.legend_entries(things, relationships)
resolved.title_block_values(view, generated_at)
resolved.provenance()                  # {"standards_ref": ..., "overrides": [{path, value, reason}, ...]}
```

`resolve` raises `PrecedenceRefused` (with `.findings`, each carrying a `code` and a reason) when
the file is invalid, when it tries to decide something the notation owns, or when an instruction
reaches outside paint and frame. Nothing is half applied. The standards document passed in is
never changed, so the next diagram starts from the standards again.

Paths in findings are the same paths an override uses (`paint.application.style.fill_color`).
List items that have an `id` or `name` are addressed by it, not by position.

## The checker

The schema is a Python validator, `validate_standards.py`, not a JSON Schema. The checks that
matter here are not shape checks. A refusal has to say why, unknown keys need did-you-mean
hints, and a few rules cross fields (a `list` row needs `values`, a `constant` field needs a
`value`). The notation library's own loader works the same way. The contracts themselves stay JSON
Schema; the standards file is the one a person edits, so it gets the friendlier checker.

```
python validate_standards.py westbrook-standards.yaml   # prints findings, exits 1 on any error
python validate_standards.py --write-readme            # refreshes the two generated tables below
python -m pytest plugins -q                            # from the repository root
```

It needs PyYAML. Files are parsed with a safe loader that also refuses a duplicate key (plain
YAML silently keeps the last one).

## Key reference

Generated from the schema. A test fails if it goes stale.

<!-- reference:start (generated: python validate_standards.py --write-readme) -->

| Path | Type | Required | Soft | Meaning |
|---|---|---|---|---|
| `contract` | constant | yes |  | Contract name. |
| `contract_version` | `0.1` | yes |  | Contract version; quote it. A reader refuses a version it does not know. |
| `id` | string | yes |  | Stable id of this standards definition. |
| `name` | string | yes |  | Name of the definition, for people. |
| `owner` | string | yes |  | The practice that owns the file. |
| `description` | string |  |  | What the standards are for. |
| `unit` | `in` / `mm` / `pt` |  |  | Unit of every length in the file. Absent: `in`. |
| `colors` | mapping |  |  | Named colors, used as `$name` elsewhere. Change one here, change it everywhere. |
| `colors.*` | color (`#RRGGBB`) |  |  |  |
| `type` | mapping |  |  | Type. |
| `type.font_family` | string | yes |  | Font for every label. |
| `type.font_color` | color (`#RRGGBB` or `$name`) |  |  | Default text color. |
| `type.sizes` | mapping | yes |  | Font sizes by role, in points. |
| `type.sizes.shape_label` | number | yes |  | Font size in points for shape labels. |
| `type.sizes.connector_label` | number | yes |  | Font size in points for connector labels. |
| `type.sizes.title` | number | yes |  | Font size in points for the title. |
| `type.sizes.note` | number | yes |  | Font size in points for notes. |
| `type.sizes.legend` | number | yes |  | Font size in points for the legend. |
| `page` | mapping |  |  | Page size and orientation. |
| `page.size` | `Letter` / `A4` / `A3` / `Tabloid` / `custom` | yes |  | Named page size, or `custom` with `width` and `height`. |
| `page.orientation` | `portrait` / `landscape` | yes |  | Page orientation. |
| `page.width` | number |  |  | Page width in `unit`; with `height`, required when `size` is `custom`. |
| `page.height` | number |  |  | Page height in `unit`. |
| `page.margin` | number |  |  | Margin inside the page edge, in `unit`. |
| `paint` | list |  |  | Palette and meaning. Every rule whose `when` matches a thing applies, in order; later rules win per field. A thing's concept is never changed. |
| `paint[]` | mapping |  |  |  |
| `paint[].id` | string | yes |  | Rule id; also how a per-diagram override addresses the rule. |
| `paint[].label` | string |  |  | Name of the category, for people. |
| `paint[].when` | mapping | yes |  | Which things this rule paints. |
| `paint[].when.kinds` | list |  | soft | Concept names to match, bare or qualified. A thing matches when its `kind` or `qualified_kind` is listed. |
| `paint[].when.kinds[]` | string |  |  |  |
| `paint[].when.metaclasses` | list |  | soft | Base types to match (`Component`, `Node`). |
| `paint[].when.metaclasses[]` | string |  |  |  |
| `paint[].when.language` | string |  | soft | Match only things of this language. |
| `paint[].when.properties` | mapping |  |  | Property name to a value, or a list of values (any of). `external: true` selects things whose `external` property is true. |
| `paint[].when.properties.*` | scalar or list of scalars |  |  |  |
| `paint[].style` | mapping | yes |  | Paint applied to matching things. |
| `paint[].style.fill_color` | color (`#RRGGBB` or `$name`) |  |  | Fill color of the shape. |
| `paint[].style.line_color` | color (`#RRGGBB` or `$name`) |  |  | Outline color of a shape, or the color of a connector. |
| `paint[].style.line_weight` | number |  |  | Line weight in points. |
| `paint[].style.line_pattern` | `solid` / `dash` / `dot` / `dash-dot` / `none` |  |  | Outline or connector pattern. |
| `paint[].style.rounding` | number |  |  | Corner rounding, in the file's `unit`. |
| `paint[].style.font_family` | string |  |  | Font family for this element. |
| `paint[].style.font_size` | number |  |  | Font size in points. |
| `paint[].style.font_color` | color (`#RRGGBB` or `$name`) |  |  | Text color. |
| `paint[].style.bold` | boolean |  |  | Bold text. |
| `paint[].style.italic` | boolean |  |  | Italic text. |
| `paint[].style.text_align` | `left` / `center` / `right` |  |  | Text alignment. |
| `paint[].legend` | string |  |  | Text that explains this paint in the legend. A rule that sets a color or pattern without it is an unexplained color. |
| `lines` | mapping |  |  | Lines. |
| `lines.routing` | `straight` / `orthogonal` / `curved` |  | soft | Routing preference, over the notation's default. |
| `lines.default` | mapping |  |  | Paint for every connector. |
| `lines.default.line_color` | color (`#RRGGBB` or `$name`) |  |  | Outline color of a shape, or the color of a connector. |
| `lines.default.line_weight` | number |  |  | Line weight in points. |
| `lines.default.line_pattern` | `solid` / `dash` / `dot` / `dash-dot` / `none` |  |  | Outline or connector pattern. |
| `lines.default.begin_arrow` | `none` / `filled-triangle` / `open-arrow` / `filled-diamond` / `open-diamond` / `circle` |  |  | Arrowhead at the source end. |
| `lines.default.end_arrow` | `none` / `filled-triangle` / `open-arrow` / `filled-diamond` / `open-diamond` / `circle` |  |  | Arrowhead at the target end. |
| `lines.default.font_color` | color (`#RRGGBB` or `$name`) |  |  | Text color. |
| `lines.default.bold` | boolean |  |  | Bold text. |
| `lines.default.italic` | boolean |  |  | Italic text. |
| `lines.by_kind` | mapping |  | soft | Relationship kind (bare or qualified) to line paint and legend. |
| `lines.by_kind.*` | mapping |  |  |  |
| `lines.by_kind.*.style` | mapping | yes |  | Paint for connectors of this kind. |
| `lines.by_kind.*.style.line_color` | color (`#RRGGBB` or `$name`) |  |  | Outline color of a shape, or the color of a connector. |
| `lines.by_kind.*.style.line_weight` | number |  |  | Line weight in points. |
| `lines.by_kind.*.style.line_pattern` | `solid` / `dash` / `dot` / `dash-dot` / `none` |  |  | Outline or connector pattern. |
| `lines.by_kind.*.style.begin_arrow` | `none` / `filled-triangle` / `open-arrow` / `filled-diamond` / `open-diamond` / `circle` |  |  | Arrowhead at the source end. |
| `lines.by_kind.*.style.end_arrow` | `none` / `filled-triangle` / `open-arrow` / `filled-diamond` / `open-diamond` / `circle` |  |  | Arrowhead at the target end. |
| `lines.by_kind.*.style.font_color` | color (`#RRGGBB` or `$name`) |  |  | Text color. |
| `lines.by_kind.*.style.bold` | boolean |  |  | Bold text. |
| `lines.by_kind.*.style.italic` | boolean |  |  | Italic text. |
| `lines.by_kind.*.legend` | string |  |  | Text that explains this line in the legend. |
| `furniture` | mapping |  |  | Page furniture. Keys are the render plan's `furniture_kind` values. |
| `furniture.border` | mapping |  |  | Page border. |
| `furniture.border.enabled` | boolean | yes |  | Whether diagrams carry this item. |
| `furniture.border.position` | mapping |  |  | Where the item sits on the page. |
| `furniture.border.position.anchor` | `top-left` / `top-center` / `top-right` / `bottom-left` / `bottom-center` / `bottom-right` | yes |  | Page corner or edge the item hangs from, inside the page margin. |
| `furniture.border.position.offset_x` | number |  |  | Distance inward from the anchor along the page's width, in `unit`. |
| `furniture.border.position.offset_y` | number |  |  | Distance inward from the anchor along the page's height, in `unit`. |
| `furniture.border.width` | number or `auto` / `content` |  |  | Width in `unit`; `content` spans the page inside the margins, `auto` fits the text. |
| `furniture.border.height` | number or `auto` |  |  | Height in `unit`, or `auto` to fit the text. |
| `furniture.border.style` | mapping |  |  | Paint for the item's frame and text. |
| `furniture.border.style.fill_color` | color (`#RRGGBB` or `$name`) |  |  | Fill color of the shape. |
| `furniture.border.style.line_color` | color (`#RRGGBB` or `$name`) |  |  | Outline color of a shape, or the color of a connector. |
| `furniture.border.style.line_weight` | number |  |  | Line weight in points. |
| `furniture.border.style.line_pattern` | `solid` / `dash` / `dot` / `dash-dot` / `none` |  |  | Outline or connector pattern. |
| `furniture.border.style.rounding` | number |  |  | Corner rounding, in the file's `unit`. |
| `furniture.border.style.font_family` | string |  |  | Font family for this element. |
| `furniture.border.style.font_size` | number |  |  | Font size in points. |
| `furniture.border.style.font_color` | color (`#RRGGBB` or `$name`) |  |  | Text color. |
| `furniture.border.style.bold` | boolean |  |  | Bold text. |
| `furniture.border.style.italic` | boolean |  |  | Italic text. |
| `furniture.border.style.text_align` | `left` / `center` / `right` |  |  | Text alignment. |
| `furniture.border.master` | mapping |  | soft | Visio master that draws the item. Absent: the composition skill's default. |
| `furniture.border.master.stencil` | string | yes |  | Stencil that holds the master. |
| `furniture.border.master.name` | string | yes |  | Master name in that stencil. |
| `furniture.border.margin` | number |  |  | Gap between the page edge and the border, in `unit`. |
| `furniture.title-block` | mapping |  |  | Title block. |
| `furniture.title-block.enabled` | boolean | yes |  | Whether diagrams carry this item. |
| `furniture.title-block.position` | mapping |  |  | Where the item sits on the page. |
| `furniture.title-block.position.anchor` | `top-left` / `top-center` / `top-right` / `bottom-left` / `bottom-center` / `bottom-right` | yes |  | Page corner or edge the item hangs from, inside the page margin. |
| `furniture.title-block.position.offset_x` | number |  |  | Distance inward from the anchor along the page's width, in `unit`. |
| `furniture.title-block.position.offset_y` | number |  |  | Distance inward from the anchor along the page's height, in `unit`. |
| `furniture.title-block.width` | number or `auto` / `content` |  |  | Width in `unit`; `content` spans the page inside the margins, `auto` fits the text. |
| `furniture.title-block.height` | number or `auto` |  |  | Height in `unit`, or `auto` to fit the text. |
| `furniture.title-block.style` | mapping |  |  | Paint for the item's frame and text. |
| `furniture.title-block.style.fill_color` | color (`#RRGGBB` or `$name`) |  |  | Fill color of the shape. |
| `furniture.title-block.style.line_color` | color (`#RRGGBB` or `$name`) |  |  | Outline color of a shape, or the color of a connector. |
| `furniture.title-block.style.line_weight` | number |  |  | Line weight in points. |
| `furniture.title-block.style.line_pattern` | `solid` / `dash` / `dot` / `dash-dot` / `none` |  |  | Outline or connector pattern. |
| `furniture.title-block.style.rounding` | number |  |  | Corner rounding, in the file's `unit`. |
| `furniture.title-block.style.font_family` | string |  |  | Font family for this element. |
| `furniture.title-block.style.font_size` | number |  |  | Font size in points. |
| `furniture.title-block.style.font_color` | color (`#RRGGBB` or `$name`) |  |  | Text color. |
| `furniture.title-block.style.bold` | boolean |  |  | Bold text. |
| `furniture.title-block.style.italic` | boolean |  |  | Italic text. |
| `furniture.title-block.style.text_align` | `left` / `center` / `right` |  |  | Text alignment. |
| `furniture.title-block.master` | mapping |  | soft | Visio master that draws the item. Absent: the composition skill's default. |
| `furniture.title-block.master.stencil` | string | yes |  | Stencil that holds the master. |
| `furniture.title-block.master.name` | string | yes |  | Master name in that stencil. |
| `furniture.title-block.format` | `line` / `table` |  |  | One line of text, or a labeled table. |
| `furniture.title-block.separator` | string |  |  | Text between fields in `line` format. |
| `furniture.title-block.show_labels` | boolean |  |  | Print each field's label in `line` format. |
| `furniture.title-block.fields` | list |  |  | Fields in order. The review board expects the revision and the author role; list them here. |
| `furniture.title-block.fields[]` | mapping |  |  |  |
| `furniture.title-block.fields[].name` | string | yes |  | Field id; how an override addresses the field. |
| `furniture.title-block.fields[].label` | string | yes |  | Label printed beside the value. |
| `furniture.title-block.fields[].source` | `view.title` / `view.revision` / `view.description` / `generated_at` / `constant` | yes |  | Where the value comes from. |
| `furniture.title-block.fields[].value` | string |  |  | The value, when `source` is `constant` (an author role, never a person). |
| `furniture.title-block.fields[].required` | boolean |  |  | A diagram without this value fails verification. |
| `furniture.legend` | mapping |  |  | Legend. |
| `furniture.legend.enabled` | boolean | yes |  | Whether diagrams carry this item. |
| `furniture.legend.position` | mapping |  |  | Where the item sits on the page. |
| `furniture.legend.position.anchor` | `top-left` / `top-center` / `top-right` / `bottom-left` / `bottom-center` / `bottom-right` | yes |  | Page corner or edge the item hangs from, inside the page margin. |
| `furniture.legend.position.offset_x` | number |  |  | Distance inward from the anchor along the page's width, in `unit`. |
| `furniture.legend.position.offset_y` | number |  |  | Distance inward from the anchor along the page's height, in `unit`. |
| `furniture.legend.width` | number or `auto` / `content` |  |  | Width in `unit`; `content` spans the page inside the margins, `auto` fits the text. |
| `furniture.legend.height` | number or `auto` |  |  | Height in `unit`, or `auto` to fit the text. |
| `furniture.legend.style` | mapping |  |  | Paint for the item's frame and text. |
| `furniture.legend.style.fill_color` | color (`#RRGGBB` or `$name`) |  |  | Fill color of the shape. |
| `furniture.legend.style.line_color` | color (`#RRGGBB` or `$name`) |  |  | Outline color of a shape, or the color of a connector. |
| `furniture.legend.style.line_weight` | number |  |  | Line weight in points. |
| `furniture.legend.style.line_pattern` | `solid` / `dash` / `dot` / `dash-dot` / `none` |  |  | Outline or connector pattern. |
| `furniture.legend.style.rounding` | number |  |  | Corner rounding, in the file's `unit`. |
| `furniture.legend.style.font_family` | string |  |  | Font family for this element. |
| `furniture.legend.style.font_size` | number |  |  | Font size in points. |
| `furniture.legend.style.font_color` | color (`#RRGGBB` or `$name`) |  |  | Text color. |
| `furniture.legend.style.bold` | boolean |  |  | Bold text. |
| `furniture.legend.style.italic` | boolean |  |  | Italic text. |
| `furniture.legend.style.text_align` | `left` / `center` / `right` |  |  | Text alignment. |
| `furniture.legend.master` | mapping |  | soft | Visio master that draws the item. Absent: the composition skill's default. |
| `furniture.legend.master.stencil` | string | yes |  | Stencil that holds the master. |
| `furniture.legend.master.name` | string | yes |  | Master name in that stencil. |
| `furniture.legend.mode` | `derived` / `explicit` |  |  | `derived`: built from the `legend` text of the paint and line rules in use. `explicit`: the `entries` below. |
| `furniture.legend.title` | string |  |  | Legend heading. |
| `furniture.legend.only_used` | boolean |  |  | Derived mode: list only rules that matched something on the page. |
| `furniture.legend.entries` | list |  |  | Entries for `explicit` mode. |
| `furniture.legend.entries[]` | mapping |  |  |  |
| `furniture.legend.entries[].label` | string | yes |  | Text beside the sample. |
| `furniture.legend.entries[].swatch` | `shape` / `line` | yes |  | Draw a shape sample or a line sample. |
| `furniture.legend.entries[].style` | mapping | yes |  | Paint of the sample. |
| `furniture.legend.entries[].style.fill_color` | color (`#RRGGBB` or `$name`) |  |  | Fill color of the shape. |
| `furniture.legend.entries[].style.line_color` | color (`#RRGGBB` or `$name`) |  |  | Outline color of a shape, or the color of a connector. |
| `furniture.legend.entries[].style.line_weight` | number |  |  | Line weight in points. |
| `furniture.legend.entries[].style.line_pattern` | `solid` / `dash` / `dot` / `dash-dot` / `none` |  |  | Outline or connector pattern. |
| `furniture.legend.entries[].style.rounding` | number |  |  | Corner rounding, in the file's `unit`. |
| `furniture.legend.entries[].style.font_family` | string |  |  | Font family for this element. |
| `furniture.legend.entries[].style.font_size` | number |  |  | Font size in points. |
| `furniture.legend.entries[].style.font_color` | color (`#RRGGBB` or `$name`) |  |  | Text color. |
| `furniture.legend.entries[].style.bold` | boolean |  |  | Bold text. |
| `furniture.legend.entries[].style.italic` | boolean |  |  | Italic text. |
| `furniture.legend.entries[].style.text_align` | `left` / `center` / `right` |  |  | Text alignment. |
| `furniture.legend.entries[].style.begin_arrow` | `none` / `filled-triangle` / `open-arrow` / `filled-diamond` / `open-diamond` / `circle` |  |  | Arrowhead at the source end. |
| `furniture.legend.entries[].style.end_arrow` | `none` / `filled-triangle` / `open-arrow` / `filled-diamond` / `open-diamond` / `circle` |  |  | Arrowhead at the target end. |
| `furniture.note` | mapping |  |  | Notes panel. |
| `furniture.note.enabled` | boolean | yes |  | Whether diagrams carry this item. |
| `furniture.note.position` | mapping |  |  | Where the item sits on the page. |
| `furniture.note.position.anchor` | `top-left` / `top-center` / `top-right` / `bottom-left` / `bottom-center` / `bottom-right` | yes |  | Page corner or edge the item hangs from, inside the page margin. |
| `furniture.note.position.offset_x` | number |  |  | Distance inward from the anchor along the page's width, in `unit`. |
| `furniture.note.position.offset_y` | number |  |  | Distance inward from the anchor along the page's height, in `unit`. |
| `furniture.note.width` | number or `auto` / `content` |  |  | Width in `unit`; `content` spans the page inside the margins, `auto` fits the text. |
| `furniture.note.height` | number or `auto` |  |  | Height in `unit`, or `auto` to fit the text. |
| `furniture.note.style` | mapping |  |  | Paint for the item's frame and text. |
| `furniture.note.style.fill_color` | color (`#RRGGBB` or `$name`) |  |  | Fill color of the shape. |
| `furniture.note.style.line_color` | color (`#RRGGBB` or `$name`) |  |  | Outline color of a shape, or the color of a connector. |
| `furniture.note.style.line_weight` | number |  |  | Line weight in points. |
| `furniture.note.style.line_pattern` | `solid` / `dash` / `dot` / `dash-dot` / `none` |  |  | Outline or connector pattern. |
| `furniture.note.style.rounding` | number |  |  | Corner rounding, in the file's `unit`. |
| `furniture.note.style.font_family` | string |  |  | Font family for this element. |
| `furniture.note.style.font_size` | number |  |  | Font size in points. |
| `furniture.note.style.font_color` | color (`#RRGGBB` or `$name`) |  |  | Text color. |
| `furniture.note.style.bold` | boolean |  |  | Bold text. |
| `furniture.note.style.italic` | boolean |  |  | Italic text. |
| `furniture.note.style.text_align` | `left` / `center` / `right` |  |  | Text alignment. |
| `furniture.note.master` | mapping |  | soft | Visio master that draws the item. Absent: the composition skill's default. |
| `furniture.note.master.stencil` | string | yes |  | Stencil that holds the master. |
| `furniture.note.master.name` | string | yes |  | Master name in that stencil. |
| `furniture.note.title` | string |  |  | Panel heading. |
| `furniture.note.source` | `view.description` / `constant` |  |  | Where the panel's text comes from. |
| `furniture.note.text` | string |  |  | Fixed text, when `source` is `constant`. |
| `furniture.logo` | mapping |  |  | Logo. |
| `furniture.logo.enabled` | boolean | yes |  | Whether diagrams carry this item. |
| `furniture.logo.position` | mapping |  |  | Where the item sits on the page. |
| `furniture.logo.position.anchor` | `top-left` / `top-center` / `top-right` / `bottom-left` / `bottom-center` / `bottom-right` | yes |  | Page corner or edge the item hangs from, inside the page margin. |
| `furniture.logo.position.offset_x` | number |  |  | Distance inward from the anchor along the page's width, in `unit`. |
| `furniture.logo.position.offset_y` | number |  |  | Distance inward from the anchor along the page's height, in `unit`. |
| `furniture.logo.width` | number or `auto` / `content` |  |  | Width in `unit`; `content` spans the page inside the margins, `auto` fits the text. |
| `furniture.logo.height` | number or `auto` |  |  | Height in `unit`, or `auto` to fit the text. |
| `furniture.logo.style` | mapping |  |  | Paint for the item's frame and text. |
| `furniture.logo.style.fill_color` | color (`#RRGGBB` or `$name`) |  |  | Fill color of the shape. |
| `furniture.logo.style.line_color` | color (`#RRGGBB` or `$name`) |  |  | Outline color of a shape, or the color of a connector. |
| `furniture.logo.style.line_weight` | number |  |  | Line weight in points. |
| `furniture.logo.style.line_pattern` | `solid` / `dash` / `dot` / `dash-dot` / `none` |  |  | Outline or connector pattern. |
| `furniture.logo.style.rounding` | number |  |  | Corner rounding, in the file's `unit`. |
| `furniture.logo.style.font_family` | string |  |  | Font family for this element. |
| `furniture.logo.style.font_size` | number |  |  | Font size in points. |
| `furniture.logo.style.font_color` | color (`#RRGGBB` or `$name`) |  |  | Text color. |
| `furniture.logo.style.bold` | boolean |  |  | Bold text. |
| `furniture.logo.style.italic` | boolean |  |  | Italic text. |
| `furniture.logo.style.text_align` | `left` / `center` / `right` |  |  | Text alignment. |
| `furniture.logo.master` | mapping |  | soft | Visio master that draws the item. Absent: the composition skill's default. |
| `furniture.logo.master.stencil` | string | yes |  | Stencil that holds the master. |
| `furniture.logo.master.name` | string | yes |  | Master name in that stencil. |
| `furniture.logo.asset` | string |  |  | Image file, relative to the standards file. |
| `furniture.logo.alt` | string |  |  | Alternative text for the image. |
| `shape_data` | list |  |  | Shape Data set: which rows a shape (or connector) of a kind carries, and which are shown on it. |
| `shape_data[]` | mapping |  |  |  |
| `shape_data[].id` | string | yes |  | Set id; also how an override addresses the set. |
| `shape_data[].target` | `shape` / `connector` |  |  | What carries the rows. Absent: `shape`. |
| `shape_data[].when` | mapping | yes |  | Which things or relationships carry these rows. |
| `shape_data[].when.kinds` | list |  | soft | Concept names to match, bare or qualified. A thing matches when its `kind` or `qualified_kind` is listed. |
| `shape_data[].when.kinds[]` | string |  |  |  |
| `shape_data[].when.metaclasses` | list |  | soft | Base types to match (`Component`, `Node`). |
| `shape_data[].when.metaclasses[]` | string |  |  |  |
| `shape_data[].when.language` | string |  | soft | Match only things of this language. |
| `shape_data[].when.properties` | mapping |  |  | Property name to a value, or a list of values (any of). `external: true` selects things whose `external` property is true. |
| `shape_data[].when.properties.*` | scalar or list of scalars |  |  |  |
| `shape_data[].rows` | list | yes |  | Rows in order. Names starting `APT_` are reserved. |
| `shape_data[].rows[]` | mapping |  |  |  |
| `shape_data[].rows[].name` | string | yes |  | Shape Data row name; letters, digits and `_`. `APT_` names are reserved. |
| `shape_data[].rows[].label` | string |  |  | Label in the Shape Data window. |
| `shape_data[].rows[].type` | `string` / `number` / `boolean` / `date` / `list` / `currency` |  |  | Row type. Absent: the content's declaration, else `string`. |
| `shape_data[].rows[].values` | list |  |  | Permitted choices; only for `type: list`. |
| `shape_data[].rows[].values[]` | string, number or boolean |  |  |  |
| `shape_data[].rows[].from_property` | string |  |  | Content property that supplies the value. Absent: the row's `name`. |
| `shape_data[].rows[].invisible` | boolean |  |  | Hide the row from the Shape Data window. |
| `shape_data[].rows[].show_on_shape` | boolean |  |  | Show the value on the shape as a data graphic. |
| `shape_data[].rows[].graphic` | mapping |  | soft | How a shown value is drawn. |
| `shape_data[].rows[].graphic.type` | `text` / `icon` / `bar` / `color` | yes |  | How the value is drawn. |
| `shape_data[].rows[].graphic.position` | `top-left` / `top-center` / `top-right` / `bottom-left` / `bottom-center` / `bottom-right` |  |  | Where on the shape. |
| `diagram_types` | mapping |  |  | The practice's own diagram types, keyed by name. |
| `diagram_types.*` | mapping |  |  | A diagram type of the practice, in the library's form. |
| `diagram_types.*.display_name` | string |  |  | Name shown to people. |
| `diagram_types.*.description` | string |  |  | What the diagram is for. |
| `diagram_types.*.refines` | mapping |  | soft | The notation's diagram type this one is drawn on. Sizing and spacing it does not state are inherited. Absent: a type of the practice's own. |
| `diagram_types.*.refines.language` | string | yes |  | Notation language id. |
| `diagram_types.*.refines.type` | string | yes |  | That language's diagram type name. |
| `diagram_types.*.admits` | list |  | soft | Concepts this diagram admits. When the type refines a notation type, only a subset of what that type admits. |
| `diagram_types.*.admits[]` | string |  |  |  |
| `diagram_types.*.grammar` | `layered-bands` / `lanes` / `nested-grid` / `radial` / `two-column-cycle` / `computed-geometry` / `matrix` / `radial-tree` / `chevron-stack` / `treemap` / `graph` / `ea-semantic` | yes | soft | Layout grammar. |
| `diagram_types.*.title` | `drawn` | yes | soft | Title convention. Visio has no diagram frame, so the title is drawn. |
| `diagram_types.*.sizing` | mapping |  | soft | Concept name to `{w, h}` in `unit`. `default` is the fallback box. |
| `diagram_types.*.sizing.*` | mapping |  |  |  |
| `diagram_types.*.sizing.*.w` | number | yes |  | Width, in `unit`. |
| `diagram_types.*.sizing.*.h` | number | yes |  | Height, in `unit`. |
| `diagram_types.*.spacing` | mapping |  | soft | Gaps and padding, in `unit`, named as the composition engine names them. |
| `diagram_types.*.spacing.item_gap_x` | number |  |  | `item_gap_x`, in `unit`. |
| `diagram_types.*.spacing.item_gap_y` | number |  |  | `item_gap_y`, in `unit`. |
| `diagram_types.*.spacing.item_gap_flow` | number |  |  | `item_gap_flow`, in `unit`. |
| `diagram_types.*.spacing.band_gap` | number |  |  | `band_gap`, in `unit`. |
| `diagram_types.*.spacing.band_pad_x` | number |  |  | `band_pad_x`, in `unit`. |
| `diagram_types.*.spacing.band_pad_y` | number |  |  | `band_pad_y`, in `unit`. |
| `diagram_types.*.spacing.lane_gap` | number |  |  | `lane_gap`, in `unit`. |
| `diagram_types.*.spacing.lane_pad` | number |  |  | `lane_pad`, in `unit`. |
| `diagram_types.*.spacing.grid_pad` | number |  |  | `grid_pad`, in `unit`. |
| `diagram_types.*.spacing.label_height` | number |  |  | `label_height`, in `unit`. |
| `diagram_types.*.spacing.label_width` | number |  |  | `label_width`, in `unit`. |
| `diagram_types.*.spacing.wrap_width` | number |  |  | `wrap_width`, in `unit`. |
| `diagram_types.*.spacing.align` | `left` / `center` / `right` |  |  | Alignment of items within a band or lane. |
| `diagram_types.*.routing` | mapping | yes | soft | Connector routing for this type. |
| `diagram_types.*.routing.default` | `straight` / `orthogonal` / `curved` | yes |  | Default connector route. |
| `diagram_types.*.routing.trunk_for` | list |  |  | Relationship kinds drawn as a shared trunk. |
| `diagram_types.*.routing.trunk_for[]` | string |  |  |  |
| `diagram_types.*.routing.trunk_route` | `straight` / `orthogonal` / `curved` |  |  | Route for a trunk. |
| `diagram_types.*.channels` | mapping | yes | soft | Which visual channels this type already uses, as the library does. |
| `diagram_types.*.channels.fill` | string or `~` | yes |  | What fill means in this diagram type, or `~` if unclaimed. |
| `diagram_types.*.channels.claimed` | mapping |  |  | Channel to the meaning it already carries. |
| `diagram_types.*.channels.claimed.*` | string |  |  |  |
| `diagram_types.*.channels.free` | list |  |  | Channels a second variable may use. |
| `diagram_types.*.channels.free[]` | `fill` / `border` / `border_width` / `line_color` / `line_style` / `font_color` / `opacity` / `icon` / `size` / `position` |  |  |  |
| `diagram_types.*.channels.notes` | string |  |  | Free text. |
| `diagram_types.*.page` | mapping |  |  | Page changes for this diagram type. |
| `diagram_types.*.page.size` | `Letter` / `A4` / `A3` / `Tabloid` / `custom` |  |  | Named page size, or `custom` with `width` and `height`. |
| `diagram_types.*.page.orientation` | `portrait` / `landscape` |  |  | Page orientation. |
| `diagram_types.*.page.width` | number |  |  | Page width in `unit`; with `height`, required when `size` is `custom`. |
| `diagram_types.*.page.height` | number |  |  | Page height in `unit`. |
| `diagram_types.*.page.margin` | number |  |  | Margin inside the page edge, in `unit`. |
| `diagram_types.*.furniture` | mapping |  |  | Furniture changes for this diagram type, merged over the file's `furniture`. |
| `diagram_types.*.furniture.border` | mapping |  |  | Page border. |
| `diagram_types.*.furniture.border.enabled` | boolean |  |  | Whether diagrams carry this item. |
| `diagram_types.*.furniture.border.position` | mapping |  |  | Where the item sits on the page. |
| `diagram_types.*.furniture.border.position.anchor` | `top-left` / `top-center` / `top-right` / `bottom-left` / `bottom-center` / `bottom-right` | yes |  | Page corner or edge the item hangs from, inside the page margin. |
| `diagram_types.*.furniture.border.position.offset_x` | number |  |  | Distance inward from the anchor along the page's width, in `unit`. |
| `diagram_types.*.furniture.border.position.offset_y` | number |  |  | Distance inward from the anchor along the page's height, in `unit`. |
| `diagram_types.*.furniture.border.width` | number or `auto` / `content` |  |  | Width in `unit`; `content` spans the page inside the margins, `auto` fits the text. |
| `diagram_types.*.furniture.border.height` | number or `auto` |  |  | Height in `unit`, or `auto` to fit the text. |
| `diagram_types.*.furniture.border.style` | mapping |  |  | Paint for the item's frame and text. |
| `diagram_types.*.furniture.border.style.fill_color` | color (`#RRGGBB` or `$name`) |  |  | Fill color of the shape. |
| `diagram_types.*.furniture.border.style.line_color` | color (`#RRGGBB` or `$name`) |  |  | Outline color of a shape, or the color of a connector. |
| `diagram_types.*.furniture.border.style.line_weight` | number |  |  | Line weight in points. |
| `diagram_types.*.furniture.border.style.line_pattern` | `solid` / `dash` / `dot` / `dash-dot` / `none` |  |  | Outline or connector pattern. |
| `diagram_types.*.furniture.border.style.rounding` | number |  |  | Corner rounding, in the file's `unit`. |
| `diagram_types.*.furniture.border.style.font_family` | string |  |  | Font family for this element. |
| `diagram_types.*.furniture.border.style.font_size` | number |  |  | Font size in points. |
| `diagram_types.*.furniture.border.style.font_color` | color (`#RRGGBB` or `$name`) |  |  | Text color. |
| `diagram_types.*.furniture.border.style.bold` | boolean |  |  | Bold text. |
| `diagram_types.*.furniture.border.style.italic` | boolean |  |  | Italic text. |
| `diagram_types.*.furniture.border.style.text_align` | `left` / `center` / `right` |  |  | Text alignment. |
| `diagram_types.*.furniture.border.master` | mapping |  | soft | Visio master that draws the item. Absent: the composition skill's default. |
| `diagram_types.*.furniture.border.master.stencil` | string | yes |  | Stencil that holds the master. |
| `diagram_types.*.furniture.border.master.name` | string | yes |  | Master name in that stencil. |
| `diagram_types.*.furniture.border.margin` | number |  |  | Gap between the page edge and the border, in `unit`. |
| `diagram_types.*.furniture.title-block` | mapping |  |  | Title block. |
| `diagram_types.*.furniture.title-block.enabled` | boolean |  |  | Whether diagrams carry this item. |
| `diagram_types.*.furniture.title-block.position` | mapping |  |  | Where the item sits on the page. |
| `diagram_types.*.furniture.title-block.position.anchor` | `top-left` / `top-center` / `top-right` / `bottom-left` / `bottom-center` / `bottom-right` | yes |  | Page corner or edge the item hangs from, inside the page margin. |
| `diagram_types.*.furniture.title-block.position.offset_x` | number |  |  | Distance inward from the anchor along the page's width, in `unit`. |
| `diagram_types.*.furniture.title-block.position.offset_y` | number |  |  | Distance inward from the anchor along the page's height, in `unit`. |
| `diagram_types.*.furniture.title-block.width` | number or `auto` / `content` |  |  | Width in `unit`; `content` spans the page inside the margins, `auto` fits the text. |
| `diagram_types.*.furniture.title-block.height` | number or `auto` |  |  | Height in `unit`, or `auto` to fit the text. |
| `diagram_types.*.furniture.title-block.style` | mapping |  |  | Paint for the item's frame and text. |
| `diagram_types.*.furniture.title-block.style.fill_color` | color (`#RRGGBB` or `$name`) |  |  | Fill color of the shape. |
| `diagram_types.*.furniture.title-block.style.line_color` | color (`#RRGGBB` or `$name`) |  |  | Outline color of a shape, or the color of a connector. |
| `diagram_types.*.furniture.title-block.style.line_weight` | number |  |  | Line weight in points. |
| `diagram_types.*.furniture.title-block.style.line_pattern` | `solid` / `dash` / `dot` / `dash-dot` / `none` |  |  | Outline or connector pattern. |
| `diagram_types.*.furniture.title-block.style.rounding` | number |  |  | Corner rounding, in the file's `unit`. |
| `diagram_types.*.furniture.title-block.style.font_family` | string |  |  | Font family for this element. |
| `diagram_types.*.furniture.title-block.style.font_size` | number |  |  | Font size in points. |
| `diagram_types.*.furniture.title-block.style.font_color` | color (`#RRGGBB` or `$name`) |  |  | Text color. |
| `diagram_types.*.furniture.title-block.style.bold` | boolean |  |  | Bold text. |
| `diagram_types.*.furniture.title-block.style.italic` | boolean |  |  | Italic text. |
| `diagram_types.*.furniture.title-block.style.text_align` | `left` / `center` / `right` |  |  | Text alignment. |
| `diagram_types.*.furniture.title-block.master` | mapping |  | soft | Visio master that draws the item. Absent: the composition skill's default. |
| `diagram_types.*.furniture.title-block.master.stencil` | string | yes |  | Stencil that holds the master. |
| `diagram_types.*.furniture.title-block.master.name` | string | yes |  | Master name in that stencil. |
| `diagram_types.*.furniture.title-block.format` | `line` / `table` |  |  | One line of text, or a labeled table. |
| `diagram_types.*.furniture.title-block.separator` | string |  |  | Text between fields in `line` format. |
| `diagram_types.*.furniture.title-block.show_labels` | boolean |  |  | Print each field's label in `line` format. |
| `diagram_types.*.furniture.title-block.fields` | list |  |  | Fields in order. The review board expects the revision and the author role; list them here. |
| `diagram_types.*.furniture.title-block.fields[]` | mapping |  |  |  |
| `diagram_types.*.furniture.title-block.fields[].name` | string | yes |  | Field id; how an override addresses the field. |
| `diagram_types.*.furniture.title-block.fields[].label` | string | yes |  | Label printed beside the value. |
| `diagram_types.*.furniture.title-block.fields[].source` | `view.title` / `view.revision` / `view.description` / `generated_at` / `constant` | yes |  | Where the value comes from. |
| `diagram_types.*.furniture.title-block.fields[].value` | string |  |  | The value, when `source` is `constant` (an author role, never a person). |
| `diagram_types.*.furniture.title-block.fields[].required` | boolean |  |  | A diagram without this value fails verification. |
| `diagram_types.*.furniture.legend` | mapping |  |  | Legend. |
| `diagram_types.*.furniture.legend.enabled` | boolean |  |  | Whether diagrams carry this item. |
| `diagram_types.*.furniture.legend.position` | mapping |  |  | Where the item sits on the page. |
| `diagram_types.*.furniture.legend.position.anchor` | `top-left` / `top-center` / `top-right` / `bottom-left` / `bottom-center` / `bottom-right` | yes |  | Page corner or edge the item hangs from, inside the page margin. |
| `diagram_types.*.furniture.legend.position.offset_x` | number |  |  | Distance inward from the anchor along the page's width, in `unit`. |
| `diagram_types.*.furniture.legend.position.offset_y` | number |  |  | Distance inward from the anchor along the page's height, in `unit`. |
| `diagram_types.*.furniture.legend.width` | number or `auto` / `content` |  |  | Width in `unit`; `content` spans the page inside the margins, `auto` fits the text. |
| `diagram_types.*.furniture.legend.height` | number or `auto` |  |  | Height in `unit`, or `auto` to fit the text. |
| `diagram_types.*.furniture.legend.style` | mapping |  |  | Paint for the item's frame and text. |
| `diagram_types.*.furniture.legend.style.fill_color` | color (`#RRGGBB` or `$name`) |  |  | Fill color of the shape. |
| `diagram_types.*.furniture.legend.style.line_color` | color (`#RRGGBB` or `$name`) |  |  | Outline color of a shape, or the color of a connector. |
| `diagram_types.*.furniture.legend.style.line_weight` | number |  |  | Line weight in points. |
| `diagram_types.*.furniture.legend.style.line_pattern` | `solid` / `dash` / `dot` / `dash-dot` / `none` |  |  | Outline or connector pattern. |
| `diagram_types.*.furniture.legend.style.rounding` | number |  |  | Corner rounding, in the file's `unit`. |
| `diagram_types.*.furniture.legend.style.font_family` | string |  |  | Font family for this element. |
| `diagram_types.*.furniture.legend.style.font_size` | number |  |  | Font size in points. |
| `diagram_types.*.furniture.legend.style.font_color` | color (`#RRGGBB` or `$name`) |  |  | Text color. |
| `diagram_types.*.furniture.legend.style.bold` | boolean |  |  | Bold text. |
| `diagram_types.*.furniture.legend.style.italic` | boolean |  |  | Italic text. |
| `diagram_types.*.furniture.legend.style.text_align` | `left` / `center` / `right` |  |  | Text alignment. |
| `diagram_types.*.furniture.legend.master` | mapping |  | soft | Visio master that draws the item. Absent: the composition skill's default. |
| `diagram_types.*.furniture.legend.master.stencil` | string | yes |  | Stencil that holds the master. |
| `diagram_types.*.furniture.legend.master.name` | string | yes |  | Master name in that stencil. |
| `diagram_types.*.furniture.legend.mode` | `derived` / `explicit` |  |  | `derived`: built from the `legend` text of the paint and line rules in use. `explicit`: the `entries` below. |
| `diagram_types.*.furniture.legend.title` | string |  |  | Legend heading. |
| `diagram_types.*.furniture.legend.only_used` | boolean |  |  | Derived mode: list only rules that matched something on the page. |
| `diagram_types.*.furniture.legend.entries` | list |  |  | Entries for `explicit` mode. |
| `diagram_types.*.furniture.legend.entries[]` | mapping |  |  |  |
| `diagram_types.*.furniture.legend.entries[].label` | string | yes |  | Text beside the sample. |
| `diagram_types.*.furniture.legend.entries[].swatch` | `shape` / `line` | yes |  | Draw a shape sample or a line sample. |
| `diagram_types.*.furniture.legend.entries[].style` | mapping | yes |  | Paint of the sample. |
| `diagram_types.*.furniture.legend.entries[].style.fill_color` | color (`#RRGGBB` or `$name`) |  |  | Fill color of the shape. |
| `diagram_types.*.furniture.legend.entries[].style.line_color` | color (`#RRGGBB` or `$name`) |  |  | Outline color of a shape, or the color of a connector. |
| `diagram_types.*.furniture.legend.entries[].style.line_weight` | number |  |  | Line weight in points. |
| `diagram_types.*.furniture.legend.entries[].style.line_pattern` | `solid` / `dash` / `dot` / `dash-dot` / `none` |  |  | Outline or connector pattern. |
| `diagram_types.*.furniture.legend.entries[].style.rounding` | number |  |  | Corner rounding, in the file's `unit`. |
| `diagram_types.*.furniture.legend.entries[].style.font_family` | string |  |  | Font family for this element. |
| `diagram_types.*.furniture.legend.entries[].style.font_size` | number |  |  | Font size in points. |
| `diagram_types.*.furniture.legend.entries[].style.font_color` | color (`#RRGGBB` or `$name`) |  |  | Text color. |
| `diagram_types.*.furniture.legend.entries[].style.bold` | boolean |  |  | Bold text. |
| `diagram_types.*.furniture.legend.entries[].style.italic` | boolean |  |  | Italic text. |
| `diagram_types.*.furniture.legend.entries[].style.text_align` | `left` / `center` / `right` |  |  | Text alignment. |
| `diagram_types.*.furniture.legend.entries[].style.begin_arrow` | `none` / `filled-triangle` / `open-arrow` / `filled-diamond` / `open-diamond` / `circle` |  |  | Arrowhead at the source end. |
| `diagram_types.*.furniture.legend.entries[].style.end_arrow` | `none` / `filled-triangle` / `open-arrow` / `filled-diamond` / `open-diamond` / `circle` |  |  | Arrowhead at the target end. |
| `diagram_types.*.furniture.note` | mapping |  |  | Notes panel. |
| `diagram_types.*.furniture.note.enabled` | boolean |  |  | Whether diagrams carry this item. |
| `diagram_types.*.furniture.note.position` | mapping |  |  | Where the item sits on the page. |
| `diagram_types.*.furniture.note.position.anchor` | `top-left` / `top-center` / `top-right` / `bottom-left` / `bottom-center` / `bottom-right` | yes |  | Page corner or edge the item hangs from, inside the page margin. |
| `diagram_types.*.furniture.note.position.offset_x` | number |  |  | Distance inward from the anchor along the page's width, in `unit`. |
| `diagram_types.*.furniture.note.position.offset_y` | number |  |  | Distance inward from the anchor along the page's height, in `unit`. |
| `diagram_types.*.furniture.note.width` | number or `auto` / `content` |  |  | Width in `unit`; `content` spans the page inside the margins, `auto` fits the text. |
| `diagram_types.*.furniture.note.height` | number or `auto` |  |  | Height in `unit`, or `auto` to fit the text. |
| `diagram_types.*.furniture.note.style` | mapping |  |  | Paint for the item's frame and text. |
| `diagram_types.*.furniture.note.style.fill_color` | color (`#RRGGBB` or `$name`) |  |  | Fill color of the shape. |
| `diagram_types.*.furniture.note.style.line_color` | color (`#RRGGBB` or `$name`) |  |  | Outline color of a shape, or the color of a connector. |
| `diagram_types.*.furniture.note.style.line_weight` | number |  |  | Line weight in points. |
| `diagram_types.*.furniture.note.style.line_pattern` | `solid` / `dash` / `dot` / `dash-dot` / `none` |  |  | Outline or connector pattern. |
| `diagram_types.*.furniture.note.style.rounding` | number |  |  | Corner rounding, in the file's `unit`. |
| `diagram_types.*.furniture.note.style.font_family` | string |  |  | Font family for this element. |
| `diagram_types.*.furniture.note.style.font_size` | number |  |  | Font size in points. |
| `diagram_types.*.furniture.note.style.font_color` | color (`#RRGGBB` or `$name`) |  |  | Text color. |
| `diagram_types.*.furniture.note.style.bold` | boolean |  |  | Bold text. |
| `diagram_types.*.furniture.note.style.italic` | boolean |  |  | Italic text. |
| `diagram_types.*.furniture.note.style.text_align` | `left` / `center` / `right` |  |  | Text alignment. |
| `diagram_types.*.furniture.note.master` | mapping |  | soft | Visio master that draws the item. Absent: the composition skill's default. |
| `diagram_types.*.furniture.note.master.stencil` | string | yes |  | Stencil that holds the master. |
| `diagram_types.*.furniture.note.master.name` | string | yes |  | Master name in that stencil. |
| `diagram_types.*.furniture.note.title` | string |  |  | Panel heading. |
| `diagram_types.*.furniture.note.source` | `view.description` / `constant` |  |  | Where the panel's text comes from. |
| `diagram_types.*.furniture.note.text` | string |  |  | Fixed text, when `source` is `constant`. |
| `diagram_types.*.furniture.logo` | mapping |  |  | Logo. |
| `diagram_types.*.furniture.logo.enabled` | boolean |  |  | Whether diagrams carry this item. |
| `diagram_types.*.furniture.logo.position` | mapping |  |  | Where the item sits on the page. |
| `diagram_types.*.furniture.logo.position.anchor` | `top-left` / `top-center` / `top-right` / `bottom-left` / `bottom-center` / `bottom-right` | yes |  | Page corner or edge the item hangs from, inside the page margin. |
| `diagram_types.*.furniture.logo.position.offset_x` | number |  |  | Distance inward from the anchor along the page's width, in `unit`. |
| `diagram_types.*.furniture.logo.position.offset_y` | number |  |  | Distance inward from the anchor along the page's height, in `unit`. |
| `diagram_types.*.furniture.logo.width` | number or `auto` / `content` |  |  | Width in `unit`; `content` spans the page inside the margins, `auto` fits the text. |
| `diagram_types.*.furniture.logo.height` | number or `auto` |  |  | Height in `unit`, or `auto` to fit the text. |
| `diagram_types.*.furniture.logo.style` | mapping |  |  | Paint for the item's frame and text. |
| `diagram_types.*.furniture.logo.style.fill_color` | color (`#RRGGBB` or `$name`) |  |  | Fill color of the shape. |
| `diagram_types.*.furniture.logo.style.line_color` | color (`#RRGGBB` or `$name`) |  |  | Outline color of a shape, or the color of a connector. |
| `diagram_types.*.furniture.logo.style.line_weight` | number |  |  | Line weight in points. |
| `diagram_types.*.furniture.logo.style.line_pattern` | `solid` / `dash` / `dot` / `dash-dot` / `none` |  |  | Outline or connector pattern. |
| `diagram_types.*.furniture.logo.style.rounding` | number |  |  | Corner rounding, in the file's `unit`. |
| `diagram_types.*.furniture.logo.style.font_family` | string |  |  | Font family for this element. |
| `diagram_types.*.furniture.logo.style.font_size` | number |  |  | Font size in points. |
| `diagram_types.*.furniture.logo.style.font_color` | color (`#RRGGBB` or `$name`) |  |  | Text color. |
| `diagram_types.*.furniture.logo.style.bold` | boolean |  |  | Bold text. |
| `diagram_types.*.furniture.logo.style.italic` | boolean |  |  | Italic text. |
| `diagram_types.*.furniture.logo.style.text_align` | `left` / `center` / `right` |  |  | Text alignment. |
| `diagram_types.*.furniture.logo.master` | mapping |  | soft | Visio master that draws the item. Absent: the composition skill's default. |
| `diagram_types.*.furniture.logo.master.stencil` | string | yes |  | Stencil that holds the master. |
| `diagram_types.*.furniture.logo.master.name` | string | yes |  | Master name in that stencil. |
| `diagram_types.*.furniture.logo.asset` | string |  |  | Image file, relative to the standards file. |
| `diagram_types.*.furniture.logo.alt` | string |  |  | Alternative text for the image. |
| `diagram_types.*.notes` | string |  |  | Free text. |
| `notes` | string |  |  | Free text. |

<!-- reference:end -->

## Alignment change list

Every field that borrows from a schema that is not settled is marked **soft**. When the notation
library's schema lands, each row below is checked against it, changed if it differs, and its
status set. Generated from the schema; a test fails if a soft field is missing here.

<!-- soft:start (generated: python validate_standards.py --write-readme) -->

| Field | Depends on | What will need aligning | Status |
|---|---|---|---|
| `paint[].when.kinds` | notation library (APT-2026-0472) | Concept names - bare, qualified (`WBA::WBABusinessApplication`) or as the notation writes them | open |
| `paint[].when.metaclasses` | notation library (APT-2026-0472) | Where a concept's base type is recorded | open |
| `paint[].when.language` | notation library (APT-2026-0472) | Language ids | open |
| `lines.routing` | notation library (APT-2026-0472) | The notation's routing convention uses EA's route names | open |
| `lines.by_kind` | notation library (APT-2026-0472) | Relationship names | open |
| `furniture.border.master` | notation library (APT-2026-0472) | The Visio rendering section decides which masters draw furniture | open |
| `furniture.title-block.master` | notation library (APT-2026-0472) | The Visio rendering section decides which masters draw furniture | open |
| `furniture.legend.master` | notation library (APT-2026-0472) | The Visio rendering section decides which masters draw furniture | open |
| `furniture.note.master` | notation library (APT-2026-0472) | The Visio rendering section decides which masters draw furniture | open |
| `furniture.logo.master` | notation library (APT-2026-0472) | The Visio rendering section decides which masters draw furniture | open |
| `shape_data[].when.kinds` | notation library (APT-2026-0472) | Concept names - bare, qualified (`WBA::WBABusinessApplication`) or as the notation writes them | open |
| `shape_data[].when.metaclasses` | notation library (APT-2026-0472) | Where a concept's base type is recorded | open |
| `shape_data[].when.language` | notation library (APT-2026-0472) | Language ids | open |
| `shape_data[].rows[].graphic` | typed Shape Data and data graphics (APV-2026-0013) | How a shown row is drawn (text, icon, bar, color) until the data graphics model is fixed | open |
| `diagram_types.*.refines` | notation library (APT-2026-0472) | Language and diagram type ids | open |
| `diagram_types.*.admits` | notation library (APT-2026-0472) | Concept names, and whether `admits` sits on the diagram type or on a viewpoint | open |
| `diagram_types.*.grammar` | notation library (APT-2026-0472) | Grammar vocabulary (hyphenated here; the contracts draft writes underscores) | open |
| `diagram_types.*.title` | notation library (APT-2026-0472) | The library also has `frame-header`, which has no Visio meaning | open |
| `diagram_types.*.sizing` | notation library (APT-2026-0472) | Integer EA pixels today; the declared unit is undecided | open |
| `diagram_types.*.spacing` | notation library (APT-2026-0472) | Key names (the composition engine's) and unit | open |
| `diagram_types.*.routing` | notation library (APT-2026-0472) | The library names EA's ten routes; Visio's are three | open |
| `diagram_types.*.channels` | notation library (APT-2026-0472) | Channel names; the style-field to channel map is this draft's proposal | open |
| `diagram_types.*.furniture.border.master` | notation library (APT-2026-0472) | The Visio rendering section decides which masters draw furniture | open |
| `diagram_types.*.furniture.title-block.master` | notation library (APT-2026-0472) | The Visio rendering section decides which masters draw furniture | open |
| `diagram_types.*.furniture.legend.master` | notation library (APT-2026-0472) | The Visio rendering section decides which masters draw furniture | open |
| `diagram_types.*.furniture.note.master` | notation library (APT-2026-0472) | The Visio rendering section decides which masters draw furniture | open |
| `diagram_types.*.furniture.logo.master` | notation library (APT-2026-0472) | The Visio rendering section decides which masters draw furniture | open |

<!-- soft:end -->

Beyond single fields, these are the cross-cutting items to align, none yet done:

| Item | Today | To settle |
|---|---|---|
| Grammar spelling | Hyphenated, as the library's loader spells them (`layered-bands`) | The contracts draft writes five of them with underscores (`layered_bands`); one spelling must win |
| Declared unit | The file declares its own `unit` (default `in`); the merge refuses to inherit a notation type's sizing and spacing when the units differ | The library's unit and conversion (its decision 3) |
| Route names | `straight`, `orthogonal`, `curved`, the render plan's | The library names EA's ten routes; its Visio rendering section must map them |
| Style field to channel map | `precedence.THING_CHANNEL` and `CONNECTOR_CHANNEL`, this draft's proposal | The library's channel meanings |
| Concept names in selectors | Bare or qualified names, matched against the content's `kind` and `qualified_kind` | How the library writes concept names |
| Where `admits` sits | On a practice's diagram type | On the library's diagram type or viewpoint |
| Furniture masters | `furniture.*.master` optional; absent means the composition skill's default | The library's Visio rendering section |
| `title` | Only `drawn` | The library also has `frame-header`, which has no Visio meaning |
| Override shape | A list of `{path, value, reason}` | The view definition's `standards.overrides` example shows `{}`; the contracts draft should state the list |
| The notation stub | `precedence.Notation.from_dict` reads a hand-written dictionary | A loader adapter over the library, when it exists |

## Not covered

- Presentation profiles and viewpoints (how much detail a view shows) are the notation library's;
  a practice cannot define them here yet.
- Per-diagram-type paint. Paint is file-wide; a practice type carries page and furniture changes
  only.
- Checking a drawn page against the standards (missing legend, wrong font, an unexplained
  color, a title block without a revision) and drafting a file from an existing diagram are
  APV-2026-0021. This module gives it the schema and the merge.
