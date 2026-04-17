# Prompt: Conference overview pass

You have been asked to produce a full overview of a systems top-conference — e.g.
"Do an overview of OSDI 2025." This prompt is self-contained: you should be able to
complete the task by following it, regardless of which coding agent is running.

Before starting, read [`../AGENTS.md`](../AGENTS.md) for hard rules (agent identity,
no fabrication, no committed PDFs, schema is law).

---

## Inputs expected from the user

- Venue name (e.g. `OSDI`, `SOSP`, `NSDI`).
- Year (4-digit).
- Optional: a path to a locally-available proceedings ZIP or folder, if the user has
  already downloaded PDFs (useful when the official site blocks bulk downloads).

If any of these are missing, ask the user once, then proceed.

---

## Step 1 — Identify the venue and create the conference file

1. Resolve the canonical program URL:
   - **USENIX venues** (OSDI, NSDI, ATC, FAST, USENIX Security): `https://www.usenix.org/conference/<venue-lower><yy>/technical-sessions`
   - **SOSP**: `https://sigops.org/s/conferences/sosp/<yyyy>/` (program page linked from there).
   - **EuroSys / ASPLOS**: linked from the conference's own site (search `<venue> <year>`).
   - **MLSys**: `https://mlsys.org/Conferences/<yyyy>`.
   - Other venues: search for the official program page.

2. Compute the conference slug: `<venue-lower>-<yyyy>` (e.g. `osdi-2025`, `sosp-2024`).
3. Create or update `src/content/conferences/<slug>.md` using
   [`templates/conference.md`](templates/conference.md). Fill in metadata you already know
   (venue, year, title, URL). Leave the body minimal for now. Set:
   - `overview_status: in-progress`
   - `written_by: <your agent id>`
   - `summary_date: <today in YYYY-MM-DD>`

## Step 2 — Get the accepted-paper list

Scrape the official program page and build a list of papers. For each paper record:

- Title
- Authors (full names, in author order)
- Affiliations (per author if listed, or aggregate)
- PDF URL if openly hosted (USENIX open-access PDFs; ACM open-access; author homepages)
- Abstract URL / DOI if PDF is paywalled
- Abstract text (optional; helps the per-paper agent get a running start)

Save this as `_inbox/<slug>/papers.json` (a simple JSON array). This file is gitignored and
serves as the dispatch list for Step 4.

Sanity check: does the count roughly match what the call-for-papers advertised? If the site
is incomplete (e.g. only day-1 is listed), tell the user and wait for the full list.

## Step 3 — Obtain PDFs

Try, in order:

1. The conference's open-access PDF URL from Step 2.
2. Author homepage (grep author names + paper title).
3. arXiv (many systems papers are mirrored there).
4. Google Scholar's top-1 PDF link.

Save PDFs to `_inbox/<slug>/pdfs/<slug-of-paper-title>.pdf`.

If any paper's PDF cannot be retrieved automatically after these attempts, write the
outstanding list to `_inbox/<slug>/needs_manual_pdf.md` with one line per paper (title,
authors, abstract URL). Tell the user:

> "I could not fetch N PDFs automatically. I've listed them in `_inbox/<slug>/needs_manual_pdf.md`.
> Please drop the PDFs (or the full proceedings archive) into `_inbox/<slug>/pdfs/` and
> re-run me, and I'll continue from where I stopped."

Then stop and wait. Do not invent summaries for missing PDFs.

## Step 4 — Parallelize per paper

For each paper with an available PDF, spawn a sub-agent (or iterate sequentially if your
harness has no sub-agent primitive) with the contents of
[`paper-summary.md`](paper-summary.md). Pass these variables to each sub-agent:

- `pdf_path`: absolute path to the PDF under `_inbox/`
- `output_path`: `src/content/papers/<slug>/<paper-slug>.md`
- `conference_slug`: e.g. `osdi-2025`
- `agent_id`: your agent id (propagate it; sub-agents inherit the identity of whichever
  agent launched them)
- `tag_vocabulary_path`: `prompts/tag-vocabulary.md`

Batch if you need to (e.g. 3–5 papers per sub-agent batch) but each paper gets its own
output file. Each sub-agent must produce a schema-valid markdown file. If a sub-agent
errors out, log the failure in `_inbox/<slug>/failures.md` and continue with the others —
never leave a partial summary in `src/content/papers/`.

After all sub-agents complete, run `npm run build` to verify every new paper file passes
Zod validation. Fix any schema violations before moving on.

## Step 5 — Write the conference-level overview

Open every `src/content/papers/<slug>/*.md` you just produced and read the summaries (not
the PDFs — you already spent that budget in Step 4). Then fill the body of
`src/content/conferences/<slug>.md` with:

1. **Themes** — 3–5 recurring themes across the program, each with a paragraph and a few
   paper pointers (use relative links: `[title](../papers/<slug>/<paper-slug>.md)`).
2. **Notable trends vs. prior years** — what's new, what's fading. Only claim a trend you
   can back up with ≥3 papers.
3. **Must-read picks** — 5 papers maximum. One line justifying each pick. Mark them as
   `star: true` in their paper frontmatter.
4. **Stats** — paper count, rough breakdown by area.

Update the conference frontmatter:

- `overview_status: complete`
- `paper_count_expected: <actual count summarized>`
- `written_by: <your agent id>` (if not already set)
- `summary_date: <today>`

## Step 6 — Commit and stop

Create a branch named `overview/<slug>` and commit in logical chunks:

- One commit: conference metadata + overview body.
- One commit per ~10 paper summaries (keeps history bisectable).

Use the conventional prefix `overview(<slug>):` on each commit. Example:

```
overview(osdi-2025): add conference metadata and overview body
overview(osdi-2025): summarize papers 1-10
```

**Do not push. Do not open a PR.** Leave the branch local and tell the user it's ready for
review.

---

## Failure modes to watch for

- **Abstract-copying.** If your summary reads like the abstract, rewrite it. PhD-depth means
  synthesis, not paraphrase.
- **Inventing numbers.** Re-check every quantitative claim against the paper. If you can't
  find it, drop the number.
- **Schema drift.** Do not add frontmatter fields that aren't in `src/content/config.ts`.
- **Tag sprawl.** Stay within the vocabulary in `prompts/tag-vocabulary.md`. Propose new
  tags in a single batch to the user; don't sprinkle new ones silently.
