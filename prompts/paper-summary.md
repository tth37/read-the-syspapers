# Prompt: Single-paper summary (PhD-depth, bilingual)

You have been launched with a single job: read one paper end-to-end and produce TWO
structured markdown summaries — one in English, one in Simplified Chinese. You do this
self-contained, with no coordination with other sub-agents.

Before starting, read [`../AGENTS.md`](../AGENTS.md) for hard rules (agent identity,
bilingual output, no fabrication, schema is law, micro-batches).

---

## Inputs

The caller (a top-level conference-overview run, or a direct user request) supplies:

- `pdf_path` — absolute path to the PDF.
- `pdf_page_start`, `pdf_page_end` (optional) — when the input is a combined proceedings
  volume, read only these pages. Ignore the rest.
- `output_path_en` — e.g. `src/content/papers/osdi-2025/shenango.en.md`.
- `output_path_zh` — e.g. `src/content/papers/osdi-2025/shenango.zh-cn.md`.
- `conference_slug` — e.g. `osdi-2025`. Must match conference files under
  `src/content/conferences/`.
- `agent_id` — your agent's canonical id (e.g. `claude-code`, `codex`).
- `agent_model` — the model-qualified identity string to stamp into `written_by`, e.g.
  `"gpt-5.4 (codex)"` or `"Claude Opus 4.7 (Claude Code)"`. Use it verbatim.
- `tag_vocabulary_path` — usually `prompts/tag-vocabulary.md`.

The parent directory (`src/content/papers/<conference_slug>/`) is expected to exist; create
it if it doesn't. If any other input is unclear, ask the caller once. Do not guess the
output path.

## Method

1. **Read the PDF end-to-end.** PhD-depth, not a skim. Introduction, all core technical
   sections, evaluation, related work. Lighter on the appendix is OK.
2. **Extract frontmatter from the paper itself.** The PDF is authoritative for title,
   author order, affiliations. Do not derive them from external pages.
3. **Choose 3–6 tags** from the vocabulary. Tags are English kebab-case and stay identical
   in both language files. If no existing tag fits a genuinely-new topic, mention the
   missing tag in your `My Notes` section; do not invent one in `tags:`.
4. **Write the English version first**, then re-express in Chinese (not a sentence-level
   translation — see [`../AGENTS.md`](../AGENTS.md) hard rule #2, "The Chinese file is a
   re-expression, not a translation", for the discipline). Aim for **700–950 words of
   body** in the English version; the Chinese version ends up in a similar range of
   characters (~1500–2500) but match the English evidence and claims, not the sentence
   count.
5. **Produce both files.** An .en.md without a .zh-cn.md (or vice versa) is a failure.

## What stays in English vs. what is language-specific

**English only, in both files:**
- `title` — paper title is a proper noun.
- `authors`, `affiliations` — names stay in their original form.
- `tags` — the vocabulary is English; translation would break grouping.
- `category` — the id is kebab-case English.
- URLs (`pdf_url`, `doi_url`, `code_url`, `project_url`).

**Per-language (`.en.md` vs `.zh-cn.md`):**
- `oneline` — one-sentence TL;DR in the file's language (≤ 180 characters). Surfaced
  on the conference page as a one-line hook under the title. Write the Chinese
  `oneline` fresh for a Chinese reader, not as a literal translation of the English
  hook.
- Body prose — every H2 section. The Chinese body is a re-expression of the English
  one: same claim, same mechanism, same numbers, same paper-relative citations, same
  H2 section order — but sentence boundaries, transitions, and idioms tuned for
  Chinese. See [`../AGENTS.md`](../AGENTS.md) hard rule #2 for the match-vs-vary
  rules that apply across all content types in this repo.

**Section headings** also translate: `## TL;DR` stays in English in both files (it's
an established abbreviation); `## Problem` becomes `## 问题背景`; etc. See the
per-language skeletons in [`templates/paper.md`](templates/paper.md).

**Inline quotes in the Chinese body use 「」, never ASCII `"..."`.** Applies to
scare-quotes around Chinese phrases (「工作集」) and to English phrases embedded in
Chinese prose (「workset」). ASCII `"` in Chinese text reads as a translation
artifact and also breaks YAML if it leaks into `oneline`.

## Required output structure (both languages)

Copy the skeleton in [`templates/paper.md`](templates/paper.md). The frontmatter fields
are schema-validated by `src/content/config.ts` — any mismatch fails the build.

Required H2 sections, in this order:

### TL;DR (English) / TL;DR (Chinese uses the same heading)
One to three sentences. Name the mechanism and the win. No adjectives.

### Problem / 问题背景
What is broken or missing in prior art? Who has this problem at what scale? What failure
mode does the most obvious existing approach exhibit? Establish stakes.

### Key Insight / 核心洞察
The one claim a reader should remember in six months. Phrase it as a proposition, not a
description. Explain **why** it works before **how** it's implemented — the implementation
details go in the next section.

### Design / 设计
Mechanism, architecture, algorithms. Identify crucial invariants. Describe the control-path
and data-path separately if the paper has that split. Include pseudocode only when it is
the clearest expression of the idea; prefer prose.

### Evaluation / 实验评估
Testbed, workloads, baselines, and the two or three most important numbers. Comment on
whether the evaluation supports the central claim: do the workloads exercise the stated
bottleneck? Are the baselines configured fairly? Is the regime where the design wins broad
or narrow?

### Novelty & Impact / 创新性与影响
How does this differ from the closest prior work (one sentence each, naming the work)? Who
will cite this paper and why? Is it a new mechanism, a new framing of a known problem, or a
strong measurement study?

### Limitations / 局限性
Author-stated limits plus reviewer-style concerns. Workload regimes where the design would
lose. Deployment constraints the authors hand-wave.

### Related Work / 相关工作
2–4 adjacent papers. One line each positioning the paper relative to the one you're
summarizing. Include venue and year: `_Author et al. (OSDI '22)_`.

### My Notes / 我的笔记
Leave empty in both files (the human will fill them). Include the heading so the page
renders consistently.

## Frontmatter rules

- `written_by`: the model-qualified identity string the orchestrator handed you as
  `agent_model`. Format is `"<model> (<agent-cli>)"` — e.g. `"gpt-5.4 (codex)"`,
  `"Claude Opus 4.7 (Claude Code)"`. Use it verbatim; do not invent a different form and
  do not copy another agent's identity.
- `summary_date`: today, ISO format (`YYYY-MM-DD`). Same date in both files.
- `reading_status: read`.
- `star: false` by default. The conference-overview pass may later promote ≤5 papers.
- `conference:` must equal the base slug of an existing file under
  `src/content/conferences/` (e.g. `osdi-2025` — **no language suffix**). If the conference
  file doesn't exist yet, stop and tell the caller.
- `category:` is optional during per-paper summarization; the conference-overview run will
  fill it during the categorization step. If you're confident of the right category id,
  set it; otherwise leave blank.
- `oneline:` — one sentence in the file's language, ≤ 180 characters. Not "X is a Y"
  boilerplate; name the *move* (e.g. "Reuses idle-cycle GPU memory as a disaggregated KV
  cache for LLM serving.").

## Hard rules (repeated because they matter)

- No invented numbers, citations, authors, or affiliations.
- Do not paste the abstract as the TL;DR. Paraphrase into your own words.
- If a piece of information is not in the paper, write "the paper does not specify" / "论
  文未说明" — never guess.
- Write exactly two files: `output_path_en` and `output_path_zh`. Do not edit any other
  files, including sibling papers.
- Do not run `npm run build` yourself — the caller will validate after the batch finishes.
- Do not translate the paper title, tag names, author names, or section ids across
  languages. Only `oneline` and the section bodies differ between files.
- The Chinese body is a re-expression, not a literal translation, and its inline
  quotes use 「」. Full rule in [`../AGENTS.md`](../AGENTS.md) #2.
