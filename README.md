# add-pdf-toc

Agent skill that adds a hierarchical **bookmark outline** (sidebar table of contents) to a PDF. Scanned files can be made searchable first. The agent runs the workflow and uses subagents on page slices; the Python scripts never call a model.

## Install

Requires [Node.js](https://nodejs.org/) so `npx` works. No skills.sh account and no marketplace submission.

```bash
# This repo, user-level skill (any project)
npx skills add . -g

# After the repo is on GitHub
npx skills add KIDPhantom1412/AddPdfToc -g
```

List what the installer sees:

```bash
npx skills add . --list
```

Without Node, copy `skills/add-pdf-toc/` to the user-level `~/.agents/skills/add-pdf-toc/` (or the current project's `.agents/skills/`).

## Use

In your coding agent's chat, ask for example:

> Add a table of contents to `D:\books\example.pdf`

The agent should load this skill and run `uv run scripts/addpdftoc.py ...` (uv is required). OCR only if needed. Bookmarks come from body headings (printed TOC is a routing hint), then entries are verified against page text.

## Layout

```text
skills/add-pdf-toc/
  SKILL.md
  scripts/addpdftoc.py
  scripts/requirements.txt
  references/artifacts.md
  references/subagents.md
```

## Runtime

- **[uv](https://docs.astral.sh/uv/)** (`uv run` reads the script's PEP 723 deps).

## License

MIT
