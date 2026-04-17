---
title: "Falcon: Algorithm-Hardware Co-Design for Efficient Fully Homomorphic Encryption Accelerator"
oneline: "Redesigns MKS-based FHE bootstrapping for hardware by cutting ModDown work, reducing inter-cluster traffic, and fitting the result into a SHARP-like accelerator."
authors:
  - "Liang Kong"
  - "Xianglong Deng"
  - "Guang Fan"
  - "Shengyu Fan"
  - "Lei Chen"
  - "Yilan Zhu"
  - "Geng Yang"
  - "Yisong Chang"
  - "Shoumeng Yan"
  - "Mingzhe Zhang"
affiliations:
  - "Ant Group, Beijing, China"
  - "State Key Laboratory of Cyberspace Security Defense, Institute of Information Engineering, CAS, Beijing, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790160"
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

Falcon starts from a practical complaint about FHE accelerators: the minimum key-switching trick used in modern bootstrapping hardware saves memory, but it makes the H-IDFT and H-DFT routines much more expensive than the best algorithmic forms on paper. The paper answers with a co-design stack that first rewrites the MKS-based BSGS routine to eliminate much of its `ModDown` cost, then reorders giant-step communication to cut cluster-to-cluster traffic, and finally maps that design onto a SHARP-like accelerator with small hardware changes. The end result is up to `1.48x` speedup over SHARP for only `0.8%` more area.

## Problem

The paper lives in the uncomfortable middle ground between cryptographic algorithms and actual hardware deployment. In CKKS bootstrapping, the dominant work sits inside homomorphic `IDFT/DFT` routines, which are usually implemented with a baby-step giant-step (`BSGS`) structure full of rotations, base conversions, and NTT/INTT transforms. Purely algorithmic optimizations such as hoisting and double hoisting reduce those computations substantially, but they require many distinct evaluation keys. On hardware, that is a serious problem because evaluation keys are huge, on-chip SRAM is limited, and off-chip key fetches quickly become a bandwidth bottleneck.

Prior accelerator designs therefore gravitated to minimum key-switching (`MKS`), introduced by ARK and used by SHARP. MKS reuses only two evaluation keys within the baby-step and giant-step phases, so it is much friendlier to hardware memory budgets. But the paper shows that this comes at a steep computational price. For the paper's running H-IDFT example at levels 35, 33, and 31, the MKS-based routines are `2.44x`, `2.64x`, and `2.64x` more expensive than double hoisting, even though double hoisting itself is not deployable because its evaluation keys still reach `403MB`, `540MB`, and `514MB`. Falcon is motivated by this gap: existing accelerators are choosing the hardware-feasible algorithm, not the hardware-efficient one.

That creates a concrete systems question. Can we keep the memory discipline of MKS while removing enough of its extra computation and communication overhead that the algorithm again looks attractive once mapped to silicon? The paper argues that the answer is yes, but only if the algorithm is rewritten with the actual data dependencies, temporary-storage limits, and cluster communication patterns of FHE accelerators in mind.

## Key Insight

The core claim is that the extra cost of MKS-based BSGS is not fundamental; much of it comes from when the routine chooses to return temporary ciphertext components from `R_QP` back to `R_Q`, and from how that choice forces repeated `ModDown`, `ModUp`, and data-redistribution steps. Once the authors inspect which ciphertext component is actually consumed by the next rotation, they find that large parts of the conventional flow are there for representational convenience rather than mathematical necessity.

That observation drives the paper's optimization ladder. First, Falcon notes that the first output of key switching often participates only in addition and automorphism, not in another key switch, so it does not always need an immediate `ModDown`. Second, in the giant step, communication overhead is inflated by a representation mismatch: one rotation leaves data in evaluation form, while the next rotation wants coefficient form, forcing extra cross-cluster redistributions. Because automorphism commutes with the relevant conversions, the system can legally move part of `ModDown` across the rotation boundary and collapse those exchanges. The enduring insight is that bootstrapping accelerators should optimize the schedule of representation changes, not just the arithmetic inside each primitive.

## Design

Falcon's design is easiest to understand as four successive versions of the same `BSGS` kernel. The baseline `MKS-BSGS` follows the ARK/SHARP style: the baby step performs `(bs - 1)` rotations that all reuse one evaluation key, the giant step performs `(gs - 1)` rotations that reuse a second evaluation key, and on-the-fly limb extension (`OF-Limb`) regenerates plaintext limbs to reduce off-chip traffic. This baseline is memory-efficient but heavy on `ModDown`.

The paper first proposes `AO-BSGS`, a purely algorithmic refinement. It introduces `Compact-KS`, which keeps the first key-switch output in `R_QP` and only `ModDown`s the second component back to `R_Q`. That removes about half of the `ModDown` operations, but it also expands plaintext generation and temporary storage because more values now live in the extended modulus domain.

Falcon's hardware-oriented version is `HO-BSGS`, which selectively applies that idea only where storage pressure is low. In the baby step, all temporary ciphertexts stay in `R_Q` so the accelerator does not need to pay the storage penalty for `bs` reusable values. In the giant step, where only one temporary ciphertext is live, Falcon uses `Compact-KS` and an `RP-Hybrid-KS` trick that cancels the explicit multiplication by `P` against the later `P^-1` inside `ModDown`. That preserves the savings from removing nearly half of the giant-step `ModDown`s while increasing storage by only `alpha` polynomial limbs. The paper also fuses the final two giant-step `ModDown`s with the following rescale.

The next step, `OC-HO-BSGS`, targets inter-cluster communication. In the conventional giant step, two consecutive rotations incur four data redistributions because `ModDown` ends in evaluation form, the following `ModUp` wants coefficient form, and both `INTT->BConv` and `BConv->NTT` switch data layouts. Falcon defers part of `ModDown`, creating a `Split-ModDown`, and pairs it with a modified `MD-ModUp` so two consecutive rotations need only two redistributions instead of four. The paper proves correctness by showing that the reordered sequence is mathematically equivalent because `INTT` is linear and automorphism commutes with scalar multiplication and base conversion.

On the hardware side, Falcon keeps SHARP's general vector-accelerator structure and adds two smaller co-design moves. The NTT unit fuses the first `BConv` multiplication into the odd-lane butterfly by pre-adjusting twiddle constants, which removes roughly half of the modular multipliers in the dedicated `MBU` and cuts that block's area by `49.78%`. The base-conversion unit is then time-multiplexed to also perform double-prime scaling and `OF-Limb`, eliminating a dedicated scaling unit and raising utilization instead of adding more specialized hardware. Because `HO/OC-HO-BSGS` changes the best baby-step size, Falcon also adds a memory-adaptive policy: use the level-specific optimal `bs` when memory allows it, rather than blindly pushing `bs` to the largest storable value as SHARP does.

## Evaluation

The evaluation is fairly comprehensive for an accelerator paper. The authors implement Falcon in RTL, synthesize it in the ASAP7 7nm predictive PDK, model `190MB` of scratchpad plus `18MB` of register files, assume two HBM stacks for `1TB/s` off-chip bandwidth, and compare against BTS, CraterLake, ARK, and SHARP. The workload mix is not just microbenchmarks: in addition to bootstrapping, the paper runs encrypted logistic regression (`HELR256` and `HELR1024`), encrypted `ResNet-20`, and encrypted sorting.

The headline table is strong. Falcon reduces bootstrapping latency from SHARP's `3.12 ms` to `2.11 ms`, a `1.48x` speedup, while also improving `HELR256` from `1.82` to `1.33 ms`, `HELR1024` from `2.53` to `1.94 ms`, `ResNet-20` from `99` to `72.84 ms`, and sorting from `1.38 s` to `0.96 s`. Relative to SHARP, that is `1.30-1.48x` across the workload set, and relative to older designs the gaps are larger. Importantly, Falcon does this with only `180.3 mm^2` area versus SHARP's `178.8 mm^2`, so the paper is not buying speed with a giant hardware expansion.

The ablation study is what really validates the mechanism. Replacing `MKS-BSGS` with `HO-BSGS` yields a `1.32x` improvement for bootstrapping, which the authors attribute mainly to removing almost half of the giant-step `ModDown`s. Adding the communication-optimized `OC-HO-BSGS` gives another `1.12x` speedup for bootstrapping and `1.08-1.11x` for applications. The sensitivity studies reinforce that explanation. The gains from `OC-HO-BSGS` become larger when NoC bandwidth is high, because the machine becomes compute-bound enough to expose the saved computation and avoid stalling on cluster traffic. By contrast, the gains are almost insensitive to off-chip bandwidth, since evaluation-key prefetching largely hides external memory latency already.

I found the memory-adaptive analysis especially convincing because it explains why the best algorithmic parameter is not simply "largest `bs` that fits." Falcon's optimal `bs` is level-dependent: the highest level prefers `bs = 4`, while lower levels prefer `bs = 7`. That makes the second-highest level, not the highest one, determine the peak `190MB` memory need in the final design. The paper also checks whether partially restoring hoisting in hardware would be better; caching extra keys for limited hoisting improves H-IDFT by only `6.67-7.31%` while demanding at least `58%` more on-chip memory. That is a strong negative result and supports Falcon's central argument that communication- and storage-aware rewrites beat naive reintroduction of theoretically cheaper algorithms.

## Novelty & Impact

Relative to _Kim et al. (MICRO '22)_, Falcon is not introducing MKS itself; it is showing that MKS should be treated as a starting point for hardware-oriented algorithm redesign rather than as a fixed compromise. Relative to _Kim et al. (ISCA '23)_, which builds SHARP around MKS and short-word arithmetic, Falcon's novelty is the full co-design chain: rewrite the BSGS schedule, reduce cluster redistributions, then reclaim the small hardware cost through arithmetic fusion and unit reuse. Relative to hoisting-heavy accelerators such as _Samardzic et al. (ISCA '22)_, the paper reframes the question from "what is the cheapest cryptographic schedule?" to "what schedule survives contact with evaluation-key storage and NoC costs?"

That makes the paper useful beyond this exact chip. Anyone building FHE accelerators, or even high-performance FHE runtimes with clustered execution resources, can cite Falcon for the principle that representation changes and data movement should be co-designed with the cryptographic algorithm. The contribution is therefore a new mechanism family, not just a slightly better implementation of SHARP.

## Limitations

The paper is deliberately narrow in scope. Falcon targets CKKS bootstrapping and the accelerator structures around it; it does not claim generality across other FHE schemes. The design also inherits the complexity of an accelerator-specific software-hardware contract, including level-specific baby-step tuning and explicit reasoning about `R_Q` versus `R_QP` domains.

The evaluation is strong for architecture-level comparison, but it still relies on simulation plus synthesized component models rather than a fabricated chip. The paper also compares primarily against prior accelerator architectures, not against the newest GPU software stacks. That is a reasonable scope choice, but it means the results say more about ASIC design space than about end-to-end deployment choices in heterogeneous systems.

Finally, Falcon does not eliminate the memory problem so much as manage it better. The best design still needs `190MB` of on-chip memory, and the sensitivity section makes clear that memory frequency and NoC bandwidth materially affect how much of the algorithmic gain shows up. So the win is real, but it remains tied to a fairly provisioned accelerator, not a tiny or highly memory-constrained device.

## Related Work

- _Kim et al. (MICRO '22)_ — ARK introduced the MKS-based BSGS structure that Falcon treats as its baseline, but Falcon rewrites that routine to recover much of the computation MKS originally sacrificed.
- _Kim et al. (ISCA '23)_ — SHARP is Falcon's architectural starting point; Falcon keeps the short-word clustered design and shows how algorithm-hardware co-design can beat SHARP with almost no area increase.
- _Samardzic et al. (ISCA '22)_ — CraterLake uses hoisting-oriented acceleration to reduce bootstrapping cost, whereas Falcon argues that hoisting's key footprint makes it a poor direct fit for practical hardware budgets.
- _Samardzic and Sanchez (ASPLOS '24)_ — BitPacker improves arithmetic efficiency inside FHE accelerators, while Falcon's distinctive move is to optimize the bootstrapping schedule and inter-cluster communication around those arithmetic units.

## My Notes

<!-- empty; left for the human reader -->
