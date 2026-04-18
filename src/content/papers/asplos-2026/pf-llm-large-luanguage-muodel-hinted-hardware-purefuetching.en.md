---
title: "PF-LLM: Large Language Model Hinted Hardware Prefetching"
oneline: "Uses a fine-tuned code LLM to assign each load instruction an offline prefetch policy, then feeds 8-bit hints to a lightweight runtime ensemble."
authors:
  - "Ceyu Xu"
  - "Xiangfeng Sun"
  - "Weihang Li"
  - "Chen Bai"
  - "Bangyan Wang"
  - "Mengming Li"
  - "Zhiyao Xie"
  - "Yuan Xie"
affiliations:
  - "The Hong Kong University of Science and Technology, Hong Kong, Hong Kong"
  - "Duke University, Durham, USA"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790202"
tags:
  - hardware
  - memory
  - caching
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

PF-LLM argues that the best hardware prefetching policy for a load is often visible in its static assembly neighborhood, not only in the dynamic address stream. The paper fine-tunes a small code LLM to emit per-load hints selecting a sub-prefetcher, an aggressiveness level, and sometimes a filter rule, then lets a lightweight runtime ensemble consume those hints from a prefetch hint table. On memory-intensive SPEC 2017 benchmarks, this combination reaches `95.0%` policy-prediction accuracy and improves IPC by `9.8%` over the best single prefetcher and `18.9%` over the best prior ensemble.

## Problem

The paper starts from the classic memory-wall argument: modern cores can still lose hundreds of cycles to a DRAM access, so hiding latency with prefetching remains central to single-thread performance. The difficulty is that no single prefetcher handles all phases of real programs well. Some phases look like simple streams, some like strides, some like spatial correlations, and some like more irregular patterns. Prior work therefore keeps building prefetcher ensembles, but that only moves the hard problem up a level: now the machine has to decide, quickly and cheaply, which specialist should react to each demand access and how aggressively it should prefetch.

Online orchestration is an awkward fit for that job. Reinforcement-learning or bandit-style selectors need trial-and-error time to converge, which makes them slow to adapt when the program shifts phases. They are also constrained by on-chip latency and area budgets, so they cannot inspect much wider program context. The authors additionally argue that these online policies interact badly with sophisticated sub-prefetchers such as spatial designs: if the wrong demand requests are routed to them, their internal state gets polluted and performance can drop below that of a good single prefetcher.

The obvious offline alternatives also have holes. Compiler heuristics need hand-designed rules and often source-level structure. Profile-guided approaches need representative inputs and recompilation. Software prefetching injects instructions into the frontend and still lacks fine-grained runtime visibility. The paper’s real target, then, is broader than “pick a prefetcher”: it wants an offline method that can read static binaries, reason about longer code context than hardware can afford, and hand the runtime just enough information to avoid costly online learning.

## Key Insight

The central claim is that a load instruction’s surrounding code often contains enough semantic structure to predict a good prefetching policy before the program ever runs. Humans can already do this informally when they look at code and notice, for example, lock acquisition, array-of-struct traversal, field-wise spatial access, or string streaming. PF-LLM tries to automate that judgment by giving a fine-tuned LLM a wide assembly window around one target load and asking it to infer which prefetching specialist should handle that load.

What makes the idea interesting is not only “use an LLM on code,” but “use the LLM to define a narrow interface between offline reasoning and online microarchitecture.” PF-LLM does not directly insert prefetch instructions. Instead, it emits hints that steer a conventional ensemble at runtime. That means the hardware still reacts to live demand streams, but it starts from a much better policy prior. In effect, the paper moves the expensive “which prefetcher, how aggressive, and should this access even train that prefetcher?” decisions out of the core and into an offline analysis pass where latency is irrelevant.

## Design

PF-LLM is built by fine-tuning `Qwen-2.5-Coder-0.5B-Instruct` on assembly contexts extracted from binaries. For each target load, the model sees `128` assembly lines before and `128` after the load, with `<load>` and `</load>` markers identifying the focal instruction. Its output is a JSON object with up to three fields: a prefetcher-selection hint, an optional degree hint, and an optional demand-request filtering hint. The authors choose assembly, rather than source or IR, because static binaries are broadly available and because assembly is closer to the runtime behavior the hardware actually sees.

The training labels come from simulation, not manual annotation. The authors implement a large candidate set of sub-prefetchers in ChampSim, run every benchmark under all relevant prefetcher-and-degree combinations, and record per-load AMAT outcomes keyed by program counter. For each PC, the configuration with the minimum AMAT becomes the “best policy.” A second heuristic picks a harmful prefetcher to filter out when doing so appears useful, except for several advanced components whose state is too brittle to tolerate such filtering. This produces a dataset that teaches the model both what to choose and what to avoid.

At runtime, the trained model disassembles an unseen binary, finds every load, infers one hint tuple per load, and stores the results in a main-memory `Prefetch Hint Table (PHT)` indexed by virtual PC. The online hardware side, called `LMHint Prefetcher`, adds a `256`-entry on-chip `Prefetch Hint Buffer (PHB)` that caches recent hint entries much like a TLB caches page-table entries. Each hint is compressed into `8` bits: `4` for prefetcher selection, `2` for degree, and `2` for the filtering policy. On a PHB hit, the selected sub-prefetcher is allowed to react to the load, the tri-state degree is mapped into that prefetcher’s native aggressiveness range, and the filter hint can suppress training traffic into a sub-prefetcher whose state would otherwise be polluted. On a PHB miss, the system falls back briefly to a reserved default policy while fetching the real hint from the PHT.

## Evaluation

The evaluation is entirely simulation-based but fairly disciplined. The hardware setup mimics an Arm Neoverse N2-like core in ChampSim, while the instruction set under study is `x86-64` and the optimization target is `L1D` prefetching in a single-core setting. PF-LLM is trained on SPEC 2006 memory-intensive programs and tested only on memory-intensive SPEC 2017 programs, which avoids direct train-test leakage. The model is fine-tuned for two epochs on `8` NVIDIA `H20` GPUs using BF16, an effective batch size of `64`, and labels computed from simulator runs.

The first headline result is predictive quality. PF-LLM reaches `95.0%` accuracy on held-out policy prediction. Just as important, the authors report that mistakes are usually not random: the model often picks the second-best policy rather than a clearly bad one. That matters because the end goal is performance, not exact label matching. The confusion-matrix analysis therefore supports the paper’s main premise that assembly context is rich enough to recover useful prefetch semantics.

The end-to-end numbers are strong for the target regime. The full `LMHint-SDF` design improves IPC by `9.8%` over the best single prefetcher, `Sandbox`, and by `18.9%` over the best prior ensemble, `Alecto`, on memory-intensive SPEC 2017 benchmarks. The ablation study is also informative: selection hints carry most of the gain, but degree hints add another `0.3%` average IPC and filtering adds a further `0.3%`. A reduced-cost version with only the four most frequently selected sub-prefetchers slightly outperforms the full design by `0.01%` on average, suggesting the hardware can shrink substantially without retraining the model.

The paper also checks realism from two angles. On Apache, MySQL, RocksDB, and Xapian, LMHint still beats the baselines, though the gains are smaller because those services are more I/O-bound and already heavily tuned. On overhead, the offline pass looks manageable rather than trivial: PF-LLM inference reaches up to `234.3` requests per second on one `H20`, and generating hints for the entire SPEC 2017 suite takes `38.5` minutes on the authors’ `8`-GPU system, versus `25.4` minutes to compile the suite on a `16`-core machine. Runtime storage overhead is `7` bytes per load, which the authors translate to `74.34 KB` per MB of executable code, or a `7.26%` static footprint increase. For the paper’s single-core setting, that overhead seems reasonable relative to a roughly `10-20%` IPC gain, though the evidence is still bounded by simulator-generated labels and a narrow hardware regime.

## Novelty & Impact

Relative to _Bera et al. (MICRO '21)_, PF-LLM is not another smarter online prefetcher like Pythia; it is a split design that lets offline code understanding steer a runtime ensemble. Relative to _Gerogiannis and Torrellas (MICRO '23)_ and _Li et al. (HPCA '25)_, the key difference is eliminating convergence-time exploration and protecting sophisticated sub-prefetchers from harmful training traffic. Relative to compiler prefetching and _Zhang et al. (ASPLOS '24)_, the paper does not inject software prefetches or rely on input-specific runtime profiles; it uses static binary analysis to produce a compact hint table instead.

That makes the paper notable less as an LLM paper than as a new microarchitectural control surface. If the interface is sound, architects could imagine similar offline hints for branch prediction, cache insertion, or other dynamic policies. The broader impact is the suggestion that foundation models can sit outside the critical path and still materially improve hardware decisions.

## Limitations

The authors are candid about several limits. The current prototype is `x86-64`, single-core, and focused on `L1D` prefetching, so it does not show what happens under multicore interference, shared-cache contention, or tighter hardware integration constraints. The model is trained for one machine configuration, and the paper explicitly says retraining or configuration-aware prompting would be needed for different ISAs, cache sizes, or bandwidth regimes. It also does not natively support JIT-generated code or bytecode systems such as Java.

Two other caveats matter from a reviewer’s perspective. First, the “ground truth” is simulator-derived best AMAT per PC, which is a practical label-generation scheme but not a proof that the chosen policy is globally optimal on real hardware. Second, the prototype does not directly handle `ASLR`; the paper proposes compensating in the OS loader, but that is future integration work, not part of the evaluated system. I would add that the web-serving evaluation is helpful but still small, and the evidence for reduced-cost hardware comes from the same benchmarking environment rather than a separate implementation study.

## Related Work

- _Ayers et al. (ASPLOS '20)_ — Classifies memory access patterns for prefetching with learned techniques, while PF-LLM replaces task-specific classifiers with a general code model over longer assembly context.
- _Bera et al. (MICRO '21)_ — Pythia adapts online with reinforcement learning inside the prefetcher; PF-LLM shifts the policy search offline and uses hints to steer an ensemble at runtime.
- _Gerogiannis and Torrellas (MICRO '23)_ — Micro-Armed Bandit learns ensemble orchestration online, whereas PF-LLM avoids warm-up and exploration costs by predicting per-load policies before execution.
- _Zhang et al. (ASPLOS '24)_ — RPG2 uses profile-guided runtime prefetch generation, while PF-LLM aims for binary-level applicability without input-specific profiling.

## My Notes

<!-- empty; left for the human reader -->
