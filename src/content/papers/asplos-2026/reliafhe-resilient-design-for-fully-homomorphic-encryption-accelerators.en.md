---
title: "ReliaFHE: Resilient Design for Fully Homomorphic Encryption Accelerators"
oneline: "Adds hierarchical checksum protection to FHE accelerators so storage and computation faults are caught with about 1.5% runtime and 1.9% area overhead."
authors:
  - "Fan Li"
  - "Mayank Kumar"
  - "Ruizhi Zhu"
  - "Mengxin Zheng"
  - "Qian Lou"
  - "Xin Xin"
affiliations:
  - "University of Central Florida, Orlando, FL, USA"
conference: asplos-2026
category: privacy-and-security
doi_url: "https://doi.org/10.1145/3779212.3790211"
tags:
  - security
  - hardware
  - memory
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

ReliaFHE asks what prior FHE accelerator papers usually assume away: what if the hardware is not perfectly reliable? Its answer is a checksum-based protection stack that covers both storage and the dominant FHE kernels through row/column checksums, total checksums, and small intra-element checksums. The paper reports more than `10^4` reliability improvement with about `1.5%` runtime overhead, `1.9%` area overhead, and under `1%` parity storage overhead.

## Problem

The paper starts from a basic asymmetry between FHE and ordinary numerical code. In RLWE-based schemes, one ciphertext polynomial carries many packed plaintext values, so one hardware fault can damage many logical results at once. Modular arithmetic can then turn a small ciphertext perturbation into a large plaintext deviation after decryption, and NTT/RNS transforms can spread a local fault across the whole ciphertext. Algorithm-level packing makes things worse: once a corrupted ciphertext is reused in a packed matrix operation, the error contaminates many outputs.

The fault-injection results make that concrete. A single bit flip that perturbs one output entry in plaintext arithmetic produces nearly random decrypted outputs across all slots under FHE, and encrypted ResNet-20 accuracy collapses to near chance around an error rate of `10^-5` while the plaintext model still stays near `90%`. Existing protections do not fit well: memory ECC stops at storage, redundant execution is too expensive for FHE kernels, and RRNS-style arithmetic protection clashes with ciphertexts that already live in RNS. The design target is therefore not generic dependability, but FHE-compatible protection that stays close to the paper's `~1%` overhead budget.

## Key Insight

The central insight is that FHE's large ciphertext polynomials are also a coding advantage. Since a limb has length `N`, typically `2^12` to `2^16`, ReliaFHE can build large checksum codewords whose parity cost is tiny relative to the protected data. Because modular addition is far cheaper than modular multiplication, those checksums can be generated and verified cheaply as long as the design uses multiplication-heavy protection only where it is unavoidable.

That leads to a hierarchical split. Storage gets checksum-based error correction, because row and column parities can reconstruct missing data. Computation gets error detection plus re-execution, and the detection logic is matched to the structure of each kernel: total checksums for scalar-like stages, intra-element checksums around modular multipliers, and row/column checksum verification for batches of sub-NTTs in a four-step transform. The key claim is that resilience becomes affordable once protection follows the same decomposition that fast FHE already uses.

## Design

ReliaFHE begins with storage protection. A polynomial limb or NTT vector is reshaped into a 2D matrix, and the system stores row checksums, column checksums, and one total checksum. That layout matches physical memory arrays and lets the design recover from whole-row or whole-column failures rather than only isolated bit errors. Because the protected objects are large, the parity overhead stays below `1%`.

The computation path is divided into three operation classes. `ScalOp` covers stages that apply one scalar or one identical transform to every element, such as BaseConv scaling and modular reduction. These preserve a direct checksum relation, so ReliaFHE can verify them cheaply, with an extra range check to catch bad reduction quotients. `ElemOp` covers element-wise modular multiplication. The paper splits it into wide multiplication plus reduction, then protects the wide product with a small intra-element checksum formed by folding each operand modulo `2^k + 1`; vector-level total checksums track the aggregate result.

`NttOp` is the most interesting part because naive ABFT-style protection is too expensive and behaves poorly with NTT symmetry. ReliaFHE instead exploits the four-step NTT used in modern FHE stacks. The large transform is decomposed into batches of smaller sub-NTTs, and row/column checksums over the reshaped matrix verify those batches jointly. The inserted twiddle multiplications reuse the `ElemOp` machinery, and the same checksum hierarchy is carried across block boundaries and the memory interface so transport faults are not ignored.

## Evaluation

The evaluation covers arithmetic kernels, primitive operations, end-to-end workloads, reliability, and hardware cost. On the kernel side, the numbers are favorable where they matter most: for practical polynomial degrees above `2^12`, ReliaNTT adds only about `1%` overhead, ReliaElemOp stays around `4.6%`, and BaseConv protection remains below `0.1%`. Since NTT dominates FHE runtime, that is the right place for the design to be cheap.

Primitive BFV and CKKS multiplication and rotation show roughly `1.5%` average overhead at `N = 2^14`. On SEAL/Lattigo/Orion-based workloads including MLP, LoLA CryptoNet, LeNet-5, and bootstrapped ResNet-20 variants, the end-to-end overhead stays below `2%`, with bootstrapping around `1.45%`. The reliability results are more important: across primitive fault scenarios, ReliaFHE improves reliability by more than `10^4`, and even aggressive injected fault rates degrade encrypted inference accuracy by less than `3%`. The memory study also supports the large-codeword argument, showing better behavior than HBM3-style `RS(19,17)` on the reported row- and column-scale failures.

The hardware story is similarly compact. Synthesis on F1, ARK, CraterLake, and Trinity-style accelerators reports about `1.9%` average area overhead and `1.46%` average power overhead. That evidence supports the main claim well, though one caveat remains: runtime overhead is measured in software stacks and hardware cost comes from synthesis rather than a fabricated resilient chip.

## Novelty & Impact

Relative to _Kim et al. (MICRO '22)_ and _Kim et al. (ISCA '23)_, ReliaFHE is not about another faster FHE kernel; it is about making those accelerator datapaths survivable under realistic faults. Relative to RRNS-style arithmetic protection, its novelty is compatibility: it works with ciphertexts that already use RNS rather than demanding a redundant representation FHE cannot naturally adopt. Relative to conventional ECC, it offers one framework across storage, transport, and the three dominant compute kernels instead of stopping at memory.

That makes the paper likely to matter to accelerator architects and to anyone who wants FHE to move from isolated demos to cluster-scale services. It is a new resilience mechanism family rather than a marginal speedup paper.

## Limitations

The paper's limits are clear. Computation protection is mostly error detection plus re-execution; only storage gets true error correction. The narrow intra-element checksum is therefore the weakest link, and the authors explicitly identify checksum collisions, especially for opposite-sign error patterns, as the main residual risk. A `24`-bit checksum appears sufficient in their Monte Carlo study, but this is still probabilistic protection.

The best NTT efficiency also assumes the four-step decomposition used by modern FHE implementations. Kernels outside `ScalOp`, `ElemOp`, and `NttOp` are handled by simple duplication because they account for less than `0.5%` of runtime. Finally, the evaluation relies on injected faults and synthesized cost models rather than long-term data from real FHE clusters.

## Related Work

- _Kim et al. (MICRO '22)_ — ARK shows how to accelerate FHE with runtime data generation and key reuse, but it still assumes correct hardware execution; ReliaFHE adds a resilience layer to that style of datapath.
- _Kim et al. (ISCA '23)_ — SHARP optimizes short-word hierarchical FHE arithmetic, whereas ReliaFHE focuses on protecting NTT, BaseConv, and multiplier units once those accelerators exist.
- _Deng et al. (MICRO '24)_ — Trinity broadens FHE acceleration into a more general-purpose design, while ReliaFHE contributes orthogonal reliability machinery that such accelerators could adopt.
- _Cilasun et al. (ISCA '24)_ — resilient processing-in-memory work studies low-cost error protection for memory-centric accelerators, and ReliaFHE adapts that general direction to FHE-specific SIMD packing and modular arithmetic.

## My Notes

<!-- empty; left for the human reader -->
