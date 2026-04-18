# Quickstart: doing a conference overview

This is the operational companion to
[`conference-overview.md`](conference-overview.md). That file explains *why* each
step exists; this one is the terse recipe a fresh orchestrator can follow
command-by-command. Read [`../AGENTS.md`](../AGENTS.md) first for hard rules, then
this file, then jump into the work.

**Trigger:** user says *"do an overview of &lt;venue&gt; &lt;year&gt;"* or equivalent, with
proceedings PDF(s) already dropped in `_inbox/<slug>/`.

**Baked-in defaults (don't re-ask):**

- Agent: `codex`, model pinned at `gpt-5.4`
- Concurrency: `5`
- Timeout: `2400s` per sub-agent
- Auto-retry: `2` attempts on transient network errors (already built into orchestrate.py)
- Branch name: `overview/<slug>`
- Commit prefix: `overview(<slug>):`
- Never push, never open PRs
- Stop and ask only on: ambiguous manifest (missing bookmarks + unreadable titles),
  pilot failing the depth bar, repeated same-class sub-agent failure, or needing to
  change the Zod schema.

---

## Step 0 — Orient

```bash
ls _inbox/<slug>/                  # what PDFs do we have?
pdfinfo _inbox/<slug>/*.pdf | head
git log --oneline -3               # anything already in flight?
```

If `_inbox/<slug>/manifest.json` already exists and has non-`pending` entries, this is
a resumed run — skip to Step 4 (`--retry-failed`).

## Step 1 — Build the manifest

See [`manifest-building.md`](manifest-building.md) for the venue-specific playbook.
For USENIX-style single-PDF proceedings, the 3-command recipe is:

```bash
# Probe bookmarks
python3 scripts/manifest_helpers.py bookmarks _inbox/<slug>/*.pdf | head -20
# Probe logical→PDF page offset (pick 3 sample pages)
python3 scripts/manifest_helpers.py offset _inbox/<slug>/*.pdf --samples 14 300 700
```

Then assemble a Python snippet that:
1. Fetches the program URL (USENIX/ACM/IEEE) for the authoritative title/author list
2. Cross-references titles → bookmark pages (or applies the constant offset)
3. Calls `write_manifest(conference_slug, entries)` from `scripts/manifest_helpers.py`
4. Runs `python3 scripts/manifest_helpers.py validate _inbox/<slug>/manifest.json`

## Step 2 — Create conference stubs

Copy [`templates/conference.md`](templates/conference.md) skeleton into:

- `src/content/conferences/<slug>.en.md`
- `src/content/conferences/<slug>.zh-cn.md`

with `overview_status: in-progress`, `written_by: "Claude Opus 4.7 (Claude Code)"`
(or the current orchestrator's model string), `summary_date: <today>`, `categories: []`.
Body body stays empty for now.

## Step 3 — Pilot one paper

```bash
./scripts/orchestrate.py --conference <slug> --agent codex --slug <pilot-slug> --concurrency 1
./scripts/validate_paper.py --conference <slug> <pilot-slug> --expected-agent "gpt-5.4 (codex)"
```

Read both `.en.md` and `.zh-cn.md` by eye (depth is schema-invisible). If structure
drifts, fix [`paper-summary.md`](paper-summary.md) before fanning out.

## Step 4 — Fan out

```bash
./scripts/orchestrate.py --conference <slug> --agent codex --concurrency 5 --timeout 2400
# Then, if any failed:
./scripts/orchestrate.py --conference <slug> --agent codex --concurrency 2 --retry-failed
# Sanity spot-check after fan-out completes:
./scripts/validate_paper.py --conference <slug> --expected-agent "gpt-5.4 (codex)"
```

Auto-retry is already built into orchestrate.py for transient stream-disconnects /
rate limits / socket hangups. Use `--retry-failed` only for runs that exhausted
those retries or for content-level failures you've diagnosed manually.

## Step 5 — Categorize

Read every paper's `oneline` + `tags` (not the full bodies). Pick 4–8 kebab-case
category ids, write titles and descriptions (translate per language). Add
`categories:` arrays to both conference files. Set `category: <id>` in **both**
`.en.md` and `.zh-cn.md` frontmatter for every paper.

A light Python script over `src/content/papers/<slug>/*.md` is fine for the
bulk-assignment pass. Re-run the validator afterwards.

## Step 6 — Synthesize

Hand off to [`conference-synthesis.md`](conference-synthesis.md). Its style rubric
(themes / trends / must-reads / stats, inline paper links) is the authoritative
guide — follow it exactly rather than reinventing structure.

Set on **both** conference files:

- `overview_status: complete`
- `paper_count_expected: <N>` (actual count)
- `summary_date: <today>`

## Step 7 — Commit and stop

```bash
git checkout -b overview/<slug>
git add src/content/conferences/<slug>.*.md
git commit -m "overview(<slug>): add conference metadata"
# …one commit per ~10 papers…
git add src/content/papers/<slug>/*.md
git commit -m "overview(<slug>): summarize papers N-M"
# …then categorization commit, then synthesis commit…
npm run build    # catch schema violations before reporting done
```

Do **not** push. Report to the user with: branch name, paper count, must-read list,
build status, and anything that required a judgment call during categorization or
synthesis.

---

## Common failure modes (all pre-seen on earlier runs)

| Symptom | First check |
|---|---|
| Sub-agent logs "stream closed" | orchestrate.py already retries; if persistent, run `--retry-failed --concurrency 2` |
| Schema error on `npm run build` | Run `./scripts/validate_paper.py --all`; most issues surface without Astro |
| `oneline` too long | validator catches it; edit the offending file, don't re-run the sub-agent |
| Missing Chinese file | validator catches it; re-run the sub-agent for that slug via `--slug` |
| Bookmark titles are opaque keys | program URL is authoritative; see [`manifest-building.md`](manifest-building.md) Pattern A |
| ASPLOS-style mixed vol1/vol2 | see [`manifest-building.md`](manifest-building.md) Pattern C — don't auto-guess |
