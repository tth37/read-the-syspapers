---
title: "Hardwired-Neuron Language Processing Units as General-Purpose Cognitive Substrates"
oneline: "Hardwires an FP4 LLM into metal-programmable neuron arrays so a 16-chip structured ASIC removes weight fetches and makes custom LLM inference economically plausible."
authors:
  - "Yang Liu"
  - "Yi Chen"
  - "Yongwei Zhao"
  - "Yifan Hao"
  - "Zifu Zheng"
  - "Weihao Kong"
  - "Zhangmai Li"
  - "Dongchen Jiang"
  - "Ruiyang Xia"
  - "Zhihong Ma"
  - "Zisheng Liu"
  - "Zhaoyong Wan"
  - "Yunqi Lu"
  - "Ximing Liu"
  - "Hongrui Guo"
  - "Zhihao Yang"
  - "Zhe Wang"
  - "Tianrui Ma"
  - "Mo Zou"
  - "Rui Zhang"
  - "Ling Li"
  - "Xing Hu"
  - "Zidong Du"
  - "Zhiwei Xu"
  - "Qi Guo"
  - "Tianshi Chen"
  - "Yunji Chen"
affiliations:
  - "State Key Lab of Processors, Institute of Computing Technology, Chinese Academy of Sciences, Beijing, China"
  - "University of Chinese Academy of Sciences, Beijing, China"
  - "University of Science and Technology of China, Hefei, China"
  - "Institute of Software, CAS, Beijing, China"
  - "Cambricon Technologies, Beijing, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790169"
tags:
  - hardware
  - llm-inference
  - energy
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

The paper argues that if one frontier LLM really becomes the long-lived substrate for many applications, then we should stop treating its weights as mutable data and instead fabricate them directly into silicon. Its key contribution is Metal-Embedding: encode weights in the topology of upper metal layers, not in bespoke device cells, so most photomasks stay shared across variants. That turns a previously absurd `>$6B` hardwiring path into a 16-chip HNLPU design with far lower estimated NRE, much higher throughput, and much lower energy than GPU- or wafer-scale baselines.

## Problem

The paper starts from a bottleneck that current LLM hardware cannot escape: even highly specialized LPUs still repeatedly move enormous weight tensors during autoregressive decoding. Groq- and Cerebras-style systems preload more state on chip, and transformer-specific accelerators harden more of the dataflow, but they still fundamentally treat model parameters as data fetched at runtime. The authors' claim is that this is why energy remains dominated by memory movement even after substantial architectural specialization.

The obvious extreme response is to hardwire the model itself. In principle, that gives perfect architecture-model matching, removes parameter fetching entirely, and lets the datapath collapse into constant-arithmetic circuits. The problem is economic, not conceptual. A straightforward cell-embedded implementation of `gpt-oss 120B` at `5nm` would need roughly `176,000 mm2` of compute fabric split across more than 200 heterogeneous chips, which in turn implies about `$6B` in photomask costs before volume amortization. Because a hardwired model would ship in tiny volume and would still need periodic re-spins when weights change, naive hardwiring looks commercially impossible.

So the real problem is narrower and more interesting than "can we build a hardwired LLM accelerator?" It is whether one can preserve the efficiency upside of hardwiring while reducing non-recurring engineering cost enough that a fixed-model inference platform is economically credible.

## Key Insight

The paper's central insight is that the expensive part of naive hardwiring is not merely storing many constants, but storing them in the wrong physical substrate. If weight values are expressed through the routing topology of metal layers rather than through heterogeneous silicon cells, then the parameter-dependent part of the design moves upward into cheaper, later metal layers while most lower layers become reusable across chips and across future re-spins.

That idea works because an FP4 model has only 16 unique weight values. HNLPU's Hardwired-Neuron (HN) units first exploit weight constancy, then factor repeated multipliers with the distributive law, and finally bit-serialize inputs so accumulation happens before constant multiplication. Once the computation is reorganized into this accumulate-multiply-accumulate form, the "which weight multiplies which input" choice becomes a wiring problem: connect an input signal to the accumulator region corresponding to weight `a`, `b`, `c`, and so on. The authors argue that metal topology is far denser and cheaper than cell-level embedding for this purpose, and that this is the step that makes hardwiring economically viable rather than merely physically possible.

## Design

Metal-Embedding has two layers. The first is the HN arithmetic block. Compared with a conventional constant-MAC neuron containing thousands of constant multipliers followed by a very wide adder tree, an HN groups inputs by identical weight value, popcounts the bit-serialized inputs inside each weight bucket, applies only 16 constant multipliers, and then reduces those partial sums. This shrinks both multiplier count and adder strength. The paper reports that Metal-Embedding is about `15x` denser than cell embedding for the operator-level comparison and cuts area by `93.4%` relative to a CMAC grid.

The second layer is Sea-of-Neurons, a structured-ASIC strategy. The parameter-independent HN array is prefabricated once using shared FEOL and lower-BEOL masks, while only metal layers `M8-M11` are customized per chip to encode weights. The practical consequence is the part the paper cares most about: `60` of `70` mask layers, including all EUV layers, remain homogeneous across the 16-chip system. That reduces photomask cost by `86.5%` for the initial tapeout and by `92.3%` for a parameter-only re-spin, with the paper summarizing this as a `112x` reduction versus the naive path.

On top of that embedding method, HNLPU implements a full `gpt-oss 120B` FP4 inference system. Sixteen chips are connected in a logical `4 x 4` row/column fabric over CXL 3.0. The HN array performs all fixed-weight projections; a VEX unit handles attention-score computation, RMSNorm, SwiGLU, softmax, residuals, and sampling; an on-chip `320 MB` attention buffer serves as the KV cache before spill to HBM. The mapping is designed so `Wqkv` is partitioned by column groups, `Wo` by row groups, and MoE experts are distributed independently across chips. The router weights are simply replicated everywhere because they are tiny. The system then pipelines all 36 layers and internally partitions each layer into six stages, enabling up to `216` in-flight tokens or sequences under its continuous-batching model.

## Evaluation

The evaluation is ambitious and mixes operator-level physical design results with full-system modeling. The RTL is synthesized and placed-and-routed in `5nm`, the multi-chip CXL fabric is modeled with CNSim, and the main system comparison uses the `gpt-oss 120B` FP4 model against an H100 server measured with TensorRT-LLM and a Cerebras WSE-3 configuration calibrated from public cloud measurements.

At the operator level, the paper's evidence for Metal-Embedding is fairly direct. For a representative `1 x 1024` by `1024 x 128` matrix-vector multiply, ME uses about `0.95x` the area of the SRAM block that would feed a conventional MAC array, whereas cell embedding needs `14.3x` that area. Execution cycles also drop because the hardwired operator parallelizes the entire multiplication instead of streaming weights from SRAM, and ME beats cell embedding on energy because it avoids both SRAM accesses and the large leakage penalty of a huge cell-embedded fabric.

At system level, the headline number is `249,960 tokens/s` at `6.9 kW`, which the paper converts to `36,226 tokens/kJ`. That is reported as `5,555x` the throughput and `1,047x` the energy efficiency of an H100 baseline, and `85x` / `283x` relative to WSE-3. The single-chip breakdown is also informative: each chip is `827.08 mm2`, `308.39 W`, and dominated by the HN array plus the attention buffer. The execution-time study shows that once weight movement disappears, inter-chip CXL communication becomes the leading bottleneck at short contexts, while attention computation dominates at long contexts.

The cost analysis is as central as the performance analysis. The paper estimates initial HNLPU NRE at `$59.25M-$123.3M`, parameter-update re-spins at `$18.53M-$37.06M`, and a three-year TCO improvement of `41.7x-80.4x` versus equivalently provisioned H100 clusters in an OpenAI-scale deployment. It also claims a `357x` reduction in carbon footprint. These results support the paper's core story, but with an important caveat: the throughput and power claims come from implementation and modeling, whereas the TCO conclusions depend on several assumed deployment-scale, packaging, electricity, and update-frequency parameters rather than a fabricated product.

## Novelty & Impact

Relative to _Yu et al. (MICRO '24)_ on Cambricon-LLM, HNLPU's novelty is not another memory hierarchy for large-model inference but the decision to eliminate model-weight fetches entirely by hardwiring the model. Relative to _Yu et al. (OSDI '22)_ on Orca and other serving-system work, it shifts the optimization target from scheduling around memory traffic to physically removing that traffic. Relative to _Sankaralingam et al. (ISCA '22)_ on Mozart-style specialized dataflow processors, it goes one step further and gives up most programmability in exchange for a fixed-model cognitive substrate.

That makes the paper important less as an immediately deployable product than as a reframing. It argues that if frontier-model deployment really converges to a few long-lived models, then the "general-purpose" boundary should move upward from hardware/software into the model and prompt interface. If that assumption holds, HNLPU is a new mechanism with unusually strong economic framing; if it does not, much of the argument weakens quickly.

## Limitations

The paper's biggest limitation is the deployment regime it assumes. HNLPU only makes sense if one model is valuable enough, stable enough, and high-volume enough to justify custom masks and multi-week re-spin cycles. That is a plausible hyperscaler scenario, but far from a universal one. The design also remains tied to one hardwired `gpt-oss 120B` FP4 configuration, so changes in architecture, quantization format, or software features are much more disruptive than on GPUs.

The evaluation is also partly prospective. The paper shows sign-off-grade layout results and detailed modeling, but not fabricated silicon. Some headline comparisons therefore mix measured baselines with simulated or estimated HNLPU numbers. Finally, the authors themselves show that CXL communication becomes a first-order bottleneck once weight movement is removed, and their discussion section leaves flexibility features such as LoRA-style updates, programmable decoding, and more automated design flow to future work.

## Related Work

- _Yu et al. (OSDI '22)_ — Orca improves distributed Transformer serving in software, whereas HNLPU argues the dominant inefficiency is weight movement and removes it in hardware.
- _Sankaralingam et al. (ISCA '22)_ — Mozart exposes reusable AI dataflow but remains a programmable processor; HNLPU instead specializes all the way down to one hardwired model.
- _Yu et al. (MICRO '24)_ — Cambricon-LLM uses chiplets and hybrid architecture to run a 70B LLM on device, but still treats weights as data in memory rather than metalized structure.
- _Mei et al. (ASPLOS '25)_ — Helix tackles heterogeneous-GPU serving and network scheduling, which is nearly the opposite design point from HNLPU's fixed-model, fixed-fabric specialization.

## My Notes

<!-- empty; left for the human reader -->
