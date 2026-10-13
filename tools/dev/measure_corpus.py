#!/usr/bin/env python3
"""DEVELOPMENT ONLY. Measure Microsoft's sample diagrams in place and write the corpus catalog.

NOT SHIPPED (lives under `tools/dev/`, outside `plugins/`).

    python tools/dev/measure_corpus.py [--content <dir>] [--master-catalog capture.json ...]

Microsoft ships its sample diagrams as templates (`.vstx`) that carry placed shapes - the
"starter diagram" templates - alongside the blank templates and the stencils. This reads
the US-unit ones (`*_U.VSTX`) IN PLACE: nothing is copied, extracted to disk, or opened in
Visio, and what is written is only measurements and a catalog that names each file
relative to `<visio-content>`, never by an absolute path.

It writes two files into `corpus/` at the repository root:

* `microsoft-catalog.json` - WHICH files were measured, where they came from (the
  template's own title, the Visio build, the content locale) and when. The catalog schema
  is `measure_visio.validate_catalog`.
* `microsoft-measurements.json` - one measurement per catalog entry, citing it by
  `catalog_id`, so any number can be traced to the file it came from. No shape text is
  written, only geometry and counts.

A file that is looked at and not measured (no placed shape, or unreadable) is listed under
`examined_not_measured` with the reason, so the catalog holds only what was really measured
and says what was passed over.

The Visio content folder is found from the registry (the Office install root), not
assumed; `--content` overrides it. The build comes from the Click-to-Run configuration.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "plugins" / "ai-power-tools-visio" / "skills" / "_shared" / "tools"))
import measure_visio as M  # noqa: E402
import vsdx_to_page_read as X  # noqa: E402

#: The instruction text Microsoft leaves on a sample page ("Select the Tip Pane and press
#: Delete"). Many sample pages carry it as a masterless group at the page foot (the
#: catalog's `scope.scaffold` says how many). It is the template talking to its author,
#: not part of the diagram, and is left out of every figure.
SCAFFOLD_PATTERN = r"\btip pane\b"

LOCALE = "1033"
UNITS_SUFFIX = "_U.VSTX"


def _registry(subkey: str, name: str) -> Optional[str]:
    try:
        import winreg
    except ImportError:
        return None
    for flag in (getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(winreg, "KEY_WOW64_32KEY", 0)):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey, 0, winreg.KEY_READ | flag) as k:
                value, _ = winreg.QueryValueEx(k, name)
                if isinstance(value, str) and value:
                    return value
        except OSError:
            continue
    return None


def discover_content() -> tuple[Optional[Path], str]:
    """`(Visio Content folder, how it was found)`; the folder is None when not found."""
    root = _registry(r"SOFTWARE\Microsoft\Office\16.0\Visio\InstallRoot", "Path")
    if root and (Path(root) / "Visio Content").is_dir():
        return Path(root) / "Visio Content", \
            "registry HKLM\\SOFTWARE\\Microsoft\\Office\\16.0\\Visio\\InstallRoot\\Path"
    return None, "not found"


def discover_build() -> Optional[str]:
    return _registry(r"SOFTWARE\Microsoft\Office\ClickToRun\Configuration", "VersionToReport")


def template_title(path: Path) -> Optional[str]:
    """The title a template declares in its core properties, or None."""
    try:
        with zipfile.ZipFile(path) as zf:
            root = ET.fromstring(zf.read("docProps/core.xml"))
    except (KeyError, zipfile.BadZipFile, ET.ParseError, OSError):
        return None
    for el in root:
        if el.tag.endswith("}title") and (el.text or "").strip():
            return el.text.strip()
    return None


def entry_id(stem: str) -> str:
    return "ms-" + re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")


def write_json(path: Path, doc: dict, per_line_key: Optional[str] = None) -> None:
    """LF, UTF-8, no BOM. `per_line_key` writes that list one compact item per line."""
    if per_line_key is None:
        text = json.dumps(doc, indent=1, ensure_ascii=False)
    else:
        head = {k: v for k, v in doc.items() if k != per_line_key}
        body = ",\n".join(" " + json.dumps(d, separators=(",", ":"), ensure_ascii=False)
                          for d in doc[per_line_key])
        text = json.dumps(head, indent=1, ensure_ascii=False)
        text = text[:-2] + f',\n "{per_line_key}": [\n{body}\n ]\n}}'
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def _instances_by_source(diagrams: list[dict]) -> dict:
    """How many sized master instances took their default from each source.

    A sample file carries its own copy of every master it uses, and that copy's UniqueID
    usually differs from the stencil master's, so a capture of the stencils matches few.
    The counts say so instead of leaving the reader to assume the captures cover it.
    """
    out: dict[str, int] = {}
    for d in diagrams:
        for rec in d["sizes"].values():
            key = rec["default"]["source"] if rec.get("default") else "none"
            out[key] = out.get(key, 0) + rec["n"]
    return dict(sorted(out.items()))


def run(content: Path, how_found: str, build: str, captures: list[str], out: Path,
        today: str) -> int:
    folder = content / LOCALE
    files = sorted(p for p in folder.iterdir() if p.name.upper().endswith(UNITS_SUFFIX))
    defaults = M.load_master_defaults(captures)
    capture_keys = sorted({d["source"] for d in defaults.values()})

    entries, skipped, diagrams = [], [], []
    masters: dict[str, dict] = {}
    for path in files:
        rel = f"{LOCALE}/{path.name}"
        try:
            pages = X.extract(str(path), path_label=f"{M.ROOT_TOKEN}\\{LOCALE}\\{path.name}",
                              include_background=False, scaffold_pattern=SCAFFOLD_PATTERN)
        except X.ReadError as exc:
            skipped.append({"file": rel, "reason": f"unreadable: {exc}"})
            continue
        placed = [(i, p) for i, p in enumerate(pages, 1)
                  if p["shapes"] or p["containers"] or p["connectors"]]
        if not placed:
            skipped.append({"file": rel, "reason": "no placed shapes"})
            continue
        cid = entry_id(path.stem)
        # Add the file's own embedded master sizes where no capture covers the master.
        local = dict(defaults)
        for m in X.master_defaults(str(path)):
            if m["unique_id"] and m["width_in"] is not None and m["height_in"] is not None \
                    and m["unique_id"] not in local:
                local[m["unique_id"]] = {"name": m["universal_name"], "width": M.q(m["width_in"]),
                                         "height": M.q(m["height_in"]), "source": "embedded"}
        counts = {"containers": 0, "shapes": 0, "connectors": 0}
        for index, page in placed:
            result = M.measure_page(page, label=f"{cid}#{index}", master_defaults=local)
            result = {"catalog_id": cid, "page_index": index, **result}
            diagrams.append(result)
            for k in counts:
                counts[k] += result["counts"][k]
            for name, rec in result["sizes"].items():
                m = masters.setdefault(name, {"diagrams": set(), "instances": 0})
                m["diagrams"].add(cid)
                m["instances"] += rec["n"]
        entries.append({"id": cid, "file": rel, "kind": "template-sample",
                        "template_name": template_title(path), "size_bytes": path.stat().st_size,
                        "sha256": M.file_sha256(str(path)), "pages_measured": len(placed), "counts": counts})

    catalog = {
        "schema": M.CATALOG_SCHEMA,
        "corpus": {"name": "microsoft-visio-content", "root": M.ROOT_TOKEN},
        "visio": {"build": build, "content_locale": LOCALE, "units": "U",
                  "install_found_by": how_found},
        "measured_on": today,
        "tool": {"name": M.TOOL, "version": M.TOOL_VERSION},
        "scope": {
            "examined": f"every *{UNITS_SUFFIX} template in the {LOCALE} content folder (US units), "
                        "read in place",
            "not_examined": "the metric (_M) twins, which repeat the same masters at metric sizes; "
                            "the right-to-left (_R2L) variants; stencils, which hold masters and no "
                            "placed shapes; other locales",
            "scaffold": {"pattern": SCAFFOLD_PATTERN,
                         "files_with_scaffold": len({d["catalog_id"] for d in diagrams
                                                      if d["counts"]["scaffold_excluded"]}),
                         "shapes_excluded": sum(d["counts"]["scaffold_excluded"]
                                                for d in diagrams)}},
        "entries": entries,
        "examined_not_measured": skipped,
    }
    errors = M.validate_catalog(catalog)
    measurements = {
        "schema": M.MEASUREMENTS_SCHEMA, "unit": M.UNIT, "measured_on": today,
        "visio_build": build,
        "master_defaults": {
            "captures": capture_keys,
            "matched_by": "master UniqueID",
            "embedded": "the file's own copy of the master, used where no capture matches it",
            "instances_by_source": _instances_by_source(diagrams)},
        "masters": {n: {"diagrams": len(v["diagrams"]), "instances": v["instances"]}
                    for n, v in sorted(masters.items())},
        "diagrams": diagrams,
    }
    errors += M.validate_measurements(measurements, catalog)
    if errors:
        print("catalog problems:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "microsoft-catalog.json", catalog)
    write_json(out / "microsoft-measurements.json", measurements, per_line_key="diagrams")
    print(f"measured {len(entries)} files, {len(diagrams)} pages; "
          f"{len(skipped)} examined and not measured -> {out.name}/")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--content", help="the Visio Content folder (default: from the registry)")
    parser.add_argument("--build", help="the Visio build (default: Click-to-Run configuration)")
    parser.add_argument("--master-catalog", action="append", default=[], metavar="capture.json")
    parser.add_argument("--out", default=str(ROOT / "corpus"))
    parser.add_argument("--date", default=datetime.date.today().isoformat())
    args = parser.parse_args(argv)
    if args.content:
        content, how = Path(args.content), "--content"
    else:
        content, how = discover_content()
    if content is None or not (content / LOCALE).is_dir():
        print(f"Visio content folder for locale {LOCALE} not found ({how})", file=sys.stderr)
        return 2
    build = args.build or discover_build()
    if not build:
        print("Visio build not found; pass --build", file=sys.stderr)
        return 2
    return run(content, how, build, args.master_catalog, Path(args.out), args.date)


if __name__ == "__main__":
    raise SystemExit(main())
