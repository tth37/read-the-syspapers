---
title: "Ouroboros: Wafer-Scale SRAM CIM with Token-Grained Pipelining for Large Language Model Inference"
oneline: "Ouroboros keeps LLM state inside wafer-scale SRAM CIM, then uses token-grained pipelining, locality-aware mapping, and distributed KV placement to recover utilization."
authors:
  - "Yiqi Liu"
  - "Yudong Pan"
  - "Mengdi Wang"
  - "Shixin Zhao"
  - "Haonan Zhu"
  - "Yinhe Han"
  - "Lei Zhang"
  - "Ying Wang"
affiliations:
  - "SKLP, Institute of Computing Technology, Chinese Academy of Sciences, Beijing, China"
  - "University of Chinese Academy of Sciences, Beijing, China"
  - "Hangzhou Institute for Advanced Study, University of Chinese Academy of Sciences, Hangzhou, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790197"
tags:
  - hardware
  - llm-inference
  - memory
  - energy
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Ouroboros argues that the dominant cost in LLM inference is no longer arithmetic, but moving weights, activations, and KV cache data across deep memory hierarchies. It therefore puts the whole inference state into wafer-scale SRAM-based computing-in-memory hardware, then adds token-grained pipelining, communication-aware mapping, and distributed KV management to keep that all-SRAM design from collapsing under utilization bottlenecks.

## Problem

The paper starts from a hardware observation rather than a scheduler observation: as LLMs scale, compute energy becomes a minority term, while on-chip to off-chip movement and inter-device communication dominate both latency and joules. GPU, TPU, and even existing wafer-scale engines still rely on a hierarchy in which SRAM is only a staging buffer and weights or KV cache spill into HBM or DRAM. That architecture pays what the authors call a hardware scaling tax: every larger model or longer context forces more traffic across expensive links.

Moving everything into SRAM sounds attractive, but wafer-scale SRAM CIM creates a different problem set. SRAM is much lower density than DRAM, so the system has to use the available first-level memory extremely efficiently. In Ouroboros, the same SRAM arrays also do computation, so poor storage utilization also becomes poor compute utilization. The authors identify three concrete failure modes. First, sequence-level pipeline parallelism leaves bubbles because prompt lengths and prefill/decode mixes vary over time. Second, KV cache growth can strand fragmented SRAM capacity and the compute associated with it. Third, once thousands of cores are spread over a wafer, mapping layers too tightly by stage hurts inter-stage traffic, while interleaving stages hurts intra-layer reductions.

## Key Insight

The paper's key claim is that an all-SRAM, wafer-scale LLM accelerator only works if utilization is treated as a first-class co-design target at every level. The wafer-scale CIM substrate removes the deep-memory tax, but that alone is not enough; the system must also recover the utilization that such a tightly capacity-constrained design would otherwise lose to bubbles, fragmentation, and long communication paths.

That is why the paper's central move is a three-part combination rather than a single accelerator primitive. Token-grained pipelining makes the pipeline track tokens instead of whole sequences, so variable request lengths stop creating stage imbalance. Communication-aware mapping places transformer layers and tiles onto cores to jointly minimize inter-stage transfers and intra-stage reductions. Distributed KV cache management turns leftover SRAM in already allocated cores into usable cache capacity without central control. The design works because these three pieces attack the main utilization killers introduced by the all-SRAM premise.

## Design

Ouroboros is a 215mm x 215mm wafer-scale chip composed of 9 x 7 dies, with 54GB of on-chip SRAM and no deep second-level memory in the inference path. Each die contains a 13 x 17 mesh of CIM cores. A core has 128KB of input buffering, 32KB of output buffering, a 4MB SRAM crossbar array, an H-tree interconnect, an SFU for operations such as softmax, and local control for synchronization.

The execution model fully unrolls each transformer block into six pipeline stages: LayerNorm, QKV generation, score, softmax, projection, and FFN. For decoder-only models, Ouroboros introduces token-grained pipelining. Instead of letting one stage process one whole sequence while another stage works on a different sequence, each stage works on different tokens. Because causal masking only needs each token to attend to itself and previous tokens, the prefill phase can legally compute attention incrementally as tokens' QKV values appear. That avoids most sequence-length-induced bubbles and also shrinks intermediate activation storage from full sequences to individual tokens. For encoder-style attention, the paper cannot keep that property end to end, so attention stages fall back to blocked sequence-level behavior while the rest of the pipeline remains token-grained.

Mapping is split into two layers. Inter-core mapping is formulated as an MIQP problem that assigns layer tiles to cores while penalizing Manhattan distance and cross-die transfers. Intra-core mapping uses dynamic programming over the H-tree layout to push concatenation closer to the root and keep reductions closer to the leaves, lowering pressure on bandwidth-critical segments. The same mapping machinery is made fault tolerant: if a core storing weights fails, neighboring cores form a replacement chain and weights are remapped locally in sub-millisecond time instead of rerunning global placement.

KV management is likewise distributed. Attention-mode crossbars are partitioned into logical blocks, with per-block row and column validity tracking. Each transformer's attention cores maintain their own multi-level address translation: a page-table-like mapping from sequence to cores, a bitmap inside each core, and block-level metadata inside the crossbar controller. Sequences are placed across different cores to separate writes for the next token from attention reads for the current token, and heads are distributed across cores to reduce H-tree concatenation pressure. A threshold-based admission rule reserves headroom for future decode growth, reducing cache thrashing and forced eviction.

## Evaluation

The evaluation is simulator-based but fairly comprehensive. The authors build an end-to-end simulator using CACTI, Synopsys DC, BookSim2, MNSIM, and a yield model, then test LLaMA-13B/32B/65B, Baichuan-13B, Qwen-32B, plus BERT-large and T5-11B on WikiText-2. Baselines are DGX A100 with vLLM, an 8x TPU v4 setup, DGX+AttAcc, and Cerebras WSE-2 with WaferLLM-style execution.

For decoder-only models, Ouroboros reports large gains. On 13B models it improves throughput by 5.4x on average; on 32B models the average is 2.8x, with the paper explicitly attributing the smaller win to single-wafer KV capacity limits that leave the pipeline underfilled. Across baselines, energy per output token drops by 84% versus DGX A100, 82% versus TPUv4, 78% versus AttAcc, and 66% versus WSE-2. The abstract highlights 4.1x average throughput and 4.2x average energy-efficiency gains overall, peaking at 9.1x throughput and 17x energy efficiency on the 13B model.

The ablations help explain where those gains come from. Relative to a mesh-of-dies baseline with static KV management, wafer-scale integration gives a modest 1.15x throughput gain, CIM raises it to 1.49x, and adding token-grained pipelining reaches 2.05x throughput at 0.51x energy. Spatial mapping contributes another 1.17x throughput gain on average, while distributed KV management raises the total to roughly 1.99x throughput and 0.81x energy versus the baseline configuration. The scaling experiment on two wafers with LLaMA-65B is also important: the paper reports 5.4x throughput over baselines and 79% lower energy, suggesting the design's benefits grow with larger models rather than disappearing once a single wafer is exceeded.

## Novelty & Impact

The paper's novelty is not merely "put LLM inference on a wafer." Its real contribution is capacity-oriented hardware/software co-design for a memory-bound workload. Relative to GPU or TPU clusters, Ouroboros eliminates deep-memory traffic by construction. Relative to previous CIM accelerator papers, it is broader: TGP, distributed KV placement, and wafer-aware mapping are designed for end-to-end autoregressive serving rather than one operator in isolation. Relative to existing wafer-scale engines, the key difference is that SRAM is not just on-chip cache; it is the place where weights, activations, KV data, and computation all live.

That makes the paper most relevant to accelerator architects and systems researchers working on LLM inference hardware. It offers a concrete argument that for memory-bound inference, giving up peak circuit density in exchange for much more first-level SRAM capacity can be the right system-level trade.

## Limitations

The biggest limitation is that the evaluation is entirely simulation-based; there is no fabricated wafer or measured deployment. The mapping algorithm also takes several hours offline on a Xeon CPU, which is acceptable for static placement but limits how adaptive the system can be. The results show a clear single-wafer KV-capacity bottleneck on 32B models, so the design is not magically free of memory pressure even with 54GB of SRAM. Encoder adaptation is weaker as well: T5-11B reaches only 0.7x average throughput gain over baselines because blocked attention reintroduces sequence-level stalls. Finally, the design deliberately uses a conservative 1/32 row activation ratio to favor capacity over peak TOPS, so it is optimized for memory-bound LLM inference rather than dense compute kernels in general.

## Related Work

- _Aminabadi et al. (SC '22)_ — DeepSpeed-Inference pipelines transformer inference across accelerators, but still pays hierarchical-memory and inter-device traffic that Ouroboros tries to remove architecturally.
- _Hong et al. (MICRO '22)_ — DFX accelerates transformer text generation on multi-FPGA hardware, whereas Ouroboros targets full on-wafer storage and in-SRAM execution for the whole inference state.
- _Ham et al. (ISCA '21)_ — ELSA co-designs efficient self-attention hardware, but at operator granularity rather than wafer-scale end-to-end LLM execution with KV management and placement.
- _Fujiwara et al. (ISSCC '22)_ — the fully digital CIM macro pushes circuit-level TOPS/W, while Ouroboros explicitly trades some circuit density for far larger SRAM capacity and better end-to-end inference efficiency.

## My Notes

<!-- empty; left for the human reader -->
