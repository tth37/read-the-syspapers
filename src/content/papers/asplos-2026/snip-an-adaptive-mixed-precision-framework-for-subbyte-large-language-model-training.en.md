---
title: "SNIP: An Adaptive Mixed Precision Framework for Subbyte Large Language Model Training"
oneline: "SNIP periodically reassigns FP4/FP8 per transformer linear layer by estimating forward loss divergence and backward weight drift, then solving an ILP."
authors:
  - "Yunjie Pan"
  - "Yongyi Yang"
  - "Hanmei Yang"
  - "Scott Mahlke"
affiliations:
  - "University of Michigan, Ann Arbor, Michigan, USA"
  - "NTT Research, Inc., Sunnyvale, California, USA"
  - "University of Massachusetts Amherst, Amherst, Massachusetts, USA"
conference: asplos-2026
category: llm-training
doi_url: "https://doi.org/10.1145/3779212.3790223"
tags:
  - llm-training
  - gpu
  - energy
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

SNIP treats mixed-precision LLM pretraining as a repeated optimization problem instead of a fixed recipe. It estimates how much each layer would hurt convergence in the forward pass and backward pass if moved to lower precision, then solves an ILP to decide which linear layers can run in FP4 and which should stay in FP8. That lets it push subbyte training to much more aggressive FP4 budgets without the instability seen in uniform or heuristic schemes.

## Problem

The paper starts from a hardware trend that makes the systems problem sharp. Hopper-class GPUs already make FP8 training materially faster than BF16, and Blackwell-class GPUs promise another step down to FP4. In principle that should cut LLM pretraining cost, runtime, and even carbon footprint. In practice, naively using one precision everywhere does not work well. Uniform FP8 leaves efficiency on the table because many layers could likely tolerate FP4, while uniform FP4 often destabilizes training. The key difficulty is that layer sensitivity is not constant: it depends on layer type, layer position, model size, and training phase.

Prior adaptive schemes are not satisfying in this setting. Some use empirical rules such as keeping the first or last layers at higher precision, or treating whole layer types as sensitive. Others optimize local quantization error, such as absolute or relative rounding error, but ignore how those local errors affect end-to-end training dynamics. The authors argue that LLM pretraining needs a quality metric tied to optimization itself, not just tensor reconstruction fidelity. Otherwise a layer that looks safe under a local error metric may still inject enough forward loss increase or gradient distortion to hurt convergence later.

## Key Insight

The paper's main claim is that the training impact of quantization can be decomposed into two quantities that are cheap enough to estimate online and informative enough to drive global precision decisions. The first is forward loss divergence: how much quantization of a layer's activations or weights increases the loss in the current step. The second is backward weight divergence: how much quantization noise perturbs gradients and therefore changes the optimizer's weight updates away from the high-precision trajectory.

That decomposition matters because pretraining quality is not just about immediate loss. A layer can have modest forward error yet still distort optimizer state and accumulate damage over many updates. SNIP therefore does not ask "which layers have the smallest quantization error?" It asks "which layers can absorb lower precision while keeping both instantaneous loss growth and update drift small enough under a target efficiency budget?" Once that question is written down layer by layer, an ILP can choose the globally best mixture instead of relying on heuristics.

## Design

SNIP targets the linear layers inside Llama-style transformer blocks, which the paper says account for more than 90% of training FLOPs. Other operations such as RMSNorm, SwiGLU, Softmax, and attention remain in BF16. The mixed-precision substrate follows the common training pattern: GEMMs run in low precision, outputs stay in BF16, master weights stay in FP32, activations and gradients use 1x128 tilewise quantization, and weights use 128x128 blockwise quantization. The paper evaluates FP8 and FP4, using E2M1 for FP4 and stochastic rounding for FP4 output gradients.

The runtime works in six steps, executed periodically and mostly asynchronously with training. Step 1 runs a normal BF16 iteration while collecting Frobenius norms for activations, weights, outputs, gradients, quantization errors, and AdamW optimizer state. Steps 2 and 3 add small Gaussian noise in the backward pass and forward pass respectively, then dump gradients so the system can estimate second-order sensitivity without explicitly forming Hessians. Step 4 converts those statistics into normalized loss divergence and normalized weight divergence. Step 5 formulates an ILP whose objective is the weighted sum `Q = ΔL + ΔW`, while efficiency is proxied by the fraction of FLOPs assigned to FP4. Step 6 applies the new layer-wise FP4/FP8 scheme asynchronously and keeps using it until the next update.

The nice systems touch is that SNIP also extends the ILP for pipeline parallelism. Instead of enforcing only a global FP4 budget, it adds per-stage efficiency constraints so one slow pipeline stage does not erase the theoretical gain from more aggressive quantization elsewhere. That makes the method compatible with the multi-stage training setups used for the largest models.

## Evaluation

The evaluation covers TinyLlama 1B, OpenLlama 3B, OpenLlama 7B, and an industry 70B Llama-like model, using resumed checkpoints across multiple training phases. The smaller models run on A40 or A100 systems with Hugging Face and DDP, while the 70B setup uses 64 H100s with FSDP, tensor parallelism, and pipeline parallelism. Because the authors do not have hardware with native FP4 and FP8 support in the same environment, they use fake quantization and treat the fraction of FP4 FLOPs as the efficiency metric rather than claiming direct wall-clock speedups.

Within that scope, the results are strong. On TinyLlama at the 50k checkpoint, SNIP remains essentially at BF16 quality even when 75% of linear-layer FLOPs are assigned to FP4: its average benchmark score is `44.21` versus `44.22` for BF16, while heuristic and local-error baselines collapse into the low `33` range. The paper also reports that SNIP maintains nearly full-precision accuracy even at `80%` FP4 FLOPs, whereas alternative schemes fail to converge. In a from-scratch 1B experiment at 75% FP4 FLOPs, BF16 reaches training loss `5.27` and SNIP reaches `5.34`, while the other schemes visibly diverge. For the 70B model under a 50% FP4 budget, SNIP tracks the BF16 loss curve much more closely than FP4-only, min-rel-err, or E-layer-type baselines, and its downstream accuracy remains stable.

I found the evaluation convincing for the paper's actual claim: SNIP is a better policy for assigning subbyte precision during LLM pretraining. It is less convincing for end-to-end throughput claims on future hardware, because those are inferred from FP4 FLOP share rather than measured directly.

## Novelty & Impact

Relative to _Micikevicius et al. (ICLR '18)_, the novelty is not mixed precision itself but turning precision selection into an online, layer-wise optimization problem for LLM pretraining. Relative to empirical policies such as protecting only certain layer ids or layer types, SNIP contributes a more principled objective that explicitly models both forward loss increase and optimizer-update drift. Relative to _Chmiel et al. (ICLR '23)_, which studies accurate 4-bit training at the numerical-format level, SNIP operates one level up: it assumes low-precision formats exist and decides where each one should be used during pretraining.

That makes the paper useful to two groups. Systems builders can treat it as a scheduling policy for precision budgets across a transformer, especially as native FP4 hardware becomes common. ML systems researchers can treat it as evidence that the right optimization target for adaptive precision is training trajectory preservation, not local quantization error alone.

## Limitations

The largest limitation is that efficiency is a proxy, not a direct runtime measurement. Since the experiments rely on fake quantization and do not run on a platform with native FP4 and FP8 kernels, the paper shows which layers should move to FP4, but not the exact end-to-end speedup operators would see in deployment. The method also adds overhead: the paper reports that the extra GPU-side statistics/noise-injection steps take roughly `10` minutes per update cycle, and the CPU-side analysis plus ILP solving adds about `15` more minutes. The authors argue this is acceptable if updates are done about every `100k` steps, but it is still an engineering tradeoff.

The method is also somewhat model- and setup-specific. Its statistics collection and optimization are built around linear layers, AdamW, and the paper's chosen quantization granularities. The paper says the method is broadly compatible with other differentiable optimizers and parallelism strategies, but that generality is argued more than exhaustively demonstrated. Finally, the 70B study is restricted to a shorter training window because of cost, so the paper does not fully prove long-horizon behavior at that scale.

## Related Work

- _Micikevicius et al. (ICLR '18)_ — established the standard mixed-precision recipe with low-precision compute and FP32 master weights; SNIP adds adaptive, per-layer precision choice for LLM pretraining.
- _Agarwal et al. (MLSys '21)_ — ACCORDION adapts communication based on critical learning regimes, while SNIP adapts numeric precision by estimating quantization harm directly.
- _Ansel et al. (ASPLOS '24)_ — PyTorch 2 and AMP automate mixed-precision execution, whereas SNIP changes the precision policy itself rather than only the implementation path.
- _Chmiel et al. (ICLR '23)_ — studies how to make 4-bit training numerically viable; SNIP is complementary because it decides which transformer layers should actually use lower precision.

## My Notes

<!-- empty; left for the human reader -->
