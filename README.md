# AI Power Tools for Microsoft Visio - Skills

Skills for **AI Power Tools for Microsoft Visio**, the MCP server that drives Microsoft Visio.

This library covers Microsoft Visio only. AI Power Tools for Sparx EA is a separate product with
its own skills library, manifest and release cadence. Nothing is shared between them.

## Status

No skills have been released yet, and nothing here can be installed. The marketplace entry in
`.claude-plugin/marketplace.json` carries an explicit placeholder instead of a release, and the
gate refuses that placeholder on the release path. Installation instructions will appear here with
the first release.

## Branches

| Branch | Holds |
|---|---|
| `main` | Released skills only. Updated when a release is cut, and nothing else. |
| `dev` | Development. Every change arrives here through a reviewed merge. |
| `apv-nnnn-<slug>` | One backlog item, one branch, taken from `dev`. |

The marketplace serves tagged releases, never `dev`. `tools/gate.py` rejects a marketplace entry
whose `ref` is anything other than a `vX.Y.Z` tag.

Use one worktree per workstream. `tools/regen-manifest.py` scans the filesystem, not git, so two
streams in one working directory produce a manifest that matches neither.

## Layout

```
.claude-plugin/marketplace.json      Marketplace entry for the plugin (a draft until the first release)
.github/workflows/gate.yml           Runs the tests, the gate and the manifest check on every push
plugins/ai-power-tools-visio/
  .claude-plugin/plugin.json         The plugin: skills only, no server
  skills/
    _shared/references/              Reference material several skills link to
    <skill-name>/SKILL.md            One directory per skill (none yet)
manifest.json                        Generated: every shipped file and its sha256
tools/
  _layout.py                         Where a manifest path lives in the repository
  regen-manifest.py                  Rewrites manifest.json from the files on disk
  gate.py                            The release gate
  test_gate.py                       Proves the gate catches what it claims to
  build-plugin.py                    Packages the plugin as a .plugin archive
```

## Working on the skills

Run these from the repository root, in the worktree you are working in:

```
python -m pytest tools -q
python tools/regen-manifest.py     # after editing any shipped file
python tools/gate.py
```

`manifest.json` is generated. Never edit its hashes by hand and never merge it by hand: run
`tools/regen-manifest.py` and commit the result.

### What the gate enforces

- No real customer names, model names, technology ids or project codes. Westbrook Bank is the
  only example organization; see
  `plugins/ai-power-tools-visio/skills/_shared/references/westbrook-example.md`.
- No absolute local paths and no personal identifiers.
- Files are UTF-8 without a byte order mark, with LF line endings (`.gitattributes` pins this),
  and every shipped file matches its sha256 in `manifest.json`.
- The plugin is skills only: no `mcpServers` entry in `plugin.json` and no `bin/` directory. The
  server is the separately installed Claude Desktop extension.
- The version in `plugin.json`, `manifest.json` and `marketplace.json` agrees.
- With `python tools/gate.py --release`, the marketplace entry must pin a release tag and the
  commit it points at.

## License

MIT. See `LICENSE`.
