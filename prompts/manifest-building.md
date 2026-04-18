# Prompt: Building `_inbox/<slug>/manifest.json`

You are the orchestrator, and you've been handed proceedings PDF(s) for a conference
pass. Your job here: produce a valid `_inbox/<slug>/manifest.json` so
[`../scripts/orchestrate.py`](../scripts/orchestrate.py) can fan out. This is the
single source of truth for the run.

There is **no one-size-fits-all builder**. Proceedings format is venue-specific, and
bookmark quality is inconsistent. Instead, compose the building blocks in
[`../scripts/manifest_helpers.py`](../scripts/manifest_helpers.py) against the
pattern that matches your venue.

The required entry shape is in
[`conference-overview.md`](conference-overview.md) Step 0 — this file covers *how* to
populate it.

---

## Tools at your disposal

`scripts/manifest_helpers.py` exposes:

| Function | What it does |
|---|---|
| `slugify(title)` | Kebab-case paper slug, truncated at word boundary to 90 chars. |
| `output_paths(conf, slug)` | `(en_path, zh_path)` under `src/content/papers/<conf>/`. |
| `pdf_page_count(pdf)` | Total pages via `pdfinfo`. |
| `pdf_title_from_metadata(pdf)` | Per-paper PDFs (ACM/IEEE) often have Title set; returns `None` on combined proceedings. |
| `probe_bookmarks(pdf)` | Top-level outline (flattened with `depth` tracked). `[]` if no outline. |
| `filter_section_headings(bms)` | Drops obvious in-paper section bookmarks (`Introduction`, `Evaluation`, numbered sections). |
| `probe_footer_offset(pdf, [pdf_pages])` | Infers `pdf_page = logical + offset` from footer text. `None` means no majority (likely per-paper numbering). |
| `spans_from_bookmarks(bms, total)` | Turns ordered paper-root bookmarks into `(title, start, end)` spans. |
| `write_manifest(conf, entries)` | Writes `_inbox/<conf>/manifest.json`. Refuses to clobber non-`pending` runs. |
| `validate_manifest(path)` | Lints for duplicate slugs / output paths, missing PDFs, inverted page ranges. |

CLI shortcuts (no Python needed):

```bash
python3 scripts/manifest_helpers.py bookmarks <pdf> [--filter-sections]
python3 scripts/manifest_helpers.py offset <pdf> --samples 14 300 700
python3 scripts/manifest_helpers.py validate _inbox/<slug>/manifest.json
```

---

## Decide which venue pattern you're in

Before writing any code, look at what you actually have:

```bash
ls _inbox/<slug>/
pdfinfo _inbox/<slug>/<the-pdf>.pdf | head
python3 scripts/manifest_helpers.py bookmarks <the-pdf> | head -20
```

The three common patterns:

### Pattern A: USENIX-style combined PDF with per-paper bookmarks
(FAST, OSDI, NSDI, ATC, often SOSP)

One huge PDF (`fast26_full_proceedings.pdf`, `osdi25_full_proceedings.pdf`, …).
Top-level outline usually has one entry per paper, often with keys like
`fast26-yang` or `osdi25-author`. Sub-bookmarks for sections (`Introduction`,
`Evaluation`, …) are mixed in at the same depth, so `filter_section_headings`
or a depth-0 filter helps but isn't perfect.

**Assembly recipe:**
1. Fetch the program URL (USENIX page) — that's the authoritative list of titles
   and authors. Parse it into `[{title, authors, affiliations}, …]`.
2. `bms = probe_bookmarks(pdf)`. Look for a depth (usually 0) that cleanly
   isolates paper roots. Match program-URL titles to bookmarks by order (both
   should follow proceedings order). If some bookmarks are missing,
   cross-reference manually — don't guess.
3. `offset = probe_footer_offset(pdf, [first_paper_pdf_page, mid_paper_pdf_page,
   last_paper_pdf_page])`. If `offset` is a positive integer, every paper's
   `pdf_page_start = logical_first_page + offset`. If `offset is None`, the PDF
   uses per-paper numbering — fall back to `spans_from_bookmarks`.
4. Assemble `ManifestEntry`s and `write_manifest(...)`.

**FAST '26 real example:** `probe_footer_offset(..., [14, 400, 700])` → `13`.
Every paper's logical page 1 is PDF page 14; logical page 5 is PDF page 18. The
44-paper manifest was built this way.

### Pattern B: ACM-style per-paper PDFs
(ASPLOS sometimes, recent SIGMOD, PLDI, POPL)

Proceedings ship as one PDF per paper, usually named by DOI suffix
(`3779212.3795613.pdf`). Each PDF's `pdf_page_start` is `1` and
`pdf_page_end = pdf_page_count(pdf)`. No bookmarks needed.

**Assembly recipe:**
1. `pdfs = sorted(glob("_inbox/<slug>/pdfs/*.pdf"))`.
2. For each PDF: `title = pdf_title_from_metadata(pdf)` (usually populated for
   ACM typesetting), plus authors/affiliations from the ACM DL page or the
   first-page text of the PDF.
3. `pdf_page_start = 1`, `pdf_page_end = pdf_page_count(pdf)`.
4. `doi_url = "https://doi.org/10.1145/<...>"` derived from the filename.
5. Write manifest.

### Pattern C: Mixed (ASPLOS '26 shape)
One giant ACM volume (`3779212.pdf`) whose outline uses **DOI fragments** as
bookmark titles (`3779212.3795613`), plus a smaller companion volume with no
outline. Bookmark titles are unreadable; you need to resolve them against the
ACM DL program page.

**Assembly recipe:**
1. Fetch the program URL. Get `[{title, authors, doi}, …]`, where `doi` is the
   suffix like `3795613`.
2. `bms = probe_bookmarks(vol2_pdf)`. Titles look like `3779212.3795613` — parse
   the suffix and join against the program-URL `doi` field.
3. For vol1 (no outline): fall back to the program URL's stated page ranges, or
   read the first page of each known PDF-page-range candidate to match titles.
4. Assemble with `slugify(program_url_title)` as the slug — never use the DOI
   fragment as the user-facing slug.

---

## Sanity checks before `write_manifest`

Run through these *before* the expensive fan-out:

- Paper count matches the program page's advertised total.
- Every `pdf_path` exists on disk (`validate_manifest` checks this).
- No two entries share a slug or output path.
- `pdf_page_end >= pdf_page_start` for every entry.
- Spot-check 3 entries by opening the PDF at `pdf_page_start` — is it page 1 of
  that paper? Are the author names matching? A one-off error here multiplies by
  N during fan-out.
- Run `python3 scripts/manifest_helpers.py validate _inbox/<slug>/manifest.json`.

---

## When to give up on automation and ask the user

If any of these happen, stop the automation and ask:

- Bookmark titles are opaque keys AND the program URL won't parse cleanly.
- `probe_footer_offset` returns `None` (per-paper numbering) AND no usable
  bookmarks.
- Paper count in your manifest differs from the program URL by more than 1–2.
- The PDF has merged volumes with inconsistent schemes (e.g. ASPLOS vol1 vs
  vol2 in 2026).

The cost of a bad manifest is N × sub-agent runs on the wrong page ranges, which
is far more expensive than a five-minute clarification.
