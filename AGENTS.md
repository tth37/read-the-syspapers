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
| `src/content/conferences/` | One `<venue>-<year>.md` per conference. Frontmatter is strictly validated. |
| `src/content/papers/<venue>-<year>/` | One `<slug>.md` per paper summary. Strictly validated. |
| `src/content/config.ts` | Zod schemas. Read before editing any frontmatter. |
| `prompts/` | Agent task prompts. |
| `prompts/templates/` | Frontmatter + section skeletons to copy-paste into new content files. |
| `_inbox/` | Gitignored. Drop PDFs and proceedings ZIPs here for processing. |

## Hard rules (read these before doing anything)

1. **Agent identity.** Set the `written_by` field in every conference and paper file you
   author to your own agent id. Canonical ids: `claude-code`, `codex`, `cursor`, `gemini`,
   `aider`, `windsurf`, `human`. If your agent is not listed, use a kebab-case slug of its
   name. Never copy another agent's id.
2. **Never fabricate.** No invented citations, no invented numbers, no invented author names
   or affiliations. If the paper does not specify something, write "the paper does not
   specify" rather than guessing. Do not copy the abstract verbatim — paraphrase.
3. **Never commit PDFs.** All PDFs stay in `_inbox/` (gitignored). The repo ships summaries
   and metadata only.
4. **Stay in your lane.** When processing a single paper, do not edit other papers'
   summaries, even to "fix" formatting. Raise concerns in the conference overview's body.
5. **Schema is law.** Do not relax `src/content/config.ts` to make a file validate. Fix the
   file. If a schema change is genuinely required, mention it in the PR description.
6. **No new dependencies** without explicit user approval. This is a content repo, not a
   framework playground.
7. **Do not push or open PRs** unless the user explicitly asks. Commit locally on a
   well-named branch and stop.

## Entry points by task

- **"Do an overview of \<venue> \<year>"** → follow [`prompts/conference-overview.md`](prompts/conference-overview.md).
- **"Summarize this one paper"** → follow [`prompts/paper-summary.md`](prompts/paper-summary.md).
- **"What tags should I use?"** → [`prompts/tag-vocabulary.md`](prompts/tag-vocabulary.md).

## Build & preview

```
npm install
npm run dev      # http://localhost:4321
npm run build    # astro build + pagefind index
```

Schema errors fail the build loudly. Run the build after producing content to catch them
early.
