---
title: "EARTH: An Efficient MoE Accelerator with Entropy-Aware Speculative Prefetch and Pattern Reuse"
oneline: "Splits INT8 MoE experts into base/delta slices, speculatively prefetches only bases, and reuses common delta patterns to cut bandwidth and latency."
authors:
  - "Fangxin Liu"
  - "Ning Yang"
  - "Jingkui Yang"
  - "Zongwu Wang"
  - "Chenyang Guan"
  - "Yu Feng"
  - "Li Jiang"
  - "Haibing Guan"
affiliations:
  - "Shanghai Jiao Tong University, Shanghai, China"
  - "Shanghai Qi Zhi Institute, Shanghai, China"
  - "National University of Defense Technology, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790155"
tags:
  - llm-inference
  - hardware
  - caching
  - energy
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

EARTH is a hardware-software co-design for bandwidth-bound MoE inference. It splits each INT8 expert into a coarse base and a refinement delta, speculatively prefetches many bases, and only fetches or reconstructs deltas when the routed expert is important enough. That combination cuts expert-loading traffic by up to 48% and improves end-to-end latency by up to 2.10x in the authors' modeled accelerator setting.

## Problem

The paper targets a specific pain point in deploying MoE language models on resource-constrained accelerators: sparse activation reduces arithmetic work, but it makes memory movement worse. Every token only needs a few experts, yet those experts come from a very large pool, so the hardware repeatedly pulls large weight tensors from off-chip memory. In the authors' profiling of Qwen3-30B-A3B with INT8 weights on DDR5-6400, expert fetching consumes about 88% of total cycles, while gating, expert compute, and aggregation together account for less than 12%. That is the central systems imbalance: MoE inference looks sparse in FLOPs but dense in data movement.

Obvious fixes each break somewhere. Keeping all experts on chip is impossible once the model grows. Expert parallelism spreads memory pressure across more devices, but it raises hardware cost and system complexity. Compression lowers footprint, yet aggressive quantization or pruning can damage output quality or require retraining. Prior offloading schemes move cold experts to slower memory and try to prefetch predicted ones, but static or heuristic prefetching misses dynamic routing behavior, wastes scarce buffer space, and can still leave the pipeline stalled on late expert loads.

The paper also identifies a subtler obstacle. If one wants adaptive precision, the naive implementation is to store multiple versions of each expert, such as INT8 and INT4. That doubles storage and transfer overhead and defeats the purpose on a bandwidth-limited design. Conversely, keeping only a truncated low-precision copy throws away numerically important information. EARTH therefore asks whether expert weights can be represented in a sliceable form that is cheap to move, accurate when needed, and simple enough for hardware to exploit at runtime.

## Key Insight

The central claim is that MoE inference does not need every routed expert at full fidelity all the time. A routed expert can be treated in two stages: a compact base captures most of the useful computation early, while a smaller delta refines the result only when the gating decision says that expert matters enough. If the system speculatively pulls many bases instead of a few full experts, it expands effective prefetch capacity and makes misses less painful.

That idea only works because the paper exploits two regularities at once. First, routing history provides enough short-term locality to predict which experts are likely to be selected for the next token. Second, low-order weight refinements exhibit repeated base-delta patterns, so many deltas do not need to be fetched verbatim every time. EARTH turns those observations into a runtime policy: always prefetch bases of predicted experts, fetch real deltas for high-importance experts, skip deltas for low-importance experts, and reconstruct reused deltas from a small LUT for the middle tier. In effect, EARTH converts "which full experts should I fetch?" into "how much fidelity does each routed expert deserve right now?"

## Design

EARTH begins with dual-entropy encoding. For an INT8 expert, each weight is split into a 4-bit high-order base and a 4-bit low-order delta. The paper motivates this as a hardware-friendly partition: it preserves a compositional structure for arithmetic, keeps accesses byte-aligned, and matches common PE data widths. Operationally, the split creates a sliceable expert format. The base can be prefetched widely and used alone for approximate execution; the delta is a conditional refinement path instead of mandatory payload.

The speculative prefetcher uses routing history from the gating layer to predict upcoming experts and places their base parts into an on-chip FIFO buffer. Once the actual routing result arrives, EARTH handles three cases. On a prefetch hit for a high-importance expert, it fetches the real delta so the expert runs at full fidelity. On a hit for a low-importance expert, it skips the delta entirely and computes with the base only. On a miss, it loads only the correct base, so the miss penalty is much smaller than fetching a whole expert. The importance thresholds are calibrated offline so that skipped deltas keep quality within about 1% of baseline perplexity.

After base-only prefetching reduces the first bottleneck, delta traffic becomes the next one. EARTH's second mechanism, pattern reuse, targets that shift explicitly. Offline, the authors profile dominant `<base, delta>` pairs and encode them in a LUT, arguing that only tens of unique patterns dominate even as model size changes. At runtime, experts with moderate gating weight use speculative delta reuse: the fetched base indexes the LUT, the predicted delta is reconstructed on chip, and DRAM access is avoided. This "match and action" path is the key difference between EARTH and a plain base-only prefetcher.

The hardware architecture is built around that representation. EARTH has a 16-PE compute core, banked weight and token buffers, a gating module with top-k selection, a weight dispatcher that performs LUT-based delta reconstruction, and an output-stationary dataflow that unicasts weights but broadcasts activations. The evaluation section fixes the on-chip storage at a 16 MB weight buffer and a 1 MB token buffer. The controller pipelines on-chip load, weight dispatch, activation dispatch, PE compute, accumulation, and write-back so that delta decoding overlaps with compute rather than serializing behind it.

## Evaluation

The evaluation is thorough in architectural terms, though it is largely modeled rather than measured on silicon. The authors implement EARTH in Verilog RTL, synthesize it in TSMC 28 nm at 250 MHz, use CACTI 7 for SRAM modeling, and drive a custom cycle-accurate simulator with fixed-length traces. They test three representative MoE LLMs: Mixtral-8x7B-Instruct, Qwen1.5-MoE-A2.7B, and DeepSeek-V2-Lite-Chat, using CNN/DM and LongBench Gov_report workloads. Baselines include EdgeMoE, AdapMoE, DAOP, HybriMoE, and APTMoE.

The main headline is end-to-end speedup. Across the three models, EARTH achieves 1.56x-2.10x lower latency than the compared baselines, with the best result on Mixtral. The reported compute-transfer overlap ratio is also high, at 86%-91%, which supports the paper's main claim that the design is really hiding memory stalls rather than merely reducing arithmetic. The ideal-versus-practical comparison is helpful here: EARTH reaches 90.5% of ideal speedup on Mixtral, 93.2% on Qwen, and 94.0% on DeepSeek.

The accuracy-versus-bandwidth story is also reasonably convincing. When the configuration keeps 80%-90% of experts in the important tier, the paper reports over 20% reduction in loading demand with negligible Rouge-L loss. On DeepSeek, more aggressive settings still deliver load reduction above 40%, and the conclusion highlights up to 48% lower memory traffic overall. The ablation study further shows the stepwise value of the design: naive prefetch gives only 1.12x speedup, adding speculative base prefetch reaches 1.52x, and full EARTH with delta reuse reaches 2.06x in the reported setup.

Energy and area numbers reinforce that this is not just a latency paper. On DeepSeek-V2-Lite-Chat, EARTH uses 0.59x of AdapMoE's total energy and 21.54% less energy than EdgeMoE. The synthesized chip area is 27.52 mm2, with the PE array dominating at 77.55% and the added LUTs plus control logic occupying only 6.08%. That supports the authors' argument that the reuse machinery is cheap relative to the compute substrate. My main reservation is that the comparison spans heterogeneous prior systems and relies on the authors' own normalized modeling stack rather than one shared implementation, so the broad trend is convincing but exact cross-system deltas should be read with that caveat.

## Novelty & Impact

Relative to _Hwang et al. (ISCA '24)_, which predicts experts early for faster MoE inference, EARTH's novelty is to shrink the payload itself through base-delta decomposition and then use hardware-managed delta recovery. Relative to _Zhang et al. (DATE '25)_ and _Wei et al. (SC '24)_, which optimize offloading and loading schedules across CPU/GPU memory hierarchies, EARTH is a more explicit accelerator co-design: representation format, prefetch policy, and datapath are all chosen together. Relative to vision-oriented FPGA accelerators such as _Sarkar et al. (ICCAD '23)_, EARTH is much more focused on LLM-style MoE weight movement rather than task-level sparsity alone.

That makes the paper likely to matter to two communities. Hardware architects can cite it as an example of attacking MoE inference through representation-aware memory scheduling, not just larger bandwidth. Systems researchers working on MoE serving can cite it as evidence that expert importance and partial-fidelity execution are useful scheduling signals even below the software runtime. The work is therefore a genuine mechanism paper, not just a measurement study.

## Limitations

EARTH depends on several offline assumptions. The importance thresholds and reuse LUT are calibrated ahead of time, so portability across models, quantization schemes, and deployment targets is not free. The design also assumes that routing history remains predictive enough for speculative prefetch and that dominant base-delta patterns remain stable enough for reuse; the paper does not deeply probe adversarial or highly non-stationary routing regimes.

The evaluation is also narrower than the headline might suggest. It focuses on single-accelerator inference under modeled hardware conditions, not distributed expert parallelism, multi-tenant serving, or training. Accuracy is reported through downstream metrics such as Rouge-L rather than a fuller set of serving-quality measurements, and the paper does not provide a fabricated prototype or runtime integration beyond RTL plus simulation. Finally, the 4/4 split is motivated as practical and hardware-friendly, but the paper does not show whether that partition remains best across wider quantization choices.

## Related Work

- _Hwang et al. (ISCA '24)_ — Pre-gated MoE predicts experts earlier, while EARTH combines prediction with a base-delta representation so the speculatively moved payload is smaller.
- _Zhang et al. (DATE '25)_ — DAOP uses CPU/GPU offloading and predictive pre-calculation, whereas EARTH assumes a dedicated accelerator and attacks the same bandwidth problem with on-chip reconstruction and reuse.
- _Wei et al. (SC '24)_ — APTMoE tunes expert loading on bandwidth-constrained GPU nodes; EARTH instead co-designs the weight format and datapath for resource-constrained accelerator hardware.
- _Sarkar et al. (ICCAD '23)_ — Edge-MoE is an FPGA accelerator for MoE vision workloads, while EARTH is tailored to LLM-style expert offloading and treats expert-fetch latency as the first-order bottleneck.

## My Notes

<!-- empty; left for the human reader -->
