# AGENTS.md

Instructions for coding agents working in this repository. Two roles exist:

- **Orchestrator** — a long-lived session that plans a whole conference pass, prepares
  the manifest, dispatches per-paper sub-agents via [`scripts/orchestrate.py`](scripts/orchestrate.py),
  and synthesizes the final overview. In practice this is Claude Code. Start here:
  [`prompts/conference-overview.md`](prompts/conference-overview.md).
- **Sub-agent** — a short-lived process that owns exactly one paper. Invoked by the
  orchestrator script (via `codex exec` or `claude -p`) with a rendered prompt from
  [`prompts/paper-summary-invocation.md`](prompts/paper-summary-invocation.md). Its
  instruction set is [`prompts/paper-summary.md`](prompts/paper-summary.md).

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
| `src/content/config.ts` | Zod schemas and the canonical `LANGS` list. Read before editing any frontmatter. |
| `src/pages/[lang]/…` | Every rendered page is locale-prefixed. URLs look like `/en/conferences/osdi-2025` and `/zh-cn/conferences/osdi-2025`. |
| `prompts/` | Agent task prompts. |
| `prompts/templates/` | Frontmatter + section skeletons to copy-paste into new content files. |
| `scripts/orchestrate.py` | Pipeline orchestrator — spawns sub-agent CLIs in parallel, flips manifest status atomically. |
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

## Entry points by role

- **Orchestrator** — starting a fresh conference pass → [`prompts/conference-overview.md`](prompts/conference-overview.md).
- **Orchestrator** — dispatching sub-agents → [`scripts/orchestrate.py`](scripts/orchestrate.py) (`--help` for flags).
- **Orchestrator** — writing the conference-level synthesis after per-paper summaries land → [`prompts/conference-synthesis.md`](prompts/conference-synthesis.md).
- **Sub-agent** — per-paper instructions (what sections to write, how deep) → [`prompts/paper-summary.md`](prompts/paper-summary.md).
- **Sub-agent** — the literal rendered prompt the orchestrator sends you → [`prompts/paper-summary-invocation.md`](prompts/paper-summary-invocation.md).
- **Anyone** — tag vocabulary → [`prompts/tag-vocabulary.md`](prompts/tag-vocabulary.md).

## Build & preview

```
npm install
npm run dev      # http://localhost:4321, redirects to /en/
npm run build    # astro build + pagefind index
```

Schema errors fail the build loudly. Run `npm run build` after producing content to catch
them early; never ship without it passing.
