# Prompt: Conference overview pass

You have been asked to produce a full overview of a systems top-conference — e.g.
"Do an overview of OSDI 2025." This prompt is self-contained: you should be able to
complete the task by following it, regardless of which coding agent is running.

Before starting, read [`../AGENTS.md`](../AGENTS.md) for hard rules (agent identity,
bilingual output, no fabrication, no committed PDFs, resumable manifest, micro-batches).

---

## Inputs expected from the user

- Venue name (e.g. `OSDI`, `SOSP`, `NSDI`).
- Year (4-digit).
- **Optional but common**: a path to a locally-available proceedings ZIP or folder, if the
  user has already downloaded PDFs (USENIX and ACM often block bulk scraping).
- **Optional**: a page-range filter inside a combined proceedings PDF (e.g. "papers 1–20
  of ASPLOS '26 proceedings volume 1, pages 1–340"). Resumability depends on this: a run
  must be able to stop and pick up on a later invocation without redoing work.

If any of these are missing, ask the user once, then proceed.

---

## Step 0 — Establish the manifest

Create `_inbox/<slug>/manifest.json` if it does not exist. It is the **single source of
truth** for which papers are in scope, where their PDFs live, and which ones have been
summarized. Schema (one entry per paper):

```json
{
  "slug": "kebab-case-of-title",
  "title": "Exact title from the paper",
  "authors": ["First Last", "First Last"],
  "affiliations": ["University / Company"],
  "doi_url": "https://doi.org/…",
  "pdf_url": "https://…",
  "volume": 1,
  "pdf_path": "_inbox/asplos-2026/pdfs/kebab-case.pdf",
  "pdf_page_start": 17,
  "pdf_page_end": 33,
  "category": "scheduling",
  "output_path_en": "src/content/papers/asplos-2026/kebab-case.en.md",
  "output_path_zh": "src/content/papers/asplos-2026/kebab-case.zh-cn.md",
  "status": "pending",
  "last_error": null
}
```

Valid `status` values: `pending`, `in-progress`, `done`, `skipped`, `failed`. On every
restart, read the manifest first and resume from the first non-`done` entry. Never
re-summarize a `done` paper.

The manifest lives under `_inbox/` and is gitignored — do not commit it.

## Step 1 — Identify the venue and create the conference files

1. Resolve the canonical program URL:
   - **USENIX venues** (OSDI, NSDI, ATC, FAST, USENIX Security): `https://www.usenix.org/conference/<venue-lower><yy>/technical-sessions`
   - **SOSP**: `https://sigops.org/s/conferences/sosp/<yyyy>/` (program page linked from there).
   - **EuroSys / ASPLOS**: linked from the conference's own site (search `<venue> <year>`).
   - **MLSys**: `https://mlsys.org/Conferences/<yyyy>`.
   - Other venues: search for the official program page.

2. Compute the conference slug: `<venue-lower>-<yyyy>` (e.g. `osdi-2025`, `sosp-2024`).
3. Create or update **both** of:
   - `src/content/conferences/<slug>.en.md`
   - `src/content/conferences/<slug>.zh-cn.md`

   using [`templates/conference.md`](templates/conference.md). Fill in metadata you already
   know (venue, year, title, URL). Leave the body minimal for now. Set:
   - `overview_status: in-progress`
   - `written_by: <your agent id>`
   - `summary_date: <today in YYYY-MM-DD>`
   - `categories: []` (you'll populate it after Step 4 during categorization)

   The two language files share frontmatter verbatim except the body prose. The
   `title`/`location`/`dates` strings use the conference's official English wording in
   both files (proper nouns, don't translate).

## Step 2 — Get the accepted-paper list

Scrape the official program page and build a list of papers. For each paper record:

- Title (exact English)
- Authors (full names, in author order)
- Affiliations (per author if listed, or aggregate)
- PDF URL if openly hosted (USENIX open-access PDFs; ACM open-access; author homepages)
- DOI / abstract URL if PDF is paywalled
- Abstract text (optional; helps the per-paper agent orient faster)

Seed `_inbox/<slug>/manifest.json` with one entry per paper, `status: "pending"`.

Sanity check: does the count roughly match what the call-for-papers advertised? If the site
is incomplete (e.g. only day-1 is listed), tell the user and wait for the full list.

## Step 3 — Obtain PDFs

Try, in order:

1. The conference's open-access PDF URL from Step 2.
2. Author homepage (grep author names + paper title).
3. arXiv (many systems papers are mirrored there).
4. Google Scholar's top-1 PDF link.

Save PDFs to `_inbox/<slug>/pdfs/<paper-slug>.pdf` and update `pdf_path` in the manifest.

If the user supplied a combined proceedings PDF, do **not** re-download papers — extract
page ranges from the proceedings and record `pdf_path`, `pdf_page_start`, `pdf_page_end`,
and `volume` in each manifest entry instead. A paper-summary sub-agent that sees a page
range reads only those pages, not the whole proceedings.

If any paper's PDF cannot be retrieved after these attempts, set that manifest entry's
`status: "skipped"` and `last_error: "needs manual PDF"`, then tell the user:

> "I could not fetch N PDFs automatically. I've marked them `skipped` in the manifest.
> Please drop the PDFs (or the combined proceedings) into `_inbox/<slug>/pdfs/` and
> re-run me — I'll resume from the manifest and will only process the skipped entries."

Do **not** invent summaries for missing PDFs.

## Step 4 — Summarize papers in micro-batches (with a pilot first)

**Pilot.** Before launching the full batch, pick ONE representative paper from the
manifest (ideally a well-known one with a clear contribution), run
[`paper-summary.md`](paper-summary.md) on it yourself, inspect both the `.en.md` and
`.zh-cn.md` outputs for depth and schema compliance, and only then parallelize. The pilot
catches template misalignment before it's repeated 40×.

**Batching.** Process at most **1–3 papers per sub-task**, or ~60 PDF pages of total
input, whichever is smaller. For each sub-agent batch, pass:

- `pdf_path`, and (if applicable) `pdf_page_start` / `pdf_page_end` / `volume`
- `output_path_en` and `output_path_zh` from the manifest
- `conference_slug` (e.g. `osdi-2025`)
- `agent_id` — propagate yours; sub-agents inherit the identity of their launcher
- `tag_vocabulary_path`: `prompts/tag-vocabulary.md`

Between batches: update the manifest (`status: "in-progress"` → `"done"`), save a
temporary rolling log at `_inbox/<slug>/run.log`, and periodically commit the so-far
summaries locally (see Step 6). This means a crash at paper 17 loses at most one batch,
not the whole run.

**Temp-dir hygiene.** Any intermediate artifacts (extracted per-paper PDFs, OCR output,
scratch JSON) go under `_inbox/<slug>/tmp/`. Do not leave them in the repo root. Do not
leave them uncleaned after the run.

**Sub-agent output contract.** Each sub-agent must produce TWO schema-valid markdown
files (one `.en.md`, one `.zh-cn.md`) per paper. If a sub-agent errors out on a paper,
mark that manifest entry `status: "failed"` with `last_error: <message>` and continue with
the others — never leave a partial summary in `src/content/papers/`.

After each batch completes, run `npm run build` to verify every new paper file passes Zod
validation. Fix schema violations before starting the next batch.

## Step 5 — Categorize papers

After all per-paper summaries exist, group them into 4–8 categories that reflect this
year's program (not a generic topic list — each venue has its own shape).

1. Choose 4–8 category ids (kebab-case, short) and a human-readable title for each.
2. Write a one-paragraph description per category — what makes a paper belong there, what
   differentiates it from the neighboring category.
3. Add the array to **both** conference `.en.md` and `.zh-cn.md` frontmatter as
   `categories:`. Titles and descriptions must be translated per-language; `id` stays the
   same across both files.
4. For each paper, set `category: <id>` in **both** its `.en.md` and `.zh-cn.md`
   frontmatter. Orphan papers are allowed (no `category` field) but try to keep it under 10%.

Example conference frontmatter:

```yaml
categories:
  - id: llm-inference
    title: "LLM inference systems"
    description: "Serving, caching, and scheduling for large-model inference."
  - id: scheduling
    title: "Datacenter scheduling"
    description: "Cluster-level task placement and resource management."
```

## Step 6 — Synthesize the conference-level overview

Hand off to [`conference-synthesis.md`](conference-synthesis.md) (which reads the
per-paper summaries, not the PDFs). Its job: write the body of both conference files
(themes, trends, must-reads, stats) and flip `overview_status: complete`.

## Step 7 — Commit and stop

Create a branch named `overview/<slug>` and commit in logical chunks:

- One commit: conference metadata (both languages) + categories.
- One commit per ~10 papers (each commit contains both `.en.md` and `.zh-cn.md` for those
  papers). Keeps history bisectable.
- One final commit: conference-level synthesis body.

Use the conventional prefix `overview(<slug>):` on each commit. Example:

```
overview(osdi-2025): add conference metadata, categories
overview(osdi-2025): summarize papers 1-10
overview(osdi-2025): synthesize conference overview
```

**Do not push. Do not open a PR.** Leave the branch local and tell the user it's ready for
review.

---

## Failure modes to watch for

- **Abstract-copying.** If your summary reads like the abstract, rewrite it. PhD-depth
  means synthesis, not paraphrase.
- **Inventing numbers.** Re-check every quantitative claim against the paper. If you can't
  find it, drop the number.
- **Unilingual drift.** Dropping the Chinese version when you run out of context is the
  #1 failure mode. Either produce both, or don't mark the paper `done`.
- **Translating paper titles or tags.** Don't. Titles and tags stay English in both
  language files. Only the `oneline` and the section bodies are translated.
- **Schema drift.** Do not add frontmatter fields that aren't in `src/content/config.ts`.
- **Tag sprawl.** Stay within the vocabulary in `prompts/tag-vocabulary.md`. Propose new
  tags in a single batch to the user; don't sprinkle new ones silently.
- **Context-window melt.** If you feel slow, stop, commit what you have, update the
  manifest, and tell the user you're pausing. A new session will resume from the manifest
  cheaper than a dying one will finish.
