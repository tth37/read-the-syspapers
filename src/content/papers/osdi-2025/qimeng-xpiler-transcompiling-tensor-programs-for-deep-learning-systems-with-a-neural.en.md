---
title: "QiMeng-Xpiler: Transcompiling Tensor Programs for Deep Learning Systems with a Neural-Symbolic Approach"
oneline: "QiMeng-Xpiler ports tensor kernels across CUDA, HIP, BANG, and VNNI by combining LLM-generated sketches, SMT repair, and hierarchical pass auto-tuning."
authors:
  - "Shouyang Dong"
  - "Yuanbo Wen"
  - "Jun Bi"
  - "Di Huang"
  - "Jiaming Guo"
  - "Jianxing Xu"
  - "Ruibai Xu"
  - "Xinkai Song"
  - "Yifan Hao"
  - "Ling Li"
  - "Xuehai Zhou"
  - "Tianshi Chen"
  - "Qi Guo"
  - "Yunji Chen"
affiliations:
  - "University of Science and Technology of China"
  - "Cambricon Technologies"
  - "SKL of Processors, Institute of Computing Technology, Chinese Academy of Sciences"
  - "Institute of Software, Chinese Academy of Sciences"
  - "University of Chinese Academy of Sciences"
conference: osdi-2025
tags:
  - compilers
  - ml-systems
  - gpu
  - hardware
category: ml-compilers-and-gpu-kernels
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

QiMeng-Xpiler treats tensor-kernel transcompilation as a sequence of small source-to-source rewrites rather than one giant translation step. LLMs propose program sketches for each pass, localized SMT-based repair fixes the low-level mistakes that survive unit tests, and hierarchical auto-tuning searches for a high-performance pass configuration.

## Problem

The paper starts from a practical compiler gap in heterogeneous deep learning systems. Operators for NVIDIA GPUs, AMD MI accelerators, Cambricon MLUs, and Intel DL Boost CPUs are all written in different low-level languages with different notions of parallelism, memory hierarchy, and special intrinsics. A developer who already has a working CUDA kernel still has to hand-port it to HIP, BANG C, or VNNI intrinsics if they want to support another platform. That cost is high because tensor code is not just arithmetic; it embeds thread binding, scratchpad placement, and architecture-specific instructions.

Existing approaches each fail on a different axis. Rule-based transcompilers such as HIPIFY or PPCG require a large body of expert-written transformation logic and do not generalize well across radically different hardware models. Symbolic-synthesis systems preserve semantics better, but the search space becomes too large on real tensor kernels, especially once parallel semantics and memory placement enter the picture. Pure LLM translation scales better, but the paper shows it is far too unreliable for a transcompiler: for CUDA-to-BANG, GPT-4 zero-shot had a 100% compilation error rate, and even few-shot prompting still suffered 92.3% computation errors.

The stakes are therefore clear. If a system builder wants "write once, run anywhere" for low-level tensor programs, they need something more flexible than handwritten rules and more trustworthy than a single LLM prompt.

## Key Insight

The key claim is that end-to-end transcompilation only becomes tractable if the system separates high-level structural reasoning from low-level semantic repair. QiMeng-Xpiler lets the LLM do what it is relatively good at: producing a plausible program sketch for one narrowly defined transformation pass, using retrieved manual snippets and pass-specific prompts. It then constrains symbolic reasoning to the much smaller problem of repairing the concrete values or intrinsics that remain wrong.

This decomposition matters for both correctness and performance. Because each pass changes only a limited part of the program, unit tests and buffer-level comparisons can localize faults to one code region, and SMT solving can focus on loop bounds, index expressions, or tensor-intrinsic parameters instead of synthesizing an entire kernel from scratch. Separately, performance can be optimized as a search over pass parameters and pass sequences, rather than asking the LLM to guess a globally optimal kernel in one shot.

## Design

QiMeng-Xpiler exposes 11 transformation passes in three groups. Sequentialization and parallelization passes rewrite loop structure and thread bindings through operations such as Loop Recovery, Loop Bind, Loop Split, Loop Fuse, Loop Reorder, Loop Expansion, and Loop Contraction. Memory-conversion passes such as Cache and Pipeline adapt the program to the target hierarchy. Tensorize and Detensorize map scalar code to special intrinsics or recover scalar structure from them. The authors argue these three families are sufficient to span the major portability gaps across the four target DLS.

Each pass follows the same neural-symbolic workflow. First, program annotation adds semantic hints to the source kernel. One LLM pass identifies computation patterns such as matmul, while a BM25 search over the target programming manual retrieves relevant intrinsics, memory-space constraints, or examples, which are then inserted back into the annotated code. Second, a meta-prompt drives LLM transformation. The prompt combines a platform-agnostic description of the desired rewrite, platform-specific examples from the retrieved manual, and optional tuning knobs such as candidate split sizes or loop orders.

Correctness comes from the post-pass repair path. After each transformed program is unit-tested, QiMeng-Xpiler uses binary search over intermediate buffers to locate the first mismatch, maps the bad region back to the transformed AST, and classifies the bug as either an index error or a tensor-instruction error. Index bugs are repaired with SMT constraints over loop bounds and access expressions; tensor-instruction bugs are repaired by extracting the scalar logic and invoking Tenspiler to synthesize an equivalent tensorized fragment. The fixed snippet is then stitched back into the program.

Performance tuning is split hierarchically. Intra-pass auto-tuning enumerates local choices such as block sizes, loop splits, loop orders, or bindings, using brute force when the design space is small enough. Inter-pass auto-tuning models the whole translation as a Markov decision process and uses MCTS to explore pass sequences, with measured execution throughput as the reward and zero reward for any candidate that fails tests. The implementation uses about 35k lines of Python, selects a search depth of 13 with 512 MCTS simulations, and relies on a 38k-line test suite spanning CUDA, HIP, BANG C, and VNNI kernels.

## Evaluation

The evaluation is broad enough to support the paper's main systems claim, though not as a full formal proof of end-to-end equivalence. The authors test four platforms, 21 operators, eight real-model shapes per operator, and 168 benchmark cases in total. The operators span matmul, convolution, activation, pooling, elementwise kernels, and LLM-oriented kernels such as LayerNorm, Self Attention, RMSNorm, and Deformable Attention.

On accuracy, QiMeng-Xpiler is clearly stronger than the baselines. Across directions, it reaches close to 100% compilation accuracy and 86.9% to 100% computation accuracy. On the hardest showcased direction, CUDA C to BANG C, it achieves 100% compilation accuracy and 91.7% computation accuracy, versus 51.8% and 48.2% for OpenAI o1 few-shot. On easier directions such as CUDA C to HIP, it reaches 100% on both metrics and beats HIPIFY's 85.7% compilation and computation accuracy. The ablation is important: removing SMT leaves major gaps, for example only 54.2% computation accuracy on CUDA C to BANG C and 52.4% on HIP to BANG C. That strongly supports the paper's central claim that LLM guidance alone is not enough.

Performance is respectable but not parity with expert kernels. Averaged over four common directions, translated programs deliver 0.78x the performance of vendor-tuned libraries such as cuDNN, cuBLAS, oneDNN, CNNL, and rocBLAS. The FlashAttention case study is even more revealing: QiMeng-Xpiler reaches 0.61x to 0.81x of vendor implementations depending on source and target direction, which suggests the system still misses the deepest hand-optimized pipelining and memory-tiling tricks. Compilation is also expensive, ranging from 1.2 to 7.8 hours with a 3.7-hour average for six representative CUDA-to-BANG operators. The productivity case study is more favorable: on a roughly 200-line Deformable Attention kernel, junior-coder time savings reach 96.0x for CUDA-to-BANG and 34.3x for VNNI-to-CUDA.

## Novelty & Impact

Relative to _Qiu et al. (ECOOP '24)_, QiMeng-Xpiler does not try to make symbolic synthesis the whole compiler; it uses Tenspiler as a narrow repair backend inside a larger transcompilation pipeline. Relative to _Bhatia et al. (ECOOP '23)_, it avoids requiring full semantic specifications of each language and instead leans on retrieved manuals plus pass-local repairs. Relative to _Verdoolaege et al. (TACO '13)_ and vendor migration tools such as HIPIFY, it is not a one-off ruleset for a single source-target pair.

That makes the contribution a new compiler architecture rather than just a better prompt. The likely users are accelerator-compiler teams and ML systems engineers who need to port low-level kernels across vendors, especially when supporting a new accelerator stack is more important than squeezing out the last 20% of performance on day one.

## Limitations

The paper does not actually achieve universal correctness. Its strongest failure mode is complex control flow: kernels such as Deformable Attention contain nested loops and conditionals that defeat both the LLM's ability to emit the right SIMD intrinsics and the SMT solver's ability to infer compact repair constraints. The authors also say that arbitrary special instructions remain difficult for GPT-4 to understand during annotation, which can poison later passes.

There is also a gap between the paper's rhetoric of correctness guarantees and what is validated experimentally. Repair within a pass is symbolically checked, but the reported end-to-end computation accuracy is still defined by unit tests rather than exhaustive equivalence. That is reasonable for a systems paper, but it means users should read the result as "much more trustworthy than direct LLM translation," not "fully verified transcompilation."

Finally, the workflow remains heavy. Compilation can take hours, performance still lags vendor libraries, and porting to a new DLS still needs one-time manual input such as thread-count hints, memory-scope hints, example intrinsics, or a Tenspiler backend extension. The system meaningfully reduces manual effort, but it does not remove hardware expertise from the loop.

## Related Work

- _Qiu et al. (ECOOP '24)_ — Tenspiler synthesizes verified tensor programs inside a common IR, while QiMeng-Xpiler uses it only for localized tensor-intrinsic repair within a larger source-to-source transcompiler.
- _Bhatia et al. (ECOOP '23)_ — MetaLift builds DSL transpilers from semantic specifications, whereas QiMeng-Xpiler targets vendor programming models with LLM-guided passes and SMT repair.
- _Ikarashi et al. (PLDI '22)_ — Exocompilation improves how humans program accelerators, but it does not automatically port legacy tensor kernels across hardware stacks.
- _Bansal et al. (PLDI '23)_ — Mosaic is an interoperable tensor-algebra compiler, while QiMeng-Xpiler focuses on translating existing low-level tensor implementations across heterogeneous DLS languages.

## My Notes

<!-- empty; left for the human reader -->
