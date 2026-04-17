# Prompt: Single-paper summary (PhD-depth)

You have been launched with a single job: read one paper end-to-end and produce a
structured markdown summary. You do this self-contained, with no coordination with other
sub-agents.

Before starting, read [`../AGENTS.md`](../AGENTS.md) for hard rules (agent identity,
no fabrication, schema is law).

---

## Inputs

The caller (a top-level conference-overview run, or a direct user request) supplies:

- `pdf_path` — absolute path to the PDF.
- `output_path` — where to write the summary, e.g.
  `src/content/papers/osdi-2025/shenango.md`. The parent directory should already exist.
- `conference_slug` — e.g. `osdi-2025`. Must match an id under `src/content/conferences/`.
- `agent_id` — your agent's canonical id (e.g. `claude-code`, `codex`).
- `tag_vocabulary_path` — usually `prompts/tag-vocabulary.md`.

If any input is unclear, ask the caller once. Do not guess the output path.

## Method

1. **Read the PDF end-to-end.** This is a PhD-depth summary, not a skim. Read introduction,
   all core technical sections, evaluation, related work. You may be lighter on the appendix.
2. **Extract frontmatter fields from the paper itself.** Do NOT derive them from external
   pages — the PDF is authoritative for title, author order, affiliations.
3. **Choose 3–6 tags** from the vocabulary. If no existing tag fits a genuinely-new topic,
   mention the missing tag in your `My Notes` section; do not invent one in `tags:`.
4. **Fill each required H2 section.** Sections and required depth below. Aim for 600–1000
   words of body overall.

## Required output structure

Copy the skeleton in [`templates/paper.md`](templates/paper.md). The frontmatter fields are
schema-validated by `src/content/config.ts` — any mismatch fails the build.

Required H2 sections, in this order:

### TL;DR
One to three sentences. Name the mechanism and the win. No adjectives.

### Problem
What is broken or missing in prior art? Who has this problem at what scale? What failure
mode does the most obvious existing approach exhibit? Establish stakes.

### Key Insight
The one claim a reader should remember in six months. Phrase it as a proposition, not a
description. Explain **why** it works before **how** it's implemented — the implementation
details go in the next section.

### Design
Mechanism, architecture, algorithms. Identify crucial invariants. Describe the control-path
and data-path separately if the paper has that split. Include pseudocode only when it is
the clearest expression of the idea; prefer prose.

### Evaluation
Testbed, workloads, baselines, and the two or three most important numbers. Comment on
whether the evaluation supports the central claim: do the workloads exercise the stated
bottleneck? Are the baselines configured fairly? Is the regime where the design wins broad
or narrow?

### Novelty & Impact
How does this differ from the closest prior work (one sentence each, naming the work)? Who
will cite this paper and why? Is it a new mechanism, a new framing of a known problem, or a
strong measurement study?

### Limitations
Author-stated limits plus reviewer-style concerns. Workload regimes where the design would
lose. Deployment constraints the authors hand-wave.

### Related Work
2–4 adjacent papers. One line each positioning the paper relative to the one you're
summarizing. Include venue and year: `_Author et al. (OSDI '22)_`.

### My Notes
Leave this section empty (the human will fill it). Include the heading so the page renders
consistently.

## Frontmatter rules

- `written_by`: your agent id, exactly matching how you want it to appear on the site.
- `summary_date`: today, ISO format (`YYYY-MM-DD`).
- `reading_status: read` (you just read it end-to-end).
- `star: false` by default. The conference-overview pass may later promote ≤5 papers to
  `star: true` for the "must-read" rail.
- `conference:` must equal the id of an existing file under `src/content/conferences/`
  (e.g. `osdi-2025`). If the conference file doesn't exist yet, stop and tell the caller.

## Hard rules (repeated because they matter)

- No invented numbers, citations, authors, or affiliations.
- Do not paste the abstract as the TL;DR. Paraphrase into your own words.
- If a piece of information is not in the paper, write "the paper does not specify" —
  never guess.
- Write one file at `output_path`. Do not edit any other files, including sibling papers.
- Do not run `npm run build` yourself — the caller will validate after all sub-agents
  finish.
