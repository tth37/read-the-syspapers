#!/usr/bin/env python3
"""Orchestrate parallel sub-agent runs for a conference overview.

Claude Code (the session running you, the human) is the orchestrator. This script
is the hand-off: it spawns sub-agent CLIs (`codex exec` or `claude -p`), one per paper,
capped at a concurrency limit. It uses a ThreadPoolExecutor pipeline so the moment a
worker finishes, the next pending entry is picked up — no batch-and-wait.

State lives in `_inbox/<conference>/manifest.json`. Each entry is flipped atomically
(`pending` → `in-progress` → `done` | `failed`) under a process-wide lock. Re-runs are
safe: already-`done` entries are skipped unless `--retry-failed` also reopens failed ones.

See `prompts/paper-summary-invocation.md` for the sub-agent prompt template and variable
list. See `AGENTS.md` for the harness rules.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import dataclasses
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys
import threading
import time
from typing import Callable, Optional


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PROMPT_TEMPLATE_PATH = REPO_ROOT / "prompts" / "paper-summary-invocation.md"
TAG_VOCAB_PATH = "prompts/tag-vocabulary.md"
SMOKE_PROMPT = "say hi in one sentence, then exit. do not touch any files."


# ---------------------------------------------------------------------------
# Agent registry
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Agent:
    """A sub-agent CLI and the identity string it should stamp into `written_by`."""

    id: str                       # canonical id (codex, claude-code, …)
    display: str                  # goes into `written_by`, e.g. "gpt-5.4 (codex)"
    build_cmd: Callable[[str], list[str]]


def _codex_cmd(prompt: str) -> list[str]:
    # Pin the model so the identity we stamp into `written_by` ("gpt-5.4 (codex)")
    # actually matches the model that produced the output. Without `-m`, codex uses
    # whatever default is configured in ~/.codex/config.toml, which is not portable
    # across machines. `--dangerously-bypass-approvals-and-sandbox` is the only way
    # to run fully unattended — the sub-agent needs to edit files without prompts.
    return [
        "codex",
        "exec",
        "-m", "gpt-5.4",
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check",
        "--cd", str(REPO_ROOT),
        prompt,
    ]


def _claude_code_cmd(prompt: str) -> list[str]:
    return [
        "claude",
        "-p",
        "--allow-dangerously-skip-permissions",
        "--add-dir", str(REPO_ROOT),
        prompt,
    ]


AGENTS: dict[str, Agent] = {
    "codex": Agent(
        id="codex",
        display="gpt-5.4 (codex)",
        build_cmd=_codex_cmd,
    ),
    "claude-code": Agent(
        id="claude-code",
        display="Claude Opus 4.7 (Claude Code)",
        build_cmd=_claude_code_cmd,
    ),
}


# ---------------------------------------------------------------------------
# Manifest I/O (thread-safe)
# ---------------------------------------------------------------------------

class Manifest:
    """Thread-safe manifest wrapper. Every mutation persists to disk under a lock."""

    def __init__(self, path: pathlib.Path):
        self.path = path
        self._lock = threading.Lock()
        self._data = json.loads(path.read_text())
        if not isinstance(self._data, list):
            raise ValueError(
                f"Expected manifest to be a JSON array of paper entries: {path}"
            )

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [dict(entry) for entry in self._data]

    def update(self, slug: str, **fields) -> None:
        with self._lock:
            for entry in self._data:
                if entry.get("slug") == slug:
                    entry.update(fields)
                    self._flush_locked()
                    return
            raise KeyError(f"slug not found in manifest: {slug}")

    def _flush_locked(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False) + "\n")
        tmp.replace(self.path)


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Result:
    slug: str
    ok: bool
    returncode: int
    duration_s: float
    stderr_tail: str
    stdout_tail: str


def _tail(s: str, n: int = 4000) -> str:
    if len(s) <= n:
        return s
    return "…[truncated]…\n" + s[-n:]


def _render_prompt(template: str, entry: dict, agent: Agent, conference_slug: str) -> str:
    repl = {
        "repo_root": str(REPO_ROOT),
        "pdf_path": entry.get("pdf_path", ""),
        "pdf_page_start": entry.get("pdf_page_start", ""),
        "pdf_page_end": entry.get("pdf_page_end", ""),
        "volume": entry.get("volume", ""),
        "output_path_en": entry.get("output_path_en", ""),
        "output_path_zh": entry.get("output_path_zh", ""),
        "conference_slug": conference_slug,
        "agent_id": agent.id,
        "agent_model": agent.display,
        "tag_vocabulary_path": TAG_VOCAB_PATH,
    }
    # Render the single fenced prompt block out of the template. We look for the first
    # triple-backtick block that mentions `{repo_root}` and substitute there.
    m = re.search(r"```\n(Work in \{repo_root\}.*?)\n```", template, re.DOTALL)
    if not m:
        raise RuntimeError(
            f"Could not locate prompt block in {PROMPT_TEMPLATE_PATH}; "
            "expected a ```-fenced block starting with 'Work in {repo_root}.'"
        )
    body = m.group(1)
    return body.format(**{k: str(v) for k, v in repl.items()})


def _run_subagent(
    agent: Agent,
    prompt: str,
    log_path: pathlib.Path,
    timeout: int,
) -> tuple[int, str, str, float]:
    """Invoke the agent CLI; stream combined output to a per-paper log file."""
    cmd = agent.build_cmd(prompt)
    start = time.monotonic()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log:
        log.write(f"$ {' '.join(cmd[:4])} …\n")
        log.flush()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(REPO_ROOT),
            )
        except subprocess.TimeoutExpired as e:
            log.write(f"\n[timeout after {timeout}s]\n")
            return -1, e.stdout or "", (e.stderr or "") + f"\n[timeout after {timeout}s]", time.monotonic() - start
        log.write(proc.stdout or "")
        log.write("\n--- stderr ---\n")
        log.write(proc.stderr or "")
    return proc.returncode, proc.stdout or "", proc.stderr or "", time.monotonic() - start


def make_worker(
    manifest: Manifest,
    agent: Agent,
    prompt_template: Optional[str],
    conference_slug: str,
    log_dir: pathlib.Path,
    timeout: int,
    smoke: bool,
) -> Callable[[dict], Result]:
    def worker(entry: dict) -> Result:
        slug = entry["slug"]
        # Atomically claim the entry.
        manifest.update(
            slug,
            status="in-progress",
            last_error=None,
            started_at=dt.datetime.utcnow().isoformat() + "Z",
        )
        try:
            if smoke:
                prompt = SMOKE_PROMPT
            else:
                prompt = _render_prompt(prompt_template, entry, agent, conference_slug)
            rc, stdout, stderr, dur = _run_subagent(
                agent=agent,
                prompt=prompt,
                log_path=log_dir / f"{slug}.log",
                timeout=timeout,
            )
            ok = rc == 0
            manifest.update(
                slug,
                status="done" if ok else "failed",
                last_error=None if ok else _tail(stderr, 2000),
                finished_at=dt.datetime.utcnow().isoformat() + "Z",
                duration_s=round(dur, 1),
            )
            return Result(
                slug=slug,
                ok=ok,
                returncode=rc,
                duration_s=dur,
                stderr_tail=_tail(stderr, 800),
                stdout_tail=_tail(stdout, 800),
            )
        except Exception as exc:  # worker-side bug; flip to failed, keep running
            manifest.update(
                slug,
                status="failed",
                last_error=f"orchestrator exception: {exc!r}",
                finished_at=dt.datetime.utcnow().isoformat() + "Z",
            )
            return Result(
                slug=slug,
                ok=False,
                returncode=-2,
                duration_s=0.0,
                stderr_tail=repr(exc),
                stdout_tail="",
            )

    return worker


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def select_entries(
    entries: list[dict],
    *,
    retry_failed: bool,
    limit: Optional[int],
    only_slugs: Optional[set[str]],
) -> list[dict]:
    if only_slugs:
        chosen = [e for e in entries if e.get("slug") in only_slugs]
    else:
        chosen = []
        for e in entries:
            status = e.get("status", "pending")
            if status == "pending":
                chosen.append(e)
            elif status == "failed" and retry_failed:
                chosen.append(e)
            # `in-progress` left over from a crashed run: pick it up only if retry_failed.
            elif status == "in-progress" and retry_failed:
                chosen.append(e)
    if limit is not None:
        chosen = chosen[:limit]
    return chosen


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--conference", required=True,
        help="Conference slug, e.g. 'asplos-2026'. Manifest is _inbox/<conference>/manifest.json.",
    )
    ap.add_argument(
        "--agent", choices=sorted(AGENTS), default="codex",
        help="Which sub-agent CLI to spawn (default: codex).",
    )
    ap.add_argument(
        "--concurrency", type=int, default=5,
        help="Max in-flight sub-agents (default: 5). The executor submits all pending "
             "entries at once and picks the next as workers free — pub/sub pipeline, "
             "not batch-wait-then-start-next-batch.",
    )
    ap.add_argument(
        "--limit", type=int, default=None,
        help="Process at most N pending entries this run.",
    )
    ap.add_argument(
        "--slug", action="append", default=None,
        help="Run only this slug (repeatable). Overrides pending/failed selection.",
    )
    ap.add_argument(
        "--retry-failed", action="store_true",
        help="Also pick up failed/in-progress entries (otherwise only pending).",
    )
    ap.add_argument(
        "--timeout", type=int, default=1800,
        help="Per-sub-agent timeout in seconds (default: 1800).",
    )
    ap.add_argument(
        "--smoke", action="store_true",
        help="Smoke-test mode: send 'say hi' instead of the real prompt. Still flips "
             "manifest status so you can see the pipeline working end-to-end.",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Print the selection and exit. No subprocesses spawned, manifest untouched.",
    )
    args = ap.parse_args()

    conference = args.conference
    inbox = REPO_ROOT / "_inbox" / conference
    manifest_path = inbox / "manifest.json"
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        print(
            "Hint: the orchestrator (Claude Code session) is responsible for creating this "
            "file before invoking orchestrate.py. See prompts/conference-overview.md.",
            file=sys.stderr,
        )
        return 2

    manifest = Manifest(manifest_path)
    entries = manifest.snapshot()

    only_slugs = set(args.slug) if args.slug else None
    selected = select_entries(
        entries,
        retry_failed=args.retry_failed,
        limit=args.limit,
        only_slugs=only_slugs,
    )

    if not selected:
        print("Nothing to do. All entries are done or filtered out.")
        return 0

    agent = AGENTS[args.agent]
    print(
        f"[orchestrator] conference={conference} agent={agent.id} "
        f"display={agent.display!r} concurrency={args.concurrency} "
        f"selected={len(selected)}/{len(entries)} smoke={args.smoke} dry_run={args.dry_run}"
    )
    for e in selected[:10]:
        print(f"  - {e['slug']} (status={e.get('status','pending')})")
    if len(selected) > 10:
        print(f"  … and {len(selected) - 10} more")

    if args.dry_run:
        return 0

    prompt_template = None
    if not args.smoke:
        if not PROMPT_TEMPLATE_PATH.exists():
            print(f"ERROR: prompt template missing: {PROMPT_TEMPLATE_PATH}", file=sys.stderr)
            return 2
        prompt_template = PROMPT_TEMPLATE_PATH.read_text()

    log_dir = inbox / "logs"
    worker = make_worker(
        manifest=manifest,
        agent=agent,
        prompt_template=prompt_template,
        conference_slug=conference,
        log_dir=log_dir,
        timeout=args.timeout,
        smoke=args.smoke,
    )

    start = time.monotonic()
    ok_count = 0
    fail_count = 0
    with cf.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        # Submit all at once — ThreadPoolExecutor enforces the cap and picks the next
        # queued task the moment any worker returns. That's the pub/sub pipeline.
        futures = {ex.submit(worker, entry): entry["slug"] for entry in selected}
        completed = 0
        total = len(futures)
        for fut in cf.as_completed(futures):
            slug = futures[fut]
            completed += 1
            try:
                res: Result = fut.result()
            except Exception as exc:
                fail_count += 1
                print(f"[{completed}/{total}] EXC  {slug}: {exc!r}")
                continue
            status = "OK  " if res.ok else "FAIL"
            if res.ok:
                ok_count += 1
            else:
                fail_count += 1
            print(
                f"[{completed}/{total}] {status} {slug}  "
                f"rc={res.returncode} {res.duration_s:.1f}s"
            )
            if not res.ok and res.stderr_tail.strip():
                for line in res.stderr_tail.strip().splitlines()[-5:]:
                    print(f"         stderr: {line}")

    elapsed = time.monotonic() - start
    print(
        f"[orchestrator] done in {elapsed:.1f}s  ok={ok_count} fail={fail_count} "
        f"(manifest: {manifest_path})"
    )
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
