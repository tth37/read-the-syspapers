---
title: "REPA: Reconfigurable PIM for the Joint Acceleration of KV Cache Offloading and Processing"
oneline: "Uses reconfigurable ReRAM PIM to both persist KV cache and execute scoring/context work, then pipelines it with the GPU for faster decoding."
authors:
  - "Yang Hong"
  - "Junlong Yang"
  - "Bo Peng"
  - "Jianguo Yao"
affiliations:
  - "Shanghai Jiao Tong University, Shanghai, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790212"
tags:
  - llm-inference
  - caching
  - memory
  - hardware
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

REPA argues that KV-cache offloading and decode-time KV processing should be treated as one problem, not two separate optimizations. It places KV data in a reconfigurable ReRAM PIM device that can both store the cache non-volatilely and execute the non-batchable `q x K^T` and `S x V` work, then uses bulk memory instructions, locality-aware placement, and GPU-PIM pipelining to make that design fast enough to beat GPU-only serving in the long-context regime.

## Problem

The paper starts from two pains that are usually optimized separately. KV cache is large enough to consume `30%-80%` of GPU memory in prior reports, and the authors measure an average per-request footprint of `670 MiB` for Llama2-7B on Azure23. Offloading is therefore common, but it is expensive: with `1-4` SSD evictions, their early experiment shows `0.3-0.8x` slowdown for median requests and `0.5-2.0x` slowdown for P99-length requests.

Decoding is also a poor GPU workload. Scoring and context have low arithmetic intensity, move KV slices back and forth frequently, and do not benefit much from batching across requests. Prior systems usually choose one side of this tradeoff: offloading systems improve movement policy but do not compute on offloaded KV state, while stage-split systems move decode elsewhere without fixing KV processing itself. REPA therefore targets the combined problem: persist KV cache cheaply and accelerate the non-batchable decode work on the same substrate.

## Key Insight

The core insight is that KV-cache offloading and KV-cache processing want the same hardware properties: large capacity, non-volatility, and high bandwidth close to the data. Reconfigurable ReRAM PIM can serve as both storage and compute substrate, so a single device can keep evicted KV state resident and also execute the two decode-time attention kernels that are hardest to batch on GPUs.

That idea only works if reconfigurable PIM's slow primitive operations are offset by much higher parallelism. REPA's claim is that the structure of per-head KV matrices makes this possible: bulk-wise memory instructions expose multi-wordline parallelism, locality-aware placement keeps intermediates inside a tile, and GPU-PIM pipelining hides transfer slack. The memorable proposition is not merely "PIM helps attention," but "a sufficiently parallel ReRAM PIM can turn KV offload storage into an active decode accelerator."

## Design

REPA is a hybrid split-execution system. The GPU performs prefill and the batch-friendly decode operations such as QKV generation, projection, and FFN. REPA-PIM handles the non-batchable decode work: scoring (`q x K^T`) and context (`S x V`). The PIM device is a 3D-stacked design with one buffer die and eight PIM dies; each die contains tiles, each tile contains processing units, and each PU contains ReRAM arrays grouped for parallel control.

The first design move is control. Because reconfigurable PIM needs many more memory operations than DRAM-PIM, REPA introduces a `BLK_SET` instruction that applies the same memory-setting primitive to 64 adjacent wordlines at once. It then adds tile-group, tile, and PU controllers so that this extra internal parallelism can actually be scheduled; moving from one to four controllers per PU costs `5.76 mm^2` per die but yields `3.91x` speedup on `q x K^T`.

The second move is placement. REPA maps KV cache by attention head and spreads each per-head matrix across four nearby arrays in different array groups rather than finely interleaving it across distant banks. `K` is row-sliced so replicated queries can dot-product against many rows in parallel, while `V^T` is partitioned into fixed-width slices so score fragments can be replicated and reduced locally. The same mapping choice improves both offload persistence and decode locality.

The third move is pipelining. REPA sub-batches requests so GPU and PIM remain busy at the same time, and overlaps transfer with compute in both prefill and decode. The intended invariant is simple: PIM mostly works on already-nearby KV state while the GPU advances the next batchable work.

## Evaluation

The host setup is a real 8xA100 server, but REPA-PIM itself is modeled in an in-house NeuroSim-3D-based simulator at `1 GHz`, so this is an architecture study rather than a silicon prototype. The workloads use Llama2 `7B`, `13B`, and `70B`, with comparisons against GPU, AttAcc, PAPI, DRISA, and AiF.

In the main token-generation experiment, REPA wins where the paper says it should: long context, large batch, large model. Against NVIDIA A100, it generates `1.8-4.8x` more tokens at sequence length `2048` and `2.1-6.5x` more at `4096`; the gain is smaller at `1024`, where it is `1.5-4.7x`. Against AttAcc, REPA is ahead by `0.4-1.4x` at `4096` but shrinks to `-0.3-0.8x` at `1024`, which supports the claim that REPA needs enough parallel work to amortize slower primitive operations.

The integration story is also credible. Plugged into FlexGen without changing FlexGen's policy, REPA improves offloading speed by `1.4-2.0x`, and the abstract summarizes the end-to-end gain as `1.2-1.4x`. On efficiency, REPA delivers `2.1-4.3x` more tokens per joule than GPU and cuts scoring/context energy by `6.2-6.3x`. The ablations are useful too: REPA beats a pure stage-split variant by `1.2-1.6x` on end-to-end latency, and its mapping policy keeps more than `92%` of computation within a single tile. Overall, the evidence supports the paper's claim in the long-sequence, memory-heavy regime, but not as strongly for short, lightly batched inference.

## Novelty & Impact

Relative to _Park et al. (ASPLOS '24)_, REPA is not just another PIM attention accelerator: AttAcc accelerates batched transformer inference with DRAM PIM, while REPA couples decode acceleration with non-volatile KV persistence. Relative to _He et al. (ASPLOS '25)_, REPA is less about dynamic dispatch and more about redesigning the storage/compute substrate so KV cache lives where scoring and context execute. Relative to _Patel et al. (ISCA '24)_, it avoids sending decode to a weaker GPU tier and instead moves the bottleneck into a different hardware class.

That makes the paper most relevant to computer architects studying ReRAM PIM and to systems builders exploring specialized memory devices for LLM serving. The contribution is mainly a new mechanism plus a workload-specific framing, not a measurement study.

## Limitations

The biggest limitation is methodological: REPA-PIM is simulated, not fabricated, so all performance and energy claims depend on the fidelity of the simulator and the assumed ReRAM parameters. The second limitation is regime sensitivity. REPA's advantages come from fine-grained parallelism over large working sets, and the paper's own results show much smaller gains, and sometimes losses versus AttAcc, on short-sequence settings.

Deployment is also narrower than the paper's broad motivation might suggest. The experiments use Llama2 models rather than a multi-model serving fleet, and the integration story is demonstrated on FlexGen with unchanged policy, not on a production disaggregated scheduler. Finally, endurance is discussed analytically rather than empirically: the authors estimate fewer than `2.8 x 10^10` memsets per cell per year under a `20 tokens/s` assumption and argue that high-endurance ReRAM should survive, but that is still a modeled argument rather than an operational one.

## Related Work

- _Park et al. (ASPLOS '24)_ — AttAcc uses DRAM PIM to accelerate batched transformer attention, whereas REPA adds non-volatile KV storage and targets the offloaded decode path specifically.
- _He et al. (ASPLOS '25)_ — PAPI exploits dynamic parallelism in a PIM-enabled decoding system, but REPA emphasizes reconfigurable ReRAM, bulk-wise instructions, and locality-aware KV placement.
- _Patel et al. (ISCA '24)_ — Splitwise separates prefill and decode across devices; REPA keeps batchable decode work on the GPU and offloads only the non-batchable KV processing to PIM.
- _Sheng et al. (ICML '23)_ — FlexGen is an offloading system that trades storage for GPU memory capacity, and REPA positions itself as an orthogonal accelerator that can speed that offloaded path.

## My Notes

<!-- empty; left for the human reader -->
