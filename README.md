# read-the-syspapers

A static site hosting PhD-depth summaries of papers from systems top conferences —
OSDI, SOSP, NSDI, ATC, EuroSys, ASPLOS, FAST, MLSys, and more.

Summaries are produced by coding agents (Claude Code, Codex, Cursor, Gemini, Aider, …)
driven by the shared harness in [`AGENTS.md`](AGENTS.md) and [`prompts/`](prompts). Each
summary records which agent wrote it (`written_by` frontmatter field), so the site
doubles as a comparison of how different agents handle the same paper.

## Stack

- [Astro](https://astro.build/) 5 with content collections (Zod-validated frontmatter)
- [Pagefind](https://pagefind.app/) for static, client-side full-text search
- Deployed to GitHub Pages via GitHub Actions

## Local dev

```bash
npm install
npm run dev      # http://localhost:4321
npm run build    # astro build + pagefind index
```

Schema violations fail the build with clear errors — see `src/content/config.ts`.

## Adding content via a coding agent

Open a fresh session of any coding agent (Claude Code, Codex, Cursor, Aider, …) in the
repo and say:

> Do an overview of **OSDI 2025**. Follow `prompts/conference-overview.md`.

The agent will:

1. Scrape the program page and download PDFs into gitignored `_inbox/`.
2. Spawn sub-agents per paper following `prompts/paper-summary.md`.
3. Write one summary per paper under `src/content/papers/osdi-2025/`.
4. Fill in the conference-level overview at `src/content/conferences/osdi-2025.md`.
5. Commit locally on branch `overview/osdi-2025` and stop.

If the agent can't auto-download every PDF, it will list the missing ones in
`_inbox/osdi-2025/needs_manual_pdf.md` and wait; drop the proceedings archive (or
individual PDFs) into `_inbox/osdi-2025/pdfs/` and re-run.

## Deployment

`.github/workflows/deploy.yml` builds and publishes to GitHub Pages on push to `main`.

Before your first deploy:

1. Update `site` and `base` in `astro.config.mjs` to match your repo name and GitHub
   username.
2. In the repo's **Settings → Pages**, set the source to **"GitHub Actions"**.

## Directory map

```
AGENTS.md                          # entry point for any coding agent
prompts/
  conference-overview.md           # top-level task: "do OSDI 2025"
  paper-summary.md                 # sub-agent task: summarize one paper
  tag-vocabulary.md                # canonical tag list + scope rules
  templates/
    conference.md                  # frontmatter skeleton for a new conference
    paper.md                       # frontmatter + sections skeleton
src/
  content/
    config.ts                      # Zod schemas (strictly validated)
    conferences/<venue>-<year>.md  # one per conference
    papers/<venue>-<year>/*.md     # one per paper summary
  layouts/ components/ pages/      # Astro site
_inbox/                            # gitignored; PDFs and proceedings live here
```

## License

Paper summaries are your own commentary on third-party publications. PDFs are not
redistributed through this site — they live in the gitignored `_inbox/` only.
