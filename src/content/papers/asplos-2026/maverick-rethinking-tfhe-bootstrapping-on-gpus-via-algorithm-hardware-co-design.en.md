---
title: "Maverick: Rethinking TFHE Bootstrapping on GPUs via Algorithm-Hardware Co-Design"
oneline: "Rebuilds TFHE blind rotation for GPUs by deferring test-vector injection, exposing sqrt(n)-way EP parallelism, and stopping NTTs early to shift work into Tensor-Core MACs."
authors:
  - "Zhiwei Wang"
  - "Haoqi He"
  - "Lutan Zhao"
  - "Qingyun Niu"
  - "Dan Meng"
  - "Rui Hou"
affiliations:
  - "State Key Laboratory of Cyberspace Security Defense, Institute of Information Engineering, CAS, Beijing, China"
  - "School of Cyber Security, University of Chinese Academy of Sciences, Beijing, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790186"
tags:
  - security
  - gpu
  - memory
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Maverick argues that GPU TFHE bootstrapping is blocked less by raw multiply throughput than by the structure of blind rotation itself. It defers test-vector injection so blind rotation becomes a `sqrt(n)`-way multi-chain process, then stops `NTT/INTT` early so more work lands in Tensor-Core-friendly `MAC`s. The result is up to `331.2x` over CPU programmable bootstrapping, `3.4x` over the best GPU programmable-bootstrapping baseline, and `108.5x` over CPU circuit bootstrapping.

## Problem

The paper starts from a familiar tension in fully homomorphic encryption. TFHE is attractive because its bootstrapping machinery supports bit-level logic, programmable look-up-table evaluation, and circuit bootstrapping, which makes it useful for encrypted inference, private databases, and cryptographic transpilation. But that flexibility is expensive: each bootstrapping performs more than ten thousand polynomial multiplications, and the paper reports that blind rotation alone accounts for nearly `70%` of both `PBS` and `CBS` runtime.

Prior acceleration work on ASICs, FPGAs, and GPUs has already pushed raw arithmetic hard, but the authors argue that these systems are still trapped by the same algorithmic dependency graph. Conventional blind rotation is a length-`n` single chain of external products (`EP`s). Each step depends on the previous one, so the implementation can issue only one `EP` per iteration. Batching improves throughput but not single-ciphertext latency, and loop unrolling shortens the chain only partially while introducing its own key-size and storage tradeoffs. In other words, existing accelerators scale hardware under an algorithm that still exposes very little hardware-friendly parallelism.

The hardware-side bottleneck is just as important. The paper shows that `(I)FFT/(I)NTT` dominates blind-rotation cost, contributing over `70%` of runtime. On GPUs, full-domain transforms require repeated stage-by-stage synchronization and irregular memory access, while the downstream `MAC` becomes comparatively lightweight scalar multiplication. That creates a badly imbalanced pipeline: the expensive operators are synchronization-heavy and underutilize the GPU, and the cheap operators do not absorb enough work to compensate. The stakes are therefore broader than "make one kernel faster." The real question is whether blind rotation can be reformulated so GPUs see more semantic parallelism and a better-balanced operator mix.

## Key Insight

Maverick's central claim is that the serialization in TFHE blind rotation is not as fundamental as prior implementations assume. The culprit is the early binding of the test vector. Standard blind rotation preloads `TestP * X^b` into the chain and then carries that value through every `EP`, which makes the whole computation look like one long dependency chain. Maverick observes that exponent accumulation does not actually need the test vector until the end. If `TestP` is injected only after those exponent terms have been accumulated, the earlier `EP`s become semantically commutative with respect to that missing test vector.

That observation lets the paper restructure a length-`n` chain into `x` independent sub-chains of depth `y` with `x * y = n`, then choose the balanced point `x = y = sqrt(n)` by minimizing the total `EP`-equivalent cost `y + c + x`, where `c` is the conversion overhead. Each sub-chain starts from a trivial `GLWE(1)` ciphertext, performs its own serial `EP`s, and emits an intermediate `GLWE`. A ciphertext-conversion stage then lifts those outputs back into `GGSW` form, and a final `sqrt(n)`-deep chain applies the deferred test vector. The lasting insight is that the best way to accelerate blind rotation is not to shave a few cycles off the old chain, but to change the chain into a parallel tree-like schedule that still preserves TFHE's semantics.

The second insight is that once this extra `EP` parallelism exists, the next limiter is operator balance, not just operator speed. Maverick therefore terminates `NTT` early, producing sub-polynomials instead of scalars, and absorbs the remaining transform work into the `MAC`. This partial-domain transform removes some synchronization-heavy butterfly stages while turning the `MAC` into denser polynomial work that maps naturally onto GPU matrix engines. The paper's core proposition is thus a true co-design claim: algorithmic dependency rewrites and hardware-aware operator-boundary rewrites have to happen together.

## Design

The multi-chain blind-rotation design has three stages. First, Maverick decomposes the original chain into `sqrt(n)` parallel sub-chains, each of depth `sqrt(n)`. Every sub-chain begins with a trivial `GLWE` encryption of `1`, then applies the corresponding `GGSW` bootstrapping-key entries to accumulate a partial exponent. Second, Maverick converts each sub-chain output from `GLWE` back to `GGSW` through homomorphic trace and scheme switching. The important systems point is that this conversion is not implemented as a brand-new primitive: both pieces reuse the existing `EP` operator stack. Third, Maverick runs a final `sqrt(n)`-deep `EP` chain, now starting from the deferred `TestP * X^b`, to absorb the converted outputs and recover the same final polynomial shift as standard blind rotation.

This restructuring is not free, so the paper is careful about cost accounting. Ciphertext conversion adds extra `EP`-equivalent work, and the design introduces a small amount of extra key material. But the overhead is modest relative to the bootstrapping key itself: under the paper's `PBS-I` setting, the added memory for ciphertext conversion is `1.06 MB`, below `0.7%` of the `163.125 MB` bootstrapping key. The authors also analyze noise explicitly. Security still rests on the same `(R)LWE` assumptions as standard TFHE, and the extra noise comes primarily from homomorphic trace and scheme switching. Using parameter-selection methodology inherited from prior circuit-bootstrapping work, they report decryption-failure probability below `2^-40`, which keeps the reformulation inside the normal TFHE correctness envelope.

The hardware-side half of Maverick is the partial-domain transformation (`PDT`). In a conventional full-domain `NTT`, the transform runs all the way down to scalar evaluation points, forcing multiple global synchronizations and leaving the `MAC` with only cheap element-wise multiplies. Maverick stops earlier, after only part of the recursive decomposition, so the representation becomes a collection of sub-polynomials. The downstream `MAC` then performs polynomial-wise multiplication on those sub-polynomials, and the inverse transform (`IPDT`) mirrors the same choice on the way back. The paper argues that this is mathematically equivalent to the ordinary `NTT-MAC-INTT` pipeline, because the omitted transform stages are not discarded; they are absorbed into the algebra executed by `MAC`. Since `NTT` is exact arithmetic over a finite field, the transformation does not introduce extra approximation noise.

To make that representation efficient on GPUs, Maverick remaps sub-polynomial multiplication into matrix operations. Bootstrapping-key polynomials are pre-arranged offline into a fixed layout, so runtime does not pay a conversion penalty. At execution time, ciphertext coefficients are packed into matrices, and the `MAC` becomes vector-matrix or matrix-matrix multiplication with strong key reuse across a batch. The implementation uses `CUTLASS`, slices 32-bit integers into `int8` pieces, and drives Tensor Cores plus Booth-style recomposition to recover full-precision results. The end-to-end system exposes CUDA kernels for `Decompose`, `PDT/IPDT`, `MAC`, sample extraction, and LWE key switching, all inside a client/server TFHE runtime.

## Evaluation

The evaluation is broad for a GPU cryptography paper. The main machine is a server with an Intel Xeon W5-3435X, `128 GB` of DRAM, and eight `RTX 4090` GPUs; the authors also evaluate portability on `A100` and `H100`. They cover `GBS`, two `PBS` parameter sets, and two `CBS` parameter sets, and the application benchmarks span non-linear functions, decision trees, DeepCNN-X private inference, and AES transciphering. That breadth matters because Maverick's argument is about the bootstrapping substrate itself, not about one synthetic kernel.

The headline microbenchmark results strongly support the core claim. Against CPU baselines, Maverick improves programmable bootstrapping by `216.7x-331.2x` over `TFHE-rs` and circuit bootstrapping by `101.1x-108.5x` over `RJX+`. Against GPU baselines on the same `RTX 4090`, it is `7.7x` faster than `XLK+`, `5.7x` faster than `HEonGPU`, and still `3.4x` ahead of `VeloFHE`, which is the strongest GPU programmable-bootstrapping baseline in the paper. Cross-platform comparisons are more mixed but still informative: Maverick beats the `XHEC` FPGA result by `8.3x` and the `MATCHA` ASIC result by `3.3x`, but it remains behind the dedicated `Morphling` ASIC by about `4.4x` on `RTX 4090`, shrinking to `2.5x` on `H100`. That is exactly the pattern one would expect from a strong general-purpose GPU design rather than a custom chip.

The sensitivity studies are useful because they test the paper's mechanism instead of just its implementation quality. The best sub-chain configuration occurs at `x = ceil(sqrt(n))`, matching the paper's analytic model. For partial-domain execution, the sweet spot is six executed stages in both `PBS` and `CBS`: fewer stages remove more `(I)NTT` synchronization, but eventually the `MAC` becomes too expensive. The batching study also clarifies where the gains come from. At small batch sizes, multi-chain blind rotation substantially raises GPU `SM` utilization relative to conventional blind rotation and loop unrolling. At large batch sizes, that part saturates earlier, and `PDT` becomes the dominant contributor, still delivering about `3x` improvement. The paper also tightens the target decryption-failure probability from `2^-40` to `2^-47` by increasing homomorphic-trace and scheme-switching levels, and sees almost no performance loss, which is reassuring for robustness.

The application results suggest that Maverick's benefits survive contact with real encrypted workloads. For non-linear functions under `PBS-II`, it achieves up to `197.4x` over `Pegasus`, `10.6x` over `Concrete-ML`, and `6.7x` over `XLK+`; moving from `RTX 4090` to `H100` adds another `1.7x`. On private decision trees, Maverick speeds up Iris classification by `46.8x` over `Pegasus` and `9.5x` over `XLK+`. On DeepCNN-X private inference, it reports `2.7x-4.8x` over `Concrete-ML` on `RTX 4090`, plus another `1.9x-2x` on `H100`. For AES transciphering using `CBS`, it reaches `71.8x-74.7x` over CPU `RJX+`. Together these results make a convincing case that the co-design helps across both programmable and circuit-style TFHE uses, not just inside one benchmark regime.

## Novelty & Impact

Relative to prior GPU TFHE work such as _Xiao et al. (TCHES '25)_ and _Shen et al. (TCHES '25)_, Maverick's novelty is not simply a faster `NTT` kernel or better use of Tensor Cores. Its main move is to change the blind-rotation dependency structure itself by postponing test-vector injection and introducing a conversion-backed multi-chain schedule. Relative to circuit-bootstrapping work like _Wang et al. (EUROCRYPT '24)_, the novelty is in repurposing homomorphic trace and scheme switching as an internal bridge inside programmable bootstrapping rather than only as end-to-end `CBS` machinery.

That gives the paper real impact potential. It is the first GPU-based design in the paper's own framing that supports `GBS`, `PBS`, and `CBS` together, and it shows that general-purpose GPUs still have unused TFHE performance headroom if the algorithm/hardware contract is redesigned. I expect future TFHE runtimes and accelerators to cite Maverick less for one exact kernel than for the broader idea that operator boundaries in homomorphic evaluation are not fixed; they can be moved to match the machine.

## Limitations

The paper does not pretend the multi-chain reformulation is free. On CPU with one thread, the extra ciphertext-conversion overhead makes multi-chain blind rotation `1.26x` slower than the baseline (`8.21 ms` versus `6.5 ms` in the `GBS` setting). The design wins only once enough thread- or GPU-level parallelism exists to amortize that extra structure. Likewise, at very large batch sizes, multi-chain blind rotation reaches saturation earlier, so its marginal gain shrinks and `PDT` carries more of the improvement. That is a healthy failure mode, but it means the benefit is regime-dependent rather than uniform.

There are also deployment limits the paper mostly leaves to future work. Maverick is tuned for NVIDIA GPUs, CUDA, Tensor Cores, and specific TFHE parameter sets; when `n` is not a perfect square, it even rounds up to the next perfect square `n'` to preserve the balanced decomposition. The evaluation says nothing about energy efficiency, multi-tenant service operation, or heterogeneous clusters. And although the GPU results are excellent, the best dedicated ASIC remains faster. So Maverick shows how far co-designed software on general-purpose GPUs can go, but it does not eliminate the long-term case for custom TFHE hardware.

## Related Work

- _Xiao et al. (TCHES '25)_ — XLK+ accelerates TFHE bootstrapping on GPUs but keeps the conventional single-chain blind-rotation schedule; Maverick attacks that dependency graph directly.
- _Shen et al. (TCHES '25)_ — VeloFHE is Maverick's closest GPU programmable-bootstrapping baseline, whereas Maverick adds both multi-chain blind rotation and partial-domain transforms instead of only faster kernels.
- _Wang et al. (EUROCRYPT '24)_ — Circuit bootstrapping provides the homomorphic-trace and scheme-switching machinery that Maverick repurposes as its ciphertext-conversion stage.
- _Putra et al. (HPCA '24)_ — Morphling shows what transform-domain reuse can buy on ASICs, while Maverick pursues a similar "move the operator boundary" idea on general-purpose GPUs.

## My Notes

<!-- empty; left for the human reader -->
