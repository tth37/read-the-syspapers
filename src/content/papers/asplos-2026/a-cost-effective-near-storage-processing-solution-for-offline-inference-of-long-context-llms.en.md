---
title: "A Cost-Effective Near-Storage Processing Solution for Offline Inference of Long-Context LLMs"
oneline: "HILOS offloads attention to SmartSSDs, recomputes part of KV from cached activations, and delays writes so one GPU can serve 175B models at 128K context."
authors:
  - "Hongsun Jang"
  - "Jaeyong Song"
  - "Changmin Shin"
  - "Si Ung Noh"
  - "Jaewon Jung"
  - "Jisung Park"
  - "Jinho Lee"
affiliations:
  - "Seoul National University, Seoul, South Korea"
  - "POSTECH, Pohang, South Korea"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790119"
code_url: "https://github.com/hongsunjang/HILOS/tree/asplos26"
tags:
  - llm-inference
  - storage
  - hardware
  - energy
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

HILOS is a storage-centric offline LLM inference system for the regime where context length and batch size make KV-cache traffic dominate everything else. It pushes exact attention onto SmartSSDs, keeps part of the history as pre-projection activations that the GPU can cheaply recompute, and delays KV writeback so SSD page writes stay off the critical path. On a real 16-SmartSSD prototype, that is enough to make a single-GPU host practical for 175B models at 128K context, with up to `7.86x` higher throughput and up to `85%` lower energy than prior offloading baselines.

## Problem

The paper targets offline inference rather than latency-critical chat serving. In that setting, longer prompts and larger batches are acceptable because the goal is throughput for workloads such as benchmarking and information extraction. The catch is that offline inference magnifies the memory problem: model weights are already large, and the KV cache grows with both context length and batch size. For large models and long contexts, the KV cache alone reaches terabyte scale and no longer fits comfortably in GPU or host DRAM.

Existing offloading systems such as FlexGen and DeepSpeed-style inference attack this by extending GPU memory with CPU DRAM and SSDs. That helps model weights fit, and batching amortizes weight transfers, but it creates a new bottleneck. During decoding, each layer repeatedly reloads a very large KV cache. HILOS's motivational study on OPT-175B shows that KV-cache transfers consume more than `60%` of total inference time for long-context offline inference. At that point the system is no longer compute-bound; it is a data-movement machine built around PCIe.

Buying more GPUs is not a satisfying answer either. The paper argues that decoding is fundamentally memory-bound, so expensive GPU compute remains underutilized, while multi-GPU servers raise cost sharply. A naive near-storage-processing design is also insufficient, because moving attention into the storage device only shifts the bottleneck inward: storage-side reads, tiny KV writes, and tight FPGA resource budgets can still erase the theoretical win.

## Key Insight

The central claim is that the expensive part of long-context offline decoding is not "attention math" in the abstract, but moving the full historical KV cache back to the host for every step. If attention is executed next to storage, the host does not need the whole cache; it only needs the final attention output. That changes the dominant traffic term from something proportional to context length to something proportional to hidden size.

The second insight is that once attention leaves the GPU, the host suddenly has useful slack. HILOS spends that slack in two ways. First, instead of storing all historical K and V tensors, it stores pre-projection activations `X` for a fraction of the workload and lets the GPU regenerate K and V on demand. Second, instead of synchronously persisting every newly generated KV vector, it buffers those writes in host memory and exposes just enough partial information for the accelerator to continue exact attention computation. The paper's message is that NSP only becomes compelling when storage and host cooperate rather than when storage tries to do everything alone.

## Design

HILOS is built around attention near storage (ANS). In the decoding path, the GPU still loads weights and performs the QKV projection, but the query, key, and value vectors are sent to SmartSSDs. The near-storage accelerator reads the historical KV cache from local flash into device DRAM, computes attention there, and returns only the final attention output to the host, after which the GPU resumes the MLP portion. Under half precision, the paper models baseline interconnect read traffic as `4sh + 4h` bytes per decoding step and HILOS traffic as `2h + 6h`, so the gain grows with context length `s`.

ANS alone is not enough because storage-internal I/O becomes the new bottleneck. HILOS therefore adds cooperative X-cache. For an `alpha` fraction of the batch-head space, the system stores pre-projection activations `X` instead of both K and V. Since `X` is half the size of KV, this cuts both flash-read traffic and storage capacity for that fraction. During decoding, the GPU fetches X-cache entries with GPUDirect Storage and recomputes K and V locally while the SmartSSD accelerator handles the remaining `1 - alpha` fraction. The two sides run in parallel, so the recomputation latency is intended to be hidden. The paper gives a first-order model balancing PCIe bandwidth and SSD bandwidth, then chooses `alpha` near a power of two; in their platform, profiling suggests an optimal `alpha` around `50%`.

The next problem is writeback. Newly generated KV entries are tiny, but SSDs want page-sized writes. In a naive scheme, every decode iteration performs small direct writes and then rereads the updated cache, which places write latency directly on the critical path. HILOS instead uses delayed KV cache writeback: new K/V vectors stay in host-memory buffers, the CPU precomputes the partial `QK^T` products for buffered keys, and the accelerator receives those scalars together with the buffered V entries. Actual SSD writeback happens later in larger chunks. The default spill interval is `16`, matching the `4 KiB` page granularity for typical `256 B` KV entries per head.

The accelerator itself is a custom SmartSSD FPGA design. It uses a temporal, block-based attention architecture rather than a fully spatial one, because long-context attention would otherwise require too much on-chip memory. Three hardware choices matter most. First, HILOS implements a two-pass softmax, not the standard three-pass version, reducing off-chip memory traffic. Second, it performs an in-place blockwise transpose to resolve the mismatch between row-wise KV writes and column-wise key reads. Third, it natively supports grouped-query attention by broadcasting shared KV data to multiple query groups, avoiding redundant reads. The implementation stores data in FP16 but performs intermediate accumulation and exponentiation in FP32 for stability.

## Evaluation

The prototype is real rather than simulated: up to `16` Samsung SmartSSDs, each with a `3.84 TB` SSD and a Kintex UltraScale+ KU15P FPGA with `4 GB` DDR4, connected through a PCIe expansion chassis to either an `A100-40GB` or `H100-80GB` host. Baselines are FlexGen with KV in DRAM, FlexGen with KV on SSD, FlexGen on the same 16 SSDs but with FPGAs disabled, and DeepSpeed-Inference extended with UVM. Workloads cover OPT-30B, OPT-66B, OPT-175B, Qwen2.5-32B, Mixtral-8x7B, and GLaM-143B at up to `128K` context, with default batch size `16` and output length `64`.

The headline performance results are strong. With four SmartSSDs, HILOS is already `1.10x-1.36x` faster than the DRAM-offloading baseline because it supports larger effective batches while reducing PCIe traffic. With sixteen SmartSSDs, that advantage rises to `1.88x-2.49x`. In the long-context cases where FlexGen(DRAM) runs out of host memory even at batch size `1`, HILOS delivers `5.3x-7.8x` higher decoding throughput than FlexGen(SSD). The paper's overall best-case claim is `7.86x`.

The sensitivity studies help explain where the gains come from. DRAM-based offloading is capped at batch size `2` on their 66B study because host memory fills up quickly, while HILOS continues scaling to batch size `16`. For GQA and MoE models, HILOS still improves end-to-end throughput by `1.16x-3.36x`, so the benefit is not limited to plain MHA models. The system-parameter sweep matches the analytical story: `alpha = 50%` is consistently the best X-cache ratio, and spill interval `c = 16` is the best writeback setting. The ablation is clean as well: ANS alone gives up to `3.39x`, adding delayed writeback yields up to another `1.32x`, and adding X-cache yields up to another `1.64x` over ANS.

The evaluation also goes beyond raw throughput. HILOS reports up to `2.02x` better cost-efficiency than FlexGen(SSD) on a 66B model and up to `1.68x` on 175B. Compared with upgrading the baseline from an A100 host to a much more expensive H100 host, HILOS delivers a similar `1.29x` speedup but `2.91x` higher cost-efficiency. On endurance, the paper estimates `1.34x-1.47x` improvement over the baseline and more than `4.08 million` long 175B requests before SSD wear-out under their assumptions. Energy breakdowns show up to `85%` lower energy consumption, and a two-node vLLM setup with eight RTX A6000 GPUs is still `1.64x-1.81x` slower than HILOS in their comparison. Overall, the evidence supports the main claim well: HILOS is not just faster, it makes a different cost/performance point plausible.

## Novelty & Impact

Relative to _Sheng et al. (ICML '23)_, HILOS's key move is to stop treating storage as passive overflow capacity and instead execute exact attention beside the KV cache. Relative to _Pan et al. (HPCA '25)_, the paper's differentiator is that it targets lossless long-context inference on a modern real SmartSSD platform rather than relying on lossy sparse retrieval and older emulation-oriented infrastructure. Relative to PIM-style accelerators such as _Heo et al. (ASPLOS '24)_, HILOS argues that flash-backed near-storage processing hits a different cost point for extremely large contexts and models.

That makes the paper important for two audiences. Systems builders can read it as a concrete recipe for turning "single GPU plus lots of flash" into a usable offline inference server for models that would otherwise require a larger GPU fleet. Architecture researchers can read it as evidence that future CSD/ISP devices should be co-designed around exact attention, page-sized writeback, and cooperative host/device execution rather than around generic storage offload.

## Limitations

The design is specialized to offline inference, where throughput matters more than per-request latency. It does not claim to solve online serving with tight TTFT/TPOT targets, and several mechanisms, especially delayed writeback, would be less natural there. HILOS also assumes SmartSSD-class hardware, custom FPGA bitstreams, GPUDirect Storage, and a middleware stack that can orchestrate GPU, CPU, SSD controller, and FPGA together; this is far from drop-in deployment.

The paper removes the KV-cache bottleneck, not every bottleneck. Model weights still have to come from host memory or storage, and models above `100B` parameters still spill weights to storage. The current accelerator saturates PCIe 3.0-era SmartSSD bandwidth, but the discussion section explicitly warns that future PCIe 5.0 devices would require about `4x` more accelerator throughput, likely more than current SmartSSD DSP budgets can supply. The paper also notes an architectural mismatch in today's hardware: HILOS spreads KV data across many SSDs to gain bandwidth, which leaves much of each `3.84 TB` device underused in capacity terms. Finally, some of the forward-looking claims about ISP and CXL applicability are reasoned extrapolations rather than end-to-end implementations.

## Related Work

- _Sheng et al. (ICML '23)_ — FlexGen is the clearest software baseline: it offloads weights and KV across GPU, DRAM, and SSD, but still drags KV data back to the host instead of computing attention near storage.
- _Aminabadi et al. (SC '22)_ — DeepSpeed-Inference also addresses memory-limited transformer inference, but HILOS targets the offline long-context regime where KV traffic, not just weight placement, dominates.
- _Pan et al. (HPCA '25)_ — InstAttention also explores storage-side attention offload, whereas HILOS emphasizes exact computation, modern SmartSSD deployment, and the extra system techniques needed to make that practical.
- _Heo et al. (ASPLOS '24)_ — NeuPIMs accelerates batched LLM inference with PIM, while HILOS pursues a flash-backed near-storage design that trades lower media cost for more complicated storage-aware scheduling.

## My Notes

<!-- empty; left for the human reader -->
