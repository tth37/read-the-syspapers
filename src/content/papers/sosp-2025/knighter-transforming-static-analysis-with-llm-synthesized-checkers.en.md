---
title: "KNighter: Transforming Static Analysis with LLM-Synthesized Checkers"
oneline: "KNighter turns bug-fix patches into Clang Static Analyzer checkers, then refines them with LLM triage to find Linux kernel bugs that expert-written analyzers miss."
authors:
  - "Chenyuan Yang"
  - "Zijie Zhao"
  - "Zichen Xie"
  - "Haoyu Li"
  - "Lingming Zhang"
affiliations:
  - "University of Illinois Urbana-Champaign"
  - "Zhejiang University"
  - "Shanghai Jiao Tong University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764827"
tags:
  - security
  - kernel
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

KNighter does not ask an LLM to scan the Linux kernel directly. Instead, it asks the model to read a bug-fix patch, synthesize a Clang Static Analyzer checker for the underlying pattern, validate that checker against the buggy and fixed versions, and then refine it with LLM-assisted bug triage. On 61 kernel patches, this produces 39 valid checkers and ultimately 92 new kernel bugs, including 30 CVEs.

## Problem

Static analysis in large systems faces a split. Hand-written analyzers scale to huge codebases, but each checker captures a narrow piece of expert knowledge, so coverage expands only as fast as humans can encode new rules. LLMs offer the opposite strength: they can read historical fixes and infer new patterns, but they cannot cheaply or reliably scan 30M+ lines of Linux because of context limits, cost, and hallucinations.

For kernel engineering, this gap matters because many bugs live in drivers and error paths that testing or fuzzing rarely exercises. The missing capability is a way to learn new bug families from history without giving up conventional static analysis’s whole-codebase reach.

## Key Insight

The key move is to use the LLM once, at checker-synthesis time, rather than on every code scan. A patch commit already pairs buggy code, the repair, and often a natural-language explanation, so it can supervise checker generation. KNighter turns that signal into a standard static-analysis checker, then grounds it by compiling the checker and verifying that it fires on pre-patch code but not on post-patch code.

This patch-grounded validation, followed by false-positive-driven refinement, is what converts the LLM from an advisory assistant into a producer of reusable analysis artifacts.

## Design

KNighter targets the Clang Static Analyzer and splits work into synthesis and refinement. In synthesis, a pattern-analysis agent reads the diff, commit message, and full modified function to infer a specific pattern, such as unchecked `devm_kzalloc` return values before dereference rather than a vague rule about nullable returns. A plan-synthesis agent then decides which callbacks, program-state maps, and helper utilities the checker should use.

An implementation agent fills a CSA checker template, and a repair agent fixes compiler errors when the model chooses the wrong APIs or types. The checker is then validated on buggy and patched objects; it is valid only if the buggy version produces more warnings and the patched version stays below a threshold. Valid checkers scan the full kernel, KNighter distills sampled reports, a triage agent judges whether they match the target pattern, and false positives trigger checker refinement plus revalidation. A checker is considered plausible if it produces fewer than 20 total reports or if at most one sampled warning is judged false positive.

## Evaluation

The main evaluation uses 61 Linux bug-fix commits spanning 10 bug categories. KNighter produces 39 valid checkers. These are nontrivial analyses: 37 are path-sensitive, 13 use region sensitivity, and 16 maintain richer checker state. The full synthesis run takes about 15.9 hours total and costs roughly $0.24 per commit with the default model, while successful commits need 2.4 synthesis attempts on average.

Refinement is important. Of the 39 valid checkers, 26 are already plausible after the first whole-kernel scan, and 11 of the remaining 13 become plausible after refinement, yielding 37 plausible checkers overall. Among the 90 reports that triage escalates as likely bugs, manual review confirms 61 true positives, a 32.2% false-positive rate in that filtered set. Most importantly, KNighter-generated checkers find 92 new Linux kernel bugs, 77 confirmed, 57 fixed, and 30 assigned CVEs; Smatch finds none of KNighter’s true positives.

## Novelty & Impact

The novelty is not simply "add an LLM to static analysis." Prior patch-mining work usually infers specifications for an existing analyzer, and LLM-augmented analyzers still rely on a large hand-built core. KNighter instead synthesizes executable checker logic, validates it against the source patch, and improves it in a closed loop.

That reframes LLMs as offline producers of reusable analysis assets rather than online scanners of huge systems.

## Limitations

KNighter is far from universal. It fails on 22 of 61 commits, mostly because synthesized checkers cannot semantically distinguish buggy from patched code even when they compile. The hardest cases are use-after-free, concurrency, and buffer reasoning that require deeper temporal or value-flow analysis.

Even successful checkers can overgeneralize trigger conditions, and the method depends on two strong prerequisites: informative bug-fix history and an existing static-analysis framework to target.

## Related Work

- _Lin et al. (USENIX Security '23)_ - APHP also learns from patches, but it infers API post-handling specifications for a separate checker pipeline rather than synthesizing the checker logic itself.
- _Chen et al. (EuroSys '25)_ - Seal mines security patches to infer Linux interface specifications, whereas KNighter targets a broader mix of bug patterns and emits executable CSA analyzers.
- _Li et al. (USENIX Security '24)_ - LR-Miner is a hand-designed, path-sensitive OS bug detector; KNighter automates that checker-construction step from historical fixes.
- _Li et al. (OOPSLA '24)_ - LLift uses LLMs to augment an existing static analyzer, while KNighter uses the model once to generate a reusable analyzer that can later scan at CPU cost.

## My Notes

<!-- empty; left for the human reader -->
