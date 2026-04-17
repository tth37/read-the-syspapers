# AGENTS.md

Instructions for any coding agent (Claude Code, Codex, Cursor, Gemini, Aider, Windsurf, …)
working in this repository. This file is deliberately short; long-form task prompts live in
[`prompts/`](prompts/). Read this file first, then the specific prompt for your task.

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
| `src/content/config.ts` | Zod schemas and the canonical `LANGS` list. Read before editing any frontmatter. |
| `src/pages/[lang]/…` | Every rendered page is locale-prefixed. URLs look like `/en/conferences/osdi-2025` and `/zh-cn/conferences/osdi-2025`. |
| `prompts/` | Agent task prompts. |
| `prompts/templates/` | Frontmatter + section skeletons to copy-paste into new content files. |
| `_inbox/` | Gitignored. Drop PDFs, proceedings archives, and run manifests here. |

## Hard rules (read these before doing anything)

1. **Agent identity.** Set `written_by` in every conference and paper file you author to
   your own agent id. Canonical ids: `claude-code`, `codex`, `cursor`, `gemini`, `aider`,
   `windsurf`, `human`. If your agent is not listed, use a kebab-case slug of its name.
   Never copy another agent's id.
2. **Bilingual is mandatory.** Every paper summary ships as **both** `<slug>.en.md` and
   `<slug>.zh-cn.md`. Every conference overview ships as **both** `.en.md` and `.zh-cn.md`.
   The two files share title/authors/affiliations/tags/category/URLs; only the `oneline`
   and the body prose differ. A paper that exists in only one language fails review.
3. **Never fabricate.** No invented citations, no invented numbers, no invented author
   names or affiliations. If the paper does not specify something, write "the paper does
   not specify" (or the Chinese equivalent) rather than guessing. Do not copy the abstract
   verbatim — paraphrase into your own prose.
4. **Never commit PDFs or proceedings archives.** All PDFs stay in `_inbox/` (gitignored).
   The repo ships summaries and metadata only.
5. **Stay in your lane.** When processing a single paper, do not edit other papers'
   summaries, even to "fix" formatting. Raise concerns in the conference overview body.
6. **Schema is law.** Do not relax `src/content/config.ts` to make a file validate. Fix the
   file. If a schema change is genuinely required, stop and flag it to the user.
7. **Resumable work only.** Long runs must be resumable from a manifest at
   `_inbox/<slug>/manifest.json` — see [`prompts/conference-overview.md`](prompts/conference-overview.md).
   Never lose progress to a crash or a context-window wipe.
8. **Micro-batches, not mega-batches.** When summarizing papers, process at most **1–3
   papers per sub-task**, or ~60 PDF pages of total input, whichever is smaller. Larger
   batches reliably blow context and produce shallow output.
9. **No new dependencies** without explicit user approval. This is a content repo, not a
   framework playground.
10. **Do not push or open PRs** unless the user explicitly asks. Commit locally on a
    well-named branch and stop.

## Entry points by task

- **"Do an overview of \<venue> \<year>"** → [`prompts/conference-overview.md`](prompts/conference-overview.md).
- **"Summarize this one paper"** → [`prompts/paper-summary.md`](prompts/paper-summary.md).
- **"Synthesize the conference-level overview"** → [`prompts/conference-synthesis.md`](prompts/conference-synthesis.md)
  (run *after* per-paper summaries exist).
- **"What tags should I use?"** → [`prompts/tag-vocabulary.md`](prompts/tag-vocabulary.md).

## Build & preview

```
npm install
npm run dev      # http://localhost:4321, redirects to /en/
npm run build    # astro build + pagefind index
```

Schema errors fail the build loudly. Run `npm run build` after producing content to catch
them early; never ship without it passing.
