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
   Chinese into `<slug>.zh-cn.md`. Same structure, same claims; translate naturally (don't
   word-for-word). Paper titles and tags stay in English in the Chinese file.

## Body structure (both languages)

```markdown
## Themes                 (## 主题, in Chinese)
## Notable trends         (## 值得关注的趋势)
## Must-read picks        (## 必读推荐)
## Stats                  (## 数据概览)
```

Must-read picks use relative links: `[title](../papers/<conference_slug>/<paper-slug>.md)`.
Astro resolves the link at build time; the `.md` extension is intentional.

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
