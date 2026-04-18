---
title: "T-Control: An Efficient Dynamic Tensor Rematerialization System for DNN Training"
oneline: "Keeps high-centrality tensors and repacks GPU memory at runtime so dynamic rematerialization can train larger DNNs with fewer evictions and recomputations."
authors:
  - "Zehua Wang"
  - "Junmin Xiao"
  - "Xiaochuan Deng"
  - "Huibing Wang"
  - "Hui Ma"
  - "Mingyi Li"
  - "Yunfei Pang"
  - "Guangming Tan"
affiliations:
  - "Institute of Computing Technology, Chinese Academy of Sciences, Beijing, China"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3779212.3790230"
tags:
  - ml-systems
  - memory
  - gpu
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

T-Control argues that dynamic tensor rematerialization loses mostly because it makes local eviction decisions on a fragmented heap. Its fix is to retain tensors that sit on many shortest computation paths in the traced dependency graph, while simultaneously migrating tensors to keep free memory contiguous. That combination lets a dynamic method close and sometimes beat the gap to static rematerialization.

## Problem

The paper studies training under tight GPU memory budgets, where activation rematerialization is the standard escape hatch: free tensors during forward, then recompute them during backward when needed. Static methods plan that schedule ahead of time from the full computation graph, which gives them good global decisions but makes them awkward for dynamic models whose graph changes with the input. Dynamic methods are naturally better suited for AlphaFold-style or MoE-style execution because they decide online, but in practice they usually run slower.

The authors isolate two reasons. First, prior dynamic systems such as DTR and DTE mostly rank tensors with local properties like size, staleness, or estimated recomputation cost. That can evict hub tensors whose value lies in how many later computations depend on them, which then triggers repeated rematerialization and deep recursive recomputation. Second, the memory side is just as damaging: dynamic rematerialization creates irregular allocation patterns, which worsen fragmentation, force avoidable evictions, and amplify recomputation further. The resulting gap is visible in the paper's motivating measurements, where dynamic methods show both more rematerialization events and deeper recursion than static baselines.

## Key Insight

The core claim is that dynamic rematerialization can become competitive if it stops treating eviction and allocation as separate problems. A runtime system can infer which tensors matter structurally from the traced tensor dependency graph, and it can adjust retention decisions based on the current amount of free memory rather than a fixed precomputed plan. In parallel, the allocator can actively reshape memory so that fragmentation does not force needless evictions.

The specific insight is to rank tensors by a shortest-computation-path variant of betweenness centrality. Tensors that lie on many shortest paths act as bridges across layer boundaries or skip connections; evicting them is much more expensive than evicting an isolated activation of similar size. If the system protects those graph hubs, the worst recursive recomputation chains disappear. Then, if the allocator concentrates live tensors into high-occupancy segments and migrates them out of sparse segments when needed, the runtime can satisfy more allocations without eviction. The paper's contribution is the claim that those two controls reinforce each other.

## Design

T-Control is implemented with lightweight extensions to PyTorch and is organized into four components: an operator executor, a tensor manager, a TDG manager, and a memory manager. At operator granularity, the system intercepts each op, allocates its outputs, executes the op, updates the traced TDG, and then marks tensors for retention, eviction, or unlocking. When memory approaches the configured budget, an eviction workflow asks the tensor manager to free tensors before execution continues.

The retention algorithm is built around an incremental TDG. The authors observe that training graphs have a layered structure, so the graph can be viewed as a sequence of per-layer subgraphs plus upper-level skip-connection edges. They define vertex importance with shortest-computation-path betweenness centrality rather than ordinary hop-count centrality, so path length reflects recomputation cost. Instead of recomputing centrality from scratch whenever a new layer appears, T-Control updates the score incrementally with four additive terms corresponding to paths fully inside the new subgraph, paths crossing older subgraphs, incoming paths, and outgoing paths. After updating scores, it locks the top `K%` of vertices into a reservation set, where `K` grows with residual memory. In other words, the less pressure the runtime sees, the more graph-critical tensors it chooses to keep.

The memory manager is the second half of the story. It reorganizes PyTorch's allocator around size buckets of contiguous segments and follows three rules. The first is occupancy-guided best-fit allocation: for equally sized free blocks, prefer the block inside the most occupied segment, packing live tensors tightly. The second is occupancy-guided migration: if a request fails because no contiguous block is large enough, move tensors out of a low-occupancy segment into denser ones so the sparse segment becomes usable again. The third is cost-aware eviction: when eviction is unavoidable, choose the segment whose evictable tensors expose the lowest recomputation cost after normalizing by size and staleness. This is meant to approximate the benefit of virtual memory stitching without paying repeated VMS overhead.

## Evaluation

The evaluation spans both distributed and single-node training. Distributed experiments run on up to 64 nodes with 4 x A100-40GB GPUs per node over RoCE, while dynamic-method experiments use a single server with 8 x A100-80GB GPUs and NVLink. The workload mix is unusually broad for this area: static transformer models such as GPT and Llama, vision models including ResNet and ViT, and dynamic models including AlphaFold, LSTM, GPT-MoE, and BERT4GCN.

Against non-recomputation and static training systems, the headline result is that T-Control beats or matches strong baselines despite being dynamic. In distributed training, it reports throughput gains of `1.05x-1.58x` on GPT models and `1.10x-1.22x` on Llama 2 models relative to DeepSpeed ZeRO, Zero Bubble, Megatron-LM, and AdaPipe. The authors attribute this to using rematerialization to reduce TP or PP, which enables higher data parallelism and less communication. More strikingly, GPT 3-121B on 128 GPUs and Llama 3-405B on 256 GPUs run only with T-Control; all non-recomputation baselines hit out-of-memory.

The dynamic comparison is also strong. Across static and dynamic models on 8 A100s, T-Control shows a geometric-mean speedup of `1.17x` over DTR, `1.25x` over DTE, and `1.47x` over GMLake plus DTR. Under tighter budgets, the gain widens to `1.04x-1.74x` over DTR and `1.09x-1.91x` over DTE, while GMLake slows down much more because repeated virtual-memory operations are expensive. The mechanism-level plots back up the causal story: T-Control cuts eviction events by up to `92%`, rematerialization events by up to `71%`, keeps recursion depth to at most `126` which is `21x` lower than DTR, and holds fragmentation below `6%` in distributed training. Reported runtime overhead stays below `5%`, which makes the systems argument plausible.

## Novelty & Impact

Relative to prior dynamic rematerialization work, T-Control's novelty is not merely "a better heuristic." It changes the decision variable from per-tensor local cost to graph-topological importance, and it couples that with a runtime allocator designed to preserve contiguous space instead of accepting fragmentation as background noise. Relative to static systems, its contribution is showing that dynamic methods do not have to give up most of the performance advantage if they exploit structure in the traced graph and the live heap together.

This paper is likely to matter to researchers working on training systems, memory management, and large-model execution under tight device budgets. It also has practical value because it is implemented inside PyTorch rather than as a paper-only optimizer. The broader impact is a reframing: dynamic rematerialization should be treated as a joint graph-and-memory-control problem, not just an online eviction policy.

## Limitations

The paper is convincing about throughput, but several constraints remain. The centrality algorithm relies on the TDG's layered regularity, so it is less obvious how well the same machinery would transfer to more irregular execution graphs. The retention threshold `K%` is still empirically chosen, which means some policy tuning remains hidden behind the algorithm. On the memory side, tensor migration is cheaper than VMS in the authors' measurements, but it is still extra data movement whose cost may change on other hardware or with larger tensors.

The evaluation also leaves a few questions open. Most comparisons focus on throughput per iteration rather than end-to-end convergence time, although the appendix indicates comparable loss curves. The paper shows support for dynamic models, which is important, but the single-node setup for dynamic baselines is much narrower than the distributed transformer evaluation. So the strongest claim is not that T-Control solves all training-memory problems; it is that it gives dynamic rematerialization a much better operating point than prior systems.

## Related Work

- _Jain et al. (MLSys '20)_ - Checkmate computes an offline globally optimized rematerialization plan, whereas T-Control trades that offline optimality for runtime adaptation and support for dynamic models.
- _Hu et al. (ICS '22)_ - MegTaiChi's DTE adds fragmentation-aware dynamic eviction, but it still relies on local heuristics instead of preserving graph-central hub tensors.
- _Guo et al. (ASPLOS '24)_ - GMLake reduces fragmentation with virtual memory stitching, while T-Control pursues a lower-overhead path through migration and segment-aware placement.
- _Sun et al. (ASPLOS '24)_ - AdaPipe is a strong static transformer-oriented planner; T-Control aims to recover similar efficiency without assuming a fixed preplanned schedule.

## My Notes

<!-- empty; left for the human reader -->
