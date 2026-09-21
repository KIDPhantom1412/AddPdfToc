# Subagent roles

The orchestrator never attaches `pages.jsonl` and never reads a chapter slice to finish a failed agent's work. Retry that agent instead.

```
detect → ocr → coarse (1, serial)
                 ↓ barrier: chapters.json
              fine headings × N (parallel, one per chapter)
                 ↓ barrier: merge + check-outline
              verify × M (parallel, one per chapter)
                 ↓
              write-toc
```

Launch each parallel group in **one turn**. A platform `resource_exhausted` on one agent is not a reason to serialize the rest; retry the missing chapter.

Pass only the sliced JSONL and the printed-TOC fragment for that chapter.

## Coarse map (one subagent)

Input: first 20–40 pages of `pages.jsonl` (and later pages only if the TOC is not in front matter).

Task:

1. Decide if a printed table of contents exists.
2. If yes, extract hierarchical entries and printed page numbers. Estimate PDF offset by searching chapter titles in later body text if those pages were provided; otherwise leave `page_offset` null for the orchestrator to resolve with extra slices. Do not trust printed numbers that OCR glued to the wrong heading until two body matches agree.
3. Emit `printed_toc.json` and a `chapters.json` draft.
4. If no printed TOC, say so. The orchestrator will split by page count (~30 pages) or by strong font hints.

Do not emit the detailed ebook outline here. Front matter may be one `front` chapter; body lessons are separate chapters.

## Fine headings (one subagent per chapter, parallel)

Input:

- Slice for `start_page`–`end_page`
- Printed TOC entries for this chapter (may be empty)
- Font hints already in the JSONL

Task: extract a finer outline than the printed TOC from **body headings**. Rules:

- Every title must appear in the page text (`quote`), except the front-matter labels below.
- Prefer headings near the start of a section, not running headers/footers or unit-preview lists of later lessons.
- Use printed TOC as a skeleton you may deepen, not a ceiling.
- Pages are PDF pages from the JSONL `page` field.
- Return JSON `{ "entries": [ { "level", "title", "page", "quote" } ] }` only. Write the file the orchestrator named.

If the slice is mostly plates, return fewer entries rather than guessing.

**Front matter:** if the slice is clearly cover / title page / preface / contents, you may use short structural titles (`Cover`, `Title page`, `Preface`, `Contents`, or the book's own script: 封面 / 扉页 / 序言 / 目次). `quote` must still be copied from that page (book title, 「目次」, the preface heading). Do not invent body section titles this way.

A chapter that is not the first in the book may start at level 2 when its parent unit already exists; the orchestrator merges.

## Verify (one subagent per chapter, parallel)

Input: that chapter's outline entries plus `page-window` JSON for each (`radius` 1, or 2 if the first pass is `not_found`).

Decide from the **target page's opening lines**, not from “string appears somewhere in the window”:

| verdict | when |
| --- | --- |
| `match` | Title/quote near the **start** of the **target** page (true section start) |
| `off_by_n` | Section actually starts on a nearby page; set `suggested_page` |
| `wrong` | Window is a different section |
| `not_found` | Not in the window |

Ignore running headers/footers and unit-preview pages that list later lesson titles. A hit on page N−1 that is only a preview is **not** `off_by_n`.

Return JSON `{ "results": [ ...verdicts ] }`.
