---
name: add-pdf-toc
description: Add a hierarchical PDF bookmark outline (sidebar TOC) to searchable or scanned PDFs, OCR image-only pages when needed, then verify bookmarks against page text with subagents. Use when the user asks to add a table of contents, bookmarks, or outline to a PDF, or to make a scanned PDF searchable and navigable.
compatibility: Requires uv.
---

# Add PDF TOC

The agent drives this workflow. Python scripts never call a model. Do not write one-off PyMuPDF snippets; use `scripts/addpdftoc.py`.

## Resolve paths

- `SKILL_DIR` = directory that contains this `SKILL.md`.
- `SCRIPT` = `SKILL_DIR/scripts/addpdftoc.py`
- Work dir = `./.addpdftoc/<pdf-stem>/` unless the user names another folder.
- Final PDF = `<stem>.with-toc.pdf` next to the source (or inside the work dir if the source is read-only).

## Run scripts

The script declares its own deps (PEP 723). Always:

```bash
uv run "$SCRIPT" check-deps
```

If `uv` is missing, stop and tell the user to install it: https://docs.astral.sh/uv/getting-started/installation/ — do not fall back to pip or a harness venv. Do not add `--with` packages.

## OCR language

Do not hardcode a language in this skill. Before `ocr`:

1. Guess the script from the cover, filename, user, or `meta.language_guess` (scans are often `unknown`).
2. Read `rapidocr_lang_rec` from `check-deps` (RapidOCR's own `rapidocr --help` does **not** list language codes). In the same env you can also run `rapidocr --help` for CLI flags.
3. Map the guess onto a `LangRec` value from that list. Use [RapidOCR model list](https://rapidai.github.io/RapidOCRDocs/main/model_list/) if the enum is ambiguous (e.g. German → `latin`).
4. Pass that code to `ocr --language`.

## Commands

```bash
uv run "$SCRIPT" detect <pdf> --work-dir <work>
uv run "$SCRIPT" ocr --engine rapidocr <pdf> --work-dir <work> --language <LangRec> [--start N --end M]
uv run "$SCRIPT" extract <searchable-or-original.pdf> --work-dir <work> [--start N --end M]
uv run "$SCRIPT" slice --pages <work>/pages.jsonl --start N --end M --out <work>/slices/ch-01.jsonl
uv run "$SCRIPT" page-window --pages <work>/pages.jsonl --page N --radius 1
uv run "$SCRIPT" check-outline --outline <work>/outline.proposed.json
uv run "$SCRIPT" write-toc <pdf> --outline <work>/outline.verified.json --out <stem>.with-toc.pdf
```

JSON field definitions: [references/artifacts.md](references/artifacts.md). Subagent roles, prompts, and parallelism: [references/subagents.md](references/subagents.md).

## Workflow

Copy and tick:

```
- [ ] check-deps
- [ ] detect
- [ ] if needs_ocr: look up LangRec, then ocr
- [ ] extract only if digital / font hints needed
- [ ] coarse map (one subagent) -> printed_toc.json + chapters.json
- [ ] fine headings: launch all chapter subagents in parallel
- [ ] merge outline.proposed.json
- [ ] check-outline (cheap)
- [ ] verify (subagents, parallel by chapter)
- [ ] fix / rerun failing chapters
- [ ] write-toc + report.md
```

Serial until `chapters.json` exists. Then fine-heading subagents in parallel; then verify subagents in parallel. Do not start the next stage until the previous barrier is done.

### 1. Detect

Run `detect`. If `has_existing_toc` and the user did not ask to replace it, ask before overwriting.

### 2. Text layer

If `needs_ocr` is true, pick `--language` as above, then `ocr --engine rapidocr` (add `--start/--end` when the user caps the range). RapidOCR writes `pages.jsonl` from recognized text. Pass `--out searchable.pdf` only if the user wants an invisible-text overlay (rewrites the whole PDF; skip for large scans unless asked). Skip a second `extract` unless you need font hints from a digital PDF.

`extract` still works on searchable/digital PDFs. Subsequent AI reads **page-aligned JSONL only**, not screenshots.

### 3. Coarse map

Launch **one** subagent with the first 20–40 pages (`slice`). Wait for `printed_toc.json` and `chapters.json`. Printed TOC is a routing skeleton, not the final ebook TOC. Align printed page numbers to PDF pages before cutting chapters.

If there is no printed TOC, split into ~30-page chunks (adjust at obvious chapter-sized font hints).

### 4. Fine outline

Launch **one subagent per chapter** (or chunk) **in the same turn**. Each gets only its slice + the printed TOC fragment for that chapter. If one fails (`resource_exhausted` or similar), retry **that** subagent; do not read its JSONL yourself.

Merge into `outline.proposed.json`: printed TOC as chapter/section backbone, body headings as deeper levels. Run `check-outline`. Fix level jumps and backward pages before verify.

### 5. Verify and write

Verify **before** the final `write-toc` (verdicts use JSONL, not the PDF). Launch **one verify subagent per chapter** in parallel (or one batch if the outline is small). Each gets `page-window` for its entries (`radius` 1, or 2 after `not_found`).

The title must appear near the **start of the target page**, not merely anywhere in the window (unit previews and running headers do not count). Apply `suggested_page` for real `off_by_n`. If a chapter's fail rate is high, rerun **that chapter's** fine-heading subagent only, then `check-outline` and verify again.

Then `write-toc` and `report.md`.

## Orchestrator context

Do not ingest `pages.jsonl` or chapter slices. You may read `meta.json`, `printed_toc.json`, `chapters.json`, outlines, `check-outline` output, verification summaries, and `report.md`.

## Report to the user

Give: output PDF path, whether OCR ran, RapidOCR `--language`, bookmark count, verify pass rate, remaining failures. Offer to rerun a named chapter or cap depth ("level 2 only").
