---
title: "Wave: Leveraging Architecture Observation for Privacy-Preserving Model Oversight"
oneline: "Wave infers LLM structure from GPU PMC traces and uses SMT checks to catch downsized or disguised inference without exposing weights or prompts."
authors:
  - "Haoxuan Xu"
  - "Chen Gong"
  - "Beijie Liu"
  - "Haizhong Zheng"
  - "Beidi Chen"
  - "Mengyuan Li"
affiliations:
  - "University of Southern California, Los Angeles, CA, USA"
  - "Carnegie Mellon University, Pittsburgh, PA, USA"
conference: asplos-2026
category: privacy-and-security
doi_url: "https://doi.org/10.1145/3779212.3790247"
code_url: "https://github.com/sept-usc/Wave"
tags:
  - llm-inference
  - security
  - observability
  - gpu
  - hardware
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Wave treats the GPU as an impartial witness for LLM inference. It collects a small set of GPU performance counters, reconstructs an architectural sketch of the model being executed, and then uses SMT solving to test whether any canonical Transformer consistent with those counters could violate the provider's promised model size or configuration.

## Problem

The paper targets outsourced inference settings where users pay for a claimed model but cannot inspect weights, kernels, or deployment code. A model provider under cost pressure could silently swap in a smaller model, alter the batch structure, or even inflate token counts while still returning superficially plausible answers. Output-only checks are weak here: watermarks and timing channels are indirect, software audits need access to internals, and zero-knowledge proofs are still expensive enough to be impractical for routine monitoring.

What the authors want instead is runtime evidence that is both privacy-preserving and difficult to fake. GPU PMCs are attractive because they expose aggregate compute and memory behavior rather than model weights or prompts. The challenge is that PMCs arrive as noisy kernel-level traces, not as a clean architectural log. An untrusted deployer can also rename kernels, split or fuse GEMMs, pad execution, or reorder work to confuse any monitor that relies on identifiers or simple thresholds.

## Key Insight

Wave's core claim is that decoder-only Transformer inference obeys hardware-constrained invariants that survive implementation noise. Once the architecture fixes quantities such as layer count, hidden size, FFN width, and whether QKV or FFN blocks are fused, the execution must induce corresponding relationships among FLOPs, off-L1 memory traffic, shared-memory intensity, and periodic repetition across layers and tokens.

That means a verifier does not need to recover weights or exact kernels. It only needs to recover a coarse architectural sketch from the PMC stream, then ask a stronger question: does there exist any canonical Transformer explanation, under allowed attack transformations, that both matches the observed counters and violates the provider's promise? Separating trace interpretation from formal checking is what lets Wave turn a noisy side-channel into an oversight mechanism.

## Design

Wave assumes the PMC trace itself is trustworthy: hardware collects counters during execution and signs them, for example via a future TEE or GPU-rooted attestation path. The deployer may change the model being run and may manipulate kernel structure, but cannot forge the physical counts reported by the GPU. The prototype focuses on single-GPU decoding with KV cache enabled and explicitly excludes distributed inference, MoE, and heavily optimized engines such as vLLM or SGLang.

Stage I, execution trace inference, reduces each observed kernel `k` to a 3-D signature: FLOPs `F(k)`, shared-memory ratio `r_sh(k)`, and off-L1 traffic `B_tot(k)`. Those features are derived from nine Nsight metrics covering scalar FMA/ADD/MUL buckets and global/shared-memory accesses. Wave then self-correlates the feature stream to detect two nested periods: a large period for one generated token and a smaller one for a Transformer layer. Counting large periods recovers token count, which can expose naive token inflation; counting small periods inside them recovers the number of layers.

After segmentation, Wave performs in-layer role assignment against a canonical layer template `S* = (QKV, Attn, O, Add, FFN, Add)`. Kernels are first classified as matmul-like, attn-like, or add-like using FLOPs and shared-memory behavior. The system then distinguishes among Q/K/V/O and FFN roles by comparing off-L1 traffic and FLOP ratios, while allowing the main implementation variants the paper sees in practice: fused or split QKV and 2-gate or 3-gate FFNs. From the assigned roles, Wave recovers dtype from the dominant scalar-FMA bucket, estimates `b*d` from projection stores, solves for hidden size `d` from projection loads, derives batch size `b`, and finally infers `d_ffn` and approximate parameter count `M = L(4d^2 + lambda*d*d_ffn)`.

Stage II turns those observations into a verifier. The paper models a canonical execution as matrix multiplies and additions with analytical lower and upper bounds on FLOPs, global loads, and global writes. It then defines an attack family consisting mainly of split attacks, where one canonical matmul is partitioned into smaller kernels, and uses `UndoAttack` to map a candidate observed sequence back to a canonical one. Verification asks whether there exists an observed sequence `S'` and allowed attack such that `PMC(S')` fits the trace within tolerance while the reconstructed `S*` violates the provider's promise, either `M(S*) >= M_promise` for lower-bound checks or `M(S*) <= M_promise` for upper-bound checks. If Z3 finds such a witness, Wave returns `Fail`; otherwise the claim passes under the stated model.

## Evaluation

The evaluation spans RTX 4090, RTX 5080, and H100 GPUs with CUDA 12.8, PyTorch 2.7.0, and Nsight Compute 2025.x. The authors instantiate GPT-2, LLaMA, and Qwen architectural templates over hidden sizes `512-8192`, model sizes from roughly `25M` to `10B`, and selected batch sizes up to `16`, using mostly FP32. This is an architectural study rather than a benchmark on production checkpoints or modern serving stacks.

Stage I works well as a fingerprinting tool. Wave distinguishes GPT-2 from LLaMA/Qwen by the combination of fused-vs-split QKV and 2G-vs-3G FFN motifs across all tested GPUs. It reliably recovers precision, batch size, layer count, and token count, and the average recovery error is about `7%` for hidden size, `3%` for FFN width, and `11%` for overall model size; the paper's abstract summarizes key-parameter recovery at `6.8%` average error. Figure 4 further shows that measured QKV load-miss bytes closely track the theoretical `(d^2 + b*s*d) * D` curve, which is the empirical basis for their parameter-recovery formulas.

Stage II is more mixed but still informative. For lower-bound verification across `44` detailed model settings, the solver reports no false positives on any of the three GPUs. The main failures are false negatives caused by global-load deviations that exceed the paper's tolerance model, especially at larger batch sizes where weights may be reloaded more often than the analytical model assumes; the authors also note occasional under-reported global writes for `b = 1`. For upper-bound verification, they build a one-layer GPT-2-like model with randomly split linear layers on an RTX 4090 and report no false positives or false negatives across `14` split configurations, with each check finishing within `1` minute. The big practical downside is profiling cost: full Wave metric collection slows execution by at least `1196%` even on H100, and monitoring just one hardware metric still costs `52%-1333%` depending on the GPU.

## Novelty & Impact

Relative to _Sun et al. (CCS '24)_, Wave gives up cryptographic exactness and instead offers a much lighter hardware-based test of whether the promised model structure was plausibly executed. Relative to _Tople et al. (ACNS '18)_, it is not generic resource accounting inside trusted isolation; it is LLM-specific structural oversight grounded in Transformer algebra. Relative to _Hu et al. (ASPLOS '20)_, which uses GPU side signals to extract DNN architectures as an attack, Wave flips the same observation channel into a defensive verifier.

That makes the paper feel like both a new mechanism and a new framing. It shows that PMCs can be more than performance diagnostics or side channels: they can serve as signed evidence for model-accountability checks. People building GPU TEEs, cloud attestation services, or ML audit pipelines will likely cite it as a concrete design point, even if the current prototype is not deployment-ready.

## Limitations

The paper is candid about its limits. Wave does not verify exact weights, distinguish base models from fine-tuned variants, or handle production-grade optimizations such as quantization, operator fusion, continuous batching, or distributed multi-GPU execution. It also focuses mainly on the decode phase; the authors argue prefill could be added later, but do not validate that path.

More fundamentally, Wave depends on infrastructure that does not really exist yet for tenants: trustworthy low-overhead PMC access, authenticated trace delivery, and perhaps TEE support around the verifier. The current prototype relies on Nsight Compute, whose overhead is far too high for online deployment. The formal guarantees are also only as good as the attack family and tolerance bounds: if real deployments use transformations outside the modeled split attacks, or if hardware noise exceeds the bound, the solver can miss violations.

## Related Work

- _Sun et al. (CCS '24)_ — zkLLM offers much stronger end-to-end correctness guarantees, but pays cryptographic overhead that Wave is explicitly trying to avoid.
- _Tople et al. (ACNS '18)_ — VeriCount measures resource usage with hardware/software isolation, whereas Wave tries to infer LLM structure directly from GPU execution traces.
- _Hu et al. (ASPLOS '20)_ — DeepSniffer shows that hardware traces leak DNN architectural hints; Wave repurposes that same style of signal as a verifier instead of an extraction attack.
- _Kumar et al. (AIMLSystems '21)_ — this PMC-based DNN layer-type side channel supports Wave's premise that microarchitectural counters can reveal model structure even without access to weights.

## My Notes

<!-- empty; left for the human reader -->
