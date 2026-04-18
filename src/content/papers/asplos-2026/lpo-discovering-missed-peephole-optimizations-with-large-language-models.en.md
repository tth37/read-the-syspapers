---
title: "LPO: Discovering Missed Peephole Optimizations with Large Language Models"
oneline: "Finds missed LLVM peephole optimizations by letting an LLM propose rewrites for extracted IR snippets and using `opt`, `llvm-mca`, and Alive2 to filter and repair them."
authors:
  - "Zhenyang Xu"
  - "Hongxu Xu"
  - "Yongqiang Tian"
  - "Xintong Zhou"
  - "Chengnian Sun"
affiliations:
  - "Cheriton School of Computer Science, University of Waterloo, Waterloo, Canada"
  - "Department of Software Systems & Cybersecurity, Monash University, Melbourne, Australia"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790184"
code_url: "https://github.com/uw-pluverse/lpo-artifact"
tags:
  - compilers
  - pl-systems
  - formal-methods
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

LPO turns missed peephole optimization discovery into a closed loop: extract LLVM IR slices, ask an LLM for a rewrite, and use `opt`, `llvm-mca`, and Alive2 to filter the result. That workflow finds more missed optimizations than Souper or Minotaur, including many confirmed or fixed upstream.

## Problem

LLVM's peephole optimizer is an evolving collection of local rewrite rules, so coverage is never complete. Manual inspection still finds missed cases, but it is slow and expertise-heavy. Differential testing is useful, yet it mostly exposes patterns that another compiler or equivalent program already happens to reveal. Superoptimizers can search for genuinely new rewrites, but their cost grows quickly and their instruction support is often narrow.

That gap matters because modern LLVM misses frequently involve vectors, memory operations, floating point, or intrinsics, exactly where synthesis-only tools weaken. The paper's problem is therefore: how do you search a broad IR space for new local rewrites without trusting an unreliable generator?

## Key Insight

The paper's main claim is that LLMs and formal validation complement each other unusually well here. LLMs are broad and creative enough to propose rewrites over messy LLVM IR, but they hallucinate. Alive2 and LLVM's own tools can validate or reject a candidate precisely, but they cannot invent one.

LPO therefore treats the LLM as a proposal engine, not as an optimizer to be trusted. Error messages from `opt`, canonicalization results, and counterexamples from Alive2 are fed back into the next prompt, so wrong answers become additional search attempts instead of silent correctness bugs.

## Design

LPO has three pieces: an extractor, an LLM optimizer, and a verifier. The extractor walks each basic block backward and enumerates dependent instruction sequences. Each sequence is wrapped into a standalone LLVM function by turning missing operands into parameters and returning the final value. LPO then drops any wrapped sequence that `opt -O3` can already optimize in isolation and hashes the rest to remove duplicates across the corpus.

For each surviving sequence, the LLM proposes a replacement function. LPO first runs `opt` on that candidate. This catches syntax errors and also canonicalizes or further simplifies the proposed code. It then applies an interestingness filter: keep the candidate if it reduces instruction count, reduces `llvm-mca` total cycles for a chosen target/CPU pair, or at least changes syntax in a way that may enable later optimization. The paper is clear that this is only a triage heuristic.

If the candidate still looks worthwhile, Alive2 checks that the original function is refined by the new one. When the proof fails, LPO feeds the counterexample back to the LLM and retries, with an attempt limit of `2`. The important invariant is simple: the LLM may suggest anything, but only candidates that survive LLVM's own tools and Alive2 are kept.

## Evaluation

The evaluation first tests recall on `25` previously reported LLVM missed-optimization issues created after August 2024 to reduce training-data leakage. LPO's success depends heavily on model quality: Gemma3 finds only up to `3/25` cases, while Gemini2.0T reaches `21/25` and `o4-mini` reaches `18/25`. Souper finds `15/25` in total even with enumerative synthesis enabled, and Minotaur finds `3/25`. The paper's explanation is convincing: LPO wins mainly on coverage and flexibility, not on proof strength.

The more important result is the long-running search over optimized IR from fifteen real projects. After deduplication, LPO searched about `800,000` unique instruction sequences and reported `62` missed peephole optimizations to LLVM. Of those, `28` were confirmed and `13` were already fixed. Several fixed patterns show up widely in real code, sometimes across thousands of IR files.

The practical impact is real but modest in the way mature compiler work often is. On `5,000` sampled cases, Gemini2.5 via API averages `6.7` seconds per case at about `$5.4` total cost, while local Llama3.3 averages `26.2` seconds. Accepted patches have negligible compile-time cost, but most SPEC CPU2017 runtime changes stay within `2%`. So the paper supports a "continuous maintenance tool" story more than a "single patch yields dramatic speedups" story.

## Novelty & Impact

LPO's novelty is not a stronger verifier or superoptimizer. It is the workflow: use an LLM to explore a wider rewrite space, then recover trust through `opt`, cost screening, and Alive2. That makes the paper valuable mainly to compiler maintainers. It suggests a practical way to keep mining the long tail of missed local optimizations in a mature compiler without pretending the LLM itself is reliable.

## Limitations

LPO inherits the limits of the tools around it. Unsupported IR or verifier failures cap what it can cover; the paper even reports an Alive2 bug. Its interestingness filter is heuristic and target-specific because `llvm-mca` is run on one chosen CPU model. Human work also remains substantial after discovery, since maintainers still need to generalize a pattern and implement it in LLVM. Finally, the accepted patches rarely shift SPEC CPU2017 by more than noise level, so discovery success should not be confused with large end-to-end speedups.

## Related Work

- _Bansal and Aiken (ASPLOS '06)_ — automatic peephole superoptimization searches for optimal rewrites directly, whereas LPO outsources candidate generation to an LLM and uses verification to recover soundness.
- _Lopes et al. (PLDI '21)_ — Alive2 provides the translation-validation backbone that makes LPO's feedback loop safe enough to use for real LLVM rewrites.
- _Liu et al. (OOPSLA '24)_ — Minotaur extends LLVM superoptimization toward SIMD integer and floating-point code, but LPO aims for broader pattern coverage by avoiding synthesis-only search.
- _Theodoridis et al. (ASPLOS '22)_ — differential testing can expose missed optimizations through semantic discrepancies, while LPO tries to invent new profitable rewrites directly from IR snippets.

## My Notes

<!-- empty; left for the human reader -->
