---
title: "I/O Analysis is All You Need: An I/O Analysis for Long-Sequence Attention"
oneline: "Derives an I/O-optimal exact-attention schedule from tall-and-skinny MMM analysis, then builds AttenIO to realize it with overlap and pipelined softmax."
authors:
  - "Xiaoyang Lu"
  - "Boyu Long"
  - "Xiaoming Chen"
  - "Yinhe Han"
  - "Xian-He Sun"
affiliations:
  - "Illinois Institute of Technology, Chicago, IL, USA"
  - "Institute of Computing Technology, Chinese Academy of Sciences, Beijing, China"
  - "University of Chinese Academy of Sciences, Beijing, China"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790174"
tags:
  - llm-inference
  - hardware
  - gpu
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

This paper treats long-sequence exact attention as an I/O problem first and a kernel problem second. It derives an explicit I/O-optimal schedule for the tall-and-skinny matrix multiplications behind long-context attention: keep a large tile of `Q` on chip, stream `K` and `V` one narrow block at a time, and update online-softmax state in place. AttenIO is the accelerator that realizes that schedule with overlap and pipelined softmax.

## Problem

The paper starts from a familiar observation in long-context LLM inference: during prefill, exact self-attention quickly becomes the dominant cost as sequence length grows. Their GPT-3 profile on an RTX 6000 shows attention taking at least `80%` of runtime beyond `4K` tokens. The reason is not just the quadratic arithmetic count, but the repeated movement of `Q`, `K`, `V`, partial scores, and outputs across the on-chip/off-chip boundary.

Existing exact-attention optimizations reduce some of that traffic, but the authors argue they still choose dataflows mostly heuristically. FlashAttention uses tiled online softmax plus recomputation; FLAT keeps row-granularity dependencies on chip. The missing piece is a principled explanation of what tile sizes and schedules are actually optimal for the `N >> d` regime under a fixed SRAM budget.

## Key Insight

The paper's core claim is that exact long-sequence attention should be analyzed through the I/O complexity of tall-and-skinny matrix multiplication, because in the relevant regime `N >> d`, the dominant score computation `QK^T` has very different reuse opportunities from square MMM.

The key proposition is that the best schedule maximizes future reuse of `Q` while keeping immediate reuse of partial outputs on chip. Under the paper's capacity model, that pushes the optimal `K`/`V` tile width to `b = 1`. So the cheapest plan is to pin as much of `Q` as possible, stream one narrow `K` or `V` block at a time, and avoid spilling intermediate state.

## Design

The paper first extends red-blue-pebbling analysis for general MMM to the tall-and-skinny case `A in R^{N x d}`, `B in R^{d x N}`, `C in R^{N x N}`. It separates immediate reuse of partial outputs from future reuse of one input matrix, then maximizes compute per I/O under on-chip capacity constraints. The resulting lower bound says the retained `A` tile should be large while the `B` tile collapses to one narrow block. Mapped back to attention, `Q` is the reusable tall tile and `K`/`V` are streamed.

That directly yields the dataflow. `Q_i` stays on chip across many inner iterations; each `K_j` block is loaded, used to compute `S_i^(j) = Q_i K_j^T`, and folded into online-softmax statistics `m_i` and `l_i`; then the matching `V_j` block is loaded so `P~_i^(j) V_j` can update `O_i` on chip. Because the optimal solution sets `b = 1`, softmax becomes a sequence of element-wise updates instead of a wide row reduction.

AttenIO is the hardware realization of that schedule. A controller enforces the traversal order, a PE array handles the matrix products, an EXP unit computes exponentials, and a small KV buffer alternates between one `K` block and one `V` block. The two main implementation moves are three levels of communication-computation overlap and a pipelined softmax built from element-wise parallel patterns.

## Evaluation

The evaluation matches the design story well. AttenIO is modeled as a synthesized accelerator with a `64 x 32` MAC array, 128 EXP modules, `512 KB` on-chip cache, and `128 GB/s` HBM, and is compared against Standard attention, FLAT, and FlashAttention-2 under the same hardware assumptions. Across sequence lengths from `8K` to `128K`, AttenIO beats all three baselines. For head dimension `64`, the geometric-mean speedups are `8.8x` over FLAT, `2.5x` over Standard, and `1.6x` over FlashAttention-2; for head dimension `128`, they are `9.9x`, `1.9x`, and `1.3x`.

The strongest evidence is the data-movement study. For head dimension `64`, FLAT, Standard, and FlashAttention-2 incur `273.7x`, `57.0x`, and `26.8x` more on/off-chip traffic than AttenIO on geometric mean. The utilization data is consistent with that story: AttenIO reaches `82.1%` PE utilization at head dimension `64` and `90.3%` at `128`, while its EXP-unit utilization is `3.3x` and `2.7x` higher than FlashAttention-2. Memory stall time stays below `1%` in all tested settings.

The paper also checks robustness rather than one lucky point. AttenIO keeps its lead across cache sizes from `64 KB` to `768 KB`, under block-wise causal masking, and in GPT-3 prefill latency where it is up to `2.3x` faster than FLAT and `1.3x` faster than FlashAttention-2 at `8K`. When scaled to match H100-class throughput, it also reports up to `3.4x` speedup over cuDNN-backed FlashAttention-2 and `3.0x` over FlashAttention-3.

## Novelty & Impact

Relative to _Dao et al. (NeurIPS '22)_, the novelty is not merely being "more I/O-aware" than FlashAttention, but deriving an explicit lower bound and a concrete optimal schedule for the tall-and-skinny regime attention actually operates in. Relative to _Kao et al. (ASPLOS '23)_, the paper argues that preserving full row-wise softmax dependencies on chip is the wrong tradeoff because it shrinks useful tile sizes and increases traffic. Relative to _Nayak et al. (MICRO '24)_, which optimizes accelerator mappings for existing attention formulations, AttenIO changes the formulation itself by making the dataflow the first-class object of optimization.

That makes the paper likely to matter to accelerator architects and to researchers working on long-context LLM inference. Its broader contribution is methodological: it argues that I/O analysis can be a design primitive.

## Limitations

The biggest limitation is scope. AttenIO targets exact forward attention for long-sequence serving, especially prefill, rather than decode-heavy serving, training, or full transformer execution. The architecture and analysis are therefore highly specialized to one bottleneck.

The validation story is also narrower than a fabricated-chip result. The paper provides RTL synthesis, CACTI-based memory modeling, and cycle-accurate simulation rather than silicon measurements. It also explicitly leaves deeper memory hierarchies and horizontal inter-node communication to future work, so the current I/O analysis is still a two-level, single-device argument.

## Related Work

- _Dao et al. (NeurIPS '22)_ — FlashAttention introduced tiled exact attention with online softmax and I/O awareness; AttenIO goes further by deriving an explicit I/O-optimal schedule for the long-sequence `N >> d` regime.
- _Kao et al. (ASPLOS '23)_ — FLAT keeps row-granularity softmax dependencies on chip to avoid recomputation, whereas AttenIO argues that this reuse pattern constrains tiling and increases total traffic.
- _Kwasniewski et al. (SC '19)_ — Red-blue pebbling for general MMM provides the analytical base that AttenIO extends to tall-and-skinny MMM and then to attention.
- _Nayak et al. (MICRO '24)_ — FuseMax improves accelerator execution of FlashAttention-style dataflows, while AttenIO changes the underlying dataflow itself through I/O analysis.

## My Notes

<!-- empty; left for the human reader -->
