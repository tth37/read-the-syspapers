---
title: "oFFN: Outlier and Neuron-aware Structured FFN for Fast yet Accurate LLM Inference"
oneline: "oFFN reorders FFN weights around stable outlier dimensions and hot/cold neurons to predict ReLU sparsity more accurately and run each region on its best GPU path."
authors:
  - "Geunsoo Song"
  - "Hoeseok Yang"
  - "Youngmin Yi"
affiliations:
  - "Sogang University, Seoul, Republic of Korea"
  - "Santa Clara University, Santa Clara, CA, USA"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790194"
tags:
  - llm-inference
  - gpu
  - memory
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

oFFN accelerates ReLU-fied LLM inference by treating two empirical regularities as first-class structure: activation outliers occur in a small, stable set of dimensions, and neurons have highly skewed activation frequencies. It reorders FFN weights offline so outlier dimensions are contiguous and hot/cold neurons are grouped, computes outlier contributions exactly during sparsity prediction, and then splits execution between dense Tensor-Core GEMM for hot neurons and predictor-guided sparse CUDA-core GEMM for cold ones. The paper reports up to `2.01x` end-to-end decoding speedup over dense inference and up to `5.46x` FFN-layer acceleration with negligible accuracy loss.

## Problem

The paper starts from a shift in where decoder latency now goes. Earlier LLM inference work mostly targeted attention because KV-cache traffic made MHA the obvious bottleneck, but the authors argue that this is no longer the whole story. With attention-side improvements such as Grouped Query Attention, sparse attention, and optimized kernels like FlashAttention, the FFN path increasingly occupies the critical path, especially in small-batch decoding where each generated token still must traverse the full stack of FFN layers.

Prior attempts to exploit FFN sparsity split into two families, both with important limits. Input-activation sparsity can skip columns in the first FFN matrix, but that disrupts coalesced memory access and often relies on thresholding near-zero activations, which risks accuracy loss. Output-activation sparsity is more attractive because zero outputs let the system skip whole weight rows and associated computation, but in non-ReLU models exact zeros are rare. ReLU-fied LLMs solve that part, yet accurate and cheap sparsity prediction remains difficult.

The authors position existing predictors as incomplete in different ways. DejaVu and PowerInfer use learned predictors, which reduces portability and adds retraining cost when the base model changes. SparseInfer is training-free and fast, but its sign-only approximation misses too much magnitude information. Grasp improves on that by grouping products and handling outliers approximately, but the paper argues that approximation error remains concentrated in a tiny set of statistically important dimensions. Separately, PowerInfer recognizes hot and cold neurons, yet mainly in a CPU-GPU hybrid setting and without integrating that observation with outlier structure or dynamic batch size. The problem, then, is to build a training-free FFN execution path that predicts sparsity accurately enough to skip substantial work, while still mapping well to GPU hardware across changing batch sizes.

## Key Insight

The paper's central claim is that two phenomena that prior work treated separately are actually coupled and can be exploited together. First, activation outliers are rare but not random: across prompts, they occur in a small, stable set of input dimensions. Second, neurons are not activated uniformly: some are "hot" and fire often, while many are "cold" and are frequently zero after ReLU. The authors argue that these hot/cold patterns are strongly tied to the stable outlier dimensions, because outliers often contribute large negative partial products for most neurons but large positive ones for a smaller aligned subset.

That observation suggests a different predictor design. Instead of approximating every partial product equally, oFFN should compute the outlier dimensions exactly, because those few dimensions dominate sparsity-prediction error. And instead of sending every neuron through the same sparse path, it should separate neurons by how often they activate, so the dense region bypasses prediction entirely while the sparse region benefits most from prediction-guided skipping. The result is not merely a better heuristic; it is a structural reorganization of the FFN so prediction accuracy and GPU execution strategy reinforce one another.

## Design

oFFN has three stages. In offline calibration, it runs a small calibration set, identifies outlier-prone activation dimensions, estimates per-neuron activation frequency, and then performs two independent weight reorderings. Column reordering moves outlier-related dimensions to the front of `Wgate` and `Wup`, so the predictor can read them contiguously and compute their partial products exactly. Row reordering groups hot neurons before cold neurons, making the dense and sparse regions contiguous in memory without any runtime shuffling.

At prediction time, oFFN keeps the group-based approximation idea from Grasp for the non-outlier dimensions, but adds an exact outlier term. The predictor therefore sums two pieces: an exact partial dot product over the top outlier dimensions, and an approximate grouped contribution over the rest, plus a bias chosen offline by binary search to hit a target specificity. The paper uses `64` outlier dimensions, about `1%` of the input width in the evaluated models. The authors report that those few dimensions account for `45.99%` of total `L1` prediction error in their analysis, which is why exact treatment matters so much.

Execution then splits by hot versus cold neurons. Hot neurons are assumed likely dense enough that predictor overhead is wasted, so their FFN submatrices run as dense GEMM on Tensor Cores. Cold neurons go through the predictor, and rows predicted sparse are skipped in the gate and up projections; the remaining rows run through sparse CUDA-core kernels. The boundary between hot and cold is batch-dependent because structural sparsity shrinks as batch size rises: if a neuron is nonzero in even one column of a batch, the row must still be loaded. oFFN therefore precomputes the best split point per layer and batch size from calibration data, then just looks it up at runtime.

The CUDA implementation tries to make this split practical. For the exact outlier term, the system materializes a small `Wtiny` and `Xtiny` so that outlier products can run efficiently on Tensor Cores. For sparse gate/up execution, it compacts only the nonzero cold-neuron rows into an indirection array, avoiding warps that immediately exit on predicted-zero rows. For the down projection, where only input sparsity is available, it stores `Wdown^T` in column-major format and reuses the indirection array so nonzero rows stay contiguous. The point is that the paper is not only proposing a predictor; it is redesigning memory layout and kernel structure around that predictor.

## Evaluation

The experiments use ProSparse-LLaMA-2-13B and 7B, two ReLU-fied models with reported sparsity of `88.80%` and `89.32%`, respectively. The runtime is `llama.cpp` with FlashAttention support, and the hardware includes Jetson AGX Orin, NVIDIA A100, and RTX A6000. Calibration uses `100` GSM8K training prompts producing `20K` tokens, and accuracy is measured on decoding-oriented benchmarks including GSM8K, BBH, TruthfulQA-Generation, HumanEval, and MBPP.

Accuracy holds up well. With target specificity set at `80%`, `84%`, or `88%`, oFFN stays within roughly `1` percentage point of the dense baseline on average for both models, and some tasks slightly improve. The authors compare against SparseInfer and Grasp under their fastest settings that keep accuracy loss below about `1%p`, which is a fair way to frame the speed-accuracy tradeoff. On predictor quality, oFFN reaches average recall of `96.71%` on ProSparse-LLaMA-2-13B and `95.57%` on the 7B model, which the paper says is `57.23%p` better than SparseInfer and `16.06%p` better than Grasp on average.

The speed story is strongest on the target regime of small-batch decoding. On Jetson AGX Orin at batch size `1`, oFFN delivers the highest end-to-end speedup and beats Grasp by `13%` on ProSparse-LLaMA-2-13B. The paper's headline claim is up to `2.01x` end-to-end speedup over dense inference during decoding, and up to `5.46x` acceleration inside FFN layers. The breakdown is useful: explicit outlier handling provides the biggest jump because it improves recall enough to unlock more skipping, while hot/cold separation matters more once batch size grows to `4` or `8`, where structural sparsity falls and routing some neurons to Tensor Cores starts paying off. On A6000 and A100, oFFN also beats the dense baseline across batch sizes `1-8`, with larger gains on the more bandwidth-constrained A6000 than on A100. Overall, the evaluation supports the paper's thesis well: the mechanism is not just predictor-accurate in isolation, but actually translates into hardware-level latency gains on multiple GPUs.

## Novelty & Impact

Relative to _Shin et al. (DATE '25)_, oFFN keeps the training-free sparsity-prediction agenda of SparseInfer but replaces sign-only approximation with an outlier-aware formulation that is much more accurate. Relative to _Shin et al. (DAC '25)_, its main step beyond Grasp is to stop treating outliers approximately and to integrate them with explicit hot/cold-neuron reordering and batch-aware dense/sparse partitioning. Relative to _Liu et al. (ICML '23)_, it shows that one can get strong sparsity prediction without auxiliary learned predictors or retraining.

That makes the paper valuable for two groups. Researchers working on LLM serving and GPU kernels get a concrete recipe for turning activation statistics into layout and kernel decisions. Practitioners interested in on-device or small-batch serving get an approach that fits GPU-only deployment better than CPU-GPU hybrid designs. The broader contribution is less a new model than a co-design pattern: if activation structure is statistically stable, the runtime should reorganize weights and kernels around that structure instead of merely approximating it online.

## Limitations

The scope is narrower than the title might suggest. The evaluation is centered on ReLU-fied models, specifically ProSparse-LLaMA-2 variants, so the strongest evidence is for models already adapted to yield abundant exact zeros. The paper does analyze outlier stability in SiLU-based Llama-3.1-8B and gpt-oss-20B, which suggests some generality, but the full speed measurements are not shown on those non-ReLU models. That means the "fast yet accurate" claim is best established for ReLU-fied deployment scenarios, not all LLMs uniformly.

There are also calibration and systems assumptions. oFFN depends on offline calibration to identify outlier dimensions, set bias terms, and precompute hot/cold thresholds per layer and batch size. The authors make that look lightweight, but portability across substantially different models, token distributions, or runtime stacks is still an empirical question. The implementation is embedded in `llama.cpp`, and the paper does not explore multi-tenant serving, large-batch datacenter decoding, or interactions with speculative decoding beyond arguing that small effective verification batches should benefit. Finally, the evaluation mostly compares against prior FFN-sparsity methods and the dense baseline; it says less about how oFFN composes with broader serving-system bottlenecks outside the FFN path.

## Related Work

- _Shin et al. (DATE '25)_ — SparseInfer predicts activation sparsity from sign counts alone; oFFN keeps the training-free setup but computes stable outlier dimensions exactly and supports multi-batch dense/sparse partitioning.
- _Shin et al. (DAC '25)_ — Grasp adds grouped magnitude information and approximate outlier handling, while oFFN turns outliers into a reordered exact-computation block and combines that with hot/cold-neuron-aware execution.
- _Liu et al. (ICML '23)_ — DejaVu uses learned auxiliary layers to predict contextual sparsity; oFFN instead aims for model portability by avoiding predictor training entirely.

## My Notes

<!-- empty; left for the human reader -->
