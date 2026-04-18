#!/usr/bin/env python3
"""Validate a paper summary pair against the harness's hard rules.

Runs the cheap checks a human reviewer would do on every sub-agent output:
frontmatter parity across languages, required section headings, `written_by`
format, `oneline` length, tag vocabulary, bilingual presence. Exit 0 means
"looks good," non-zero means "stop and fix before fanning out more work."

The Zod schema in `src/content/config.ts` is the authoritative check — but it
only runs at `npm run build` time. This script catches 90% of the mistakes a
sub-agent makes, instantly, without spinning up the Astro build.

Usage:
  ./scripts/validate_paper.py <slug>                    # one paper pair
  ./scripts/validate_paper.py --conference fast-2026    # every paper in a conference
  ./scripts/validate_paper.py --all                     # every paper in the repo
  ./scripts/validate_paper.py --expected-agent "gpt-5.4 (codex)" ...
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys
from dataclasses import dataclass
from typing import Optional


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PAPERS_ROOT = REPO_ROOT / "src" / "content" / "papers"
TAG_VOCAB_PATH = REPO_ROOT / "prompts" / "tag-vocabulary.md"

REQUIRED_H2_EN = [
    "## TL;DR",
    "## Problem",
    "## Key Insight",
    "## Design",
    "## Evaluation",
    "## Novelty & Impact",
    "## Limitations",
    "## Related Work",
    "## My Notes",
]
REQUIRED_H2_ZH = [
    "## TL;DR",
    "## 问题背景",
    "## 核心洞察",
    "## 设计",
    "## 实验评估",
    "## 创新性与影响",
    "## 局限性",
    "## 相关工作",
    "## 我的笔记",
]


@dataclass
class Problem:
    file: str
    msg: str


def _split_frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    fm_text, body = m.group(1), m.group(2)
    fm: dict = {}
    # Minimal YAML subset — fields we actually check.
    current_key: Optional[str] = None
    list_accum: list[str] = []
    for line in fm_text.splitlines():
        if re.match(r"^[a-z_]+:", line) and not line.startswith(" "):
            if current_key and list_accum:
                fm[current_key] = list_accum
                list_accum = []
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if not value:
                current_key = key
                continue
            # Strip surrounding quotes
            if value.startswith(('"', "'")) and value.endswith(value[0]):
                value = value[1:-1]
            fm[key] = value
            current_key = None
        elif line.lstrip().startswith("- "):
            item = line.lstrip()[2:].strip()
            if item.startswith(('"', "'")) and item.endswith(item[0]):
                item = item[1:-1]
            list_accum.append(item)
    if current_key and list_accum:
        fm[current_key] = list_accum
    return fm, body


def _load_tag_vocabulary() -> set[str]:
    if not TAG_VOCAB_PATH.exists():
        return set()
    text = TAG_VOCAB_PATH.read_text()
    # Tags are marked as `- \`tag-name\`` in the vocabulary file.
    return set(re.findall(r"^-\s+`([a-z0-9][a-z0-9-]*)`", text, re.MULTILINE))


def _collect_h2(body: str) -> list[str]:
    return [line.strip() for line in body.splitlines() if line.startswith("## ")]


def check_paper_pair(
    slug: str,
    conference: str,
    expected_agent: Optional[str] = None,
    tag_vocabulary: Optional[set[str]] = None,
) -> list[Problem]:
    """Return a list of Problems for the paper pair. Empty list = clean."""
    en_path = PAPERS_ROOT / conference / f"{slug}.en.md"
    zh_path = PAPERS_ROOT / conference / f"{slug}.zh-cn.md"
    problems: list[Problem] = []

    for p in (en_path, zh_path):
        if not p.exists():
            problems.append(Problem(str(p.relative_to(REPO_ROOT)), "missing file"))
    if problems:
        return problems

    en_fm, en_body = _split_frontmatter(en_path.read_text())
    zh_fm, zh_body = _split_frontmatter(zh_path.read_text())

    # Cross-language frontmatter parity.
    for shared in ("title", "conference", "category", "written_by", "star",
                   "reading_status"):
        if shared in en_fm and shared in zh_fm and en_fm[shared] != zh_fm[shared]:
            problems.append(Problem(
                f"{slug}",
                f"{shared} differs between .en.md and .zh-cn.md: "
                f"{en_fm[shared]!r} vs {zh_fm[shared]!r}",
            ))
    # authors / affiliations / tags: list equality
    for shared_list in ("authors", "affiliations", "tags"):
        if en_fm.get(shared_list) != zh_fm.get(shared_list):
            problems.append(Problem(
                f"{slug}",
                f"{shared_list} list differs between language files",
            ))

    # conference slug matches
    if en_fm.get("conference") != conference:
        problems.append(Problem(
            str(en_path.relative_to(REPO_ROOT)),
            f"frontmatter conference={en_fm.get('conference')!r} does not match "
            f"directory ({conference!r})",
        ))

    # written_by — must be model-qualified and (if expected given) match verbatim
    for lang, fm, path in [("en", en_fm, en_path), ("zh", zh_fm, zh_path)]:
        wb = fm.get("written_by", "")
        if not wb:
            problems.append(Problem(str(path.relative_to(REPO_ROOT)), "written_by missing"))
            continue
        # Either "human" (bare) or "<model> (<agent-cli>)".
        if wb != "human" and not re.match(r"^\S.+ \(\S.+\)$", wb):
            problems.append(Problem(
                str(path.relative_to(REPO_ROOT)),
                f"written_by {wb!r} not in '<model> (<agent>)' form",
            ))
        if expected_agent and wb != expected_agent:
            problems.append(Problem(
                str(path.relative_to(REPO_ROOT)),
                f"written_by {wb!r} != expected {expected_agent!r}",
            ))

    # oneline length (schema says ≤ 400, but the soft guidance is ≤ 180)
    for lang, fm, path in [("en", en_fm, en_path), ("zh", zh_fm, zh_path)]:
        oneline = fm.get("oneline", "")
        if not oneline:
            problems.append(Problem(str(path.relative_to(REPO_ROOT)), "oneline missing"))
        elif len(oneline) > 400:
            problems.append(Problem(
                str(path.relative_to(REPO_ROOT)),
                f"oneline is {len(oneline)} chars (schema limit 400)",
            ))

    # tags — must all be in vocabulary, if we loaded one
    if tag_vocabulary:
        tags = en_fm.get("tags", [])
        if isinstance(tags, list):
            unknown = [t for t in tags if t not in tag_vocabulary]
            if unknown:
                problems.append(Problem(
                    f"{slug}",
                    f"tags not in vocabulary: {unknown}",
                ))

    # Required H2 sections, in order
    for required, body, path in [
        (REQUIRED_H2_EN, en_body, en_path),
        (REQUIRED_H2_ZH, zh_body, zh_path),
    ]:
        found = _collect_h2(body)
        for heading in required:
            if heading not in found:
                problems.append(Problem(
                    str(path.relative_to(REPO_ROOT)),
                    f"missing required heading: {heading!r}",
                ))

    return problems


def iter_slugs(conference: Optional[str], all_conf: bool) -> list[tuple[str, str]]:
    """Yield (conference, slug) pairs."""
    results: list[tuple[str, str]] = []
    if all_conf:
        conferences = [p.name for p in PAPERS_ROOT.iterdir() if p.is_dir()]
    elif conference:
        conferences = [conference]
    else:
        return []
    for conf in conferences:
        conf_dir = PAPERS_ROOT / conf
        if not conf_dir.is_dir():
            continue
        slugs = set()
        for p in conf_dir.glob("*.md"):
            name = p.name
            if name.endswith(".en.md"):
                slugs.add(name[: -len(".en.md")])
            elif name.endswith(".zh-cn.md"):
                slugs.add(name[: -len(".zh-cn.md")])
        for s in sorted(slugs):
            results.append((conf, s))
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug", nargs="?", help="Paper slug (requires --conference).")
    ap.add_argument("--conference", help="Conference slug (e.g. fast-2026).")
    ap.add_argument("--all", action="store_true", help="Validate every paper in the repo.")
    ap.add_argument("--expected-agent", help="Exact written_by string to require.")
    ap.add_argument("--no-tag-check", action="store_true", help="Skip tag-vocabulary check.")
    args = ap.parse_args()

    tag_vocab = None if args.no_tag_check else _load_tag_vocabulary()

    if args.slug:
        if not args.conference:
            print("ERROR: --conference required when slug is given", file=sys.stderr)
            return 2
        pairs = [(args.conference, args.slug)]
    else:
        pairs = iter_slugs(args.conference, args.all)

    if not pairs:
        print("nothing to validate (pass a slug, --conference, or --all)", file=sys.stderr)
        return 2

    total_problems = 0
    clean_count = 0
    for conf, slug in pairs:
        problems = check_paper_pair(
            slug=slug, conference=conf,
            expected_agent=args.expected_agent,
            tag_vocabulary=tag_vocab,
        )
        if not problems:
            clean_count += 1
            continue
        total_problems += len(problems)
        print(f"\n{conf}/{slug}:")
        for pr in problems:
            print(f"  - [{pr.file}] {pr.msg}")

    print(
        f"\n[validate] {clean_count}/{len(pairs)} pairs clean, "
        f"{total_problems} problems total"
    )
    return 0 if total_problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
