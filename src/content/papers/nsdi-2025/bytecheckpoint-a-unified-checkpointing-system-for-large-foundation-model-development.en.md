---
title: "ByteCheckpoint: A Unified Checkpointing System for Large Foundation Model Development"
oneline: "ByteCheckpoint separates tensor metadata from bytes so checkpoints can be resharded at load time across frameworks and backends, cutting LFM checkpoint stalls to sub-second."
authors:
  - "Borui Wan"
  - "Mingji Han"
  - "Yiyao Sheng"
  - "Yanghua Peng"
  - "Haibin Lin"
  - "Mofan Zhang"
  - "Zhichao Lai"
  - "Menghan Yu"
  - "Junda Zhang"
  - "Zuquan Song"
  - "Xin Liu"
  - "Chuan Wu"
affiliations:
  - "The University of Hong Kong"
  - "ByteDance"
conference: nsdi-2025
tags:
  - llm-training
  - fault-tolerance
  - storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

ByteCheckpoint treats distributed checkpoints as metadata-indexed byte ranges rather than artifacts bound to one TP/DP/PP layout. That lets it save once, then reload into different parallelism configurations across pre-training, post-training, and evaluation, while a common planner/engine/storage stack hides framework and backend differences. On the authors' production workloads, it reduces runtime checkpoint stalls by 12.13x-161.50x and keeps stall time below one second even for very large runs.

## Problem

The paper starts from a very practical observation: in large foundation model development, checkpointing is not only for crash recovery. Checkpoints must also move between pre-training and post-training, feed automatic evaluation jobs, and adapt to changing GPU allocations when faulty machines are removed or quotas fluctuate. Those scenarios almost always require checkpoint resharding, because the new job rarely uses the same parallelism layout as the old one. On the authors' platform, six months of traces show 1,870 resharding events for training resumption, 13,080 for cross-stage transitions, and 19,844 for evaluation.

The default industrial solution is ugly. Teams maintain offline resharding scripts tied to particular frameworks, model components, optimizer layouts, and parallelism combinations. The appendix says their largest script reached 3,193 lines of Python. Those scripts are also slow: the paper reports average offline resharding-job completion times of 1,870.38 seconds for resumption, 650.34 seconds for cross-stage transition, and 593.21 seconds for evaluation. Worse, the resulting checkpoints are still tied to one target layout, so they increase storage overhead rather than solving the format problem.

Even without resharding, checkpoint I/O is already expensive at LFM scale. The authors report that saving checkpoints for a GPT 175B model trained on 4,096 GPUs to HDFS can take about 200 seconds end to end. Asynchronous checkpointing helps hide part of that cost, but long save and load paths still hurt effective training time and delay evaluation. Existing systems either assume fixed parallelism, or support only narrow framework/back-end combinations, or fail to scale cleanly to production-sized jobs.

## Key Insight

The core insight is that checkpoint resharding becomes manageable once the stored representation is decoupled from the runtime layout that produced it. Instead of naming files by rank and assuming the loader already knows how those files map onto a new training job, ByteCheckpoint records tensor identity and location explicitly: what global tensor a shard belongs to, where that shard sits in the original tensor, and where its bytes live inside storage files. Loading into a new parallelism is then a metadata matching problem, not a pile of custom conversion scripts.

That abstraction only works if it extends beyond model weights. ByteCheckpoint therefore also separates dataloader state into replicated pieces and sharded pieces, so changing TP or PP can copy state, while changing DP can split or merge token buffers without retraining or skipping data. Once both tensor state and dataloader state are described this way, a framework-specific planner can generate unified plans and a backend-specific engine can execute them with the same overall workflow.

## Design

ByteCheckpoint has four layers: a small API, framework-specific planners, an execution engine, and storage-I/O wrappers. The API is intentionally minimal: users hand in model, optimizer, dataloader, and extra state dictionaries, then call `bytecheckpoint.save()` or `bytecheckpoint.load()`. Planners for Megatron-LM, FSDP, DDP, and veScale translate framework-native sharding metadata into ByteCheckpoint's internal format. The engine executes save or load plans, while the storage layer hides whether the target is memory, local disk, HDFS, or NAS.

The checkpoint format is centered on one global metadata file plus per-rank storage files. For tensors, each saved shard carries three kinds of metadata. `BasicMeta` stores runtime properties such as stride and device. `ShardMeta` identifies the shard by fully qualified name plus n-dimensional offsets and lengths within the original global tensor. `ByteMeta` records which file contains the bytes and at what offset. Together, these maps let a new job look up exactly which byte ranges it needs, regardless of the old parallelism layout. Dataloader state is stored separately: replicated parts are written once, while per-worker state such as token buffers and read offsets is written in split form so it can later be copied, merged, or split.

The paper spends real effort on one nasty corner case: irregular optimizer tensors from ZeRO-style sharding. After flattening and concatenation, a shard may no longer correspond to a clean n-dimensional slice of the original tensor. In the FSDP path used with DCP, those shards are avoided by synchronously all-gathering optimizer pieces and interleaving that with D2H copies before saving. ByteCheckpoint instead decomposes one irregular shard into multiple regular sub-shards, each with its own metadata entry. That increases metadata size slightly, but it avoids synchronous communication during saving.

Load-time resharding then follows a generic six-step workflow. Each rank loads the global metadata file, matches its desired tensors against saved shards, and builds a local load plan. A coordinator gathers all plans, eliminates redundant reads, balances work, and scatters the finalized plans back out. The engine executes those plans with an asynchronous pipeline. For dataloaders, if only TP or PP changes, token buffers are copied to the new workers; if DP changes, buffers are merged or split to preserve exact sample progress.

The performance optimizations are as important as the representation. Saving uses a worst-fit load balancer so one DP group does not become the checkpointing straggler. Loading avoids duplicated reads across DP replicas by reading once and redistributing via all-to-all. Planning and global metadata are cached so large jobs do not pay the full planning cost every checkpoint; the paper says a 405B model on 8,960 GPUs would otherwise spend 62 seconds just planning. The engine overlaps read, deserialize, H2D, and inter-GPU transfer on load, and D2H, serialize, dump, and upload on save. For HDFS, ByteCheckpoint adds multithreaded single-file reads, parallel sub-file writes followed by metadata concatenation, and dataloader-state prefetching to remove checkpoint-time stalls.

## Evaluation

The evaluation uses two production-style workloads: a 4B video-generation transformer trained with FSDP on A100s, and a 70B text transformer trained with Megatron-LM on H800s, both backed by HDFS. The main comparison is against PyTorch DCP for FSDP and Megatron MCP for Megatron-LM. On the 128-GPU FSDP workload, ByteCheckpoint cuts checkpoint stall time from 61.37 seconds to 0.38 seconds, save time from 236.34 seconds to 23.74 seconds, load time from 105.74 seconds to 12.01 seconds, and reshard time from 91.01 seconds to 13.64 seconds. On the 4,800-GPU Megatron workload, it reduces stall time from 4.70 seconds to 0.36 seconds and save time from 76.21 seconds to 8.59 seconds, while still improving load and reshard time.

Across all compared cases, the paper reports 12.13x-161.50x lower stall time, 6.05x faster saving on average, and 3.88x faster loading plus resharding on average. ETTR improves by 1.16x-1.29x. The microbenchmarks support the mechanism story: adding asynchronous save, workload balancing, and plan caching cuts average save time for the smaller tGPT models from 48.3 seconds to 19.27 seconds, while irregular-tensor decomposition reduces blocking time to about 0.20 seconds instead of the 4-6 second all-gather-plus-D2H path.

The correctness results are also relevant. Loss curves continue smoothly after PP, TP, DP, and hybrid resharding, and the paper shows bit-wise aligned resumption on a real 175B production run when parallelism does not change. The deployment numbers are strong as well: ByteCheckpoint supports a 405B Megatron-LM model on 8,960 GPUs with average checkpoint stall of 0.59 seconds, 51.06-second end-to-end save time, and 129.49-second load time. That is a meaningful production claim, not only a lab benchmark.

## Novelty & Impact

The closest named prior systems are PyTorch DCP and Megatron MCP. DCP introduces online resharding metadata for FSDP-style checkpoints, but it does not cover TP/PP-style layouts and pays heavy overhead on irregular optimizer shards. MCP extends checkpointing for Megatron, but remains tied to that ecosystem and does not solve the broader multi-framework problem. ByteCheckpoint's novelty is integrating three pieces that are usually treated separately: a parallelism-agnostic representation, a unified save/load workflow across training frameworks and storage backends, and the engineering work needed to make that design scale in production.

This paper will matter to teams running long, multi-stage model-development pipelines rather than one-off training jobs. It turns checkpointing from a framework-local utility into shared platform infrastructure, and it suggests that future elastic-training systems can get much more flexible if they build on layout-independent training-state representations.

## Limitations

The strongest baseline comparisons only cover GPU states, because DCP and MCP do not support dataloader-state resharding. Once full training state is included, ByteCheckpoint's own reshard times get much worse: the 2,400-GPU Megatron full-state result reports 401.21 seconds for load-time resharding, largely because unique dataloader components such as token buffers are expensive to transform and often create stragglers.

The system is also deeply shaped by the authors' production environment. Several wins depend on HDFS-specific engineering, a custom C++ implementation plus NNProxy, tree-shaped gRPC collectives, and hot-cold storage management. The paper does not show how much of the benefit transfers to more commodity storage systems or to deployments without comparable control over the backend. Finally, correctness evidence is mostly loss continuity and exact resumption, not a broad fault-injection study across many frameworks and failure modes.

## Related Work

- _Eisenman et al. (NSDI '22)_ - `Check-N-Run` reduces recommendation-model checkpoint cost with differential saving and quantization, whereas `ByteCheckpoint` targets persistent, reshardable checkpoints for multi-stage foundation-model development.
- _Mohan et al. (FAST '21)_ - `CheckFreq` pipelines snapshotting and tunes checkpoint frequency, while `ByteCheckpoint` focuses on layout-independent checkpoint representation plus production-grade save/load/reshard performance.
- _Wang et al. (SOSP '23)_ - `Gemini` emphasizes in-memory checkpointing for fast recovery, but `ByteCheckpoint` assumes durable storage because checkpoints must also feed evaluation, debugging, and cross-stage transfer.
- _Thorpe et al. (NSDI '23)_ - `Bamboo` improves elastic training on preemptible instances; `ByteCheckpoint` is orthogonal, providing a state format that could make elastic reconfiguration less dependent on custom resharding logic.

## My Notes

<!-- empty; left for the human reader -->
