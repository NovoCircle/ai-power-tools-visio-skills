# Where `fidelity.py` came from

`fidelity.py` is a copy, byte for byte, of the fidelity checker in the AI Power Tools for Sparx EA
skills library. It is copied rather than rewritten so that it can later be replaced by an import
from a shared location without anything else changing.

| | |
|---|---|
| Library | `ai-power-tools-skills` (public) |
| Path in that library | `plugins/ai-power-tools/skills/ea-diagram-composition/tools/fidelity.py` |
| Commit it was copied from | `0baca5baa7ec182e0907bdfc60ee388464c9e1a2` (last commit to touch the file; the library's `main` was at `91a997b92d76cb745c9529368ea2ab84adc14e36` when copied) |
| sha256 of the copied bytes | `3bdda20149d3f007a8a68a5a35612ac1ec2086b1aaaaf04c480a684c3534b0dc` |

`test_fidelity.py` is copied from the same commit (source sha256
`2e9de4ddb150869d7c67ac458b5f49a0968f868fe550f56723a637ec780499f2`) with one change: the source
imports the EA skill's linter, which this library does not have, so the import is guarded and the
single test that uses it, `test_a_faithful_reproduction_of_a_hand_placed_diagram_fails_the_linter`,
skips with its reason until a linter is importable here. Every other test passes unchanged. Run
against the source, all 50 tests pass; here, 49 pass and 1 skips.

`fidelity_page_read.py` is the only code written for this library. It reshapes a page read
(top-left origin, inches, y down) into the checker's input (EA's negative-y rectangles) and calls
the checker. It changes none of the checker's arithmetic and adds no tolerance: the tolerance is
the reference reading's declared `precision`, as in the source.

To replace the copy with an import, delete `fidelity.py` and `test_fidelity.py` here, make the
shared module importable as `fidelity`, and run the tests in this directory; `fidelity_page_read.py`
needs no change.
