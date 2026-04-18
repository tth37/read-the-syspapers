# Prompt: Conference overview pass (orchestrator)

You are the **orchestrator** for a full conference pass — e.g. "Do an overview of
OSDI 2026." In practice you are Claude Code, driving the work from a single long-lived
session while farming per-paper summaries out to sub-agents (`codex exec` or `claude -p`)
via [`../scripts/orchestrate.py`](../scripts/orchestrate.py). This split keeps your
context focused on planning, categorization, and synthesis — the heavy PDF-reading
happens inside short-lived sub-processes that each die with their own context.

Before starting, read [`../AGENTS.md`](../AGENTS.md) for hard rules (agent identity with
model qualifier, bilingual output, no fabrication, no committed PDFs, resumable manifest,
one paper per sub-agent).

---

## Inputs expected from the user

- Venue name (e.g. `OSDI`, `SOSP`, `NSDI`).
- Year (4-digit).
- **The full proceedings PDF(s)**, already dropped under `_inbox/<slug>/` by the user.
  You do **not** download papers — assume the user has handed them over.
- **Optional**: a page-range map (title → `volume`, `pdf_page_start`, `pdf_page_end`) if
  the user has already parsed the proceedings ToC. If not, you parse the ToC yourself as
  part of manifest generation.

If any of these are missing, ask the user once, then proceed.

---

## Step 0 — Establish the manifest

The manifest at `_inbox/<slug>/manifest.json` is the **single source of truth** for the
run. Every sub-agent launch is keyed on it, and [`../scripts/orchestrate.py`](../scripts/orchestrate.py)
flips statuses atomically (`pending` → `in-progress` → `done` | `failed`).

Required per-entry shape (extra fields ok, but keep these):

```json
{
  "slug": "kebab-case-of-title",
  "title": "Exact title from the paper",
  "authors": ["First Last", "First Last"],
  "affiliations": ["University / Company"],
  "doi_url": "https://doi.org/…",
  "pdf_url": "https://…",
  "volume": 1,
  "pdf_path": "_inbox/asplos-2026/proceedings-vol1.pdf",
  "pdf_page_start": 17,
  "pdf_page_end": 33,
  "category": "",
  "output_path_en": "src/content/papers/asplos-2026/kebab-case.en.md",
  "output_path_zh": "src/content/papers/asplos-2026/kebab-case.zh-cn.md",
  "status": "pending",
  "last_error": null
}
```

Valid `status` values: `pending`, `in-progress`, `done`, `skipped`, `failed`. The script
writes `started_at`, `finished_at`, `duration_s`, and `last_error` on each flip; you don't
need to author those fields.

The manifest lives under `_inbox/` and is gitignored — do not commit it.

## Step 1 — Identify the venue and create the conference files

1. Resolve the canonical program URL (USENIX / SIGOPS / SIGARCH / MLSys / …).
2. Compute the conference slug: `<venue-lower>-<yyyy>` (e.g. `osdi-2026`, `sosp-2025`).
3. Create or update **both** of:
   - `src/content/conferences/<slug>.en.md`
   - `src/content/conferences/<slug>.zh-cn.md`

   using [`templates/conference.md`](templates/conference.md). Set:
   - `overview_status: in-progress`
   - `written_by: "Claude Opus 4.7 (Claude Code)"` (or whatever model-qualified string
     matches the session you're running)
   - `summary_date: <today in YYYY-MM-DD>`
   - `categories: []` (populated in Step 4 after per-paper summaries land)

   Body stays minimal for now. The two language files share frontmatter verbatim except
   the body prose. `title`/`location`/`dates` use the conference's official English
   wording in both files.

## Step 2 — Build the manifest

From the accepted-papers program page **and** the user-provided proceedings PDFs:

1. Scrape / copy the paper list: title, authors, affiliations, DOI/PDF URL, abstract.
2. For each paper, determine which `volume` of the proceedings contains it and the
   `pdf_page_start` / `pdf_page_end` range within that volume.
3. Compute the `slug` (`kebab-case-of-title`, trimmed to ~90 chars if long) and derive
   `output_path_en` / `output_path_zh` under `src/content/papers/<conference_slug>/`.
4. Write `_inbox/<slug>/manifest.json` as a JSON array. Set every entry's initial
   `status: "pending"`.

Sanity checks before launching any sub-agent:

- Paper count matches what the call-for-papers advertised (or the user's stated total).
- Every `pdf_path` exists on disk.
- No two entries share a slug.
- `output_path_en` and `output_path_zh` are unique across the manifest.

## Step 3 — Pilot one paper manually

Before fanning out, pick ONE representative paper (ideally a well-known one with a clear
contribution) and run a sub-agent on it manually so you can inspect depth and schema
compliance:

```
./scripts/orchestrate.py \
  --conference <slug> \
  --agent codex \
  --slug <pilot-slug> \
  --concurrency 1
```

Read both the `.en.md` and `.zh-cn.md` outputs. If the depth, structure, or frontmatter
don't match the template, fix [`paper-summary.md`](paper-summary.md) or the
[`paper-summary-invocation.md`](paper-summary-invocation.md) template **before**
parallelizing. The pilot catches misalignment once; skipping it costs you N × the fix.

## Step 4 — Fan out via `scripts/orchestrate.py`

Once the pilot looks good, launch the full run:

```
./scripts/orchestrate.py \
  --conference <slug> \
  --agent codex \
  --concurrency 5
```

What the script does:

- Submits every `pending` entry to a `ThreadPoolExecutor(max_workers=N)` up front.
- Renders [`paper-summary-invocation.md`](paper-summary-invocation.md) with variables
  from the manifest entry + the agent registry (model name, agent id) and pipes the
  result to `codex exec` / `claude -p`.
- Flips the entry `pending` → `in-progress` at launch, `done` / `failed` at exit (under
  a thread lock). `last_error` gets the tail of stderr on failure.
- As workers finish, the executor immediately picks up the next queued slug — a
  publisher-subscriber pipeline, **not** batch-wait-then-start-next-batch.
- Streams per-paper combined output to `_inbox/<slug>/logs/<paper-slug>.log` for debug.

Useful flags:

| Flag | When to use |
|---|---|
| `--dry-run` | Print the selection and exit. Use before every run to confirm you're about to do what you think you are. |
| `--smoke` | Sends `"say hi in one sentence…"` instead of the real prompt. Proves dispatch/timeout/status-flip logic without touching content. Use when debugging the orchestrator itself. |
| `--limit N` | Process only the first N pending entries. Good for a second pilot. |
| `--slug foo --slug bar` | Target specific papers (overrides pending selection). |
| `--retry-failed` | Re-queue `failed` and stale `in-progress` entries. |
| `--timeout 1800` | Per-sub-agent wall-clock cap (default 1800s). |
| `--agent claude-code` | Use Claude Code sub-agents instead of Codex. Comparable runs across agents are a feature — the site shows `written_by`. |

Between runs:

- Check `_inbox/<slug>/manifest.json` for `failed` entries. Inspect the `last_error`
  tail; inspect `_inbox/<slug>/logs/<paper-slug>.log` for the full run; re-run with
  `--retry-failed`.
- Run `npm run build` periodically to catch schema violations early. If a specific
  sub-agent produced invalid frontmatter, flip its manifest entry back to `pending`
  manually and re-run.

## Step 5 — Categorize papers

After every manifest entry is `done` (or intentionally `skipped`), group papers into 4–8
categories that reflect this year's program (not a generic topic list — each venue has
its own shape).

1. Choose 4–8 category ids (kebab-case, short) and a human-readable title for each.
2. Write a one-paragraph description per category — what makes a paper belong there, what
   differentiates it from the neighboring category.
3. Add the array to **both** conference `.en.md` and `.zh-cn.md` frontmatter as
   `categories:`. Titles and descriptions must be translated per-language; `id` stays the
   same across both files.
4. For each paper, set `category: <id>` in **both** its `.en.md` and `.zh-cn.md`
   frontmatter. Orphan papers are allowed (no `category` field) but try to keep it under 10%.

## Step 6 — Synthesize the conference-level overview

Hand off to [`conference-synthesis.md`](conference-synthesis.md) (which reads the
per-paper summaries, not the PDFs). Its job: write the body of both conference files
(themes, trends, must-reads, stats) and flip `overview_status: complete`.

## Step 7 — Commit and stop

Create a branch named `overview/<slug>` and commit in logical chunks:

- One commit: conference metadata (both languages).
- One commit per ~10 papers (each commit contains both `.en.md` and `.zh-cn.md` for those
  papers). Keeps history bisectable.
- One commit: categorization (both languages, plus `category:` fields on papers).
- One final commit: conference-level synthesis body.

Use the conventional prefix `overview(<slug>):` on each commit. Example:

```
overview(osdi-2026): add conference metadata
overview(osdi-2026): summarize papers 1-10
overview(osdi-2026): categorize 48 papers into 6 tracks
overview(osdi-2026): synthesize conference overview
```

**Do not push. Do not open a PR.** Leave the branch local and tell the user it's ready
for review.

---

## Failure modes to watch for (orchestrator edition)

- **Context melt during categorization.** By the time all papers land, you've already
  spent a lot of context. If the session feels slow, commit the per-paper summaries, push
  the branch, and start a fresh session for Step 5 — the new session reads the finished
  summaries and the manifest, which is cheaper than finishing in a dying context.
- **Trusting the sub-agents blindly.** `manifest[*].status == "done"` only means the
  sub-agent exited 0. Spot-check ~5% of outputs for schema compliance and depth. If a
  batch looks shallow, blame the template, not the sub-agent — fix
  [`paper-summary.md`](paper-summary.md) and re-run.
- **Abstract-copying / inventing numbers.** Same PhD-depth standard applies. Reject and
  re-run papers whose summaries read like the abstract.
- **Unilingual drift.** Sub-agents sometimes drop the Chinese file when they run out of
  context. The schema rejects one-language papers at build time — but catch it earlier
  by eyeballing file counts (`ls src/content/papers/<slug>/*.en.md | wc -l` should match
  `*.zh-cn.md`).
- **Schema drift.** Do not relax `src/content/config.ts` to make a failed sub-agent
  output validate. Fix the output (or re-run).
- **Tag sprawl.** Stay within [`tag-vocabulary.md`](tag-vocabulary.md). Propose new tags
  in a single batch to the user during Step 5; don't sprinkle new ones silently.
