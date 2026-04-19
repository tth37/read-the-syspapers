# Paper summary template

Each paper ships as **two** files:

- `src/content/papers/<conference-slug>/<paper-slug>.en.md`
- `src/content/papers/<conference-slug>/<paper-slug>.zh-cn.md`

Titles, author names, affiliations, tags, category ids, and URLs are identical in both
files. The `oneline` and the body prose differ: English in the `.en.md`, Simplified
Chinese in the `.zh-cn.md`.

---

## Frontmatter (shared — copy verbatim, only `oneline` differs)

`<paper-slug>.en.md`:

```yaml
---
title: "Exact title as it appears on the paper"
oneline: "One-sentence English TL;DR, ≤ 180 chars. Name the move, not the adjective."
authors:
  - "First Last"
  - "First Last"
affiliations:
  - "University / Company"
conference: osdi-2025       # base slug, no language suffix — must match an existing file
category: scheduling        # optional during per-paper run; conference-overview fills it in Step 5
pdf_url: "https://…"        # open-access URL; optional if truly unavailable
doi_url: "https://doi.org/…"      # optional; use when PDF is paywalled or for canonical reference
code_url: "https://github.com/…"  # optional
project_url: "https://…"          # optional
tags:
  - scheduling
  - datacenter              # 3–6 tags, all from prompts/tag-vocabulary.md, always English
reading_status: read
star: false                 # conference-overview may promote up to 5 to true
written_by: claude-code     # your agent id
summary_date: 2026-04-17    # today
---
```

`<paper-slug>.zh-cn.md`:

```yaml
---
title: "Exact title as it appears on the paper"
oneline: "一句话中文 TL;DR，≤ 180 字符。点明技术招式，避免形容词堆砌。"
authors:
  - "First Last"
  - "First Last"
affiliations:
  - "University / Company"
conference: osdi-2025
category: scheduling
pdf_url: "https://…"
doi_url: "https://doi.org/…"
code_url: "https://github.com/…"
project_url: "https://…"
tags:
  - scheduling
  - datacenter
reading_status: read
star: false
written_by: claude-code
summary_date: 2026-04-17
---
```

---

## English body skeleton

```markdown
## TL;DR

(1–3 sentences.)

## Problem

## Key Insight

## Design

## Evaluation

## Novelty & Impact

## Limitations

## Related Work

- _Author et al. (VENUE 'YY)_ — one-line positioning.
- _Author et al. (VENUE 'YY)_ — one-line positioning.

## My Notes

<!-- empty; left for the human reader -->
```

## Simplified Chinese body skeleton

```markdown
## TL;DR

（1–3 句中文摘要。）

## 问题背景

## 核心洞察

## 设计

## 实验评估

## 创新性与影响

## 局限性

## 相关工作

- _Author et al. (VENUE 'YY)_ — 一句话定位这篇论文与所综述论文的关系。
- _Author et al. (VENUE 'YY)_ — 一句话定位。

## 我的笔记

<!-- 留空；由人工补充 -->
```

---

## Notes

- Keep `TL;DR` literal as a heading in both languages — it's a well-known abbreviation and
  renders consistently.
- The Chinese body is a re-expression of the English one, not a sentence-level
  translation. Same TL;DR / key insight / mechanism / numbers / H2 order; sentence
  boundaries and idioms are free to diverge so the Chinese reads natively. Full
  match-vs-vary rules in [`../../AGENTS.md`](../../AGENTS.md) hard rule #2.
- **Inline quotes in the Chinese body use 「」, never ASCII `"..."`.** This covers
  scare-quotes around Chinese phrases and embedded English phrases alike. ASCII `"`
  in Chinese prose reads as a translation artifact and can break YAML if it leaks
  into `oneline`.
- In the Chinese body, keep paper titles, product names, system names, and venue
  abbreviations in English. Prose around them is Chinese.
- The related-work citations stay in English in both files (they reference English-titled
  papers at English-named venues).
