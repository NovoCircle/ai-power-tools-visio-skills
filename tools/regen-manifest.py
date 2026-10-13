"""Regenerate manifest.json with current file hashes.

Run after editing any SKILL.md / reference file. Reads the per-skill
metadata (description, version, min_server_version) from the existing
manifest.json and only refreshes the file list + sha256 map. If you
need to bump a skill's version or min_server_version, edit
manifest.json by hand first, then run this script — it will preserve
your edits.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "manifest.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _layout import source_dir as _source_dir  # noqa: E402


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# Anything a tool leaves behind rather than something we authored. Without
# this, running a skill's tests and then regenerating quietly adds .pyc files
# to the shipped bundle -- and because the manifest carries a hash per file,
# every one of them becomes a thing install_skills must download and verify.
_RESIDUE_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
_RESIDUE_SUFFIXES = {".pyc", ".pyo"}


def _is_build_residue(p: Path) -> bool:
    return (any(part in _RESIDUE_DIRS for part in p.parts)
            or p.suffix in _RESIDUE_SUFFIXES)


def main() -> int:
    current = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for entry in current["skills"]:
        name = entry["name"]
        skill_dir = _source_dir(name)
        if skill_dir is None:
            print(f"Skill dir missing: {name}", file=sys.stderr)
            return 1
        # Paths in the manifest are INSTALL-relative, not repo-relative: the
        # installer writes each one straight under the skills directory, and
        # publish-bundle.py derives the flat release-asset name from the same
        # string. Both are unaffected by where the file sits in the repo, so
        # moving the skills under the plugin must not change these values.
        base = skill_dir.parent
        files = sorted(str(p.relative_to(base).as_posix())
                       for p in skill_dir.rglob("*")
                       if p.is_file() and not _is_build_residue(p))
        if not files:
            print(f"No files under: {name}", file=sys.stderr)
            return 1
        entry["files"] = files
        entry["sha256"] = {f: sha256(base / f) for f in files}

    # newline="" prevents Windows from translating LF to CRLF on write.
    # A CRLF manifest is what broke the v1.4.1 release: the assets hash as LF,
    # the manifest ships as CRLF, and every post-download hash check fails.
    with MANIFEST.open("w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(current, indent=2))
    n_skills = len(current["skills"])
    n_files = sum(len(s["files"]) for s in current["skills"])
    print(f"manifest.json rewritten — {n_skills} skills, {n_files} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
