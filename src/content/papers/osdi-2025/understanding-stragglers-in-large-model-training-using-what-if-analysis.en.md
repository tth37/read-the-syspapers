---
title: "Understanding Stragglers in Large Model Training Using What-if Analysis"
oneline: "The paper turns hybrid-parallel LLM training traces into a what-if simulator that quantifies how much stragglers cost and which root causes matter most."
authors:
  - "Jinkun Lin"
  - "Ziheng Jiang"
  - "Zuquan Song"
  - "Sida Zhao"
  - "Menghan Yu"
  - "Zhanghan Wang"
  - "Chenyuan Wang"
  - "Zuocheng Shi"
  - "Xiang Shi"
  - "Wei Jia"
  - "Zherui Liu"
  - "Shuguang Wang"
  - "Haibin Lin"
  - "Xin Liu"
  - "Aurojit Panda"
  - "Jinyang Li"
affiliations:
  - "New York University"
  - "ByteDance Seed"
  - "ByteDance"
  - "Zhejiang University"
conference: osdi-2025
code_url: "https://github.com/ByteDance-Seed/StragglerAnalysis"
tags:
  - llm-training
  - observability
  - datacenter
  - gpu
category: llm-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

The paper asks a basic but operationally important question: in real multi-thousand-GPU LLM training, how much do stragglers actually hurt, and why? Its answer is a trace-driven what-if simulator that replays hybrid-parallel training with idealized operation durations. On 3,079 ByteDance training jobs, the authors find that stragglers are common, mostly computation-driven, and usually caused by persistent imbalance rather than one-off machine failures.

## Problem

Large-model training is much less forgiving than MapReduce-style data processing because every training step contains repeated synchronization across data-parallel, pipeline-parallel, tensor-parallel, and sometimes context-parallel groups. A slow worker in any one of those groups can bubble up and stall the rest of the job. Existing straggler mitigation ideas, such as backup workers or asynchronous updates, fit poorly here: backup workers are too expensive for tightly synchronized training, while asynchronous SGD or dropped updates change optimization behavior and are not standard practice for frontier-model training.

The harder issue is measurement. In a real hybrid-parallel job, thousands of operations overlap across streams and ranks, so the effect of one slow operation cannot be read off from a simple critical path. The paper therefore frames the problem as a counterfactual: what would the same job have looked like if comparable operations had run at non-straggling speed? That requires reconstructing dependencies inside Megatron-LM-style execution and separating intrinsic communication time from time spent waiting for peers to launch.

## Key Insight

The paper’s key claim is that straggler analysis for LLM training should be done as what-if simulation over traced operation structure, not as ad hoc log inspection or single-path profiling. In a hybrid-parallel training step, many operations are equivalent up to rank, microbatch, and step position. If those equivalent operations are normalized to their non-straggling durations and then replayed under the job’s dependency graph, the difference between real and simulated job completion time becomes a defensible estimate of straggler cost.

That framing matters because it lets the authors attribute slowdown at multiple levels: whole-job slowdown, per-operation-type slowdown, and per-worker slowdown. It also reveals whether the dominant pattern is “a few broken workers” or “the system is structurally imbalanced almost every step.” Much of the paper’s value comes from showing that the second pattern is far more common in their production traces.

## Design

The system is built around NDTimeline traces collected from ByteDance’s LLM training cluster between January and May 2024. The paper keeps only pretraining jobs using at least 128 GPUs, yielding 3,079 analyzed jobs; 31.7% use at least 256 GPUs, 18.3% use at least 512 GPUs, and 3.6% use at least 5,000 GPUs. NDTimeline samples 10% of training steps and records coarse-grained forward compute, backward compute, pipeline send/receive, parameter sync, and gradient sync operations, together with step, microbatch, pipeline rank, and data-parallel rank metadata.

The simulator organizes each operation type into an `OpDuration` tensor indexed by step, microbatch, PP rank, and DP rank. For compute operations, the traced duration is used directly. For communication, the paper separates transfer duration from blocking duration: only the transfer portion is kept as the intrinsic cost because waiting for peers is a scheduling consequence rather than a property of the collective itself. Idealized durations are then estimated by equalizing comparable operations, using the average for compute and the median for communication. The average for compute is meant to model rebalanced work; the median for communication avoids letting a few pathological network events skew the counterfactual.

The second part is the dependency model. Each worker has several streams: one for compute, one for DP communication, and four for PP send/receive directions. Operations on the same stream serialize. Compute depends on the relevant receives and parameter synchronization; sends depend on preceding compute; collectives and P2P transfers cannot make progress until all peers have launched. The simulator launches each operation as soon as dependencies finish and then computes completion time from its idealized duration. That same machinery is reused to ask narrower questions such as “what if all workers except this one were fixed?” or “what if only the last pipeline stage were fixed?”

## Evaluation

The headline result is that stragglers are not edge cases. Using slowdown ratio `S > 1.1` as the threshold, 42.5% of jobs straggle. Across all traces, stragglers waste 10.4% of allocated GPU-hours; more than 10% of jobs waste at least 21.3% of their GPU-hours, and about 1% waste at least 45.0%. Within a straggling job, slowdowns are also steady rather than spiky: the median step slowdown normalized by job slowdown is 1.0, and even the 90th percentile step is only 1.06, which argues against “one bad step” explanations.

Attribution is the more interesting part. Computation dominates communication as the source of wasted resources, which the authors tie to their dedicated, well-tuned cluster and lack of network congestion. Worker-specific faults explain most of the slowdown for only 1.7% of straggling jobs, though those jobs are severe when they happen. By contrast, last-stage pipeline imbalance is widespread: for 39.3% of jobs, fixing the last pipeline stage would recover a majority of the slowdown. Sequence-length imbalance is also common in long-context training; using forward/backward correlation as a proxy, the paper estimates that 21.4% of jobs are affected, with average slowdown 1.34. A prototype sequence-redistribution scheme improves throughput by 23.9% on a representative 32K-context job, and manual retuning of an imbalanced pipeline example yields 9.9% speedup. For Python GC, manually synchronized “planned GC” improves a 128-DP-rank job by 12.6%.

The simulator itself looks credible. Simulation discrepancy has 1.3% median and 5.5% 90th-percentile error, and injected slowdowns of 1.16, 1.40, and 2.03 are estimated as 1.21, 1.42, and 1.98.

## Novelty & Impact

Relative to _Ousterhout et al. (NSDI '15)_, the paper carries what-if analysis from Spark-style data analytics into the much more tangled dependency structure of hybrid-parallel LLM training. Relative to _Ananthanarayanan et al. (OSDI '10)_, it shows that the classical “bad machine” view of stragglers misses the main failure modes in modern training clusters. Relative to _Jiang et al. (NSDI '24)_, which describes operating 10,000+ GPU training infrastructure, this paper isolates stragglers as a first-class systems problem and attaches numbers to them.

The practical impact is also stronger than a one-off measurement study because the authors deploy part of the pipeline as SMon, an online monitoring service that turns worker slowdowns into heatmaps and helps the on-call team localize failures. That makes the contribution partly methodological and partly operational: it gives people running large training clusters a way to turn “the job is slow” into a concrete diagnosis.

## Limitations

The analysis is only as good as the traces. NDTimeline is coarse-grained, so the method cannot reliably isolate stragglers that occur entirely within TP or CP groups when every affected microbatch already looks uniformly slow at the granularity the trace records. The paper also admits that CPU-side work such as data loading is omitted, which is the main reason simulation can diverge from reality.

There is also a significant coverage caveat. To preserve fidelity, the authors discard many traces: repeatedly failing jobs, traces whose command lines could not be parsed to recover parallelism degrees, jobs with too few analyzable steps, corrupt traces, and traces whose simulation discrepancy exceeds 5%. After filtering, the study covers 38.2% of jobs but 56.4% of GPU-hours. Finally, the strongest empirical claims come from a dedicated, well-provisioned cluster, so the result that computation dominates communication should not be read as universal across shared or congestion-prone environments.

## Related Work

- _Ananthanarayanan et al. (OSDI '10)_ — Mantri studies stragglers in MapReduce and motivates why classic redundancy-based mitigation does not transfer cleanly to tightly synchronized LLM training.
- _Ousterhout et al. (NSDI '15)_ — The paper borrows the spirit of what-if analysis from Spark diagnosis, but extends it to mixed DP/PP/TP execution with collectives and pipeline bubbles.
- _Narayanan et al. (SC '21)_ — Megatron-LM provides the hybrid-parallel execution model whose streams, microbatches, and synchronization structure this paper explicitly simulates.
- _Jiang et al. (NSDI '24)_ — MegaScale documents large-scale LLM training infrastructure, while this paper zooms in on straggler prevalence, attribution, and operational debugging in that setting.

## My Notes

<!-- empty; left for the human reader -->
