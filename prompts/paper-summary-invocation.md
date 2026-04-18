# Prompt template: single-paper sub-agent invocation

This file is a **template** consumed by [`scripts/orchestrate.py`](../scripts/orchestrate.py).
The orchestrator substitutes `{var}` placeholders with values from a manifest entry and
pipes the result to the chosen sub-agent CLI (`codex exec` or `claude -p`).

Do **not** translate, reformat, or add extra prose. Each substituted prompt must stay
compact — sub-agents should spend their context reading the assigned PDF pages, not this
wrapper.

---

```
Work in {repo_root}.

Task: read AGENTS.md and prompts/paper-summary.md, then summarize exactly one assigned
paper into two markdown files.

You are not alone in the codebase. Other sub-agents are running in parallel on sibling
papers. Do not revert, rename, or re-format anyone else's changes. Own only these files:
- {output_path_en}
- {output_path_zh}

Inputs:
- pdf_path: {pdf_path}
- pdf_page_start: {pdf_page_start}
- pdf_page_end: {pdf_page_end}
- volume: {volume}
- output_path_en: {output_path_en}
- output_path_zh: {output_path_zh}
- conference_slug: {conference_slug}
- agent_id: {agent_id}
- agent_model: {agent_model}
- tag_vocabulary_path: {tag_vocabulary_path}

Requirements:
- Read only the assigned proceedings page range from the combined volume.
- Match the depth and structure of existing pilot summaries in
  src/content/papers/{conference_slug}/.
- Produce both files with schema-valid frontmatter and full bilingual bodies
  (English + Simplified Chinese).
- Set `written_by: "{agent_model}"` on both files — this is the model-qualified identity
  string the orchestrator passed you; use it verbatim.
- Do not run `npm run build` — the orchestrator validates after each batch.
- Do not edit any file outside the two output paths.

Return: the files you changed and any blocking concerns. Nothing else.
```

---

## Variable reference

All variables are filled by the orchestrator from the manifest entry plus the agent
registry:

| Variable | Source | Example |
|---|---|---|
| `{repo_root}` | orchestrator arg | `/Users/tth37/Repositories/read-the-syspapers` |
| `{pdf_path}` | manifest `pdf_path` | `_inbox/asplos-2026/proceedings-vol1.pdf` |
| `{pdf_page_start}` | manifest | `17` |
| `{pdf_page_end}` | manifest | `33` |
| `{volume}` | manifest | `1` |
| `{output_path_en}` | manifest | `src/content/papers/asplos-2026/shenango.en.md` |
| `{output_path_zh}` | manifest | `src/content/papers/asplos-2026/shenango.zh-cn.md` |
| `{conference_slug}` | orchestrator arg | `asplos-2026` |
| `{agent_id}` | agent registry | `codex` |
| `{agent_model}` | agent registry | `gpt-5.4 (codex)` |
| `{tag_vocabulary_path}` | constant | `prompts/tag-vocabulary.md` |

## Smoke-test prompt

When `scripts/orchestrate.py --smoke` is invoked, the orchestrator ignores this file and
sends each sub-agent the literal string `say hi in one sentence, then exit. do not touch
any files.` instead. That run proves the parallel dispatch, timeout, and status-flip logic
without risking content corruption.
