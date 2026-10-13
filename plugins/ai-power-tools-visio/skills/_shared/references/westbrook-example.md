# Westbrook Bank - the example organization for the Visio skills

Westbrook Bank is the fictitious organization used in every example, walkthrough, test fixture
and demo across the AI Power Tools skills. It exists so that no real customer's name, model or
metamodel shape ever ships.

The full specification (stereotypes, tagged values, diagram types, path placeholders, rule ids)
is maintained once, in the AI Power Tools for Sparx EA skills library, and is deliberately not
copied here so the two cannot drift:

<https://github.com/NovoCircle/ai-power-tools-skills/blob/main/plugins/ai-power-tools/skills/_shared/references/westbrook-example.md>

Read it before writing a new example. Do not invent a parallel vocabulary.

## Name slots

| Slot | Value |
|---|---|
| Organization | Westbrook Bank |
| MDG technology id | `WBA` |
| Technology display name | `WestbrookBankArchitecture` |
| Qualified stereotype form | `WBA::WBABusinessApplication` |
| Model file | `WestbrookBank.qea` |

The qualified stereotype form in these skills is `WBA::` followed by the stereotype name. Where
the linked document writes the qualified form with the display name instead, this note takes
precedence and the linked document is being corrected.

## Writing a Visio example

- Name a diagram file `WestbrookBank-<Subject>.vsdx`, for example
  `<diagram-dir>\WestbrookBank-ApplicationLandscape.vsdx`. Never write an absolute local path;
  use a placeholder such as `<diagram-dir>`, or an environment-relative path such as
  `%USERPROFILE%\...`.
- Take the names that appear on shapes from the linked specification (its stereotype list, for
  example `WBABusinessApplication`), so a diagram and the model it depicts tell one story.
- Owners on a shape are a team or a role, such as `Payments Engineering`, never a person.

## Westbrook is an illustration

A customer does not have `WestbrookBank.qea` or the `WBA` technology. No skill step may require
either, and no skill may tell the reader to verify that `WBA` is loaded. Present Westbrook values
as an illustration the reader replaces with their own diagrams, shapes, technology and model.
