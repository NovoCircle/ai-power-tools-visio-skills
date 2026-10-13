#!/usr/bin/env python3
"""Release gate for the AI Power Tools for Microsoft Visio skills library.

Enforces the standing rule: no real customer names, no absolute local paths,
no personal identifiers in anything we ship. Westbrook Bank is the only
permitted example organization.

Usage:
    python tools/gate.py            # check the whole library
    python tools/gate.py <path>     # check one path, relative to the repo root
    python tools/gate.py --release  # also require the marketplace to pin a release

Exit code 0 = clean, 1 = violations found.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Manifest paths are install-relative, so they do not say where a file sits in
#: the repo. Skills live under the plugin -- one tree serving both the
#: marketplace and the packaged `.plugin`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _layout import source_path as _source_path, asset_dirs as _asset_dirs  # noqa: E402

# --------------------------------------------------------------------------
# Rule 1 — known real-customer identifiers. Denylist: catches what we know.
# --------------------------------------------------------------------------
# A path is fine when the user-specific segment is an obvious placeholder:
#   C:\Users\<you>\AppData\...   — the reader substitutes their own name.
# Only a *real* username or our own working tree is a violation.
PLACEHOLDER_PATH = re.compile(r"[A-Za-z]:\\{1,2}Users\\{1,2}[<%{$]")

# "TEA Framework" is a technology that genuinely ships with stock Sparx
# Enterprise Architect, so that exact phrase is allowed. Anything that reads as a
# CUSTOMER extension of it is not: TEA on its own, TEA:: as a stereotype prefix,
# TEA inside a customer's own identifier like "CA EDD TEA", and "TEA Framework"
# followed by extension wording (Extension, Custom, Customization, Profile, MDG,
# Toolbox, Add-in). A customer MDG built on the Sparx technology therefore still
# trips the gate for a human decision. The same rule is in the server repo's gate.
FORBIDDEN = [
    (re.compile(r"\bTVO\b"), "real customer identifier 'TVO'"),
    (re.compile(r"\bTEA\b(?!\s+Framework\b(?!\s+(?i:Extensions?|Extended|Custom|"
                r"Customi[sz](?:ed|ation)|Profiles?|MDG|Toolbox(?:es)?|Add-?ins?)\b))"),
     "real customer identifier 'TEA'"),
    (re.compile(r"\bCA\s+EDD\b|\bEDD\b"), "real customer identifier 'EDD'"),
    (re.compile(r"TechVentures", re.I), "non-canonical example org 'TechVentures'"),
    (re.compile(r"RyanSchmierer|rschmierer", re.I), "personal identifier"),
    (re.compile(r"[A-Za-z]:\\\\?(?:SparxServices|Users)\b"), "absolute local path"),
    (re.compile(r"/c/(?:SparxServices|Users)\b"), "absolute local path"),
]

# --------------------------------------------------------------------------
# Rule 2 — unknown MDG/model identifiers. Allowlist: catches what we don't.
#
# A *new* customer name must trip the gate the first time it appears, so any
# MDG-shaped id or .qea filename that is neither Westbrook nor a Sparx-shipped
# technology is reported for a human decision.
# --------------------------------------------------------------------------
KNOWN_IDS = {
    # Westbrook Bank — the canonical example org
    "WBA", "WestbrookBankArchitecture", "WestbrookBank",
    # Sparx-shipped sample model. Every EA install has it, so citing it is how
    # a measurement in a shipped binding stays reproducible by the reader. It
    # is a vendor file, not anybody's model.
    "EAExample",
    # Sparx-shipped / standard technologies
    "ArchiMate", "ArchiMate2", "ArchiMate3", "BPMN", "BPMN2", "BPMN20",
    # BMM is the OMG Business Motivation Model, shipped by Sparx as
    # InternalTechnologies/BMM.xml, with bmm_* model patterns beside it.
    # Proof it is nobody's project code: EAExample.qea itself stores an
    # element whose stereotype FQName is `BMM::CourseOfAction`.
    "BMM",
    # EA's extended diagram set -- Data Modeling, Dashboard, Requirements
    # and others. A Sparx-shipped technology id, verified from the
    # reference model's own MDGDgm tokens, not a project code.
    "Extended",
    "UML", "SysML", "SysML15", "SysML16", "TOGAF", "DoDAF", "MODAF", "NIEM",
    # UPDM2 is the second-generation Sparx-shipped UPDM technology and appears
    # as an FQName namespace in real repositories (`UPDM2::Node`). `UPDM` alone
    # was listed, so a measurement citing the id EA actually writes was flagged.
    "UPDM", "UPDM2", "SPEM", "SOMF", "BPEL", "XSD", "WSDL", "ERD", "DMN", "CMMN",
    # EA's own internal UML profile. `EAUML::report package` is EA's machinery,
    # which the census has to recognize in order to EXCLUDE it - so the id has
    # to be nameable in our own source.
    "EAUML",
    # The UML 2 Standard Profile EA ships and applies by default. Real
    # repositories carry `StandardProfileL2::Realization` on ordinary
    # Realization connectors, so a skill citing what `t_xref` actually holds
    # was flagged as naming a customer technology.
    "StandardProfileL2",
    "MDG", "EA", "XMI", "SQL", "COM", "API", "XML", "YAML", "JSON", "HTML",
    "PNG", "SVG", "CSV", "UTF", "BOM", "URL", "ID", "OK", "NOT", "AND", "OR",
    # EA's strategic-modeling and mind-mapping MDGs, read from the reference
    # model's own `MDGDgm` values rather than guessed. Both look like a made-up
    # name to this rule precisely because neither spells a standard notation, and
    # both are Sparx-shipped: `StrategyMap` declares six diagram types
    # (StrategyMap, BalancedScorecard, ValueChain, DecisionTree, OrgChart,
    # FlowChart) and `MindMapping` declares one of its own name.
    "StrategyMap", "MindMapping",
    # UAF/UPDM. EA ships this as EIGHT separate technology ids, one per
    # viewpoint, not as one "UAF" — read from the loaded MDG, not guessed.
    # A binding names them because a binding binds exactly one id.
    "UAF", "UAFP", "UAFP_Framework", "UAFP_AV", "UAFP_AcV", "UAFP_OV",
    "UAFP_SOV", "UAFP_SV", "UAFP_SvcV", "UAFP_StV", "UAFP_CV", "UAFP_PV",
    "UAFP_TV", "UAFP_StdV",
    # TOGAF and Zachman, the two FRAMEWORK overlays. Same lesson as UAF: EA does
    # not ship one id per framework. TOGAF is two (`TOGAF Diagrams` and
    # `TOGAF_DataArchitecture`) and Zachman is seven (`ZF` plus one per framework
    # row), read from the loaded MDG rather than guessed. Only the ones without a
    # space belong here; the rest are in KNOWN_SPACED_IDS below, because MDG_NS
    # cannot see a space.
    "TOGAF_DataArchitecture", "ZF", "ZF_Interface", "TOGAF_Interface",
    # UAF/DoDAF/MODAF viewpoint abbreviations. Standard framework vocabulary
    # (Services, Capability, Project, Operational, Strategic, Acquisition,
    # Technical/Standards), not anybody's project code.
    "AV", "AcV", "OV", "SOV", "SV", "SvcV", "StV", "CV", "PV", "TV", "StdV",
    # Deliberately generic test stubs. Two or three interchangeable
    # technologies are needed to test ambiguity and override behavior, and
    # naming them after a real notation would imply the test says something
    # about that notation. No customer is involved.
    "Alpha", "Beta", "Overlay",
    # Generic placeholder model filenames in tests. Not anybody's model.
    "model", "missing",
}

# Sparx-shipped technology ids that CONTAIN A SPACE, which `MDG_NS` cannot see:
# it captures the last word only, so `TOGAF Diagrams::TOGAF_Interface` arrives as
# `Diagrams` and `ZF Owner::OwnerTime` as `Owner`. Putting those bare words into
# KNOWN_IDS would whitelist `Acme Diagrams::` and `Contoso Owner::` along with
# them, which is the opposite of what this rule is for, so the FULL id is matched
# against the line instead and the bare word stays unknown.
KNOWN_SPACED_IDS = (
    "TOGAF Diagrams",
    # Sparx-shipped, and the technology behind the corpus row whose
    # diagram type is TechnicalReferenceModel -- which was being counted
    # under TOGAF until it was measured.
    "FEAF Diagrams",
    "ZF Interface", "ZF Owner", "ZF Designer", "ZF Planner", "ZF Builder",
    "ZF Subcontractor",
    # Sparx-shipped (see the TEA note under Rule 1). Its own namespace is
    # allowed; a customer extension's namespace is not.
    "TEA Framework",
)
QEA_FILE = re.compile(r"\b([A-Za-z][A-Za-z0-9_-]*)\.(?:qea|eapx|eap|feap)\b")
MDG_NS = re.compile(r"\b([A-Z][A-Za-z0-9_]{1,30})::")

# --------------------------------------------------------------------------
# Rule 3 — encoding hygiene
# --------------------------------------------------------------------------
# The first four alternatives are the historical list, kept so nothing that
# used to be caught stops being caught. The fifth is the general rule they
# were special cases of: a double-encoding always leaves a lead character of
# U+00C2 / U+00C3 / U+00E2 followed by another non-ASCII one. The old list
# missed "â‰", which let a mangled >= through in the sibling repo's shipped
# docs. Keep this in step with ea-mcp-server/build.py's _MOJIBAKE.
MOJIBAKE = re.compile("â€|Ã¢|â†|Â |[ÂÃâ][^\x00-\x7f]")
FENCE = re.compile(r"^```")
CURLY = re.compile(r"[\u2018\u2019\u201c\u201d]")

MAX_SKILL_LINES = 400

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".pytest_cache"}
# tools/ holds this script, whose own patterns would trip it.
# gate.py holds the forbidden patterns themselves, and test_gate.py holds
# the fixtures that prove they fire. Both are deliberately full of the
# strings this gate exists to reject, and neither is shipped - the
# manifest does not list tools/.
SKIP_FILES = {"gate.py", "test_gate.py"}


def iter_files(target: Path):
    for p in sorted(target.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.name in SKIP_FILES:
            continue
        if p.suffix.lower() in {".md", ".yaml", ".yml", ".json", ".py", ".txt"}:
            yield p


def check_file(path: Path) -> list[str]:
    out: list[str] = []
    rel = path.relative_to(ROOT)
    raw = path.read_bytes()

    if raw.startswith(b"\xef\xbb\xbf"):
        out.append(f"{rel}:1: UTF-8 BOM — strip it")

    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()

    in_fence = False
    for n, line in enumerate(lines, 1):
        if FENCE.match(line.strip()):
            in_fence = not in_fence
            continue

        for pattern, why in FORBIDDEN:
            if not pattern.search(line):
                continue
            if why == "absolute local path" and PLACEHOLDER_PATH.search(line):
                continue
            out.append(f"{rel}:{n}: {why} — convert to Westbrook Bank: {line.strip()[:90]}")

        if MOJIBAKE.search(line):
            out.append(f"{rel}:{n}: mojibake — file was written as cp1252")

        if in_fence and CURLY.search(line):
            out.append(f"{rel}:{n}: curly quotes inside a code block — breaks copy/paste")

        for m in QEA_FILE.finditer(line):
            if m.group(1) not in KNOWN_IDS:
                out.append(f"{rel}:{n}: unrecognized model file '{m.group(0)}' — "
                           f"if this is a real customer model, convert it")
        for m in MDG_NS.finditer(line):
            ident = m.group(1)
            if ident in KNOWN_IDS or ident.startswith("WBA"):
                continue
            # A known id with a space in it: the capture is only its last word,
            # so the check is whether the text ending there IS the whole id.
            if any(line[:m.end(1)].endswith(full) for full in KNOWN_SPACED_IDS):
                continue
            out.append(f"{rel}:{n}: unrecognized MDG namespace '{ident}::' — "
                       f"if this is a real customer technology, convert it")

    if path.name == "SKILL.md" and len(lines) > MAX_SKILL_LINES:
        out.append(f"{rel}: {len(lines)} lines — over the {MAX_SKILL_LINES}-line limit; "
                   f"move detail into references/")

    return out


def check_manifest() -> list[str]:
    """Every manifest hash must match the file on disk, byte for byte.

    The installer verifies each download against this map and refuses a
    mismatch, so a stale hash means the skill cannot install. This is also
    the CRLF trap: a checkout that rewrites line endings after the map was
    generated silently invalidates it. `.gitattributes` pins LF; this is the
    check that proves it held.
    """
    import hashlib
    import json

    out: list[str] = []
    mf = ROOT / "manifest.json"
    if not mf.exists():
        return ["manifest.json: missing"]

    mf_raw = mf.read_bytes()
    if b"\r\n" in mf_raw:
        out.append("manifest.json: CRLF line endings — assets must ship as LF")

    m = json.loads(mf_raw.decode("utf-8"))
    listed: set[str] = set()
    for skill in m.get("skills", []):
        for rel, want in skill.get("sha256", {}).items():
            listed.add(rel)
            f = _source_path(rel, ROOT)
            if not f.exists():
                out.append(f"manifest.json: lists a missing file: {rel}")
                continue
            raw = f.read_bytes()
            got = hashlib.sha256(raw).hexdigest()
            if got != want:
                out.append(f"manifest.json: stale sha256 for {rel} "
                           f"(manifest {want[:12]}…, file {got[:12]}…) — "
                           f"run tools/regen-manifest.py")
            if b"\r\n" in raw:
                out.append(f"{rel}: CRLF line endings — assets must ship as LF")

    for base, skill_dir in _asset_dirs(ROOT):
        for f in skill_dir.rglob("*"):
            # Tool caches are not assets. `.pytest_cache/README.md` appears the
            # moment anybody runs the skill's own tests, and reporting it turns
            # the gate red for a reason nobody can act on -- which is how a
            # release gate stops being read.
            if any(part in SKIP_DIRS for part in f.parts):
                continue
            if f.is_file() and f.suffix.lower() in {".md", ".yaml", ".yml"}:
                rel = f.relative_to(base).as_posix()
                if rel not in listed:
                    out.append(f"{rel}: present in the repo but not in manifest.json "
                               f"— it will not ship")
    return out


_STATED_VERSION = re.compile(r"\bv(\d+\.\d+\.\d+)\+")


def check_stated_server_version() -> list[str]:
    """A server version a skill states in its tools line must be its floor.

    The tools line is the italic `*Tools: ...*` block under the title. When it
    names a server version (`v3.6.0+`), that version must equal the skill's
    `min_server_version` in manifest.json, which is the floor the installer
    enforces. A skill whose text says one version while the manifest says
    another tells the reader the wrong requirement. APT-2026-0337.
    """
    import json

    mf = ROOT / "manifest.json"
    if not mf.exists():
        return []
    out: list[str] = []
    for skill in json.loads(mf.read_text(encoding="utf-8")).get("skills", []):
        name, floor = skill.get("name", ""), skill.get("min_server_version", "")
        f = _source_path(f"{name}/SKILL.md", ROOT)
        if not f.exists():
            continue
        block: list[str] = []
        for line in f.read_text(encoding="utf-8").splitlines():
            if not block and not line.startswith(("*Tool:", "*Tools:")):
                continue
            block.append(line)
            if line.rstrip().endswith("*"):
                break
        for stated in _STATED_VERSION.findall("\n".join(block)):
            if stated != floor:
                out.append(f"{name}/SKILL.md: tools line states v{stated}+ but "
                           f"manifest.json min_server_version is {floor}")
    return out


def _version_key(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split("."))


def check_bundle_floor() -> list[str]:
    """The bundle's `min_server_version` must not sit below any skill's.

    The installer enforces the bundle-level floor all-or-nothing and treats
    the per-skill floors as finer detail. A bundle floor below a skill's lets a
    server that is too old for that skill install the rest of the bundle and
    take delivery of a partial set that documents operations it does not have.
    """
    import json

    mf = ROOT / "manifest.json"
    if not mf.exists():
        return []
    data = json.loads(mf.read_text(encoding="utf-8"))
    bundle = data.get("min_server_version", "")
    floors = {s.get("name", ""): s["min_server_version"]
              for s in data.get("skills", []) if s.get("min_server_version")}
    if not floors:
        return []
    try:
        highest_name = max(floors, key=lambda n: _version_key(floors[n]))
        highest = floors[highest_name]
        if bundle and _version_key(bundle) >= _version_key(highest):
            return []
    except ValueError:
        return [f"manifest.json: a min_server_version is not a dotted number "
                f"(bundle {bundle!r})"]
    return [f"manifest.json: bundle min_server_version is {bundle or 'missing'} "
            f"but {highest_name} requires {highest}. Raise the bundle floor to "
            f"at least {highest}."]


def check_plugin_package() -> list[str]:
    """The plugin is skills only, and its version files agree.

    Fails when `plugin.json` declares `mcpServers` at all or the plugin tree has
    a top-level `bin/`: claude.ai refuses a plugin that points at an `.mcpb`,
    and a plugin's server never runs in Claude Desktop chat or Cowork, so the
    server is the separately installed Desktop extension. Also runs the version
    consistency check that `tools/build-plugin.py` runs.
    """
    import importlib.util

    plugin = ROOT / "plugins" / "ai-power-tools-visio"
    manifest = ROOT / "manifest.json"
    marketplace = ROOT / ".claude-plugin" / "marketplace.json"
    if not (plugin / ".claude-plugin" / "plugin.json").is_file():
        return []
    spec = importlib.util.spec_from_file_location(
        "build_plugin", Path(__file__).resolve().parent / "build-plugin.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    out = [f"plugin: {p}" for p in build.package_problems(plugin)]
    if manifest.is_file() and marketplace.is_file():
        out.extend(f"plugin: {p}" for p in
                   build.version_problems(plugin, manifest, marketplace)[1])
    return out


#: What the marketplace entry carries until the first release exists. It is
#: deliberately not a ref or a sha, so nothing can resolve it: the marketplace
#: serves released skills only, never this repository's development branch.
PLACEHOLDER_PIN = "UNRELEASED"
_RELEASE_REF = re.compile(r"^v\d+\.\d+\.\d+$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


def check_marketplace_pin(release: bool = False) -> list[str]:
    """The marketplace entry names a release, or says plainly that none exists.

    Always: `source` must be a git-subdir object whose `ref` and `sha` are
    either both the placeholder or both a release pin (`vX.Y.Z` and a 40-digit
    commit). A branch name in `ref` would make the marketplace serve
    development.

    With `release=True` (the release path, `--release`): the placeholder is a
    finding. A release must pin the tag and the commit it points at.
    """
    import json

    mf = ROOT / ".claude-plugin" / "marketplace.json"
    if not mf.is_file():
        return []
    out: list[str] = []
    for entry in json.loads(mf.read_text(encoding="utf-8")).get("plugins", []):
        name = entry.get("name", "?")
        src = entry.get("source")
        if not isinstance(src, dict) or src.get("source") != "git-subdir":
            out.append(f"marketplace.json: {name}: source must be a git-subdir "
                       f"object pinned to a release; anything else serves a "
                       f"working tree")
            continue
        ref, sha = src.get("ref"), src.get("sha")
        placeholder = ref == PLACEHOLDER_PIN and sha == PLACEHOLDER_PIN
        pinned = bool(_RELEASE_REF.match(str(ref))) and bool(_SHA40.match(str(sha)))
        if not (placeholder or pinned):
            out.append(f"marketplace.json: {name}: ref/sha must both be "
                       f"'{PLACEHOLDER_PIN}' or a release pin (vX.Y.Z and a "
                       f"40-digit commit); got ref={ref!r}, sha={sha!r}")
        elif release and not pinned:
            out.append(f"marketplace.json: {name}: still the '{PLACEHOLDER_PIN}' "
                       f"placeholder - a release must pin its tag and commit")
        elif pinned and entry.get("version") != str(ref).lstrip("v"):
            out.append(f"marketplace.json: {name}: version {entry.get('version')!r} "
                       f"does not match the pinned ref {ref}")
    return out


def is_blocking(finding: str) -> bool:
    """Whether a finding stops the release. Everything does but the line limit.

    Blocking is the default a new rule inherits, and the right one: a rule
    nobody has classified should hold the release, not slide past in a wall of
    warnings.
    """
    return "over the" not in finding


def main() -> int:
    # Findings quote source lines that may contain em-dashes and smart quotes.
    # A cp1252 console would raise UnicodeEncodeError mid-report and truncate it.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    import argparse
    parser = argparse.ArgumentParser(
        description="Release gate for the skills bundle.")
    parser.add_argument("path", nargs="?", default=None,
                        help="limit the scan to this path (default: the repo)")
    parser.add_argument("--release", action="store_true",
                        help="also require the marketplace entry to pin a "
                             "release. Use on the release path; development "
                             "branches carry the placeholder.")
    args = parser.parse_args()

    target = ROOT / args.path if args.path else ROOT
    if not target.exists():
        print(f"no such path: {target}")
        return 2

    findings: list[str] = []
    for f in iter_files(target):
        findings.extend(check_file(f))
    if target == ROOT:
        findings.extend(check_manifest())
        findings.extend(check_stated_server_version())
        findings.extend(check_bundle_floor())
        findings.extend(check_plugin_package())
        findings.extend(check_marketplace_pin(release=args.release))

    if not findings:
        print("GATE GREEN — no violations")
        return 0

    blocking = [f for f in findings if is_blocking(f)]
    print(f"GATE RED — {len(findings)} finding(s), {len(blocking)} blocking\n")
    for f in findings:
        print(f"  {f}")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
