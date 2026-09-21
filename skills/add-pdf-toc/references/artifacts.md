# Artifact contracts

All paths are UTF-8. Page numbers are **1-based PDF pages**, not printed book numbers.

Work directory default: `./.addpdftoc/<pdf-stem>/` relative to the agent's cwd.

## `meta.json` (from `detect`)

```json
{
  "ok": true,
  "source_pdf": "C:/books/book.pdf",
  "work_dir": "C:/proj/.addpdftoc/book",
  "page_count": 320,
  "needs_ocr": false,
  "low_text_pages": 12,
  "median_chars": 1400,
  "language_guess": "chi_sim+eng",
  "has_existing_toc": false,
  "existing_toc_count": 0,
  "metadata": {"title": "..."}
}
```

## `pages.jsonl` (from `extract`)

One JSON object per line:

```json
{
  "page": 12,
  "char_count": 980,
  "text": "....",
  "font_heading_hints": [
    {"text": "2.1 Methods", "size": 16.0, "font": "Times-Bold", "bbox": [72, 680, 220, 700]}
  ]
}
```

The orchestrator must **not** load this whole file. Use `slice` / `page-window`.

## `printed_toc.json` (from the coarse-map subagent, may be empty)

```json
{
  "found": true,
  "toc_pages": [3, 4, 5],
  "page_offset": 12,
  "notes": "Printed page 1 is PDF page 13",
  "entries": [
    {"level": 1, "title": "Chapter 1 Overview", "printed_page": 1, "pdf_page": 13}
  ]
}
```

If no printed TOC: `{"found": false, "entries": []}`.

`page_offset` is `pdf_page - printed_page` after aligning a chapter title in the body. Confirm at least two headings before trusting it.

## `chapters.json` (routing map for subagents)

```json
{
  "source": "printed_toc",
  "chapters": [
    {"id": "ch-01", "title": "Chapter 1 Overview", "start_page": 13, "end_page": 40}
  ]
}
```

`source` is `printed_toc` or `page_chunks`. Ranges are inclusive PDF pages and must cover the body without overlap (front matter may be a `front` chunk).

## `outline.proposed.json` / `outline.verified.json`

```json
{
  "entries": [
    {"level": 1, "title": "Chapter 1 Overview", "page": 13, "quote": "Chapter 1 Overview"},
    {"level": 2, "title": "1.1 Background", "page": 15, "quote": "1.1 Background"}
  ]
}
```

`quote` is a short span copied from the page text. Do not invent body titles. Front-matter structural labels (cover / title page / preface / contents) are allowed; `quote` is still from that page.

## Verification verdicts

Each checked bookmark:

```json
{
  "title": "1.1 Background",
  "page": 15,
  "level": 2,
  "verdict": "match",
  "suggested_page": 15,
  "reason": "Heading appears near the start of the target page"
}
```

`verdict` is one of: `match`, `off_by_n`, `wrong`, `not_found`.

## `report.md`

Short markdown: page count, OCR yes/no, chapter count, bookmark count, verify sample size, pass rate, failures, chapters rerun.
