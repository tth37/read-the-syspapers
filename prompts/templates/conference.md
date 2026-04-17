# Conference overview template

Each conference ships as **two** files, identical frontmatter plus a translated body:

- `src/content/conferences/<slug>.en.md`
- `src/content/conferences/<slug>.zh-cn.md`

Frontmatter is identical in both files (proper nouns don't translate) **except** that the
`categories[*].title` and `categories[*].description` fields are translated per-language.
The `id` for each category is a kebab-case English slug and is the same in both files.

---

## Shared frontmatter skeleton

```yaml
---
venue: OSDI        # one of: OSDI, SOSP, NSDI, ATC, EuroSys, ASPLOS, FAST, MLSys, SIGCOMM,
                   # VLDB, SIGMOD, USENIX-Security, CCS, S&P, NDSS, HPCA, ISCA, MICRO,
                   # PLDI, POPL, SC, PPoPP, HotOS
year: 2025
title: "OSDI '25"
location: "Boston, MA"             # optional
dates: "2025-07-07 to 2025-07-09"  # optional
url: "https://www.usenix.org/conference/osdi25"
paper_count_expected: 48           # optional; set once you have the full list
overview_status: in-progress       # pending | in-progress | complete
written_by: claude-code            # your agent id; null while pending
summary_date: 2026-04-17           # today when you start writing; null while pending
categories:                        # empty array is fine until Step 5 of conference-overview.md
  - id: scheduling
    title: "Datacenter scheduling"
    description: "Cluster-level task placement and resource management."
  - id: llm-inference
    title: "LLM inference systems"
    description: "Serving, caching, and batching for large-model inference."
---
```

In `<slug>.zh-cn.md`, translate `title`/`description` on each category:

```yaml
categories:
  - id: scheduling
    title: "数据中心调度"
    description: "面向集群的任务放置与资源管理。"
  - id: llm-inference
    title: "大模型推理系统"
    description: "大模型推理的服务化、缓存与批处理。"
```

---

## Body skeleton (English)

```markdown
## Themes

Short paragraphs, each pointing at 2–4 papers that exemplify the theme. Relative links:
`[title](../papers/<slug>/<paper-slug>.md)`.

## Notable trends

Only claim a trend you can back up with ≥3 papers. Cite them inline.

## Must-read picks

- **[paper title](../papers/<slug>/<paper-slug>.md)** — one line of justification.
- **[paper title](../papers/<slug>/<paper-slug>.md)** — …
- (up to 5 total; also set `star: true` in each paper's `.en.md` and `.zh-cn.md`.)

## Stats

- Papers summarized: N
- Rough breakdown by category: scheduling (x), llm-inference (y), storage (z), …
```

## Body skeleton (Simplified Chinese)

```markdown
## 主题

用短段落刻画本届会议的 3–5 个主题，每段指向 2–4 篇代表论文。使用相对链接：
`[title](../papers/<slug>/<paper-slug>.md)`（论文标题保持英文原文）。

## 值得关注的趋势

只在有 ≥3 篇论文支撑时才声称某项趋势，并在段落中内联引用这些论文。

## 必读推荐

- **[paper title](../papers/<slug>/<paper-slug>.md)** — 一句话说明为何值得读。
- **[paper title](../papers/<slug>/<paper-slug>.md)** — ……
- （最多 5 篇；同时把这些论文的 `.en.md` 与 `.zh-cn.md` 中的 `star` 字段都改为 `true`。）

## 数据概览

- 已综述论文数：N
- 分类概览：调度（x）、大模型推理（y）、存储（z）……
```

Paper titles in relative links stay in English (proper nouns); only the surrounding
prose is translated.
