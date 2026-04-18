# Blog post template

Each blog post ships as **two** files with identical frontmatter (except `oneline` and
`total_words`, which are per-language) plus a translated body:

- `src/content/blog/<slug>.en.md`
- `src/content/blog/<slug>.zh-cn.md`

`<slug>` is a kebab-case English slug. It stays identical across languages. Pick it from
the post's thesis, not its topic — "log-structured-storage-returns" beats "storage-blog".

---

## Frontmatter skeleton

`<slug>.en.md`:

```yaml
---
title: "The same thesis-framing title in both files (English)"
oneline: "One-sentence English hook, ≤ 400 chars. State the argument, not the subject matter."
topic: llm-inference      # kebab-case; the user-supplied topic — same in both files
tags:
  - inference             # 3–6 tags. Reuse the paper tag vocabulary where it fits;
  - caching               # invent new tags only when genuinely novel.
total_words: 1850         # body word count (English), excluding frontmatter + headings
reading_time_minutes: 9   # optional; derived from total_words if omitted (220 wpm EN / 380 chars-per-min ZH)
written_by: "Claude Opus 4.7 (Claude Code)"   # your agent identity string, verbatim
publish_date: 2026-04-18
draft: false              # true while iterating; clear when the post is ready
---
```

`<slug>.zh-cn.md` (identical except for `oneline` and `total_words`):

```yaml
---
title: "The same thesis-framing title in both files (English)"
oneline: "一句话中文钩子，≤ 400 字符。讲明立场，而非主题。"
topic: llm-inference
tags:
  - inference
  - caching
total_words: 3100         # Chinese body character count (different from English word count)
reading_time_minutes: 9
written_by: "Claude Opus 4.7 (Claude Code)"
publish_date: 2026-04-18
draft: false
---
```

### Field notes

- `title` stays in English in both files. It's a proper-noun-ish identifier (paper titles
  follow the same rule). If you truly need a Chinese subtitle, add it as an opening line
  in the Chinese body — not in the frontmatter.
- `topic` is the user-supplied kebab-case topic slug. Do not invent a new one without
  permission; if the user's perspective doesn't fit an existing topic, ask.
- `tags` are English kebab-case, same vocabulary as paper tags
  ([`prompts/tag-vocabulary.md`](../tag-vocabulary.md)). Mint a new tag only for a
  genuinely new concept; mention it in your return message.
- `total_words`:
  - English file — count words in the body (`wc -w` minus headings is a fine
    approximation; round to the nearest 10).
  - Chinese file — count characters in the body (CJK is counted per-character by
    convention). Include punctuation but exclude markdown syntax.
- `reading_time_minutes` is optional. If you set it, use 220 wpm for English and
  380 chars/min for Chinese. If omitted, the UI computes it from `total_words`.
- `written_by` — use your orchestrator-supplied `agent_model` string verbatim, same
  format as paper summaries (e.g. `"Claude Opus 4.7 (Claude Code)"`).
- `publish_date` — today, ISO `YYYY-MM-DD`. Same date in both files.
- `draft: true` is fine while you're still iterating. Clear it once the post is ready.

---

## Body skeleton (English)

```markdown
## Thesis

One paragraph. State the claim the rest of the essay defends. Not "this post is about X",
but "X is best understood as Y; here's why."

## The setup

Frame the problem. What prior understanding are you pushing against? Name the 2–3
foundational papers that set the usual framing and link to them inline:
`[Paper Name](/en/papers/<conf-slug>/<paper-slug>)`.

## The evidence

The substantive middle. Organize by argument, not by paper. Every claim cites either:
- an indexed paper via a relative link (`[Name](/en/papers/<conf-slug>/<paper-slug>)`), or
- an external source via a plain URL in inline-link form.

Group papers by what they show, not by venue. Weave them together — if three papers
independently converge on the same insight, that's worth a paragraph that cites all three.

## The counter-evidence

Name the strongest counter-argument. Cite papers or blog posts that push back. Don't
strawman; if the counter-argument is actually right in some regime, say so.

## What this means

Operational takeaways. Who should read these papers? What decision does the thesis
change for someone building a system?

## References

Optional — only if the post leans on enough external material that an explicit list
helps. Otherwise the inline links are sufficient.
```

## Body skeleton (Simplified Chinese)

```markdown
## 核心论点

一段话，陈述后文要捍卫的主张。不是「这篇文章谈 X」，而是「X 其实应被理解为 Y，理由如下」。

## 背景与铺垫

刻画问题。你要挑战哪些既有认知？点名 2–3 篇奠定原有框架的论文，并使用相对链接内联引用：
`[Paper Name](/zh-cn/papers/<conf-slug>/<paper-slug>)`。

## 论据

实质的中段。按论点组织，而不是按论文逐一罗列。每个主张要么来自站内收录的论文（相对链接），
要么来自外部来源（普通 URL 的内联链接）。

按「论据共同说明的内容」而非「发表于哪个会议」来组织论文。如果三篇论文各自独立地指向同一个
洞察，这就值得用一段话同时引用它们。

## 反方证据

点名最强的反方观点。引用提出反方观点的论文或博文。不要稻草人；如果反方观点在某些场景下
确实成立，要明说。

## 这意味着什么

操作层面的启示。谁应该读这些论文？如果你正在构建一个相关系统，这篇文章的论点会改变你的什么决策？

## 参考资料

可选 —— 仅当文章依赖足够多的外部材料时才单列。否则正文中的内联链接就够了。
```

---

## Notes on bilingual discipline

- Paper titles, system names, and venue abbreviations stay in English in the Chinese body
  (e.g. "Shenango"、"LLM"、"OSDI '25"). The surrounding prose is Chinese.
- Section headings translate. The `Thesis` heading becomes `核心论点`, etc.
- `title` stays in English in both frontmatter files (proper noun). Only `oneline` and
  the body prose differ across languages.
- When inlining a link to a paper page, use the language-appropriate URL:
  - `<slug>.en.md` → `/en/papers/<conf-slug>/<paper-slug>`
  - `<slug>.zh-cn.md` → `/zh-cn/papers/<conf-slug>/<paper-slug>`
  Both URLs point at the same pair of files (Astro routes are language-prefixed). The
  linked paper always has both translations, so the cross-link is safe.
