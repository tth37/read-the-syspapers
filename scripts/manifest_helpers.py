#!/usr/bin/env python3
"""Building blocks for assembling `_inbox/<slug>/manifest.json`.

The orchestrator (Claude Code) composes these helpers — this module is deliberately
NOT a one-shot "run this and it works" script. Different venues ship proceedings in
different shapes:

  USENIX (FAST, OSDI, NSDI, ATC, SOSP):
    One combined proceedings PDF. Per-paper bookmarks usually present at top level.
    Footer page numbers restart at 1 per paper in some years, run continuously in
    others. Use `probe_bookmarks` + `probe_footer_offset`.

  ACM (ASPLOS, SIGMOD, PLDI, POPL):
    Typically one PDF per paper (keyed by DOI like `3779212.3795613`), or a single
    mega-volume whose outline uses DOI fragments as entry titles. Bookmarks may be
    absent entirely on cover/frontmatter volumes. Use `list_pdf_files` + look up
    titles from the program URL rather than from the PDF bookmarks.

  IEEE (HPCA, ISCA, MICRO):
    Usually per-paper PDFs downloaded individually. No bookmarks inside; title comes
    from the program page or `pdfinfo -Title`.

The orchestrator picks the pattern that fits the proceedings it was handed. See
`prompts/manifest-building.md` for worked examples per venue class.

Entry point conventions:
  - Functions that parse PDFs return plain Python data (list/dict). They never
    mutate state on disk.
  - `write_manifest()` is the only function that touches `_inbox/`.
  - Everything here is idempotent and safe to run twice.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
from dataclasses import dataclass, asdict, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Slug + path utilities
# ---------------------------------------------------------------------------

_SLUG_STRIP = re.compile(r"[^a-z0-9\s-]")
_SLUG_DASHES = re.compile(r"[\s_-]+")


def slugify(title: str, max_len: int = 90) -> str:
    """Kebab-case slug from a paper title. Truncates at word boundary to `max_len`."""
    s = title.lower()
    # Drop punctuation, keep word chars / spaces / hyphens
    s = _SLUG_STRIP.sub(" ", s)
    s = _SLUG_DASHES.sub("-", s).strip("-")
    if len(s) <= max_len:
        return s
    # Truncate on word boundary, not mid-word
    cut = s[:max_len]
    if "-" in cut:
        cut = cut.rsplit("-", 1)[0]
    return cut


def output_paths(conference_slug: str, paper_slug: str) -> tuple[str, str]:
    """Return (en_path, zh_path) relative to repo root."""
    base = f"src/content/papers/{conference_slug}/{paper_slug}"
    return f"{base}.en.md", f"{base}.zh-cn.md"


# ---------------------------------------------------------------------------
# PDF inspection (calls out to `pdfinfo` / `pdftotext`; no Python PDF dep needed)
# ---------------------------------------------------------------------------

def pdf_page_count(pdf_path: str) -> int:
    out = subprocess.check_output(["pdfinfo", pdf_path], text=True)
    for line in out.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    raise RuntimeError(f"pdfinfo produced no Pages field for {pdf_path}")


def pdf_title_from_metadata(pdf_path: str) -> Optional[str]:
    """Return the Title field from pdfinfo, or None. Per-paper ACM/IEEE PDFs often
    have the paper title here; USENIX combined proceedings usually don't."""
    out = subprocess.check_output(["pdfinfo", pdf_path], text=True)
    for line in out.splitlines():
        if line.startswith("Title:"):
            title = line.split(":", 1)[1].strip()
            return title or None
    return None


@dataclass
class Bookmark:
    title: str
    pdf_page: int  # 1-indexed page in the combined PDF
    depth: int = 0


def probe_bookmarks(pdf_path: str) -> list[Bookmark]:
    """Extract top-level bookmarks from a combined-proceedings PDF.

    Requires PyPDF2 (already available on this machine). Returns flattened
    list with `depth=0` for the first layer of the outline. If there is no
    outline, returns [].

    Caveat: some USENIX PDFs flatten per-paper outlines so sub-chapter headings
    ('Introduction', 'Evaluation', …) appear at depth 0 alongside paper titles.
    The orchestrator must filter those out — look at the titles and compare
    against the program URL. Helper: `filter_section_headings()`.
    """
    try:
        from PyPDF2 import PdfReader  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "PyPDF2 is required for probe_bookmarks(). Install with `pip install PyPDF2`."
        ) from e

    reader = PdfReader(pdf_path)
    result: list[Bookmark] = []

    def _walk(node, depth: int):
        if isinstance(node, list):
            for child in node:
                _walk(child, depth + 1)
        elif hasattr(node, "title"):
            try:
                page_num = reader.get_destination_page_number(node) + 1  # 1-indexed
            except Exception:
                return
            if page_num <= 0:
                # PyPDF2 returns -1 for unresolvable destinations; skip those
                # rather than injecting bogus page-0 entries.
                return
            result.append(Bookmark(title=str(node.title), pdf_page=page_num, depth=depth))

    _walk(reader.outline, -1)  # top-level children are depth 0
    result.sort(key=lambda b: b.pdf_page)
    return result


_SECTION_HEADING_PATTERNS = (
    r"^introduction$",
    r"^background$",
    r"^related\s+work$",
    r"^motivation$",
    r"^design$",
    r"^implementation$",
    r"^evaluation$",
    r"^methodology$",
    r"^experiments?$",
    r"^results$",
    r"^discussion$",
    r"^conclusion$",
    r"^references$",
    r"^appendix($|\s+[a-z])",
    r"^acknowledgments?$",
    r"^\d+(\.\d+)*\s+\w+",  # "2.3 Something"
)


def filter_section_headings(bookmarks: list[Bookmark]) -> list[Bookmark]:
    """Drop bookmark entries that look like section headings inside a paper
    (rather than paper titles themselves)."""
    kept: list[Bookmark] = []
    for b in bookmarks:
        lower = b.title.strip().lower()
        if any(re.search(p, lower) for p in _SECTION_HEADING_PATTERNS):
            continue
        if len(lower.split()) <= 1 and lower not in ("abstract",):
            # Single-word bookmarks are almost always sections, not titles.
            continue
        kept.append(b)
    return kept


# ---------------------------------------------------------------------------
# Footer-offset probing (for USENIX-style combined PDFs)
# ---------------------------------------------------------------------------

def probe_footer_offset(pdf_path: str, sample_pdf_pages: list[int]) -> Optional[int]:
    """Read the footers of a few PDF pages and infer the offset between logical
    (printed) page numbers and PDF (1-indexed) page numbers.

    A return value of N means `pdf_page = logical_page + N`. Returns None if no
    consistent offset was detected.

    Typical usage: probe the first, middle, and last paper's first page — if all
    three agree, the PDF uses one constant offset (e.g. FAST '26 is +13). If they
    disagree, the PDF likely restarts numbering per paper (treat each paper
    independently via bookmarks instead).
    """
    offsets: list[int] = []
    for pdf_page in sample_pdf_pages:
        logical = _extract_footer_page_number(pdf_path, pdf_page)
        if logical is not None:
            offsets.append(pdf_page - logical)
    if not offsets:
        return None
    # Pick the offset that appears most often.
    most = max(set(offsets), key=offsets.count)
    if offsets.count(most) < max(1, len(offsets) // 2 + 1):
        return None  # no majority — likely per-paper numbering
    return most


def _extract_footer_page_number(pdf_path: str, pdf_page: int) -> Optional[int]:
    """Pull the first number from the footer text of a single PDF page."""
    try:
        text = subprocess.check_output(
            ["pdftotext", "-layout", "-f", str(pdf_page), "-l", str(pdf_page), pdf_path, "-"],
            text=True, errors="replace",
        )
    except subprocess.CalledProcessError:
        return None
    # Footer is usually on the last non-empty line, or a line with just a number.
    for line in reversed([ln.strip() for ln in text.splitlines()]):
        if not line:
            continue
        m = re.match(r"^(\d+)$", line)
        if m:
            return int(m.group(1))
        # Some venues put "USENIX Association   15th USENIX Conference ...   page"
        m = re.search(r"\b(\d{1,4})\b\s*$", line)
        if m:
            candidate = int(m.group(1))
            if candidate < 10000:
                return candidate
    return None


# ---------------------------------------------------------------------------
# Manifest assembly
# ---------------------------------------------------------------------------

@dataclass
class ManifestEntry:
    slug: str
    title: str
    authors: list[str]
    affiliations: list[str]
    pdf_path: str
    pdf_page_start: int
    pdf_page_end: int
    output_path_en: str
    output_path_zh: str
    volume: int = 1
    doi_url: Optional[str] = None
    pdf_url: Optional[str] = None
    category: Optional[str] = None
    status: str = "pending"
    last_error: Optional[str] = None


def spans_from_bookmarks(
    bookmarks: list[Bookmark],
    total_pages: int,
) -> list[tuple[str, int, int]]:
    """Convert a list of paper-root bookmarks to (title, pdf_start, pdf_end) tuples.

    Each paper runs until the next paper's first page minus one; the last paper
    runs to `total_pages`. Expects bookmarks already filtered of section headings.
    """
    spans: list[tuple[str, int, int]] = []
    for i, bm in enumerate(bookmarks):
        start = bm.pdf_page
        end = (bookmarks[i + 1].pdf_page - 1) if i + 1 < len(bookmarks) else total_pages
        spans.append((bm.title, start, end))
    return spans


def write_manifest(
    conference_slug: str,
    entries: list[ManifestEntry],
    inbox_root: pathlib.Path = pathlib.Path("_inbox"),
) -> pathlib.Path:
    """Write `_inbox/<conference_slug>/manifest.json` and return the path.

    Refuses to clobber a manifest that already has any non-`pending` status —
    the orchestrator should inspect and decide rather than silently overwriting
    a partial run.
    """
    target = inbox_root / conference_slug / "manifest.json"
    if target.exists():
        existing = json.loads(target.read_text())
        if any(e.get("status") not in (None, "pending") for e in existing):
            raise RuntimeError(
                f"refusing to overwrite {target} — has non-pending entries. "
                "Move it aside first if you really want to rebuild."
            )
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(e) for e in entries]
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(target)
    return target


def validate_manifest(path: pathlib.Path) -> list[str]:
    """Return a list of human-readable problems with a manifest, or [] if clean.

    Checks the invariants the orchestrator script later depends on: unique slugs,
    unique output paths, positive page spans, referenced PDF files exist.
    """
    data = json.loads(path.read_text())
    problems: list[str] = []
    seen_slugs: set[str] = set()
    seen_paths: set[str] = set()
    for i, e in enumerate(data):
        where = f"entry[{i}] ({e.get('slug', '?')})"
        for required in ("slug", "title", "pdf_path", "pdf_page_start",
                         "pdf_page_end", "output_path_en", "output_path_zh"):
            if not e.get(required) and e.get(required) != 0:
                problems.append(f"{where}: missing {required}")
        slug = e.get("slug")
        if slug in seen_slugs:
            problems.append(f"{where}: duplicate slug {slug!r}")
        seen_slugs.add(slug)
        for key in ("output_path_en", "output_path_zh"):
            p = e.get(key)
            if p in seen_paths:
                problems.append(f"{where}: duplicate {key} {p!r}")
            seen_paths.add(p)
        try:
            if int(e.get("pdf_page_end", 0)) < int(e.get("pdf_page_start", 0)):
                problems.append(f"{where}: pdf_page_end < pdf_page_start")
        except (TypeError, ValueError):
            problems.append(f"{where}: non-integer page range")
        pdf = e.get("pdf_path")
        if pdf and not pathlib.Path(pdf).exists():
            problems.append(f"{where}: pdf_path missing on disk: {pdf}")
    return problems


# ---------------------------------------------------------------------------
# CLI (for spot-use; not the main intended entry point)
# ---------------------------------------------------------------------------

def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_bk = sub.add_parser("bookmarks", help="Print bookmarks found in a PDF.")
    p_bk.add_argument("pdf")
    p_bk.add_argument("--filter-sections", action="store_true")

    p_off = sub.add_parser("offset", help="Probe the logical-to-PDF page offset.")
    p_off.add_argument("pdf")
    p_off.add_argument("--samples", nargs="+", type=int, required=True,
                       help="PDF page numbers to sample (e.g. 14 300 700).")

    p_v = sub.add_parser("validate", help="Validate a manifest file.")
    p_v.add_argument("manifest")

    args = ap.parse_args()

    if args.cmd == "bookmarks":
        bms = probe_bookmarks(args.pdf)
        if args.filter_sections:
            bms = filter_section_headings(bms)
        for bm in bms:
            print(f"  p{bm.pdf_page:>4}  [d={bm.depth}]  {bm.title}")
        print(f"({len(bms)} entries)")
        return 0

    if args.cmd == "offset":
        offset = probe_footer_offset(args.pdf, args.samples)
        print(f"offset={offset}" if offset is not None else "offset=<no majority>")
        return 0 if offset is not None else 1

    if args.cmd == "validate":
        problems = validate_manifest(pathlib.Path(args.manifest))
        if not problems:
            print("clean")
            return 0
        for p in problems:
            print(p)
        return 1

    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
