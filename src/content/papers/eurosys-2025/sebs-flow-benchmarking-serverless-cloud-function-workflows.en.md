---
title: "SeBS-Flow: Benchmarking Serverless Cloud Function Workflows"
oneline: "SeBS-Flow turns one workflow spec into AWS, GCP, and Azure implementations, exposing how orchestration, data movement, and cold starts shape workflow performance."
authors:
  - "Larissa Schmid"
  - "Marcin Copik"
  - "Alexandru Calotoiu"
  - "Laurin Brandner"
  - "Anne Koziolek"
  - "Torsten Hoefler"
affiliations:
  - "Karlsruhe Institute of Technology, Germany"
  - "ETH Zurich, Switzerland"
conference: eurosys-2025
category: cloud-scheduling-and-serverless
doi_url: "https://doi.org/10.1145/3689031.3717465"
code_url: "https://github.com/spcl/serverless-benchmarks"
project_url: "https://github.com/spcl/sebs-flow-artifact"
tags:
  - serverless
  - datacenter
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

SeBS-Flow is a benchmarking framework for serverless workflows, not just single functions. Its core move is a portable workflow model, based on workflow nets plus explicit data-movement annotations, that can be transpiled into AWS Step Functions, Google Cloud Workflows, and Azure Durable Functions. Using six application benchmarks and four microbenchmarks, the paper shows that orchestration dominates outcomes: AWS is often fastest end-to-end, Azure often has the shortest compute critical path but the largest orchestration overhead, and Google Cloud is steadier than Azure but usually slower on the critical path.

## Problem

Serverless functions are easy to benchmark in isolation, but real applications increasingly use workflows: chains of functions, fan-out/fan-in stages, loops, and conditional branches. That is where cloud lock-in gets worse. AWS and Google expose state-machine languages, Azure uses a code-level orchestrator model, their parallelism limits differ, and they bill orchestration differently. A workflow that is natural on one platform can be awkward on another, and the same application can hide different costs in orchestration, data passing, or cold starts.

That makes prior evaluation weak as a baseline. The authors review 72 workflow papers and find no common foundation: different applications, different workload classes, and different platform subsets. Existing suites such as SeBS benchmark single-function FaaS rather than workflow orchestrators. Without a portable model, it is hard to tell whether a measured difference comes from the cloud platform or from the author's platform-specific rewrite.

## Key Insight

The key insight is that fair workflow benchmarking requires abstracting away provider syntax without abstracting away the performance-relevant semantics. SeBS-Flow therefore models workflows as phases of serverless-function transitions plus coordinator transitions, and it annotates how data moves between phases: object storage, NoSQL, invocation payload, provider-transparent return, or reference passing.

That split is enough to generate comparable implementations across providers while still preserving the mechanisms that affect runtime and cost. The benchmark does not try to hide cloud differences; it isolates them.

## Design

The model extends workflow nets in two ways. Transitions are split into serverless functions and coordinators, so the workflow explicitly represents orchestration boundaries, and reads and writes carry resource annotations, so the workflow specifies not just dependencies but where data lives and how it is transferred. On top of that, the language offers six phase types: `task`, `map`, `loop`, `repeat`, `switch`, and `parallel`.

The platform backends expose where managed workflow services differ. AWS lacks a native sequential loop over arrays, so SeBS-Flow emulates `loop` with a sequential `map`. Google Cloud Workflows lacks a true task primitive, so each task becomes an HTTP POST plus extra states to unpack results, and even a one-function parallel body must be wrapped as a sub-workflow. Azure takes the opposite route: SeBS-Flow uploads the abstract definition and a user orchestrator parses it at runtime and spawns Durable Functions activities.

The benchmark suite is built on SeBS and adds object storage management, a cross-cloud NoSQL abstraction, and Redis-based timestamp collection. The six applications are Video Analysis, Trip Booking, MapReduce, ExCamera, an ML training pipeline, and 1000Genomes, plus four microbenchmarks for function chains, storage I/O, parallel scheduling, and OS noise.

## Evaluation

The authors first test expressiveness, then transcription overhead, then cloud behavior. In the literature review, 53 of 58 sufficiently detailed workflows can be fully modeled and transcribed; two rely on programming models outside SeBS-Flow's scope, and three hit current transcription limits. The Azure orchestrator's own parsing cost is negligible: on 1000Genomes, it averages 13.6 ms while the workflow's median runtime is 3757.55 s.

The cloud comparison uses the same high-level workflow definitions on AWS, Google Cloud, and Azure, the lowest common memory setting that still succeeds, burst submissions of 30 concurrent workflow invocations, and 180 total executions for most workloads. The results support the paper's thesis that orchestration effects dominate. Azure often has the shortest critical path, but its orchestration overhead can explode: for ExCamera, the average overhead is 495.5 s on top of a 13.5 s critical path, over 36x the useful work. Microbenchmarks tie that to storage I/O and poor parallel scheduling; a parallel-download test shows Azure adding almost 149 s of overhead for 128 MB downloads while AWS stays around one second. Cold starts are the other big factor: AWS sees 73.58%-100% cold-start rates across the application suite, Google Cloud 38.24%-99.26%, and Azure only 0.6%-7.72%. Once the authors isolate warm runs, AWS critical paths improve by up to 4.5x and Google Cloud by up to 2.0x. 1000Genomes still takes 259.8 s on AWS and 457.7 s on Google Cloud, versus 7.7 s on the Ault HPC system.

## Novelty & Impact

The novelty is not a new serverless runtime or workflow engine. The contribution is a reproducible benchmarking method for workflows: a portable control-flow and data-flow model, automatic transcription to provider-specific workflow services, and a workload suite that spans web, data, ML, media, and scientific workflows. That gives researchers a common baseline instead of ad hoc demos and gives practitioners a concrete way to reason about which managed workflow service is actually a good fit.

## Limitations

The workload suite has only six real applications, the platform study covers only three managed workflow services in one region each, and the paper notes that day-to-day and region-to-region variation could matter. Portability is also only near-equivalence: AWS loops are emulated with `map`, Google Cloud tasks are wrapped as HTTP calls and sub-workflows, and Azure relies on a custom interpreter-like orchestrator. Finally, the model does not target workflows with direct function-to-function communication or load-balanced orchestration based on dynamic system state, so SeBS-Flow is best read as a benchmark for mainstream managed workflow services rather than for every orchestration design.

## Related Work

- _Copik et al. (Middleware '21)_ - SeBS benchmarks single FaaS functions, while SeBS-Flow extends that infrastructure to workflow orchestration, shared data services, and cross-cloud workflow comparison.
- _García López et al. (UCC Companion '18)_ - This study compares FaaS orchestration systems with microbenchmarks, whereas SeBS-Flow adds portable workflow definitions and a larger application-level benchmark suite.
- _Wen and Liu (ICWS '21)_ - Their measurement study analyzes serverless workflow services with two applications and microbenchmarks; SeBS-Flow contributes a reusable open benchmark suite and a transcription layer that lets one workflow spec run on multiple providers.
- _Kulkarni et al. (CCGrid '24)_ - XFBench also benchmarks cross-cloud FaaS workflows, but SeBS-Flow focuses on provider-native workflow services, cloud-native data movement, and direct cost/scalability analysis.

## My Notes

<!-- empty; left for the human reader -->
