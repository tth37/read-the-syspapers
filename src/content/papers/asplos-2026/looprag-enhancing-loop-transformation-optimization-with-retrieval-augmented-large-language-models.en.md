---
title: "LOOPRAG: Enhancing Loop Transformation Optimization with Retrieval-Augmented Large Language Models"
oneline: "Retrieves loop-property-matched compiler examples and uses compilation, testing, and ranking feedback to steer LLMs toward faster legal loop transformations."
authors:
  - "Yijie Zhi"
  - "Yayu Cao"
  - "Jianhua Dai"
  - "Xiaoyang Han"
  - "Jingwen Pu"
  - "Qinran Wu"
  - "Sheng Cheng"
  - "Ming Cai"
affiliations:
  - "Zhejiang University, Hangzhou, Zhejiang, China"
  - "Zhejiang Institute of Administration, Hangzhou, Zhejiang, China"
  - "Beijing ShenZhou Aerospace Software Technology Ltd., Beijing, Beijing, China"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790183"
code_url: "https://github.com/Git-zyj/LOOPRAG/tree/ASPLOS26Summer"
tags:
  - compilers
  - pl-systems
  - formal-methods
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

LOOPRAG treats loop optimization as a retrieval-and-feedback problem rather than asking an LLM to invent profitable transformations from scratch. It synthesizes a large corpus of legal SCoPs, retrieves demonstrations using loop-aware features such as schedules and array indexes, and iteratively regenerates code using compilation, equivalence-testing, and performance-ranking feedback. On CPU loop benchmarks, that recipe beats base LLMs by large margins and often beats mainstream compilers, though PLuTo still remains stronger on PolyBench.

## Problem

The paper starts from a clear mismatch between what loop transformation demands and what current LLMs provide. Good loop optimization depends on dependence analysis, legality constraints, and some sense of which composition of tiling, interchange, fusion, skewing, shifting, or parallelization is actually profitable for the target loop nest. Base LLMs can read code, but they do not have built-in cost models or legality machinery comparable to a compiler. The authors' motivating experiment with GPT-4 versus PLuTo makes that concrete: GPT-4 frequently misses profitable loop transformations and often emits code that is not semantically equivalent to the original.

Simply saying "add demonstrations" is not enough. The paper argues that if demonstrations are going to teach an LLM transformation patterns, then the system needs three things that prior work does not provide together. First, it needs a large supply of diverse, legal loop examples and optimized counterparts; existing loop datasets and generators are too narrow in the loop properties they cover, so they cannot expose rich transformation compositions. Second, it needs retrieval based on loop semantics rather than just text similarity, because tiny changes in array indexes or schedules can completely change what transformation is appropriate. Third, it needs a pragmatic correctness filter, since semantic equivalence for transformed programs is undecidable in general and formal methods do not scale cleanly to the generated programs the authors target. The real systems problem is therefore not merely "use an LLM for loop optimization," but "build enough compiler-like structure around the LLM that it can search the space without constantly breaking correctness or settling for weak optimizations."

## Key Insight

The central claim is that LLMs become useful loop optimizers once they are forced to learn from the right exemplars and the right feedback. LOOPRAG's demonstrations are not retrieved by surface syntax alone; they are selected using loop properties that are closely tied to transformation choice, especially loop schedules and array indexes. That lets the prompt show the model examples that are similar enough to transfer profitable transformations, but still diverse enough to avoid overfitting to one brittle pattern.

Just as importantly, the paper treats generation as an iterative search guided by compiler-style signals. Compilation errors, failed equivalence tests, and performance rankings are all fed back into later rounds. The paper's deeper point is that LLMs do not need to internalize a full polyhedral compiler if the surrounding system can externalize three things for them: a structured source of transformation knowledge, a legality filter, and a ranking signal for better versus merely valid outputs.

## Design

LOOPRAG has three parts: dataset synthesis, retrieval, and feedback-based iterative generation. The dataset synthesis stage is the foundation. Instead of randomly assigning loop properties and hoping they remain legal, the authors introduce a parameter-driven method that uses ten parameters to configure eleven loop properties while enforcing constraints through decoupling, priority-based assignment, and contradiction checking. That matters because many properties are interdependent: dependence patterns constrain writes, array indexes constrain loop bounds, and circular dependences must be excluded. The system synthesizes complete C programs around the SCoPs, then uses Clan and CAnDL to extract data-flow information and a modified PLuTo 0.11.4 to generate optimized counterparts. In the implementation, this produces `135,364` example codes.

The retrieval stage then scores target and example SCoPs with a loop-aware LAScore. BM25 provides a base text-similarity term, but the distinctive part is the weighted feature score over loop schedules and array indexes. The retriever gives reward for overlapping features and penalty for extra features in the example that might teach an inappropriate transformation. It also penalizes statement-count mismatch. In effect, LOOPRAG is trying to balance similarity and diversity: retrieve examples that are structurally close enough to be relevant, but not so redundant that they narrow the transformation search space unnecessarily. The system retrieves ten examples and randomly picks three optimized pairs as demonstrations.

The generation stage runs a four-step loop. Step 1 prompts the base LLM with the retrieved examples and compiles the resulting programs. Step 2 regenerates failed outputs using compiler error messages, then tests passing codes and ranks their performance. Step 3 feeds testing outcomes and performance rankings back to the LLM so it can learn both what broke correctness and what improved speed. Step 4 repeats the compile-test-rank cycle and chooses the fastest surviving result. Correctness checking is empirical but fairly serious: GPT-4 is used to synthesize seed-input initializers, then LOOPRAG applies value-, operator-, and statement-based mutations, drives branch coverage with `gcov`, and performs checksum plus element-wise differential testing. The paper reports cutting the average number of tests from more than `500` to about `25` per program via coverage guidance.

## Evaluation

The evaluation targets CPU loop optimization, not GPUs or mixed-language code. Experiments run on a dual-EPYC Linux server and use DeepSeek-V3 and GPT-4o (`gpt-4o-2024-08-06`) as base LLMs. The benchmark set is reasonably broad within the paper's scope: `30` PolyBench kernels, `84` TSVC kernels, and `49` LORE kernels that satisfy the SCoP assumptions. The main raw result is that LOOPRAG with DeepSeek reaches average speedups of `23.97x`, `32.66x`, and `20.44x` over the original code on PolyBench, TSVC, and LORE, respectively, with pass@k of `70.00`, `94.05`, and `86.71`. Those are much higher than the base LLM baselines, which sit around `1.61x` on PolyBench and `1.60x-1.72x` on LORE, and only `4.91x-6.75x` on TSVC. Framed as improvement over base LLMs, the paper reports up to `11.97x`, `5.61x`, and `11.59x`.

Against compilers, the story is stronger than I expected but also more uneven than the abstract alone suggests. LOOPRAG clearly beats Graphite and ICX, with reported average improvements of `19.47x` over Graphite on PolyBench and `17.14x` on LORE, plus `18.18x`, `27.97x`, and `12.67x` over ICX across the three suites. Perspective also loses badly. Polly is the more serious baseline: LOOPRAG is roughly comparable on PolyBench and TSVC, and much better on LORE, but it is not a clean sweep. The comparison to PLuTo is even more revealing. LOOPRAG loses on PolyBench, where PLuTo still reaches `43.29x` average speedup versus LOOPRAG's `23.97x` or `14.58x`, but wins on TSVC and LORE, improving over PLuTo by `5.44x` and `4.38x` respectively. That supports the paper's main claim in a nuanced way: LOOPRAG is not universally better than the compiler it learns from, but it can surpass that compiler once the problem leaves PLuTo's sweet spot.

The ablations are valuable rather than perfunctory. Replacing the synthesized dataset with COLA-Gen weakens both pass@k and speedup; the paper reports average speedup improvements of `3.81x`, `1.68x`, and `1.22x` for LOOPRAG's dataset construction over COLA-Gen across the three suites. The loop-aware retriever beats plain BM25 on PolyBench and LORE and beats a weighted-score-only variant on PolyBench and TSVC, which is consistent with the "similarity plus diversity" thesis. Finally, feedback matters materially: compilation feedback alone raises pass@k by over `21%` on PolyBench, and testing-plus-ranking feedback yields roughly `43-44%` more faster codes across the suites. Overall, the evaluation supports the paper's central claim well within the SCoP/CPU regime.

## Novelty & Impact

Relative to _Bondhugula et al. (PLDI '08)_, LOOPRAG does not replace a polyhedral optimizer with a language model; it wraps compiler-generated examples in retrieval and iterative search so the LLM can sometimes go beyond fixed compiler heuristics. Relative to _Berezov et al. (PARMA-DITAM '22)_, its novelty is not merely generating loop benchmarks, but synthesizing a property-diverse demonstration bank specifically designed to teach richer transformation compositions. Relative to _Gao et al. (ICSE '25)_, LOOPRAG is less about generic search over LLM outputs and more about specializing the search space with loop-aware retrieval and compiler-style feedback. The paper's likely impact is therefore on LLM-assisted compiler tooling and autotuning, especially for scenarios where human-written heuristics are incomplete but full formal optimization remains too rigid.

## Limitations

The authors are fairly candid about the system's boundaries. LOOPRAG only handles C SCoPs, so loops with pointers, non-affine expressions, or side-effecting function calls are out of scope. The framework explicitly guides only six loop transformations; other profitable rewrites still depend on the base model's own knowledge. Correctness is checked by testing rather than proof, which is practical but cannot guarantee semantic preservation. The full optimization loop is also expensive, because each candidate is compiled, tested, and timed.

The paper also shows a more subtle weakness: the synthesized dataset still misses some important computation patterns. Their `jacobi-2d` case study is the clearest example. LOOPRAG only achieves `0.58x` there because the demonstration bank does not adequately capture stencil-style wavefront parallelism, so the system settles for tiling instead of loop skewing. Even with temperature set to zero, output variance remains visible across repeated runs and across underlying models. So the contribution here is a strong scaffold for LLM-based loop optimization, not a complete or stable replacement for compilers.

## Related Work

- _Bondhugula et al. (PLDI '08)_ — PLuTo is the polyhedral optimizer LOOPRAG mines for demonstrations, but LOOPRAG adds retrieval and iterative feedback so the final search is not limited to one compiler's fixed strategy.
- _Berezov et al. (PARMA-DITAM '22)_ — COLA-Gen generates parametric loop benchmarks, whereas LOOPRAG broadens the legal property combinations specifically to expose more transformation compositions.
- _Apostolakis et al. (ASPLOS '20)_ — Perspective attacks automatic loop parallelization inside a compiler, while LOOPRAG uses an outer retrieval-and-feedback loop around an LLM to synthesize transformed source.
- _Gao et al. (ICSE '25)_ — Search-Based LLMs for Code Optimization also iteratively refines model outputs, but LOOPRAG specializes that idea to SCoP loop optimization with retrieved compiler demonstrations and equivalence-testing feedback.

## My Notes

<!-- empty; left for the human reader -->
