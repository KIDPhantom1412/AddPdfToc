# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "pymupdf>=1.24.0",
#   "rapidocr>=3.0.0",
#   "onnxruntime>=1.17.0",
# ]
# ///
"""Mechanical PDF helpers for the add-pdf-toc skill. No AI calls."""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

MIN_CHARS_SEARCHABLE = 30
OCR_PAGE_RATIO = 0.4
HEADING_SIZE_RATIO = 1.12
HEADING_MAX_LEN = 80
DEFAULT_OCR_DPI = 144


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


def _die(message: str, code: int = 1) -> None:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(code)


def _dump(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _require_pymupdf():
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        _die("pymupdf is not installed in this interpreter. Install it in an isolated env (uvx --with pymupdf or venv + pip).")
    import pymupdf

    return pymupdf


def _pdf_path(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        _die(f"PDF not found: {path}")
    return path


def _work_dir(pdf: Path, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (Path.cwd() / ".addpdftoc" / pdf.stem).resolve()


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _which_first(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def _try_import(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def cmd_check_deps(_args: argparse.Namespace) -> None:
    python_ok = True
    pymupdf_ok = _try_import("pymupdf")
    rapidocr_ok = _try_import("rapidocr")
    lang_rec: list[str] = []
    if rapidocr_ok:
        try:
            from rapidocr import LangRec

            lang_rec = [item.value for item in LangRec]
        except Exception:
            lang_rec = []

    _dump(
        {
            "ok": True,
            "python": sys.executable,
            "python_version": sys.version.split()[0],
            "python_ok": python_ok,
            "pymupdf": pymupdf_ok,
            "rapidocr": rapidocr_ok,
            "rapidocr_lang_rec": lang_rec,
            "ocr_ready": rapidocr_ok,
        }
    )


def _guess_language(samples: Iterable[str]) -> str:
    text = "".join(samples)
    if not text:
        return "unknown"
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    kana = sum(1 for ch in text if ("\u3040" <= ch <= "\u309f") or ("\u30a0" <= ch <= "\u30ff"))
    hangul = sum(1 for ch in text if "\uac00" <= ch <= "\ud7af")
    latin = sum(1 for ch in text if ("A" <= ch <= "Z") or ("a" <= ch <= "z"))

    if kana > 10:
        return "japan"
    if hangul > 10:
        return "korean"
    if cjk > latin * 0.3 and cjk > 20:
        return "chi_sim+eng" if latin else "chi_sim"
    if latin:
        return "eng"
    return "unknown"


def cmd_detect(args: argparse.Namespace) -> None:
    pymupdf = _require_pymupdf()
    pdf = _pdf_path(args.pdf)
    work = _ensure_dir(_work_dir(pdf, args.work_dir))

    doc = pymupdf.open(pdf)
    try:
        page_count = doc.page_count
        char_counts: list[int] = []
        samples: list[str] = []
        empty_or_image = 0
        for i, page in enumerate(doc):
            text = page.get_text("text") or ""
            n = len(text.strip())
            char_counts.append(n)
            if n < MIN_CHARS_SEARCHABLE:
                empty_or_image += 1
            if i < 8:
                samples.append(text[:1500])
        existing = doc.get_toc(simple=True) or []
        existing_entries = [{"level": int(row[0]), "title": str(row[1]), "page": int(row[2])} for row in existing]
        (work / "existing_toc.json").write_text(
            json.dumps({"ok": True, "count": len(existing_entries), "entries": existing_entries}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        needs_ocr = page_count > 0 and (empty_or_image / page_count) >= OCR_PAGE_RATIO
        language = _guess_language(samples)
        meta = {
            "ok": True,
            "source_pdf": str(pdf),
            "work_dir": str(work),
            "page_count": page_count,
            "needs_ocr": needs_ocr,
            "low_text_pages": empty_or_image,
            "median_chars": int(statistics.median(char_counts)) if char_counts else 0,
            "language_guess": language,
            "has_existing_toc": bool(existing),
            "existing_toc_count": len(existing),
            "metadata": {k: v for k, v in (doc.metadata or {}).items() if v},
        }
    finally:
        doc.close()

    (work / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    _dump(meta)


def _ocr_language(args: argparse.Namespace, work: Path) -> str:
    if args.language:
        return args.language
    meta_path = work / "meta.json"
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        guess = meta.get("language_guess") or "eng"
        if guess != "unknown":
            return guess
    return "chi_sim+eng"


def _rapidocr_rec_lang(language: str) -> str:
    raw = language.lower().replace(" ", "")
    if "jpn" in raw or "japan" in raw:
        return "japan"
    if raw in {"chi_tra", "chi-tra", "zh-tw", "zh-hant"} or "chi_tra" in raw:
        return "chinese_cht"
    if "chi" in raw or raw in {"ch", "zh", "zh-cn", "zh-hans"}:
        return "ch"
    if raw in {"en", "eng", "english"}:
        return "en"
    if "kor" in raw or "korean" in raw:
        return "korean"
    return "ch"


def _rapidocr_lines(result: Any) -> list[tuple[list[list[float]], str, float]]:
    boxes = getattr(result, "boxes", None)
    txts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if txts is not None:
        lines: list[tuple[list[list[float]], str, float]] = []
        n = len(txts)
        for i in range(n):
            txt = str(txts[i] or "").strip()
            if not txt:
                continue
            box = boxes[i] if boxes is not None else [[0, 0], [0, 0], [0, 0], [0, 0]]
            score = float(scores[i]) if scores is not None else 0.0
            pts = [[float(p[0]), float(p[1])] for p in box]
            lines.append((pts, txt, score))
        return lines
    if not result:
        return []
    # Older RapidOCR: list of [box, text, score]
    lines = []
    for item in result:
        if not item or len(item) < 2:
            continue
        box, txt = item[0], str(item[1] or "").strip()
        if not txt:
            continue
        score = float(item[2]) if len(item) > 2 else 0.0
        pts = [[float(p[0]), float(p[1])] for p in box]
        lines.append((pts, txt, score))
    return lines


def _lines_to_text(lines: list[tuple[list[list[float]], str, float]]) -> str:
    ordered = sorted(lines, key=lambda row: (min(p[1] for p in row[0]), min(p[0] for p in row[0])))
    return "\n".join(txt for _box, txt, _score in ordered)


def _insert_invisible_ocr(page, lines: list[tuple[list[list[float]], str, float]], zoom: float, fontname: str) -> int:
    import pymupdf

    written = 0
    for box, txt, _score in lines:
        xs = [p[0] / zoom for p in box]
        ys = [p[1] / zoom for p in box]
        rect = pymupdf.Rect(min(xs), min(ys), max(xs), max(ys))
        if rect.width < 1 or rect.height < 1:
            continue
        fontsize = max(4.0, min(rect.height * 0.9, 48.0))
        try:
            rc = page.insert_textbox(
                rect,
                txt,
                fontname=fontname,
                fontsize=fontsize,
                color=(0, 0, 0),
                render_mode=3,
                overlay=True,
            )
        except Exception:
            continue
        if rc >= 0:
            written += 1
    return written


def _ocr_rapidocr(args: argparse.Namespace, pdf: Path, work: Path, language: str) -> dict[str, Any]:
    try:
        from rapidocr import RapidOCR
    except ImportError:
        _die(f"rapidocr is not installed. Run this script with uv: uv run {Path(__file__).name}")

    pymupdf = _require_pymupdf()
    rec_lang = _rapidocr_rec_lang(language)
    fontname = "japan" if rec_lang == "japan" else "china-s"
    dpi = int(args.dpi or DEFAULT_OCR_DPI)
    zoom = dpi / 72.0
    start = args.start or 1
    doc = pymupdf.open(pdf)
    page_count = doc.page_count
    end = args.end or page_count
    if start < 1 or end < start or end > page_count:
        doc.close()
        _die(f"Invalid page range {start}-{end} for page_count={page_count}")

    engine = RapidOCR(params={"Rec.lang_type": rec_lang})
    jsonl_path = Path(args.pages_out).expanduser().resolve() if args.pages_out else work / "pages.jsonl"
    out_pdf = Path(args.out).expanduser().resolve() if args.out else None
    overlay_written = 0
    overlay_errors = 0
    pages_done = 0

    mode = "a" if args.append else "w"
    try:
        with jsonl_path.open(mode, encoding="utf-8") as handle:
            for index in range(start, end + 1):
                page = doc[index - 1]
                pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
                try:
                    result = engine(pix.tobytes("png"))
                    lines = _rapidocr_lines(result)
                except Exception as exc:
                    lines = []
                    print(
                        json.dumps({"ok": False, "page": index, "error": str(exc)}, ensure_ascii=False),
                        file=sys.stderr,
                    )
                text = _lines_to_text(lines)
                handle.write(
                    json.dumps(
                        {
                            "page": index,
                            "char_count": len(text.strip()),
                            "text": text,
                            "font_heading_hints": [],
                            "ocr_engine": "rapidocr",
                            "ocr_line_count": len(lines),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                handle.flush()
                if out_pdf is not None:
                    try:
                        overlay_written += _insert_invisible_ocr(page, lines, zoom, fontname)
                    except Exception:
                        overlay_errors += 1
                pages_done += 1
                print(
                    json.dumps(
                        {
                            "progress": True,
                            "page": index,
                            "end": end,
                            "chars": len(text.strip()),
                            "lines": len(lines),
                        },
                        ensure_ascii=False,
                    ),
                    file=sys.stderr,
                )
        if out_pdf is not None:
            out_pdf.parent.mkdir(parents=True, exist_ok=True)
            doc.save(out_pdf, garbage=4, deflate=True)
    finally:
        doc.close()

    return {
        "ok": True,
        "engine": "rapidocr",
        "input": str(pdf),
        "output": str(out_pdf) if out_pdf else None,
        "pages_jsonl": str(jsonl_path),
        "language": language,
        "rapidocr_rec_lang": rec_lang,
        "dpi": dpi,
        "start": start,
        "end": end,
        "pages_done": pages_done,
        "overlay_textboxes": overlay_written,
        "overlay_errors": overlay_errors,
        "work_dir": str(work),
    }


def _ocr_ocrmypdf(args: argparse.Namespace, pdf: Path, work: Path, language: str) -> dict[str, Any]:
    out = Path(args.out).expanduser().resolve() if args.out else work / f"{pdf.stem}.searchable.pdf"
    tesseract = _which_first("tesseract")
    ghostscript = _which_first("gs", "gswin64c", "gswin32c")
    if not tesseract or not ghostscript:
        _die(
            "ocrmypdf engine needs Tesseract and Ghostscript on PATH. "
            f"tesseract={tesseract!r}, ghostscript={ghostscript!r}. "
            "This skill uses RapidOCR only. Run: uv run <script> ocr --engine rapidocr ..."
        )

    cmd = [
        sys.executable,
        "-m",
        "ocrmypdf",
        "--skip-text",
        "-l",
        language,
        str(pdf),
        str(out),
    ]
    if args.deskew:
        cmd.insert(3, "--deskew")
    if args.start or args.end:
        start = args.start or 1
        end = args.end or start
        cmd[3:3] = ["--pages", f"{start}-{end}"]

    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        _die(f"Failed to launch ocrmypdf: {exc}")

    if completed.returncode != 0:
        _die(
            "ocrmypdf failed. Install ocrmypdf in the same isolated env "
            f"(uv run --with ocrmypdf). stderr: {(completed.stderr or '')[-2000:]}"
        )

    return {
        "ok": True,
        "engine": "ocrmypdf",
        "input": str(pdf),
        "output": str(out),
        "language": language,
        "work_dir": str(work),
    }


def cmd_ocr(args: argparse.Namespace) -> None:
    pdf = _pdf_path(args.pdf)
    work = _ensure_dir(_work_dir(pdf, args.work_dir))
    language = _ocr_language(args, work)
    engine = args.engine
    if engine == "auto":
        engine = "rapidocr" if _try_import("rapidocr") else "ocrmypdf"

    if engine == "rapidocr":
        payload = _ocr_rapidocr(args, pdf, work, language)
    elif engine == "ocrmypdf":
        payload = _ocr_ocrmypdf(args, pdf, work, language)
    else:
        _die(f"Unknown OCR engine: {engine}")

    (work / "ocr.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _dump(payload)


def _heading_hints(page) -> list[dict[str, Any]]:
    data = page.get_text("dict")
    sizes: list[float] = []
    spans_out: list[tuple[float, str, str, list[float]]] = []
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = (span.get("text") or "").strip()
                size = float(span.get("size") or 0)
                if not text or size <= 0:
                    continue
                sizes.append(size)
                spans_out.append((size, text, span.get("font") or "", list(span.get("bbox") or [])))
    if not sizes:
        return []
    body = statistics.median(sizes)
    threshold = body * HEADING_SIZE_RATIO
    hints: list[dict[str, Any]] = []
    seen: set[str] = set()
    for size, text, font, bbox in spans_out:
        if size < threshold:
            continue
        if not (2 <= len(text) <= HEADING_MAX_LEN):
            continue
        if text.isdigit():
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        hints.append({"text": text, "size": round(size, 2), "font": font, "bbox": [round(x, 2) for x in bbox]})
        if len(hints) >= 12:
            break
    return hints


def cmd_extract(args: argparse.Namespace) -> None:
    pymupdf = _require_pymupdf()
    pdf = _pdf_path(args.pdf)
    work = _ensure_dir(_work_dir(pdf, args.work_dir))
    out = Path(args.out).expanduser().resolve() if args.out else work / "pages.jsonl"

    doc = pymupdf.open(pdf)
    page_count = doc.page_count
    start = args.start or 1
    end = args.end or page_count
    if start < 1 or end < start or end > page_count:
        doc.close()
        _die(f"Invalid page range {start}-{end} for page_count={page_count}")
    count = 0
    try:
        with out.open("w", encoding="utf-8") as handle:
            for index in range(start, end + 1):
                page = doc[index - 1]
                text = page.get_text("text") or ""
                record = {
                    "page": index,
                    "char_count": len(text.strip()),
                    "text": text,
                    "font_heading_hints": _heading_hints(page) if args.hints else [],
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1
    finally:
        doc.close()

    payload = {
        "ok": True,
        "source_pdf": str(pdf),
        "pages_jsonl": str(out),
        "page_count": count,
        "start": start,
        "end": end,
        "work_dir": str(work),
        "hints": bool(args.hints),
    }
    (work / "extract.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _dump(payload)


def _iter_pages(jsonl: Path) -> Iterable[dict[str, Any]]:
    with jsonl.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def cmd_slice(args: argparse.Namespace) -> None:
    jsonl = Path(args.pages).expanduser().resolve()
    if not jsonl.is_file():
        _die(f"pages.jsonl not found: {jsonl}")
    start, end = args.start, args.end
    if start < 1 or end < start:
        _die("Need 1-based --start/--end with end >= start")

    rows = [row for row in _iter_pages(jsonl) if start <= int(row["page"]) <= end]
    if args.out:
        out = Path(args.out).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as handle:
            for row in rows:
                compact = {
                    "page": row["page"],
                    "char_count": row.get("char_count", 0),
                    "text": row.get("text", ""),
                    "font_heading_hints": row.get("font_heading_hints") or [],
                }
                handle.write(json.dumps(compact, ensure_ascii=False) + "\n")
        _dump({"ok": True, "start": start, "end": end, "count": len(rows), "out": str(out)})
        return
    _dump({"ok": True, "start": start, "end": end, "count": len(rows), "pages": rows})


def cmd_page_window(args: argparse.Namespace) -> None:
    jsonl = Path(args.pages).expanduser().resolve()
    if not jsonl.is_file():
        _die(f"pages.jsonl not found: {jsonl}")
    target = args.page
    radius = max(0, args.radius)
    lo, hi = target - radius, target + radius
    pages = [row for row in _iter_pages(jsonl) if lo <= int(row["page"]) <= hi]
    _dump(
        {
            "ok": True,
            "target_page": target,
            "radius": radius,
            "pages": [
                {
                    "page": row["page"],
                    "text": row.get("text", ""),
                    "font_heading_hints": row.get("font_heading_hints") or [],
                }
                for row in pages
            ],
        }
    )


def _load_outline(path: Path) -> list[list[Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("entries", data) if isinstance(data, dict) else data
    toc: list[list[Any]] = []
    for item in entries:
        if isinstance(item, dict):
            level = int(item["level"])
            title = str(item["title"]).strip()
            page = int(item["page"])
        else:
            level, title, page = int(item[0]), str(item[1]).strip(), int(item[2])
        if level < 1 or page < 1 or not title:
            _die(f"Invalid outline entry: {item}")
        toc.append([level, title, page])
    if not toc:
        _die("Outline is empty")
    return toc


def cmd_check_outline(args: argparse.Namespace) -> None:
    toc = _load_outline(Path(args.outline).expanduser().resolve())
    issues: list[str] = []
    last_by_level: dict[int, int] = {}
    for i, (level, title, page) in enumerate(toc):
        if i == 0 and level != 1:
            issues.append(f"first entry is level {level}, expected 1 ({title})")
        if i > 0:
            prev_level = toc[i - 1][0]
            if level > prev_level + 1:
                issues.append(f"level jump {prev_level} -> {level} at {title}")
        parent_level = level - 1
        if parent_level >= 1 and parent_level in last_by_level and page < last_by_level[parent_level]:
            issues.append(f"page {page} for {title} is before parent page {last_by_level[parent_level]}")
        last_by_level = {lv: pg for lv, pg in last_by_level.items() if lv < level}
        last_by_level[level] = page
        if i > 0 and page < toc[i - 1][2] and level <= toc[i - 1][0]:
            issues.append(f"page went backwards at {title}: {toc[i - 1][2]} -> {page}")
    _dump({"ok": True, "entries": len(toc), "issue_count": len(issues), "issues": issues})


def cmd_write_toc(args: argparse.Namespace) -> None:
    pymupdf = _require_pymupdf()
    pdf = _pdf_path(args.pdf)
    toc = _load_outline(Path(args.outline).expanduser().resolve())
    out = Path(args.out).expanduser().resolve() if args.out else pdf.with_name(f"{pdf.stem}.with-toc.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(pdf)
    try:
        if doc.page_count < 1:
            _die("PDF has no pages")
        for _level, title, page in toc:
            if page > doc.page_count:
                _die(f"Outline page {page} ({title}) exceeds page_count {doc.page_count}")
        doc.set_toc(toc)
        doc.save(out, garbage=4, deflate=True)
    finally:
        doc.close()

    payload = {"ok": True, "input": str(pdf), "output": str(out), "entries": len(toc)}
    work = _work_dir(pdf, args.work_dir)
    if work.exists() or args.work_dir:
        _ensure_dir(work)
        (work / "write.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _dump(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mechanical PDF TOC helpers (no AI).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check-deps", help="Report interpreter and OCR binaries")

    detect = sub.add_parser("detect", help="Inspect PDF text density and existing outline")
    detect.add_argument("pdf")
    detect.add_argument("--work-dir")

    ocr = sub.add_parser("ocr", help="OCR with RapidOCR (default) or ocrmypdf")
    ocr.add_argument("pdf")
    ocr.add_argument("--work-dir")
    ocr.add_argument("--out")
    ocr.add_argument("--pages-out", dest="pages_out", help="Write OCR text JSONL (RapidOCR)")
    ocr.add_argument("--language")
    ocr.add_argument("--engine", choices=["auto", "rapidocr", "ocrmypdf"], default="auto")
    ocr.add_argument("--start", type=int)
    ocr.add_argument("--end", type=int)
    ocr.add_argument("--dpi", type=int, default=DEFAULT_OCR_DPI)
    ocr.add_argument("--deskew", action="store_true")
    ocr.add_argument("--append", action="store_true", help="Append OCR lines to pages_out instead of overwriting")

    extract = sub.add_parser("extract", help="Write per-page JSONL text")
    extract.add_argument("pdf")
    extract.add_argument("--work-dir")
    extract.add_argument("--out")
    extract.add_argument("--start", type=int)
    extract.add_argument("--end", type=int)
    extract.add_argument("--hints", action="store_true", default=True)
    extract.add_argument("--no-hints", action="store_false", dest="hints")

    slice_p = sub.add_parser("slice", help="Slice pages.jsonl to a page range")
    slice_p.add_argument("--pages", required=True)
    slice_p.add_argument("--start", type=int, required=True)
    slice_p.add_argument("--end", type=int, required=True)
    slice_p.add_argument("--out")

    window = sub.add_parser("page-window", help="Load target page +/- radius from JSONL")
    window.add_argument("--pages", required=True)
    window.add_argument("--page", type=int, required=True)
    window.add_argument("--radius", type=int, default=1)

    check_o = sub.add_parser("check-outline", help="Cheap structural checks on an outline JSON")
    check_o.add_argument("--outline", required=True)

    write = sub.add_parser("write-toc", help="Write PDF bookmarks from outline JSON")
    write.add_argument("pdf")
    write.add_argument("--outline", required=True)
    write.add_argument("--out")
    write.add_argument("--work-dir")

    return parser


def main(argv: list[str] | None = None) -> None:
    _configure_stdio()
    args = build_parser().parse_args(argv)
    commands = {
        "check-deps": cmd_check_deps,
        "detect": cmd_detect,
        "ocr": cmd_ocr,
        "extract": cmd_extract,
        "slice": cmd_slice,
        "page-window": cmd_page_window,
        "check-outline": cmd_check_outline,
        "write-toc": cmd_write_toc,
    }
    commands[args.cmd](args)


if __name__ == "__main__":
    main()
