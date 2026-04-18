---
title: "LAER-MoE: Load-Adaptive Expert Re-layout for Efficient Mixture-of-Experts Training"
oneline: "Shards every expert across all GPUs and re-lays them out each iteration, letting MoE training rebalance hot experts without paying explicit relocation overhead."
authors:
  - "Xinyi Liu"
  - "Yujie Wang"
  - "Fangcheng Fu"
  - "Xuefeng Xiao"
  - "Huixia Li"
  - "Jiashi Li"
  - "Bin Cui"
affiliations:
  - "School of Computer Science & Beijing Key Laboratory of Software and Hardware Cooperative Artificial Intelligence Systems, Peking University, Beijing, China"
  - "School of Artificial Intelligence, Shanghai Jiao Tong University, Shanghai, China"
  - "Bytedance Seed, Beijing, China"
  - "Bytedance Seed, Shenzhen, China"
  - "Institute of Computational Social Science, Peking University (Qingdao)"
conference: asplos-2026
category: llm-training
doi_url: "https://doi.org/10.1145/3779212.3790180"
code_url: "https://github.com/PKUDAIR/Hetu-Galvatron/tree/laer-moe"
tags:
  - llm-training
  - gpu
  - scheduling
  - ml-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

LAER-MoE argues that the main reason prior system-level MoE load balancing reacts too slowly is not a lack of routing signals, but the cost of moving experts around. Its answer is Fully Sharded Expert Parallelism (`FSEP`), which shards every expert across all devices, reconstructs only the experts a device needs, and folds expert re-layout into FSDP-style prefetch and reshard communication. With that substrate plus a lightweight planner that separates fast token routing from slower replica placement, the system reports up to `1.69x` speedup over Megatron without changing model math or hurting convergence.

## Problem

The paper studies a bottleneck that shows up in real MoE training runs: routing distributions are highly skewed and change from iteration to iteration, so a few hot experts can dominate step time. In their Mixtral `8x7B` trace, overloaded experts appear almost every iteration, and the resulting tail latency pushes the All-to-All share of iteration time from under `10%` to above `40%`. In expert-parallel training, that means the slowest devices, not average compute, determine progress.

Purely algorithmic balancing is an unsatisfying fix. Auxiliary losses can encourage more even routing, but the paper shows they also slow convergence, increasing the number of steps needed to reach the same quality. From a systems perspective, existing remedies also come with a hard tradeoff. Replication-based systems such as FasterMoE and Prophet add extra gradient synchronization for replicated experts, while relocation-based systems such as SmartMoE move expert parameters and optimizer state explicitly. The paper states that relocation can cost about `6x` the expert parameter size and increase peak memory because send and receive buffers coexist. As a result, prior systems either update layouts infrequently or penalize aggressive re-layout, which is exactly the opposite of what fast-changing routing skew demands.

## Key Insight

The key claim is that expert re-layout becomes much cheaper if the system stops thinking of experts as whole objects that live on one device and instead treats every expert as already sharded across all devices. Once each GPU stores one shard of every expert, "moving" an expert is no longer a heavyweight migration of parameters and optimizer state. It becomes the much simpler question of which full experts each device should reconstruct for the next iteration.

That reframing matters because it turns irregular, skewed re-layout traffic into regular balanced All-to-All communication. The planner can then optimize expert placement aggressively at iteration granularity without paying the traditional relocation penalty. LAER-MoE builds on that observation by splitting control into two timescales: a fast routing rule that immediately sends tokens to nearby replicas, and a slower layout tuner that uses recent routing history to decide how many replicas each expert should have and where those replicas should be placed next.

## Design

`FSEP` is the mechanism that makes the whole system plausible. For `N` devices and `E` experts, each device stores `1/N` of every expert and has capacity `C` full experts reconstructed at a time. Training adds three operations on top of FSDP-style sharding. `shard` flattens and partitions all expert parameters during initialization. `unshard` restores only the experts required on a device through All-to-All. `reshard` repartitions expert gradients after backward. Because only `C` experts are materialized per device, FSEP keeps the memory behavior close to fully sharded training while giving the runtime freedom to choose different expert layouts every iteration.

The paper spends real effort on making that freedom affordable. It separates flattened expert storage from the metadata used to rebuild individual parameters so that PyTorch autograd still sees the expected shapes. It then schedules communication more aggressively than standard FSDP: prefetching for the next MoE layer is overlapped with the current layer's expert computation rather than the preceding attention layer, prefetch is launched after token All-to-All to reduce channel contention, and gradient synchronization is delayed to overlap with the next layer's backward pass. The analytical result is that FSEP's communication volume is only slightly above an `FSDP+EP` baseline and converges toward it as cluster size grows; the paper gives a representative ratio of about `1.1x`. The additional memory cost is also modest, essentially the extra parameter and gradient buffers needed for these overlap optimizations.

On top of `FSEP`, LAER-MoE builds a planner. The full optimization objective minimizes communication time plus the maximum per-device compute time under constraints on expert capacity and token-to-expert routing. Solving that formulation exactly is too slow, so the authors decompose it. The synchronous token dispatcher uses a lite routing heuristic: if a requested expert has a replica within the same node, tokens are spread evenly across in-node replicas; otherwise they are spread across global replicas. The asynchronous expert layout tuner separately decides replica counts and placements. It tries both a load-proportional replica scheme and an even-replica scheme, perturbs them randomly, and evaluates them with a cost model. Placement itself is topology-aware and greedy: it tries to spread replicas of the same expert across nodes first, then assigns them to the least-loaded eligible devices.

## Evaluation

The evaluation is thorough enough to support the paper's main systems claim. The authors run on a `4`-node cluster with `32` `A100-80GB` GPUs total, `300 GB/s` intra-node NVLink, and `800 Gbps` inter-node InfiniBand. They test Mixtral-`8x7B`, Mixtral-`8x22B`, and Qwen-`8x7B`, each in `e8k2` and `e16k4` variants, on WikiText and C4 using dropless routing. Baselines are Megatron, a tuned `FSDP+EP` implementation with the same communication optimizations where applicable, and a reproduced FlexMoE-style planner.

Across those settings, LAER-MoE reaches up to `1.69x` acceleration over Megatron, up to `1.50x` over `FSDP+EP`, and up to `1.39x` over FlexMoE, with an average `1.20x` gain over the latter. The case study explains where that comes from: in the imbalanced runs, `FSDP+EP` spends as much as `40%` of total time in All-to-All, FlexMoE helps somewhat, and LAER-MoE cuts that share to below `20%`, producing up to `2.68x` speedup in All-to-All time relative to the baseline. The load-balance visualization is consistent with that story: LAER-MoE keeps the maximum per-device token count close to the ideal line across layers, especially on the harder `e16k4` models.

The convergence study is also important. With auxiliary-loss weight `1e-4`, LAER-MoE tracks Megatron to within relative error `< 1e-3`, which supports the claim that `FSEP` changes communication structure rather than training semantics. Because it can tolerate a smaller auxiliary loss while still running fast, the system also converges faster in wall-clock time than Megatron with larger balancing loss. Planner overhead looks negligible in the intended regime: lite routing takes about `25-31 ms`, under `0.1%` of total time, and the CPU-side layout solver stays below per-layer baseline time even in the paper's scale-out analysis. My main reservation is scope: real experiments stop at `32` A100s, while larger-scale claims rely on analysis and simulation rather than full end-to-end runs.

## Novelty & Impact

Relative to _He et al. (PPoPP '22)_ and _Wang et al. (CLUSTER '23)_, the paper's novelty is not just another policy for which experts to replicate, but a new substrate that makes replication and relocation cheap enough to do continuously. Relative to _Zhai et al. (USENIX ATC '23)_ and _Nie et al. (Proc. ACM Manag. Data '23)_, its distinctive move is refusing to treat re-layout as a separate costly phase. That is why it can adapt every iteration instead of every few hundred steps or only when the planner predicts the move will pay for itself.

This makes the paper meaningful for people building distributed MoE training stacks, not just for researchers studying one more load-balancing heuristic. `FSEP` also appears composition-friendly: the authors explicitly position it as orthogonal to other communication/computation overlap work such as Comet, Lancet, Lina, and DeepEP. If that composability holds in practice, LAER-MoE is best understood as a systems building block for future large-scale MoE training pipelines.

## Limitations

The paper is honest that LAER-MoE is most valuable in imbalanced regimes. In balanced workloads, it should look similar to `FSDP+EP`, because its communication volume is nearly the same. That means the benefit depends on routing skew being frequent and large enough to dominate step time.

There are also deployment constraints. The overlap argument assumes enough tokens per micro-batch to hide prefetch behind expert compute; the paper provides a threshold analysis and says its experiments satisfy it, but very small batches could weaken the effect. The large-scale scalability discussion beyond the 32-GPU cluster is mostly theoretical or simulation-based. And because FlexMoE has no public implementation, that comparison depends on the authors' reproduction rather than a head-to-head against released code. None of those issues invalidate the result, but they narrow how far we should generalize it.

## Related Work

- _He et al. (PPoPP '22)_ — FasterMoE replicates hot experts to all devices, whereas LAER-MoE instead shards every expert universally and makes layout changes look like balanced parameter reconstruction.
- _Zhai et al. (USENIX ATC '23)_ — SmartMoE performs online expert relocation, but relocation remains an explicit expensive phase; LAER-MoE's main contribution is hiding that cost inside routine sharding communication.
- _Wang et al. (CLUSTER '23)_ — Prophet selectively replicates hot experts, yet must account for skewed synchronization overhead, while LAER-MoE aims to make the planner optimize mostly for balance rather than migration cost.
- _Nie et al. (Proc. ACM Manag. Data '23)_ — FlexMoE also combines replication and relocation, but its search is constrained by relayout cost; LAER-MoE expands the feasible search space by changing the underlying parallelism model.

## My Notes

<!-- empty; left for the human reader -->
