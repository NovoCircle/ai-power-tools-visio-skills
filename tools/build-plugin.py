#!/usr/bin/env python3
"""Package the plugin as `dist/ai-power-tools-visio.plugin` for the Cowork channel.

Claude Code installs this plugin from the marketplace, which pins the released
copy of this tree in the releases repository (see tools/publish-plugin.py,
which reads its tree out of the archive built here). Cowork does not read that
marketplace: the desktop app
enumerates Cowork's plugins itself from its own stores, one of which is fed by
an in-app upload that accepts a `.zip` or `.plugin` archive. This script builds
that archive.

A `.plugin` IS a zip -- the desktop normalises the extension before validating
it -- with the plugin's own contents at the archive root, so `.claude-plugin/`
sits at the top level.

The skill content is not copied or transformed: both channels ship the exact
bytes under `plugins/ai-power-tools-visio/`, so there is one source of truth and no
way for the two to drift. `version_problems` and `plugin_files` are imported by
publish-plugin.py for the same reason.
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "ai-power-tools-visio"
MANIFEST = ROOT / "manifest.json"
DIST = ROOT / "dist"

#: The desktop upload rejects anything larger. Checked here so the failure
#: surfaces at build time rather than in front of a customer.
MAX_UPLOAD_BYTES = 209_715_200

_RESIDUE_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
_RESIDUE_SUFFIXES = {".pyc", ".pyo"}


def _is_build_residue(p: Path) -> bool:
    return (any(part in _RESIDUE_DIRS for part in p.parts)
            or p.suffix in _RESIDUE_SUFFIXES)


def package_problems(plugin: Path = PLUGIN) -> list[str]:
    """The plugin is skills only: no server declaration, no bundled binary.

    A server declared in `plugin.json` is refused by claude.ai when it is an
    `.mcpb` URL, and never runs in Claude Desktop chat or Cowork whatever its
    form; a bundled `bin/` is the same server carried by hand. The server is
    the Claude Desktop extension, installed separately.
    """
    plugin_json = plugin / ".claude-plugin" / "plugin.json"
    problems = []
    if plugin_json.is_file():
        data = json.loads(plugin_json.read_text(encoding="utf-8"))
        if "mcpServers" in data:
            problems.append("plugin.json declares mcpServers. The plugin is "
                            "skills only; the server is the Claude Desktop "
                            "extension.")
    if (plugin / "bin").exists():
        problems.append("The plugin has a top-level bin/. The plugin is skills "
                        "only and must not carry a server binary.")
    return problems


def version_problems(plugin: Path = PLUGIN, manifest: Path = MANIFEST,
                     marketplace: Path = ROOT / ".claude-plugin" / "marketplace.json"
                     ) -> tuple[str | None, list[str]]:
    """`(plugin_version, problems)` for the files that carry the version.

    Three version files: plugin.json, manifest.json and marketplace.json.
    """
    plugin_json = plugin / ".claude-plugin" / "plugin.json"
    if not plugin_json.is_file():
        return None, [f"Missing {plugin_json}"]

    # The two channels are versioned from different files, so they can drift.
    # A customer comparing them would see the same skills under two version
    # numbers, with no way to tell which is newer. Refuse instead.
    plugin_version = json.loads(plugin_json.read_text(encoding="utf-8"))["version"]
    bundle_version = json.loads(manifest.read_text(encoding="utf-8"))["bundle_version"]
    if plugin_version != bundle_version:
        return plugin_version, [f"Version drift: plugin.json {plugin_version} != "
                                f"manifest.json bundle_version {bundle_version}"]

    entry = next((p for p in json.loads(marketplace.read_text(encoding="utf-8"))["plugins"]
                  if p["name"] == "ai-power-tools-visio"), None)
    if entry is None or entry.get("version") != plugin_version:
        return plugin_version, [f"Version drift: marketplace.json entry != plugin.json "
                                f"{plugin_version}"]
    return plugin_version, []


def plugin_files(plugin: Path = PLUGIN) -> list[Path]:
    """Every file that ships in the plugin, in archive order."""
    return sorted(p for p in plugin.rglob("*")
                  if p.is_file() and not _is_build_residue(p))


def main() -> int:
    plugin_version, problems = version_problems()
    problems += package_problems()
    if problems:
        for p in problems:
            print(p, file=sys.stderr)
        return 1

    files = plugin_files()
    if not files:
        print(f"No files under {PLUGIN}", file=sys.stderr)
        return 1

    DIST.mkdir(exist_ok=True)
    out = DIST / "ai-power-tools-visio.plugin"
    # Fixed timestamps: the same input must produce the same archive, so a
    # rebuild that changed nothing is visibly identical.
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            info = zipfile.ZipInfo(str(f.relative_to(PLUGIN).as_posix()),
                                   date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, f.read_bytes())

    size = out.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        print(f"{out.name} is {size} bytes — over the "
              f"{MAX_UPLOAD_BYTES}-byte desktop upload limit", file=sys.stderr)
        return 1

    print(f"{out.relative_to(ROOT)} — {len(files)} files, {size} bytes, "
          f"version {plugin_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
