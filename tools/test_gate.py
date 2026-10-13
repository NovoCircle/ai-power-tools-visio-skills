"""Tests for the release gate.

The gate is what we accept releases on: if it stops catching something, every
later release passes silently and we find out from a customer. Until now it
was the one piece of code here with nothing proving it, while `regen-manifest`
— its sibling — had already shipped a release-breaking bug of exactly this
kind (it wrote CRLF, so every downloaded file failed its hash check).

So each test below feeds the gate something known-bad and asserts it complains,
and something known-good and asserts it does not. A gate that stops checking is
indistinguishable from a gate that passes, which is the whole problem.

Run:  python -m pytest tools/test_gate.py
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_GATE_PATH = Path(__file__).resolve().parent / "gate.py"
_spec = importlib.util.spec_from_file_location("gate_under_test", _GATE_PATH)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


@pytest.fixture
def library(tmp_path, monkeypatch):
    """A throwaway library root the gate treats as its own."""
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    return tmp_path


def _write(root: Path, rel: str, text: str, *, encoding="utf-8", newline="\n") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding=encoding, newline=newline) as fh:
        fh.write(text)
    return p


def _findings(path: Path) -> str:
    return " | ".join(gate.check_file(path))


# ---------------------------------------------------------------------------
# Rule 1 — identifiers that must never ship
# ---------------------------------------------------------------------------

class TestForbiddenIdentifiers:
    @pytest.mark.parametrize("line,expect", [
        ("The TVO model was the source.", "TVO"),
        ("Applied to the TEA repository.", "TEA"),
        ("Delivered for CA EDD last year.", "EDD"),
        ("TechVentures used this pattern.", "TechVentures"),
    ])
    def test_a_real_customer_identifier_is_caught(self, library, line, expect):
        f = _write(library, "s/SKILL.md", f"# s\n\n{line}\n")
        assert expect.lower() in _findings(f).lower()

    @pytest.mark.parametrize("line", [
        "Probe for TEA Framework, APM and BCM, which ship with EA.",
        "Stereotypes in the `TEA Framework::Capability` namespace are Sparx's own.",
    ])
    def test_the_sparx_shipped_tea_framework_is_allowed(self, library, line):
        f = _write(library, "s/SKILL.md", f"# s\n\n{line}\n")
        assert "TEA" not in _findings(f)

    @pytest.mark.parametrize("line", [
        "Install the TEA Framework Extension first.",
        "Our TEA Framework custom MDG adds two stereotypes.",
        "Load the TEA Framework Profile.",
        "Apply TEA::Capability to the element.",
    ])
    def test_a_customer_extension_of_tea_framework_is_caught(self, library, line):
        f = _write(library, "s/SKILL.md", f"# s\n\n{line}\n")
        assert "tea" in _findings(f).lower()

    def test_a_personal_identifier_is_caught(self, library):
        f = _write(library, "s/SKILL.md", "# s\n\nAsk rschmierer about it.\n")
        assert "personal identifier" in _findings(f)

    @pytest.mark.parametrize("line", [
        r"Open C:\SparxServices\demos\model.qea",
        r"See C:\Users\Ryan\AppData\Roaming\Claude",
        "Run /c/SparxServices/tools/gate.py",
    ])
    def test_an_absolute_local_path_is_caught(self, library, line):
        f = _write(library, "s/SKILL.md", f"# s\n\n{line}\n")
        assert "absolute local path" in _findings(f)

    @pytest.mark.parametrize("line", [
        r"Open C:\Users\<you>\AppData\Roaming\Claude",
        r"Open C:\Users\%USERNAME%\AppData",
    ])
    def test_a_placeholder_path_is_not_a_false_positive(self, library, line):
        # The reader substitutes their own name; flagging this would train
        # people to ignore the gate.
        f = _write(library, "s/SKILL.md", f"# s\n\n{line}\n")
        assert "absolute local path" not in _findings(f)

    def test_westbrook_is_allowed(self, library):
        f = _write(library, "s/SKILL.md",
                   "# s\n\nUse WBA::WBABusinessApplication in WestbrookBank.qea\n")
        assert _findings(f) == ""


# ---------------------------------------------------------------------------
# Rule 2 — identifiers we do not recognize, which may be the next customer
# ---------------------------------------------------------------------------

class TestUnknownIdentifiers:
    def test_an_unrecognized_model_file_is_reported(self, library):
        f = _write(library, "s/SKILL.md", "# s\n\nOpen NorthWindBank.qea\n")
        assert "unrecognized model file" in _findings(f)

    def test_an_unrecognized_mdg_namespace_is_reported(self, library):
        f = _write(library, "s/SKILL.md", "# s\n\nUse ACME::AcmeThing here\n")
        assert "unrecognized MDG namespace" in _findings(f)

    def test_a_sparx_shipped_technology_is_not_reported(self, library):
        f = _write(library, "s/SKILL.md", "# s\n\nUse ArchiMate3::ArchiMate_Node\n")
        assert "unrecognized" not in _findings(f)

    def test_a_sparx_id_containing_a_space_is_not_reported(self, library):
        """`MDG_NS` cannot see a space, so these need their own allowance.

        The pattern captures only the last word before `::`, so
        `TOGAF Diagrams::TOGAF_Interface` arrives as `Diagrams` and
        `ZF Owner::OwnerTime` as `Owner` - both real Sparx-shipped ids, and both
        were blocking honest bindings until the full id was matched instead.
        """
        for text in ("Use TOGAF Diagrams::TOGAF_Interface here",
                     "Use ZF Owner::OwnerTime here",
                     "Use ZF Planner::PlannerData here"):
            f = _write(library, "s/SKILL.md", "# s\n\n" + text + "\n")
            assert "unrecognized" not in _findings(f), text

    def test_the_bare_word_before_the_space_is_still_unknown(self, library):
        """THE REASON THE FULL ID IS MATCHED RATHER THAN THE BARE WORD.

        Adding `Diagrams` and `Owner` to `KNOWN_IDS` would have been the one-line
        fix, and it would have whitelisted every customer whose technology
        happens to end in one of those words - the exact opposite of what this
        rule exists for. This fails if anyone ever takes that shortcut.
        """
        for text in ("Use Acme Diagrams::AcmeThing here",
                     "Use Contoso Owner::ContosoThing here",
                     "Use Diagrams::Thing here"):
            f = _write(library, "s/SKILL.md", "# s\n\n" + text + "\n")
            assert "unrecognized MDG namespace" in _findings(f), text



# ---------------------------------------------------------------------------
# Encoding — the class that broke v1.4.1
# ---------------------------------------------------------------------------

class TestEncoding:
    def test_a_utf8_bom_is_caught(self, library):
        p = library / "s" / "SKILL.md"
        p.parent.mkdir(parents=True)
        p.write_bytes(b"\xef\xbb\xbf# s\n\nplain\n")
        assert "BOM" in _findings(p)

    def test_mojibake_is_caught(self, library):
        p = library / "s" / "SKILL.md"
        p.parent.mkdir(parents=True)
        # An em dash written as cp1252 and read back as UTF-8.
        p.write_bytes("# s\n\nbroken \u00e2\u20ac\u201d dash\n".encode("utf-8"))
        assert "mojibake" in _findings(p)

    def test_curly_quotes_inside_a_code_fence_are_caught(self, library):
        f = _write(library, "s/SKILL.md",
                   '# s\n\n```python\nx = \u201chello\u201d\n```\n')
        assert "curly quotes" in _findings(f)

    def test_curly_quotes_in_prose_are_allowed(self, library):
        # Prose is read, not pasted into a shell.
        f = _write(library, "s/SKILL.md", '# s\n\nHe said \u201chello\u201d to her.\n')
        assert "curly quotes" not in _findings(f)


# ---------------------------------------------------------------------------
# Size limit
# ---------------------------------------------------------------------------

class TestSkillLineLimit:
    def test_an_oversized_skill_is_caught(self, library):
        body = "\n".join(f"line {i}" for i in range(gate.MAX_SKILL_LINES + 5))
        f = _write(library, "s/SKILL.md", body + "\n")
        assert "over the" in _findings(f)

    def test_a_skill_at_the_limit_passes(self, library):
        body = "\n".join(f"line {i}" for i in range(gate.MAX_SKILL_LINES - 1))
        f = _write(library, "s/SKILL.md", body + "\n")
        assert "over the" not in _findings(f)

    def test_the_limit_applies_only_to_skill_md(self, library):
        body = "\n".join(f"line {i}" for i in range(gate.MAX_SKILL_LINES + 50))
        f = _write(library, "s/references/long.md", body + "\n")
        assert "over the" not in _findings(f)



class TestStatedServerVersion:
    """APT-2026-0337: the tools line and the manifest floor must agree."""

    def _setup(self, root: Path, tools_line: str, floor: str = "3.6.0") -> None:
        _write(root, "s/SKILL.md",
               f"# s\n\n{tools_line}\n\nBody v1.0.0+ is not the tools line.\n")
        payload = {"manifest_version": 1, "bundle_version": "9.9.9",
                   "skills": [{"name": "s", "min_server_version": floor,
                               "files": ["s/SKILL.md"], "sha256": {}}]}
        (root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_a_stated_version_other_than_the_floor_is_caught(self, library):
        self._setup(library, "*Tools: `ea_model` (AI Power Tools for EA, v2.1.0+)*")
        found = gate.check_stated_server_version()
        assert len(found) == 1
        assert "states v2.1.0+" in found[0] and "is 3.6.0" in found[0]

    def test_a_stated_version_on_a_continuation_line_is_read(self, library):
        self._setup(library, "*Tools: `ea_model` and `ea_analyze`,\nAI Power Tools v2.1.0+*")
        assert len(gate.check_stated_server_version()) == 1

    def test_a_matching_version_passes(self, library):
        self._setup(library, "*Tools: `ea_model` (AI Power Tools for EA, v3.6.0+)*")
        assert gate.check_stated_server_version() == []

    def test_no_stated_version_passes_and_body_versions_are_ignored(self, library):
        self._setup(library, "*Tools: `ea_model`*")
        assert gate.check_stated_server_version() == []


class TestBundleFloor:
    """The bundle-level floor is the installer's all-or-nothing guard."""

    def _manifest(self, root: Path, bundle: str, *skill_floors: str) -> None:
        payload = {"manifest_version": 1, "bundle_version": "9.9.9",
                   "skills": [{"name": f"s{i}", "min_server_version": f}
                              for i, f in enumerate(skill_floors)]}
        if bundle:
            payload["min_server_version"] = bundle
        _write(root, "manifest.json", json.dumps(payload, indent=2))

    def test_a_bundle_floor_below_a_skill_floor_is_caught(self, library):
        self._manifest(library, "3.0.0", "2.2.0", "3.6.0")
        found = gate.check_bundle_floor()
        assert len(found) == 1
        assert "is 3.0.0" in found[0] and "s1 requires 3.6.0" in found[0]

    def test_versions_compare_numerically_not_as_text(self, library):
        self._manifest(library, "3.9.0", "3.10.0")
        assert len(gate.check_bundle_floor()) == 1

    def test_a_missing_bundle_floor_is_caught(self, library):
        self._manifest(library, "", "2.2.0")
        assert "missing" in gate.check_bundle_floor()[0]

    def test_a_bundle_floor_equal_to_the_highest_skill_floor_passes(self, library):
        self._manifest(library, "3.6.0", "2.2.0", "3.6.0")
        assert gate.check_bundle_floor() == []

    def test_a_bundle_floor_above_every_skill_floor_passes(self, library):
        self._manifest(library, "3.6.0", "2.2.0", "3.0.0")
        assert gate.check_bundle_floor() == []

    def test_no_manifest_is_not_this_checks_business(self, library):
        assert gate.check_bundle_floor() == []


# ---------------------------------------------------------------------------
# Manifest integrity — the check that caught the v1.4.1 CRLF bug
# ---------------------------------------------------------------------------

class TestManifest:
    def _manifest(self, root: Path, sha: str) -> None:
        payload = {
            "manifest_version": 1, "bundle_version": "9.9.9",
            "skills": [{"name": "s", "files": ["s/SKILL.md"], "sha256": {"s/SKILL.md": sha}}],
        }
        with (root / "manifest.json").open("w", encoding="utf-8", newline="") as fh:
            fh.write(json.dumps(payload, indent=2))

    def test_a_stale_hash_is_caught(self, library):
        _write(library, "s/SKILL.md", "# s\n\nreal content\n")
        self._manifest(library, "0" * 64)
        assert any("stale sha256" in f for f in gate.check_manifest())

    def test_a_matching_hash_passes(self, library):
        import hashlib
        p = _write(library, "s/SKILL.md", "# s\n\nreal content\n")
        self._manifest(library, hashlib.sha256(p.read_bytes()).hexdigest())
        assert not [f for f in gate.check_manifest() if "stale sha256" in f]

    def test_a_crlf_manifest_is_caught(self, library):
        """This exact fault broke the v1.4.1 release.

        Assets hash as LF, the manifest ships as CRLF, and every post-download
        hash check fails on the customer's machine.
        """
        import hashlib
        p = _write(library, "s/SKILL.md", "# s\n\nreal content\n")
        payload = {
            "manifest_version": 1, "bundle_version": "9.9.9",
            "skills": [{"name": "s", "files": ["s/SKILL.md"],
                        "sha256": {"s/SKILL.md": hashlib.sha256(p.read_bytes()).hexdigest()}}],
        }
        (library / "manifest.json").write_bytes(
            json.dumps(payload, indent=2).replace("\n", "\r\n").encode("utf-8")
        )
        assert any("CRLF" in f for f in gate.check_manifest())


# ---------------------------------------------------------------------------
# The negative case that matters most
# ---------------------------------------------------------------------------

def test_a_clean_file_produces_no_findings(library):
    f = _write(library, "visio-modeling/SKILL.md", (
        "---\n"
        "name: visio-modeling\n"
        "description: Build diagrams.\n"
        "---\n\n"
        "# Modeling\n\n"
        "Use `visio_shapes(operation=\"add_shape\", params={})` to build "
        "WestbrookBank-ApplicationLandscape.vsdx.\n"
    ))
    assert gate.check_file(f) == []


# ---------------------------------------------------------------------------
# The plugin is skills only, and its version files agree
# ---------------------------------------------------------------------------

PLUGIN = "ai-power-tools-visio"


class TestPluginPackage:
    """No server in the plugin; plugin.json, manifest.json and marketplace.json agree."""

    VERSION = "9.9.9"

    def _plugin(self, root: Path, *, extra: dict | None = None,
                version: str | None = None) -> None:
        version = version or self.VERSION
        pj = {"name": PLUGIN, "version": version, **(extra or {})}
        _write(root, f"plugins/{PLUGIN}/.claude-plugin/plugin.json", json.dumps(pj))
        (root / "manifest.json").write_text(
            json.dumps({"bundle_version": version, "skills": []}), encoding="utf-8")
        _write(root, ".claude-plugin/marketplace.json", json.dumps(
            {"plugins": [{"name": PLUGIN, "version": version}]}))

    def test_a_skills_only_plugin_passes(self, library):
        self._plugin(library)
        assert gate.check_plugin_package() == []

    def test_no_plugin_tree_is_not_a_finding(self, library):
        assert gate.check_plugin_package() == []

    def test_any_mcp_servers_entry_is_caught(self, library):
        for value in ("https://example.invalid/Server.mcpb", {"x": {}}, ""):
            self._plugin(library, extra={"mcpServers": value})
            found = gate.check_plugin_package()
            assert len(found) == 1 and "mcpServers" in found[0]

    def test_a_top_level_bin_is_caught(self, library):
        self._plugin(library)
        _write(library, f"plugins/{PLUGIN}/bin/server.txt", "x")
        found = gate.check_plugin_package()
        assert len(found) == 1 and "bin/" in found[0]

    def test_version_drift_between_the_files_is_caught(self, library):
        self._plugin(library)
        (library / "manifest.json").write_text(
            json.dumps({"bundle_version": "9.9.8", "skills": []}), encoding="utf-8")
        assert "Version drift" in gate.check_plugin_package()[0]

    def test_a_marketplace_entry_that_lags_the_plugin_is_caught(self, library):
        self._plugin(library)
        _write(library, ".claude-plugin/marketplace.json", json.dumps(
            {"plugins": [{"name": PLUGIN, "version": "9.9.8"}]}))
        assert "Version drift" in gate.check_plugin_package()[0]


# ---------------------------------------------------------------------------
# The marketplace serves released skills only
# ---------------------------------------------------------------------------

SHA = "a" * 40


class TestMarketplacePin:
    """A draft entry points at no release; a release must pin its tag and commit."""

    def _entry(self, root: Path, *, ref, sha, version="1.2.3", source="git-subdir"):
        src = {"source": source, "url": "https://example.invalid/r.git",
               "path": f"plugins/{PLUGIN}"}
        if ref is not None:
            src["ref"] = ref
        if sha is not None:
            src["sha"] = sha
        _write(root, ".claude-plugin/marketplace.json", json.dumps(
            {"plugins": [{"name": PLUGIN, "source": src, "version": version}]}))

    def test_no_marketplace_is_not_a_finding(self, library):
        assert gate.check_marketplace_pin() == []
        assert gate.check_marketplace_pin(release=True) == []

    def test_the_placeholder_passes_on_a_development_branch(self, library):
        self._entry(library, ref=gate.PLACEHOLDER_PIN, sha=gate.PLACEHOLDER_PIN)
        assert gate.check_marketplace_pin() == []

    def test_the_placeholder_is_refused_on_the_release_path(self, library):
        self._entry(library, ref=gate.PLACEHOLDER_PIN, sha=gate.PLACEHOLDER_PIN)
        found = gate.check_marketplace_pin(release=True)
        assert len(found) == 1 and "placeholder" in found[0]

    def test_a_real_pin_passes_both_ways(self, library):
        self._entry(library, ref="v1.2.3", sha=SHA)
        assert gate.check_marketplace_pin() == []
        assert gate.check_marketplace_pin(release=True) == []

    @pytest.mark.parametrize("ref", ["dev", "main", "release/1.2", "1.2.3", "v1.2"])
    def test_a_branch_or_loose_ref_is_caught(self, library, ref):
        """A branch name here would make the marketplace serve development."""
        self._entry(library, ref=ref, sha=SHA)
        assert "ref/sha must both be" in gate.check_marketplace_pin()[0]

    def test_a_missing_ref_or_sha_is_caught(self, library):
        for ref, sha in ((None, None), ("v1.2.3", None), (None, SHA)):
            self._entry(library, ref=ref, sha=sha)
            assert gate.check_marketplace_pin(), (ref, sha)

    def test_a_half_placeholder_is_caught(self, library):
        self._entry(library, ref="v1.2.3", sha=gate.PLACEHOLDER_PIN)
        assert gate.check_marketplace_pin()

    def test_a_short_sha_is_caught(self, library):
        self._entry(library, ref="v1.2.3", sha="abc123")
        assert gate.check_marketplace_pin()

    def test_a_pin_whose_version_disagrees_is_caught(self, library):
        self._entry(library, ref="v1.2.3", sha=SHA, version="1.2.4")
        assert "does not match the pinned ref" in gate.check_marketplace_pin()[0]

    def test_a_bare_path_source_is_caught(self, library):
        _write(library, ".claude-plugin/marketplace.json", json.dumps(
            {"plugins": [{"name": PLUGIN, "source": f"./plugins/{PLUGIN}"}]}))
        assert "git-subdir" in gate.check_marketplace_pin()[0]


class TestRunTheGate:
    """The command line, end to end, against a throwaway library."""

    def _run(self, monkeypatch, capsys, *argv):
        monkeypatch.setattr("sys.argv", ["gate.py", *argv])
        code = gate.main()
        return code, capsys.readouterr().out

    def _library(self, root: Path) -> None:
        _write(root, "manifest.json", json.dumps(
            {"manifest_version": "1.0", "bundle_version": "0.0.0", "skills": []}))
        _write(root, ".claude-plugin/marketplace.json", json.dumps({"plugins": [{
            "name": PLUGIN, "version": "0.0.0",
            "source": {"source": "git-subdir", "url": "https://example.invalid/r.git",
                       "path": f"plugins/{PLUGIN}",
                       "ref": gate.PLACEHOLDER_PIN, "sha": gate.PLACEHOLDER_PIN}}]}))

    def test_an_empty_library_with_a_draft_marketplace_is_green(
            self, library, monkeypatch, capsys):
        self._library(library)
        code, out = self._run(monkeypatch, capsys)
        assert code == 0 and "GATE GREEN" in out

    def test_the_release_flag_turns_the_placeholder_red(
            self, library, monkeypatch, capsys):
        self._library(library)
        code, out = self._run(monkeypatch, capsys, "--release")
        assert code == 1 and "GATE RED" in out and "placeholder" in out

    def test_a_violation_anywhere_turns_the_run_red(self, library, monkeypatch, capsys):
        self._library(library)
        _write(library, "plugins/x/skills/s/SKILL.md", "# s\n\nThe TVO model.\n")
        code, out = self._run(monkeypatch, capsys)
        assert code == 1 and "TVO" in out
