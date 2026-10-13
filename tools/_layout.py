"""Where a manifest path's file actually lives in this repository.

Manifest paths are INSTALL-relative: the installer writes each one straight
under the skills directory, and publish-bundle derives the flat release-asset
name from the same string. Neither says anything about where the file sits in
the repo -- and since the skills moved under the plugin, the two differ.

Shared by regen-manifest.py, gate.py and publish-bundle.py. It lived in all
three as a private copy first, which is one update away from a release that
stages the wrong tree.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Skills live inside the plugin so a single tree serves both delivery
#: channels: the marketplace for Claude Code, and the packaged `.plugin` for
#: Cowork, which only loads skills from `<plugin>/skills/`.
PLUGIN_SKILLS = ROOT / "plugins" / "ai-power-tools-visio" / "skills"

#: Where the skills sit under a root. Every function below takes the root as an
#: argument rather than closing over the module-level one: `gate.py` patches its
#: own ROOT to run against a throwaway library, and a helper that quietly
#: resolved against the real repository instead made that test pass over the
#: wrong tree.
_PLUGIN_REL = ("plugins", "ai-power-tools-visio", "skills")


def plugin_skills(root: Path | None = None) -> Path:
    return (Path(root) if root is not None else ROOT).joinpath(*_PLUGIN_REL)


def source_path(rel: str, root: Path | None = None) -> Path:
    """Resolve an install-relative manifest path to its file in the repo."""
    base = Path(root) if root is not None else ROOT
    candidate = plugin_skills(base) / rel
    return candidate if candidate.exists() else base / rel


def source_dir(name: str, root: Path | None = None) -> Path | None:
    """Where a manifest entry's directory lives, or None if it is missing."""
    base = Path(root) if root is not None else ROOT
    for parent in (plugin_skills(base), base):
        if (parent / name).is_dir():
            return parent / name
    return None


def asset_dirs(root: Path | None = None) -> list[tuple[Path, Path]]:
    """(base, directory) pairs to scan for assets the manifest forgot.

    `base` is what a found file is made relative to, so the result can be
    compared against the manifest's install-relative paths.
    """
    base = Path(root) if root is not None else ROOT
    skills = plugin_skills(base)
    pairs: list[tuple[Path, Path]] = []
    if skills.is_dir():
        pairs += [(skills, d) for d in sorted(skills.iterdir())
                  if d.is_dir() and not d.name.startswith((".", "_"))]
    pairs += [(base, d) for d in sorted(base.iterdir())
              if d.is_dir() and not d.name.startswith((".", "_"))
              and d.name not in {"tools", "plugins", "docs", "dist"}]
    return pairs
