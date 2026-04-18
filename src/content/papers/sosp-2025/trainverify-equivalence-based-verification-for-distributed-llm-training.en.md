---
title: "TrainVerify: Equivalence-Based Verification for Distributed LLM Training"
oneline: "TrainVerify proves a distributed LLM training plan matches the logical model, using staged symbolic verification and shape reduction to scale to frontier models."
authors:
  - "Yunchi Lu"
  - "Youshan Miao"
  - "Cheng Tan"
  - "Peng Huang"
  - "Yi Zhu"
  - "Xian Zhang"
  - "Fan Yang"
affiliations:
  - "University of Michigan"
  - "Microsoft Research Asia"
  - "Northeastern University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764850"
code_url: "https://github.com/verify-llm/TrainVerify"
tags:
  - llm-training
  - verification
  - formal-methods
category: llm-training-infra
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

TrainVerify verifies the distributed training plan rather than the entire training stack. It proves that the parallel execution graph is equivalent to the logical model and uses staged solving plus shape reduction to scale to Llama3 405B and DeepSeek-V3 671B.

## Problem

Distributed LLM training is now expensive enough that a silent parallelization bug can waste weeks of GPU time. The authors survey MegatronLM, DeepSpeed, and nnScaler and find recurring bugs in tensor partitioning, communication groups, operator transformation, gradient scaling, and pipeline scheduling.

Testing is a weak defense here. Floating-point reordering, mixed precision, and kernel diversity make differential testing noisy, full single-device ground truth is infeasible for frontier models, and smaller-scale tests can miss bugs that appear only at production parallelism. Verifying the entire stack would be even harder because compilers, kernels, collective runtimes, and vendor code are all in the loop. The paper therefore narrows the target to one concrete question: does the generated execution plan preserve the logical model's semantics?

## Key Insight

TrainVerify defines parallelization equivalence: for every valid input, the parallelized data-flow graph must produce outputs equivalent to the logical graph. Execution plans are the right verification boundary because they already encode sharding, communication, and schedule decisions, yet are still structured enough for symbolic reasoning. The second insight is that most deep-learning operators are regular SIMD-style computations, so tensor sizes can often be shrunk to representative minima without invalidating the proof.

## Design

TrainVerify takes a logical model and a distributed plan, converts both to data-flow graphs, and then symbolically executes them over symbolic reals rather than concrete FP16/BF16 values. The graphs are completed to include backward pass, optimizer logic, and metrics such as gradient norm, because those are common sites of distributed-training bugs.

The bridge between the two graphs is lineage metadata. For each logical tensor, TrainVerify records how the distributed plan slices, replicates, or aggregates the corresponding tensors. That lets it formulate obligations such as "these shards concatenate to the logical tensor" or "these replicas sum to the logical value"; missing communication, wrong communication groups, or inconsistent slicing break those obligations.

To scale, TrainVerify uses staged verification. It partitions the logical and parallel graphs into aligned stages via lineage-aware backward slicing, proves local input-output equivalence for each stage, and then composes the verified stage boundaries into an end-to-end proof. It also uses shape reduction: each tensor dimension is shrunk to the smallest size that still satisfies operator semantics and cross-tensor shape constraints. The implementation is about 6,000 lines of Python on top of nnScaler, uses Z3 as the solver, and manually adapts about 40 operators for symbolic execution.

## Evaluation

TrainVerify verifies plans for Llama3 8B/70B/405B and DeepSeek-V3 16B/236B/671B, with the largest configurations reaching 8192 GPUs for Llama3 and 2048 GPUs for DeepSeek-V3. Verification runs on a 32-core Xeon Platinum 8473C machine with 1.34 TB of memory.

The main numbers support the paper's scalability claim. Llama3-8B verifies in 0.2 hours and DeepSeek-V3-16B in 0.4 hours; the largest plans, Llama3-405B and DeepSeek-V3-671B, finish in 8.0 and 9.0 hours respectively. Because of shape reduction, cost stays mostly insensitive to original batch size, hidden size, sequence length, and attention heads, and disabling stage-parallel solving makes a small Llama3-8B case about 5x slower. For correctness coverage, the authors reproduce 14 non-trivial bug cases derived from MegatronLM, DeepSpeed, and nnScaler; TrainVerify catches all of them within one minute. The weak point is that there is no direct verifier baseline, so the evaluation argues mostly through scale and fault detection rather than comparative efficiency.

## Novelty & Impact

The novelty is choosing execution-plan equivalence as the proof target and then making it tractable with lineage-aware graph alignment, staged solving, and shape reduction. Prior neural-network equivalence systems mostly validate local graph rewrites or small models; TrainVerify applies the same formal impulse to full distributed training plans. That gives framework builders a practical verification boundary: if a system can expose SSA-style graphs and lineage, it can potentially prove plans correct before spending weeks of cluster time.

## Limitations

TrainVerify assumes the logical model is the specification, so it does not prove the original model code itself is correct. It also does not verify CUDA kernels, NCCL, memory-layout constraints, or floating-point behavior on real hardware; symbolic reals intentionally abstract away numerical drift. On the systems side, the prototype works best with graph-based frameworks that preserve lineage, requires manual operator and shape-reduction rules when new operators appear, and currently supports only a limited optimizer space centered on ZeRO Stage 1.

## Related Work

- _Lin et al. (OSDI '24)_ - nnScaler generates distributed training plans efficiently, while TrainVerify adds a proof layer that checks whether those generated plans preserve the logical model's semantics.
- _Jia et al. (SOSP '19)_ - TASO verifies local graph substitutions for neural-network optimization, whereas TrainVerify verifies end-to-end equivalence of full distributed training plans.
- _Arora et al. (POPL '25)_ - TensorRight also verifies tensor-graph rewrites, but it targets rewrite correctness rather than multi-device training plans with communication and scheduling structure.
- _Jiang et al. (OSDI '25)_ - Training with Confidence adds runtime checks for silent training errors, while TrainVerify offers offline symbolic guarantees for parallelization logic before or alongside long runs.

## My Notes

<!-- empty; left for the human reader -->
