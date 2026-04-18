---
title: "Mugi: Value Level Parallelism For Efficient LLMs"
oneline: "Extends value-level parallelism from GEMM to nonlinear ops and BF16-INT4 small-batch LLM inference so one array can run the full pipeline more efficiently."
authors:
  - "Daniel Price"
  - "Prabhu Vellaisamy"
  - "John P. Shen"
  - "Di Wu"
affiliations:
  - "University of Central Florida, Department of ECE, Orlando, FL, USA"
  - "Carnegie Mellon University, Department of ECE, Pittsburgh, PA, USA"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790189"
tags:
  - llm-inference
  - hardware
  - energy
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Mugi argues that value-level parallelism (VLP) should not stop at low-precision GEMM. By reformulating nonlinear functions and asymmetric BF16-INT4 GEMMs around value reuse, it lets one VLP-style array cover softmax, SiLU, GELU, and the core matrix operations of LLM inference. The payoff is very large nonlinear speedups and a more modest but still meaningful end-to-end LLM gain, plus lower operational and embodied carbon.

## Problem

Prior VLP work such as Carat was built for a much simpler regime than modern LLM inference: large-batch, symmetric, low-precision GEMM. Transformer inference is different in four ways the paper cares about. First, the runtime is not only GEMM. Softmax, SiLU, and GELU matter, and if they are left unoptimized they can consume a noticeable fraction of runtime. Second, LLM deployments increasingly use asymmetric quantization, especially BF16 activations with INT4 weights or INT4 KV cache, while prior VLP designs assumed more symmetric formats such as FP8-FP8. Third, real-time serving prefers small batches, which hurts the utilization story of architectures tuned for large-batch reuse. Fourth, many accelerators bolt separate nonlinear units next to matrix engines, which increases area and therefore embodied carbon.

The obvious fallback is to keep using a conventional GEMM accelerator and approximate nonlinear functions with separate Taylor-series or piecewise-linear hardware. The paper's critique is that this leaves reuse opportunities on the table twice: once because nonlinear operations are still treated as a separate problem, and again because the GEMM side is mismatched to the quantization and batching patterns LLMs actually use. The target problem is therefore broader than "make one kernel faster." It is to design a single architecture that remains efficient across the full LLM inference path.

## Key Insight

The paper's core idea is that VLP can be generalized from multiplication to function approximation if the input is decomposed into fields that expose reusable structure. For nonlinear functions, Mugi splits floating-point inputs into sign, mantissa, and exponent, approximates the input rather than the output, and then uses two temporal subscription steps to recover the final lookup result. This matters because the architecture can spend its precision budget where the workload actually lives instead of treating all input ranges equally.

The second half of the insight is that LLM-friendly asymmetric GEMM also becomes VLP-friendly if the mapping is transposed. Mugi places INT4 weights or KV values on rows and BF16 activations or queries on columns, which keeps utilization high for batch size 8 and grouped-query attention (GQA) group size 8. Taken together, these two observations let the same compute substrate support both nonlinear operators and BF16-INT4 GEMM, which is why the paper can claim gains in throughput, efficiency, and carbon rather than only in one isolated microbenchmark.

## Design

For nonlinear operations, Mugi first reformulates a lookup-table computation into four phases: input-field split, value reuse, mantissa temporal subscription, and exponent temporal subscription. The input mantissa is rounded down to a smaller representation, then the architecture retrieves a row of precomputed values that share the same sign-mantissa pattern, and finally subscribes to the right element in time using temporal spikes. The total latency is the sum of the mantissa and exponent subscription delays. For softmax, Mugi computes exponentials this way, accumulates the sum in the output accumulator, stores that sum, and then uses a small vector unit to multiply each `exp` result by the reciprocal.

The accuracy trick is value-centric approximation. The authors profile the exponent distributions of softmax, SiLU, and GELU and observe that important values cluster in a smaller range than the full representable input domain. Mugi therefore stores only a sliding LUT window over those important exponents rather than covering the entire space uniformly. It also rounds mantissas aggressively, to 3-bit magnitude in the walkthrough example, because the measured error is relatively uniform while the savings in temporal-signal length are large. The result is not "most accurate everywhere"; it is "most accurate where the workload spends its probability mass."

For GEMM, Mugi departs from Carat in two practical ways. The first is format customization: rows carry INT4 weights or quantized KV cache, while columns carry BF16 activations or query tokens. That aligns the datapath with weight-only quantization (WOQ), KV-cache quantization (KVQ), and GQA, instead of forcing BF16 values through the temporally encoded dimension. The second is buffer minimization. By relying on broadcasting and what the paper calls output-buffer leaning, Mugi cuts total buffer area by `4.5x` relative to the FIFO-heavy structure inherited from prior VLP designs.

At the architectural level, Mugi combines `M-proc`, `E-proc`, LUT-backed `iSRAM`, temporal converters, processing elements, post-processing blocks, output accumulators, and a vector unit in one design. The same array handles nonlinear work and GEMM, while a 2D mesh NoC can scale the design out across nodes with output-stationary dataflow and inter-node accumulation. That shared-array story is the real invariant of the paper: the nonlinear side is not an add-on, and the GEMM side is not optimized in isolation.

## Evaluation

The evaluation spans both workload-level accuracy and architecture-level performance. On the workload side, the authors profile Llama 2 `7B/13B/70B`, Whisper Tiny/Large, SwinV2 Tiny/Large, and ViViT, using HuggingFace implementations and 100 inferences per model. On the hardware side, they simulate a 45nm design at `400 MHz` with `256 GB/s` HBM bandwidth, synthesize the basic modules, and place-and-route a single 8x8 Mugi node. That setup is broad enough to test the paper's main claim that one architecture can serve both nonlinear kernels and LLM GEMMs, though the absolute carbon numbers should be read as modeled rather than silicon-measured; that is my inference from the evaluation methodology.

For nonlinear operations, the results are strong. The paper reports that Mugi usually matches or beats Taylor-series, piecewise-linear, and partial-approximation baselines in end-to-end perplexity or loss, with Llama 2 as the main awkward case because its softmax distributions vary more by layer. The throughput and efficiency gains are the headline numbers: up to `45x` throughput and `667.85x` energy efficiency for nonlinear operators, with softmax alone seeing `45x` throughput and `481.07x` energy-efficiency improvement over a precise vector array in the iso-area comparison. That supports the central value-centric approximation argument well.

For end-to-end LLM inference, the gains are smaller but more meaningful. In the single-node comparison on Llama 2 70B with GQA, batch size `8`, and sequence length `4096`, `Mugi (256)` improves throughput, energy efficiency, and power efficiency by `2.07x`, `3.11x`, and `1.50x` over a baseline 16-high systolic array. It also reduces operational and embodied carbon by `1.45x` and `1.48x`. The multi-node NoC results preserve the same qualitative ranking. One nuance the paper itself makes visible is that Mugi's raw full-workload throughput is nearly tied with Carat in Table 3, while energy efficiency is clearly better. That is consistent with the paper's real contribution: not faster GEMM alone, but eliminating the need for separate nonlinear machinery and matching the LLM-serving regime better.

## Novelty & Impact

Relative to _Pan et al. (ASPLOS '24)_, Mugi's novelty is not merely "another VLP accelerator." It extends VLP to nonlinear approximation and retools the GEMM mapping for asymmetric BF16-INT4, small-batch, GQA-heavy inference. Relative to conventional Taylor or piecewise-linear nonlinear units, its novelty is also architectural: nonlinear work is folded into the same value-reuse substrate rather than delegated to a side engine.

That makes the paper interesting to at least two groups. Accelerator architects can cite it as a concrete argument that reuse-oriented arithmetic should be designed around workload value distributions, not only around operator syntax. LLM-system builders may also cite it as evidence that quantization choices, KV-cache format, and GQA are not just software-level optimizations; they can change which hardware mapping is sensible.

## Limitations

The paper is candid about several gaps. Mugi does not fully support every LLM operation: layer normalization would run on the vector unit, while rotary positional embedding (RoPE) would either need its own approximation path or offloading to external hardware. The authors also argue that the design should generalize to mixture-of-experts and multimodal models, but they do not validate that claim directly.

Another limitation is the reliance on offline LUT construction and profiled value distributions. The sliding-window mechanism helps with drift, and the paper argues that quantized KV-cache and FFN values are already stable enough for this to work, but there is no online mechanism that retunes LUT contents as the workload changes. A reviewer-style concern is that the carbon story is somewhat technology-dependent because the study is modeled at 45nm; that concern is an inference from the setup, not an explicit paper claim.

## Related Work

- _Pan et al. (ASPLOS '24)_ — Carat introduced VLP for multiplier-free GEMM, while Mugi extends the idea to nonlinear approximation and LLM-shaped asymmetric GEMM.
- _Wu et al. (ISLPED '21)_ — UNO virtualizes nonlinear operations with dedicated approximation hardware; Mugi instead shares the main VLP array across nonlinear work and GEMM.
- _Zhao et al. (ISCA '24)_ — ALISA accelerates LLM inference with sparsity-aware KV caching, whereas Mugi focuses on a more general execution substrate compatible with KVQ and GQA.
- _Qin et al. (ISCA '25)_ — MECLA improves LLM accelerators through memory-compute co-optimization and sub-matrix partitioning; Mugi's lever is value reuse plus shared hardware for nonlinear and matrix operations.

## My Notes

<!-- empty; left for the human reader -->
