---
title: "QoServe: Breaking the Silos of LLM Inference Serving"
oneline: "Co-schedules mixed-SLO LLM requests on shared GPUs using slack-aware chunk sizing, hybrid deadline/length priority, and eager relegation."
authors:
  - "Kanishk Goel"
  - "Jayashree Mohan"
  - "Nipun Kwatra"
  - "Ravi Shreyas Anupindi"
  - "Ramachandran Ramjee"
affiliations:
  - "Microsoft Research, Bengaluru, India"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790206"
tags:
  - llm-inference
  - scheduling
  - datacenter
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

QoServe asks a simple production question: if LLM applications already have different latency targets, why do we still isolate them into separate "interactive" and "batch" clusters? Its answer is a shared serving stack that treats deadline slack as a schedulable resource, grows or shrinks prefill chunk sizes online, blends deadline-first and short-job-first priorities, and proactively relegates requests that are already doomed. The result is higher GPU utilization without turning overload into system-wide collapse.

## Problem

The paper starts from a real deployment pattern that is easy to recognize: interactive jobs get their own replicas because they need small prefill chunks to keep `TTFT` and `TBT` low, while relaxed jobs get separate replicas with large chunks to maximize throughput. That separation is operationally simple, but it strands capacity whenever demand shifts across classes. It also does not scale to finer-grained QoS tiers; every new latency target pushes operators toward another isolated deployment.

Naively merging those workloads does not work either. Fixed small chunks satisfy the strictest class but waste throughput for everyone else. `FCFS` suffers head-of-line blocking. `EDF` respects deadlines when the system is lightly loaded, but once the queue grows it cascades into near-universal misses. `SJF` or `SRPF` keep the median healthy by sacrificing long prompts, which is not acceptable when request length and business importance are unrelated. The core systems problem is therefore not just "schedule LLM requests well," but "co-schedule requests with different latency contracts on one cluster while degrading gracefully under overload."

## Key Insight

The paper's central claim is that chunked-prefill LLM serving exposes enough structure to make QoS-aware co-scheduling practical. In particular, the prefill phase is predictable enough that the system can estimate how much extra work fits before the next decode deadlines arrive. That deadline slack can be spent on larger prefill chunks, temporarily raising throughput for relaxed jobs without violating the tighter jobs already in decode.

This only works if chunk selection and job selection reinforce each other. QoServe therefore couples slack-aware dynamic chunking with a hybrid priority rule that interpolates between `EDF` and `SRPF`: at low load it behaves more like a deadline scheduler, and under overload it increasingly accounts for remaining work. Once a request has already missed, or is about to miss, its deadline, the system stops pretending it can still be saved and moves it into a relegated queue. That prevents a few doomed requests from poisoning latency for everyone else.

## Design

QoServe organizes requests into three queues: prefill, decode, and relegated. Each scheduling iteration forms a mixed batch containing all currently decoding requests plus a prefill chunk chosen from the prefill queue. Interactive requests carry `TTFT` and `TBT` SLOs; non-interactive requests carry a `TTLT` SLO. The scheduler computes deadlines from those SLOs and uses them as the backbone of admission and prioritization.

The first mechanism is hybrid prioritization. For interactive jobs, priority is based on arrival time plus the `TTFT` deadline and a tunable `alpha` times remaining prefill work; for non-interactive jobs, the same structure adds estimated remaining decode work. This gives QoServe a continuous knob between deadline awareness and short-job bias instead of forcing a brittle switch between `EDF` and `SRPF`. The paper reports using `alpha = 8 ms/token` for fixed-load runs and lower values at light load.

The second mechanism is dynamic chunking. Rather than fixing chunk size to the minimum required by the strictest tier, QoServe estimates the available decode slack in the current batch and asks a lightweight predictor for the largest safe prefill budget. That predictor is a random forest trained from latency profiles collected with Vidur for a particular model, hardware target, and parallelism configuration. The system deliberately under-predicts slightly so it does not accidentally overshoot latency budgets.

The third mechanism is overload management. QoServe allows selective preemption only for requests still in prefill and only when a one-iteration delay will not itself trigger a miss; decode-phase requests are never preempted because `TBT` budgets are too tight. If a request has already violated, or will violate, its target in the current iteration, QoServe eagerly relegates it. Application hints such as free-tier versus premium requests determine which jobs get relegated first.

Implementation-wise, the system is not a new inference runtime from scratch. It extends Sarathi's scheduler on top of vLLM, preserving tensor parallelism and PagedAttention while replacing the scheduling logic and request API.

## Evaluation

The evaluation is reasonably broad for a serving paper. The authors test three model setups: Llama3-8B on `A100-80GB (TP1)`, Qwen-7B on `A100-80GB (TP2)`, and Llama3-70B on `H100-80GB (TP4)`, using ShareGPT plus Azure conversation and code traces. Their default workload splits requests evenly across three QoS buckets: one interactive tier with `6s TTFT` and `50ms TBT`, plus two non-interactive tiers with `600s` and `1800s TTLT`.

At cluster scale, a 35 QPS Azure-Code workload that needs 13 GPUs in the siloed Sarathi deployment can be served by 10 mixed-workload replicas under QoServe while keeping p99 latency within the target tiers, a 23% reduction in GPU count. When the siloed deployment is forced down to the same 10 GPUs, deadline violations jump to `60.4%`. On single shared replicas, QoServe delivers `1.5x-2.4x` higher goodput than Sarathi-FCFS and `20-40%` higher goodput than Sarathi-EDF across models and traces. The dynamic chunking study is especially clear: by exploiting slack, QoServe uses chunk sizes up to about `2500` instead of the default `256`, which the authors associate with roughly `2x` throughput at that operating point and a `20%` end-to-end throughput gain.

Under overload, the qualitative story is as important as the absolute numbers. QoServe sustains zero deadline violations up to `30%` higher load than Sarathi-EDF and handles up to `40%` higher load while keeping tail-latency SLOs intact. In a transient diurnal-load experiment, it misses deadlines for no important requests and only `8.75%` of requests overall; the baselines collapse much earlier. This supports the paper's main claim well: the design does not merely raise peak throughput, it changes the failure mode from global queue meltdown to selective, policy-driven degradation.

I found the evaluation convincing for single-model serving on a shared cluster, but narrower for other regimes. The disaggregated evaluation improves prefill-node goodput, yet explicitly leaves decode-side multi-`TBT` support to future work. Also, the interactive bucket uses a `6s TTFT` target, so the results speak more directly to preserving stream smoothness than to ultra-low-latency chatbot scenarios. That is an inference from the chosen SLOs, not a claim the paper makes explicitly.

## Novelty & Impact

Relative to _Agrawal et al. (OSDI '24)_, QoServe's novelty is not chunked prefills themselves, but turning deadline slack into a first-class scheduling signal and coupling that with a hybrid policy plus eager relegation. Relative to PolyServe-style deployment separation, its key move is refusing to bin QoS classes into isolated fleets, which lets it reclaim stranded capacity when demand mixes shift. Relative to SLOs-Serve, the authors argue for a much simpler scheduling surface: priority-queue selection rather than repeated dynamic programming over all active requests.

That makes the paper most likely to matter to practitioners building cloud inference backends and to researchers working on multi-tenant LLM serving. It is less a new kernel trick than a production-ready scheduler design for the "many applications, one model fleet" era.

## Limitations

QoServe depends on offline profiling and predictor training for each model, hardware platform, and parallelism configuration, so portability is not free. Its handling of non-interactive jobs also relies on a simple history-based estimate of decode length, which may drift if application behavior changes abruptly. The disaggregated results only cover the prefill side; the paper explicitly leaves decode-side support for heterogeneous `TBT` targets as future work. More broadly, the implementation and experiments focus on one model family at a time inside the vLLM/Sarathi stack, so the paper does not address multi-model routing, autoscaling, or admission control across fleets.

## Related Work

- _Agrawal et al. (OSDI '24)_ — Sarathi-Serve establishes chunked-prefill serving, but QoServe adds multi-QoS co-scheduling, slack-aware chunk selection, and overload relegation on top of that base.
- _Kwon et al. (SOSP '23)_ — PagedAttention makes continuous LLM serving practical by fixing KV-cache memory management; QoServe assumes that substrate and focuses on scheduling policy rather than memory layout.
- _Agrawal et al. (MLSys '24)_ — Vidur provides the profiling and simulation harness QoServe uses to train its chunk-size predictor, so QoServe builds on that measurement infrastructure instead of replacing it.

## My Notes

<!-- empty; left for the human reader -->
