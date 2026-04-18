---
title: "RowArmor: Efficient and Comprehensive Protection Against DRAM Disturbance Errors"
oneline: "Defends DRAM against RowHammer-style corruption and DoS by confining disturbance to octets, correcting them reactively, and scrubbing only when overlap risk builds up."
authors:
  - "Minbok Wi"
  - "Yoonyul Yoo"
  - "Yoojin Kim"
  - "Jaeho Shin"
  - "Jumin Kim"
  - "Yesin Ryu"
  - "Saeid Gorgin"
  - "Jung Ho Ahn"
  - "Jungrae Kim"
affiliations:
  - "Seoul National University, Seoul, Republic of Korea"
  - "Samsung Electronics, Suwon, Republic of Korea"
  - "Sungkyunkwan University, Suwon, Republic of Korea"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790213"
tags:
  - memory
  - security
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

RowArmor argues that DRAM disturbance defense should stop trying to prevent every risky activation and instead recover safely when errors actually appear. It confines each aggressor's damage to octet-sized symbols, extends ECC to correct up to eight overlapping octet errors, hides row adjacency with controller-side obfuscation, and scrubs only when observed corrections imply that accumulation is becoming dangerous. The result is strong protection against both silent corruption and denial of service with at most `0.7%` performance overhead.

## Problem

The paper starts from an uncomfortable trend: modern DRAM keeps lowering the hammer-count threshold at which disturbance errors appear, while attack patterns keep getting broader than the original RowHammer model. Prior defenses mostly react by counting activations and issuing preventive refreshes, swaps, or throttling before a row reaches a pessimistic threshold. That works in principle, but it makes three things worse at once.

First, prevention is tuned to worst-case cells. Real devices show large variation across rows, chips, data patterns, aging state, and row open time, so a threshold safe for the weakest cells forces unnecessary action on the majority of accesses. Second, newer attacks such as RowPress are not cleanly characterized by activation count alone, so count-based defenses are increasingly mismatched to the physics they are trying to contain. Third, preventive actions themselves can become the attack surface: the paper cites prior work showing PRAC-style backoff can consume up to `94%` of available DRAM bandwidth in the worst case, turning protection into a denial-of-service vector.

Existing ECC does not fully solve this either. Commodity and server DRAM already spend substantial redundancy on On-Die ECC and rank-level ECC, but those schemes are designed around random errors or failed chips, not coordinated disturbance patterns that can span multiple chips and whole transfer blocks. Once those patterns exceed correction capability, systems often turn them into Detected-but-Uncorrectable Errors, which can trigger service interruption, checkpoint rollback, or machine shutdown. So the real problem is not just "stop bit flips." It is "stop both targeted corruption and availability failures without adding another attacker-triggerable bottleneck."

## Key Insight

The central idea is that reactive protection becomes viable if the hardware can reshape disturbance errors into a form ECC is naturally good at handling. RowArmor therefore does not try to identify every dangerous aggressor in time. Instead, it changes the data layout so that one aggressor can corrupt at most one 8-bit octet per access, then uses a stronger symbol-based ECC that can recover several such octet errors in one codeword.

That only covers the low-aggressor case, so the paper layers two more claims on top. If the controller randomizes physical-to-row mapping, attackers lose the ability to align many aggressors onto the same victim address with useful precision. And if the system starts scrubbing once moderate overlap is observed, it can stop the slow buildup toward an uncorrectable state without paying the cost of constant patrol scrubbing. In other words, RowArmor's proposition is that confinement plus stronger correction plus probabilistic obscurity is a better systems balance than ever more pessimistic prevention.

## Design

RowArmor is built from four mechanisms: confine, correct, obfuscate, and scrub.

The confinement mechanism is octet scrambling. Inside DRAM, DQ Address Scrambling gives different DQs and chips different row-address mappings, while Sub-WordLine Permutation makes the two octets carried on the same DQ land on different local wordline patterns. Together, these changes spread the disturbance footprint of one aggressor across addresses so that a single access sees at most two corrupted octets from the two adjacent victim rows, instead of a wide multi-bit burst that ordinary ECC would not understand.

The correction mechanism is Octuple-Octet Correcting (OOC) ECC. The paper reorganizes each transfer block into `64` data symbols and `16` parity symbols, one 8-bit symbol per octet, and applies Reed-Solomon coding so the system can correct up to eight octet errors per access. This is the paper's main upgrade over chipkill-style ECC: it is explicitly sized for multi-aggressor overlap. Because aggressive correction raises the risk of miscorrecting random faults, RowArmor adds correction validation. When a suspicious pattern appears, it rereads the row and checks OD-ECC counters through mode-register reads; growing counters indicate disturbance-style propagation, while stable counters cause the system to reject the aggressive correction and report a DUE instead.

For many-aggressor attacks, RowArmor adds Row Address Obfuscation in the memory controller. The controller stores per-bank keys and runs a Feistel-based permutation over row addresses, so the physical pages visible to software no longer reveal which DRAM rows are adjacent. The paper's analysis says that with `128K` rows per bank, a 9-aggressor attack has only `4 x 10^-27` probability of creating nine overlapping errors at one address under this randomization model.

Finally, guardband scrubbing handles accumulation. OOC corrects on read but does not automatically write corrected values back everywhere, so untouched rows could keep collecting errors. RowArmor therefore treats a moderate correction count as an early warning. Its example threshold is three corrected octets out of the eight-octet correction budget; crossing that threshold triggers bank scrubbing, which read-correct-writes the bank before hidden rows can drift into nine-error territory. The system can also escalate by throttling suspicious threads or rotating per-bank obfuscation keys if scrubbing repeats.

## Evaluation

The evaluation covers security, performance, reliability, and area. On security, the authors compare against PARA, SRS, Cube, RAMPART, Graphene, ABACuS, and PRAC under BERs from `0.01%` to `10%` and up to `256` aggressors. At `0.01%` BER, RowArmor's targeted-attack success probability is already tiny and still falls to only `3 x 10^-57` with `256` aggressors. For DoS, it stays at `1 x 10^-43` with `16` aggressors and `9 x 10^-32` even with `256`. The low-BER story is that confinement plus OOC already makes attacks nearly impossible; the high-BER story is that guardband scrubbing becomes more valuable because error events become visible sooner.

The performance study uses McSimA+ with SPEC CPU2017 traces on a `16`-core DDR5-6400 system. The most important result is that RowArmor's cost is almost flat: only about `0.7%` slowdown even on the memory-intensive `Mix-High` workloads, and essentially no dependence on whether the assumed hammer threshold is `2048` or `128`. That contrasts with preventive schemes whose overhead rises as thresholds fall because they pay more refreshes, swaps, stalls, or counter traffic.

I found the broader support convincing because the paper also checks reliability and hardware cost instead of hiding them. OOC can correct up to three independent 1-bit errors in the Monte Carlo study, and the paper analytically estimates its silent-data-corruption probability at about `5 x 10^-19`. The controller-side obfuscation logic is only about `1,460 um^2`, and the DRAM-side scrambling logic is reported as negligible, under `0.005%` of the cited DRAM die area estimate. The combined picture supports the paper's main claim: the design meaningfully changes the security/performance frontier rather than buying safety with a hidden hardware tax.

## Novelty & Impact

Relative to _Kim et al. (MICRO '23)_, RowArmor's novelty is not merely adding another layer of scrambling to ECC-based RowHammer defense; it changes the granularity from chip-level damage handling to octet-level confinement and then sizes ECC around that new fault model. Relative to _Woo et al. (MEMSYS '23)_, it is less interested in hiding addresses alone and more interested in combining obfuscation with stronger recovery and controlled cleanup. Relative to preventive families such as PRAC or MOAT, its contribution is reframing disturbance protection as a reactive correction problem rather than a continuous counting problem.

That makes the paper likely to matter to DRAM architects, server-memory designers, and systems security researchers working on hardware-backed availability. It is a new mechanism, but also a strong reframing: the paper argues that future low-threshold DRAM may be easier to defend by making faults correctable than by making every dangerous activation observable in time.

## Limitations

RowArmor is still a fairly invasive hardware proposal. It needs controller-side row obfuscation, DRAM-internal address scrambling, a larger ECC organization, OD-ECC counter visibility, and scrubbing support in the system stack. The key-rotation path is especially heavy: the paper says the operating system may need to pause accesses to a bank and remap rows under a new permutation, which is safe but not cheap.

The security evidence is also largely analytical and simulation-based. The attack probabilities depend on a threat model where attackers cannot read the secret keys or directly probe DRAM signals, and the scrubbing analysis assumes background accesses help surface moderate-error rows before UEs form. Those assumptions are reasonable, but they mean the strongest claim is "the mechanism is robust under the modeled disturbance process," not "commodity hardware has already validated this exact implementation."

## Related Work

- _Kim et al. (MICRO '23)_ — Cube also mixes ECC with address randomization, but its protection remains limited against large overlapping-error patterns, whereas RowArmor explicitly corrects up to eight octet overlaps and then scrubs to prevent accumulation.
- _Woo et al. (MEMSYS '23)_ — RAMPART uses controller-side obfuscation and ECC-based repair, while RowArmor pushes more of the fault-shaping work into DRAM so that the ECC sees octet-confined errors rather than chip-scale damage.
- _Kim et al. (ISCA '14)_ — PARA is the classic low-cost preventive baseline based on probabilistic victim refresh, and RowArmor's main contrast is avoiding attacker-triggerable preventive refresh altogether.
- _Qureshi and Qazi (ASPLOS '25)_ — MOAT improves PRAC-style counting and refresh inside DRAM, whereas RowArmor argues that even optimized counting remains fundamentally exposed to overhead and DoS pressure.

## My Notes

<!-- empty; left for the human reader -->
