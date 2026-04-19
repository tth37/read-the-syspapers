# AGENTS.md

Instructions for coding agents working in this repository. Three roles exist:

- **Orchestrator** — a long-lived session that plans a whole conference pass, prepares
  the manifest, dispatches per-paper sub-agents via [`scripts/orchestrate.py`](scripts/orchestrate.py),
  and synthesizes the final overview. In practice this is Claude Code. Start here:
  [`prompts/conference-overview-quickstart.md`](prompts/conference-overview-quickstart.md)
  for the terse recipe, [`prompts/conference-overview.md`](prompts/conference-overview.md)
  for the long-form rationale.
- **Sub-agent** — a short-lived process that owns exactly one paper. Invoked by the
  orchestrator script (via `codex exec` or `claude -p`) with a rendered prompt from
  [`prompts/paper-summary-invocation.md`](prompts/paper-summary-invocation.md). Its
  instruction set is [`prompts/paper-summary.md`](prompts/paper-summary.md).
- **Blog writer** — a single session that takes a user-supplied perspective on a topic,
  does comprehensive research across indexed papers and the open web, and ships one
  bilingual blog post. Instruction set: [`prompts/blog-writing.md`](prompts/blog-writing.md).
  Unlike paper summaries, blog posts are perspective-driven (the user always supplies
  a thesis) and are not orchestrated — one prompt, one agent, one post.

This file is deliberately short; long-form task prompts live in [`prompts/`](prompts/).
Read this file first, then the specific prompt for your role.

## What this repo is

`read-the-syspapers` is a static Astro site of long-form, PhD-depth summaries of systems
top-conference papers (OSDI, SOSP, NSDI, ATC, EuroSys, ASPLOS, FAST, MLSys, …). Summaries
are produced by coding agents following shared prompts. Each summary records which agent
wrote it via the `written_by` frontmatter field, so the site doubles as a comparison of how
different agents handle the same papers.

## Directory map

| Path | Purpose |
|---|---|
| `src/content/conferences/` | Two files per conference: `<venue>-<year>.en.md` **and** `<venue>-<year>.zh-cn.md`. Frontmatter is strictly validated. |
| `src/content/papers/<venue>-<year>/` | For each paper: `<slug>.en.md` **and** `<slug>.zh-cn.md`. Both must exist. |
| `src/content/blog/` | Two files per blog post: `<slug>.en.md` **and** `<slug>.zh-cn.md`. Perspective-driven long-form essays; see [`prompts/blog-writing.md`](prompts/blog-writing.md). |
| `src/content/config.ts` | Zod schemas and the canonical `LANGS` list. Read before editing any frontmatter. |
| `src/pages/[lang]/…` | Every rendered page is locale-prefixed. URLs look like `/en/conferences/osdi-2025` and `/zh-cn/conferences/osdi-2025`. |
| `prompts/` | Agent task prompts. |
| `prompts/templates/` | Frontmatter + section skeletons to copy-paste into new content files. |
| `scripts/orchestrate.py` | Pipeline orchestrator — spawns sub-agent CLIs in parallel, flips manifest status atomically. Auto-retries transient network errors. |
| `scripts/manifest_helpers.py` | Building blocks for manifest assembly (bookmark probing, footer-offset detection, slug/path helpers, validation). CLI subcommands: `bookmarks`, `offset`, `validate`. |
| `scripts/validate_paper.py` | Cheap pre-build validator for paper pairs (frontmatter parity, required H2s, tag vocabulary, `written_by` format). Run after every fan-out. |
| `_inbox/` | Gitignored. Drop PDFs, proceedings archives, and run manifests here. |

## Hard rules (read these before doing anything)

1. **Agent identity (`written_by`).** Stamp a model-qualified identity string on every
   conference and paper file you author. Format: `"<model> (<agent-cli>)"`. Canonical
   examples:
   - Codex runs: `"gpt-5.4 (codex)"`
   - Claude Code runs: `"Claude Opus 4.7 (Claude Code)"`, `"Claude Sonnet 4.6 (Claude Code)"`, …
   - Human: `"human"` (no model qualifier).

   The orchestrator passes you the correct string as `{agent_model}`; use it verbatim and
   never substitute another agent's identity.
2. **Bilingual is mandatory.** Every paper summary, conference overview, and blog post
   ships as **both** `<slug>.en.md` and `<slug>.zh-cn.md`. Shared fields stay identical
   across the two files; `oneline` and body prose are per-language (and for blog posts,
   `total_words` too, since Chinese counts characters and English counts words). A file
   that exists in only one language fails review.

   **The Chinese file is a re-expression, not a translation.** Both files defend the
   same claim, cite the same papers, report the same numbers, and carry the same
   H2 section order — but sentence boundaries, transitions, idioms, and paragraph
   counts can differ. Aim for prose that would read as natively Chinese if the English
   version did not exist; translation-shaped Chinese ("翻译腔") is the failure mode to
   avoid. Practical rules that apply across paper summaries, conference overviews, and
   blog posts:

   - **Match across files:** thesis / key insight / mechanism, section order, paper
     citations, every empirical number, every external URL.
   - **Vary so it reads natively:** sentence boundaries (merge/split/reorder within a
     paragraph), transitions (其实、不过、换句话说 instead of literal "however" /
     "in other words"), paragraph count within ±1 per section, idioms, rhetorical
     register. Write the Chinese `oneline` fresh, not as a translation of the English
     one.
   - **Inline quotes in Chinese bodies use 「」**, never ASCII `"..."`. This applies
     to scare-quotes around Chinese phrases (「启动本身」) and to English phrases
     embedded in Chinese prose (「workset」、「reflections and optimizations」).
     ASCII `"` in Chinese text reads as a translation artifact and also breaks YAML
     if it leaks into `oneline`.
   - **Keep technical identifiers in English** inside the Chinese body: paper titles,
     system names (Shenango, vLLM, FlashAttention), benchmark names, venue
     abbreviations (OSDI '25), product names, function / flag names.
   - **Rewrite URL language prefix** when carrying a link from the English body:
     `/en/papers/...` → `/zh-cn/papers/...`.
   - Role-specific prompts (paper summary, conference synthesis, blog) may add
     further constraints; they never loosen the ones above.
3. **Never fabricate.** No invented citations, no invented numbers, no invented author
   names or affiliations. If the paper does not specify something, write "the paper does
   not specify" (or the Chinese equivalent) rather than guessing. Do not copy the abstract
   verbatim — paraphrase into your own prose.
4. **Never commit PDFs or proceedings archives.** All PDFs stay in `_inbox/` (gitignored).
   The repo ships summaries and metadata only.
5. **Stay in your lane.** Sub-agents running in parallel edit disjoint file pairs. Do not
   touch other papers' summaries, even to "fix" formatting. Raise concerns in your return
   message; the orchestrator will handle cross-paper fix-ups during synthesis.
6. **Schema is law.** Do not relax `src/content/config.ts` to make a file validate. Fix
   the file. If a schema change is genuinely required, stop and flag it to the user.
7. **Resumable work only.** The orchestrator drives work from a manifest at
   `_inbox/<slug>/manifest.json`. `scripts/orchestrate.py` flips each entry
   `pending` → `in-progress` → `done`|`failed` atomically and skips `done` entries on
   re-run. Never lose progress to a crash or a context-window wipe.
8. **One paper per sub-agent.** Sub-agents own exactly one paper (one `.en.md` + one
   `.zh-cn.md` pair). Batching multiple papers into a single sub-agent reliably blows
   context and produces shallow output — the orchestrator script fans out, that's its job.
9. **No new dependencies** without explicit user approval. This is a content repo, not a
   framework playground.
10. **Do not push or open PRs** unless the user explicitly asks. Commit locally on a
    well-named branch and stop.

## Orchestrator invariants (bake these in; stop re-deriving)

When running a conference overview, these defaults are already known-good. Don't
re-ask the user about them and don't improvise:

- **Sub-agent + model.** `codex` with `gpt-5.4`. The orchestrator identity is
  `"<current-claude-model> (Claude Code)"` — e.g. `"Claude Opus 4.7 (Claude Code)"`.
- **Concurrency.** `5` for fan-out; `2` for `--retry-failed` (calmer on flaky paths).
- **Timeout.** `2400s` per sub-agent. Long-paper PhD-depth summaries occasionally
  hit the 1800s default.
- **Auto-retry.** Built into orchestrate.py — 2 retries on transient stream
  disconnects / rate limits / socket hangups. Don't wrap the script in external retry.
- **Branch.** `overview/<slug>`; commit prefix `overview(<slug>):`; never push.
- **Must-reads.** At most 5, each with a one-line justification, chosen to span
  different tracks.
- **Conference overview body.** Required structure: at-a-glance intro paragraph
  before `## Themes` / `## 主题` → Themes (3–5 bullets) → Notable trends (3–4
  bullets, each with ≥3 papers) → Must-read picks (≤5) → Stats. Every paper
  reference in the overview is an inline markdown link of the form
  `[Name](../papers/<slug>/<paper-slug>.md)` — never bare text, never
  `/en/papers/...` or `/zh-cn/papers/...`. See
  [`prompts/conference-synthesis.md`](prompts/conference-synthesis.md) for the
  style rubric.

## Entry points by role

- **Orchestrator** — fresh conference pass (terse recipe) → [`prompts/conference-overview-quickstart.md`](prompts/conference-overview-quickstart.md).
- **Orchestrator** — long-form rationale / failure modes → [`prompts/conference-overview.md`](prompts/conference-overview.md).
- **Orchestrator** — assembling `_inbox/<slug>/manifest.json` → [`prompts/manifest-building.md`](prompts/manifest-building.md).
- **Orchestrator** — dispatching sub-agents → [`scripts/orchestrate.py`](scripts/orchestrate.py) (`--help` for flags).
- **Orchestrator** — writing the conference-level synthesis after per-paper summaries land → [`prompts/conference-synthesis.md`](prompts/conference-synthesis.md).
- **Sub-agent** — per-paper instructions (what sections to write, how deep) → [`prompts/paper-summary.md`](prompts/paper-summary.md).
- **Sub-agent** — the literal rendered prompt the orchestrator sends you → [`prompts/paper-summary-invocation.md`](prompts/paper-summary-invocation.md).
- **Blog writer** — perspective-driven tech-insight essay (research methodology + bilingual output) → [`prompts/blog-writing.md`](prompts/blog-writing.md).
- **Anyone** — tag vocabulary → [`prompts/tag-vocabulary.md`](prompts/tag-vocabulary.md).

## Build & preview

```
npm install
npm run dev      # http://localhost:4321, redirects to /en/
npm run build    # astro build + pagefind index
```

Schema errors fail the build loudly. Run `npm run build` after producing content to catch
them early; never ship without it passing.
