# Prompt: Conference-level synthesis

You run **after** per-paper summaries exist. Your job is to read those summaries (not the
PDFs again) and write the body of the conference overview in both languages, then promote
up to five papers to must-read status.

Before starting, read [`../AGENTS.md`](../AGENTS.md) for hard rules. You are typically
invoked from Step 6 of [`conference-overview.md`](conference-overview.md).

---

## Inputs

- `conference_slug` — e.g. `osdi-2025`.
- `agent_id` — your agent's canonical id.

The two conference files you will edit are:

- `src/content/conferences/<conference_slug>.en.md`
- `src/content/conferences/<conference_slug>.zh-cn.md`

The per-paper summaries live under `src/content/papers/<conference_slug>/` as
`<slug>.en.md` and `<slug>.zh-cn.md` pairs.

## Method

1. **Read every `<slug>.en.md`** — only the English copy. Note each paper's `oneline`,
   `tags`, `category`, and TL;DR. You do not need to re-read the full bodies.
2. **Cluster into 3–5 themes.** Themes are a level above categories; a theme may span
   categories. Each theme should cite 2–4 papers using relative links.
3. **Identify notable trends.** Only claim a trend you can back up with ≥3 papers.
   Contrast with prior years only if you are confident (e.g. you've seen the prior-year
   conference files in this repo).
4. **Pick up to five must-reads.** One line justifying each. Set `star: true` in those
   papers' **both** `.en.md` and `.zh-cn.md` frontmatter.
5. **Collect stats**: paper count, rough breakdown by category, any interesting ratios
   (e.g. industry vs. academia authorship).
6. **Write the body twice.** Once in English into `<slug>.en.md`, once in Simplified
   Chinese into `<slug>.zh-cn.md`. The Chinese version is a re-expression, not a
   translation — same themes, same paper picks, same numbers, same H2 section order,
   but sentence boundaries and transitions tuned for Chinese readers. See
   [`../AGENTS.md`](../AGENTS.md) hard rule #2 for the match-vs-vary discipline and
   the 「」 quoting convention. Paper titles and tags stay in English in the Chinese
   file.

## Body structure (both languages)

```markdown
<one-paragraph at-a-glance intro, BEFORE Themes — not under a heading>
## Themes                 (## 主题, in Chinese)
## Notable trends         (## 值得关注的趋势)
## Must-read picks        (## 必读推荐)
## Stats                  (## 数据概览)
```

## Style rubric (authoritative — follow exactly)

These patterns came out of the ASPLOS '26 and FAST '26 passes and are the house style.

### 1. At-a-glance intro paragraph, before `## Themes`

Not under a heading. One paragraph. Lead with the paper count, then name the 1–2
tensions that define *this year's* program (not a generic venue description), then a
nod to classical breadth preserved. 3–5 sentences, no bullets. Example shape:

> _Venue '26_ brought **N papers** — a sprawling single-track program that doubles
> as a map of where the community is investing. The distribution is almost
> shockingly AI-heavy: roughly a third of the program is … At the same time,
> _Venue_ kept its classical breadth — _area-1_, _area-2_, and _area-3_ all show up
> in force.

### 2. Every paper reference is an inline link

Never write a bare system name in the overview body. Always:

```markdown
[SystemName](../papers/<conference_slug>/<paper-slug>.md)
```

- Relative path (`../papers/...`), **never** `/en/papers/...` or `/zh-cn/papers/...`
  — those forms break one of the two language surfaces.
- The `.md` extension is intentional; Astro resolves it at build time.
- The visible text is the system name or a short phrase naming the contribution,
  not the full paper title.

### 3. Themes — 3 to 5 bullets, bold lead

Each theme bullet:
- Opens with a **bold lead sentence** naming the shift or pattern.
- Cites 2–7 papers, each with an inline link (rule 2).
- One sentence of context per cluster of papers is fine; avoid paragraph-long
  ramblings. Themes are a higher level than categories — a theme may span
  categories.

### 4. Notable trends — 3 to 4 bullets, ≥3 papers each

- One line per trend. Trend name in bold prose (not a heading).
- At least 3 linked papers as evidence. If you can't find 3, it's not a trend yet
  — drop it.
- Prefer trends that name a *technique* ("speculate and recover", "per-core
  primitives") over trends that name a *topic* ("sparsity", "LLM serving"). Topics
  are already in Themes.

### 5. Must-read picks — ≤ 5

- At most 5. Space them across different tracks.
- Format: `**[Name](../papers/<conf>/<slug>.md)** — one-line justification.`
- Justification names the specific contribution or result (a number, a mechanism,
  a community-infrastructure role), not adjectives like "excellent" or "impressive."

### 6. Stats

Short bullet list:
- Papers summarized (actual count, not expected).
- Category breakdown (counts per category, largest and smallest).
- Tag count; flag newly-added tags if any.
- Industry participation if notable (Apple / Alibaba / ByteDance / … on ≥1 paper
  each is worth calling out; all-academic isn't).

### 7. Chinese-file specifics

The `.zh-cn.md` body mirrors the English structure — same intro paragraph, same
theme bullets, same must-reads, same stats, same paper citations (with
`../papers/...` relative links unchanged; the `.md` extension resolves the same
on both language surfaces). It is **not a sentence-level translation**: merge,
split, or reorder sentences within a paragraph so the result reads as native
Chinese prose; use Chinese-native connectors (其实、不过、换句话说) instead of
literal renderings of English ones. Full discipline in
[`../AGENTS.md`](../AGENTS.md) hard rule #2.

Paper titles, system names, venue abbreviations stay in English; body prose is
Simplified Chinese. Section headings translate per the table above. Inline
quotes in the Chinese body use 「」, never ASCII `"..."` (the latter reads as
翻译腔 and also breaks YAML if it leaks into `oneline`).

## Frontmatter update

In **both** conference files, set:

- `overview_status: complete`
- `paper_count_expected: <actual count summarized>` (the integer count of unique papers,
  not file count)
- `written_by: <your agent id>`
- `summary_date: <today YYYY-MM-DD>`

Keep `categories:` exactly as the conference-overview run wrote it — you are not
re-categorizing.

## Hard rules

- Do not re-read the PDFs. Use the existing summaries.
- Do not alter any paper's body while here. You may only flip its `star: true` flag (in
  both language files).
- Do not invent themes. A theme needs ≥2 supporting papers, a trend needs ≥3.
- Do not skip the Chinese version if you are tired — stop, commit, and tell the user
  instead.
