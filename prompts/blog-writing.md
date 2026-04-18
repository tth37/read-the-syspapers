# Prompt: Tech-insight blog post (perspective-driven, bilingual)

You have been launched with a single job: write ONE long-form tech-insight blog post,
driven by a user-supplied **perspective**, published as two files (English + Simplified
Chinese). A perspective is an argumentative framing — not a topic — the user hands you.
"LLM inference" is a topic; "every LLM-inference paper is really a cache paper" is a
perspective. Your job is to defend the perspective using the papers already indexed on
this site plus targeted external research.

Before starting, read [`../AGENTS.md`](../AGENTS.md) for hard rules that apply to all
written output (agent identity, bilingual output, no fabrication, schema is law).

---

## Inputs

The user (or caller) supplies:

- **`perspective`** — the argumentative thesis you are asked to defend. This is the
  most important input. Do not substitute a different thesis because it's easier to
  write. If the perspective is vague ("something about scheduling"), ask the user to
  sharpen it into a defensible claim before you start.
- **`slug`** — kebab-case English slug. If the user didn't supply one, propose one
  derived from the thesis and get it approved before writing files.
- **`topic`** — kebab-case topic label. If the user says the topic is "llm inference",
  that's `llm-inference`. Used to group related posts in the UI.
- **`target_length`** (optional) — body word count in English. Default: **1600–2200
  words** (a long-form essay, ≈ 8–12 min read). Chinese version scales accordingly
  (typically 2.5–3.5× the English word count in characters).
- **`agent_model`** — the model-qualified identity string, verbatim into
  `written_by`. Same format as paper summaries: `"<model> (<agent-cli>)"`.
- **`output_path_en`** — usually `src/content/blog/<slug>.en.md`.
- **`output_path_zh`** — usually `src/content/blog/<slug>.zh-cn.md`.

If anything is unclear, ask the user **once** before writing files. Do not guess the
perspective or the slug.

---

## Methodology (how to do the research, not the writing)

This is the part that matters. A blog post is only as good as its evidence base. Work
through the following phases in order — do not jump to drafting before you have the
evidence assembled.

### Phase 1 — Sharpen the perspective

Before any research, write the thesis as **one sentence of the form "X is best
understood as Y because Z"** or "The conventional framing of X misses Y". If you cannot
fit the thesis into one sentence, you don't understand it well enough yet. Ask the user
to clarify.

Write down **two competing framings** the thesis is pushing against. This forces you to
find counter-evidence later instead of only cherry-picking papers that agree with the
thesis.

### Phase 2 — Survey the indexed corpus

The papers under `src/content/papers/` are your primary evidence source, because they
are already curated, summarized, and inline-linkable. Survey them as follows:

1. **Scan by tag first.** Check `prompts/tag-vocabulary.md` and list the 2–4 tags
   closest to the perspective. Then `grep -l` the paper frontmatter for those tags:

   ```
   rg -l '^\s*-\s*(tag1|tag2|tag3)\s*$' src/content/papers --glob '*.en.md'
   ```

2. **Expand by venue + year.** If the perspective is time-sensitive ("recent trend in
   X"), restrict to the last 2–3 years of relevant venues (OSDI/SOSP for systems,
   NSDI/SIGCOMM for networking, ASPLOS for arch, MLSys for ML systems, etc.).

3. **Read the summaries, not just titles.** For each candidate paper, read the
   `TL;DR`, `Key Insight`, and `Novelty & Impact` sections of its `.en.md`. Decide
   whether it is (a) supporting evidence, (b) counter-evidence, or (c) irrelevant.
   Keep a running list with one-line rationale per paper. Discard irrelevant entries
   immediately — do not let them creep into the draft.

4. **Reach for the PDF when needed.** If a paper seems load-bearing for the thesis,
   open the PDF (under `_inbox/` if present) and confirm the summary didn't miss a
   nuance that would flip your classification.

Minimum bar: an essay that cites fewer than **4 indexed papers** is a "hot take", not a
tech-insight post. Target 6–12. If the corpus genuinely doesn't have enough coverage,
tell the user before drafting — the right answer may be to summarize a few more papers
first.

### Phase 3 — Web search to patch gaps

Papers are conservative; the conversation around them happens elsewhere. Use web search
to gather the material the papers don't contain. Good targets:

- **Follow-up work** published after the corpus cutoff — arXiv preprints, newer
  conference versions.
- **Industry blog posts** from the system's operators — often the strongest
  counter-evidence, because they describe what broke in practice.
- **Author talk videos or slide decks** — frequently expose reviewer concerns that
  didn't make the paper.
- **Benchmark suites and leaderboards** — useful for quantitative grounding.
- **Retrospectives** — "five years on, here's what we learned" posts age perspectives
  well.

Guardrails:

- Never cite a source you cannot open and read. "I recall that X said Y" is not
  evidence.
- Prefer primary sources (the author's own blog, the project's docs, the repo) over
  secondary aggregators.
- Record URLs as you go. Drop dead URLs — do not cite a 404.

### Phase 4 — Outline against the evidence, not the other way round

With the evidence list in hand, outline the post. The outline is not the template
skeleton — it's the specific argumentative skeleton of **this** essay. A good outline
names the claim of each section and which pieces of evidence it relies on:

```
§ Thesis              claim: "X is really about caching"
§ The setup           cites: Paper A (OSDI '22), Paper B (ATC '23)
§ Evidence            cites: Paper C, D, E, F on KV-cache reuse
§ Evidence            cites: Paper G, H on prompt prefix sharing
§ Counter-evidence    cites: Paper I (batch-first framing), Blog J
§ What this means     no new cites
```

If a section in the outline has no cites, it's probably filler — cut it or merge it.

### Phase 5 — Draft English first, then translate

- Write English first. The argumentative structure drives the essay; translating
  afterwards preserves it. (Writing Chinese first and translating backwards tends to
  produce a weaker English version because Chinese prose tolerates more implicit
  connectors than English does.)
- Keep paragraphs tight: **3–6 sentences**. A blog post is not a paper. Readers scan;
  reward them with topic sentences.
- **Every empirical claim is linked.** If you write "X is 2× faster than Y", the 2×
  number must be traceable — either to an indexed paper (inline link to its page) or
  to an external source (inline link to the URL). No dangling numbers.
- **Inline links** are the main citation mechanism. Use markdown `[text](url)` form.
  See the link-style subsection below.
- Do not quote the papers. Paraphrase and cite. If a sentence is so well-phrased it
  must be quoted, keep it short (< 20 words) and mark it as a blockquote.
- **Voice:** confident but falsifiable. State the thesis assertively, but make each
  supporting claim narrow enough that the reader can point at what would refute it.

### Phase 6 — Translate to Simplified Chinese

- Translate in whole paragraphs, not sentence-by-sentence. The unit of meaning is the
  paragraph.
- Keep technical identifiers in English: paper titles, system names (Shenango, vLLM,
  FlashAttention), benchmark names, venue abbreviations (OSDI '25), product names.
- Translate headings. Use the same heading as the English version, translated
  idiomatically. (See [`templates/blog.md`](templates/blog.md).)
- Rewrite the `oneline` independently in Chinese — don't literal-translate it. The
  English `oneline` is an English hook; the Chinese `oneline` is a Chinese hook.
- Every inline link in the English body becomes a link in the Chinese body, but
  rewrite the URL's language prefix: `/en/papers/...` → `/zh-cn/papers/...`.

### Phase 7 — Count words and fill in frontmatter

- **`total_words` (English file)** — body word count, excluding frontmatter and
  heading text. `wc -w <file.md>` then subtract the rough frontmatter/heading
  overhead, rounded to the nearest 10.
- **`total_words` (Chinese file)** — body **character** count (Chinese convention),
  excluding frontmatter and headings. Round to the nearest 100.
- `reading_time_minutes` — optional. If you want to pin it, use 220 wpm for English
  and 380 chars/min for Chinese. If omitted, the site computes it.
- `tags` — 3–6 tags, English kebab-case, mostly from
  [`tag-vocabulary.md`](tag-vocabulary.md). Mint a new tag only for a genuinely new
  concept and note it in your return message.
- `written_by` — your `agent_model` string verbatim.
- `publish_date` — today, ISO format. Same date in both files.
- `draft: false` when the post is ready. Leave `true` if you're handing back for
  review.

### Phase 8 — Self-review before handing back

Before you declare done, verify:

- [ ] The thesis is stated in the first paragraph and every section defends it.
- [ ] There is at least one section of counter-evidence that genuinely pushes back
      against the thesis.
- [ ] Every paper citation is an inline link to the paper's page on this site.
- [ ] Every external citation is an inline link to a URL you actually opened.
- [ ] No bare numbers without a source.
- [ ] Both files exist; `title`, `topic`, `tags`, `written_by`, `publish_date`,
      `draft` are identical across them; `oneline` and `total_words` are
      language-specific.
- [ ] Neither file has leftover template placeholder text.

---

## Link-style rules

- **Paper pages on this site** — use a site-relative link to the language-matched
  path, not a markdown-file-relative link:
  - English: `[Shenango](/en/papers/osdi-2025/shenango)`
  - Chinese: `[Shenango](/zh-cn/papers/osdi-2025/shenango)`

  (Paper summary files are markdown-file-relative when linked from inside a
  conference overview, because both live under `src/content/`. Blog posts are
  rendered at a different route, so use absolute-from-root.)

- **External URLs** — plain inline markdown link with descriptive text. Never bare
  URLs: `[vLLM's blog post on continuous batching](https://…)` not `(https://…)`.
- **Conference pages** — `/en/conferences/<slug>` or `/zh-cn/conferences/<slug>`.
- **Tag pages** — `/en/tags/<tag>` or `/zh-cn/tags/<tag>`. Use sparingly; tag pages
  aren't always interesting to read.

---

## Required output structure

Copy the skeleton in [`templates/blog.md`](templates/blog.md). The frontmatter fields
are schema-validated by `src/content/config.ts` — any mismatch fails the build.

Required H2 sections (English / Chinese). Order matters. Headings translate:

### Thesis / 核心论点
One paragraph. The claim the whole post defends. Not a description of topic.

### The setup / 背景与铺垫
Frame what prior thinking this is pushing against. Name 2–3 foundational papers with
inline links. Short — 1–2 paragraphs.

### The evidence / 论据
The middle of the essay. Multiple subsections allowed (use H3). Organize by argument,
not by paper. Every claim cites.

### The counter-evidence / 反方证据
Mandatory. One or two paragraphs. Name the strongest objection, cite papers or blog
posts that push back. If you can't find counter-evidence, your thesis is probably
vacuous — go back to Phase 1.

### What this means / 这意味着什么
Operational takeaways. Who benefits from this framing? What decisions does it change?
Short — this is not the place for new evidence.

### References / 参考资料 (optional)
Only include if the post leans on enough external material that an explicit list
helps. Otherwise inline links are sufficient.

---

## Hard rules (repeated because they matter)

- Defend the user-supplied perspective. If you change the thesis mid-draft, stop and
  check with the user.
- No invented numbers, citations, authors, or affiliations. If a fact is not in a
  source you have opened, it doesn't go in the essay.
- Cite with inline links. Do not footnote, do not use academic `[1]`-style citations.
- Produce exactly two files: `output_path_en` and `output_path_zh`. Do not touch
  sibling blog posts or unrelated content.
- Do not run `npm run build` yourself — the caller will validate after you return.
- Do not translate paper titles, system names, or venue abbreviations. Surrounding
  prose only.
- `title`, `topic`, `tags`, `written_by`, `publish_date`, `draft` stay identical
  across both files. Only `oneline` and `total_words` differ.
