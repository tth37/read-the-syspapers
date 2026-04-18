---
title: "DARTH-PUM: A Hybrid Processing-Using-Memory Architecture"
oneline: "Combines analog MVM arrays and digital Boolean PUM tiles on one ReRAM chip, using coordinated dataflow and shift-add support to keep whole kernels in memory."
authors:
  - "Ryan Wong"
  - "Ben Feinberg"
  - "Saugata Ghose"
affiliations:
  - "Univ. of Illinois Urbana-Champaign, Urbana, IL, USA"
  - "Sandia National Laboratories, Albuquerque, NM, USA"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790151"
tags:
  - hardware
  - memory
  - energy
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

DARTH-PUM combines analog ReRAM arrays for fast matrix-vector multiplication with nearby digital Boolean PUM pipelines for shift-add reduction, table lookup, and control-heavy stages. The key move is not another special-function unit, but a hybrid tile interface that lets full kernels stay in memory. That is enough to turn analog PUM from a narrow MVM accelerator into a more general in-memory execution substrate.

## Problem

The paper targets a basic mismatch in prior PUM systems. Analog PUM is excellent at bulk MVM, but real workloads are full of non-MVM stages: CNNs need activations and pooling, transformers need softmax and normalization, and AES spends most of its time in lookup, shift, and XOR rather than in its one matrix-multiply-like step. Existing analog designs therefore either rely on host communication or add custom CMOS special-function units, which hurts both flexibility and the original energy argument for PUM.

Digital PUM is more general and more robust to analog noise, but it is far worse at matrix-heavy kernels. A naive hybrid is still not enough, because the two domains naturally speak different "data languages": analog arrays emit wide bitline vectors, while digital PUM expects bit-striped data for pipelined Boolean operations. Once input bit-slicing is added, the system must also manage long chains of partial products, temporary registers, and instruction dependencies. The real problem is therefore architectural coordination, not simply colocating two kinds of arrays.

## Key Insight

The central claim is that digital PUM should serve as the programmable companion to analog PUM. If the analog side produces partial products and the digital side consumes them at the right rate and layout, then the digital pipelines can absorb the shift-add, lookup, element-wise logic, and control-path work that usually pushes analog accelerators back to a CPU. DARTH-PUM therefore focuses on coordination hardware, data reshaping, and a usable abstraction for variable precision, rather than on adding more application-specific units.

## Design

DARTH-PUM is organized around hybrid compute tiles (HCTs). Each tile contains 64 analog ReRAM arrays in an analog compute element (ACE), 64 RACER-style digital PUM pipelines in a digital compute element (DCE), and local coordination logic. The chip front end fetches and decodes hybrid instructions, while an 8 B/cycle ACE-DCE transfer path is provisioned to roughly match analog output bandwidth with digital write bandwidth.

The key mechanism is that the ACE performs one-bit MVM slices and streams the resulting partial-product vectors into the DCE, where shift-and-add reduction happens. Because analog results emerge along bitlines while digital PUM wants bit-striped row-wise data, DARTH-PUM adds an A/D transpose unit and fixed shift support. To preserve correctness, it also adds an analog-digital arbiter so long analog operations appear atomic to digital code, plus a pipeline-reserve mechanism so live temporary vectors are not overwritten.

The tile also includes an instruction injection unit that locally expands repeated shift-add sequences, preventing the global front end from stalling on long Boolean micro-op streams. For flexibility, the paper introduces a virtual analog core (`vACore`) abstraction that groups arrays into wider logical units and automatically configures the matching reduction sequence for different bit widths or bits-per-cell settings. On the digital side, element-wise loads and stores enable table-driven operations such as AES `SubBytes`, where each vector element indexes a different S-box entry.

The paper also addresses analog error. For AES, it remaps strictly positive matrix values into differential `-1/+1` form to reduce IR-drop effects, then applies a simple compensation factor in digital PUM after the MVM. The broader point is that the digital side is not just a logic engine; it is also the place where the hybrid design can absorb cheap post-processing corrections.

## Evaluation

The evaluation combines a modified digital-PUM simulator with CrossSim and MILO-based analog modeling. DARTH-PUM is compared against an analog-plus-CPU baseline, a pure DigitalPUM design, several application-specific accelerators, and an RTX 4090 GPU. With SAR ADCs, the modeled iso-area DARTH-PUM chip contains 1860 HCTs and about 4.1 GB of capacity.

The headline result is large and consistent. Compared with the analog-plus-CPU baseline, DARTH-PUM improves throughput by `59.4x` for AES, `14.8x` for ResNet-20 inference, and `40.8x` for an LLM encoder, for a geometric mean of `31.4x`. Energy improves by `39.6x`, `51.2x`, and `110.7x`, or `66.8x` on average. Relative to pure DigitalPUM, DARTH-PUM also cuts energy by about `2.0x`, showing that analog MVM meaningfully shortens the long Boolean sequences that dominate matrix-heavy kernels.

The workload breakdowns support the paper's story. For AES, DARTH-PUM beats the application-specific comparison point by `36.9x` because it keeps `SubBytes`, `ShiftRows`, and `AddRoundKey` in digital PUM while accelerating `MixColumns` in analog PUM, eliminating host round-trips. For ResNet-20, it comes within `26.2%` of the specialized accelerator even though it has no CNN-specific SFUs, and inference latency falls by `40.0%` over baseline. For the LLM encoder, DARTH-PUM still trails the specialized design because `71%` of its execution time remains in non-MVM stages, but it still achieves a `45.6x` speedup over baseline. I found this convincing as evidence that the hybrid interface changes the system bottleneck, even if it does not erase the advantage of fully specialized datapaths.

## Novelty & Impact

Relative to _Truong et al. (MICRO '21)_, DARTH-PUM's novelty is not faster Boolean PUM itself, but repurposing digital PUM as the programmable companion to analog arrays. Relative to _Shafiee et al. (ISCA '16)_, it rejects the assumption that analog PUM needs workload-specific post-processing hardware. Its broader contribution is to make the hybrid interface reusable enough that the same tile organization can cover cryptography, CNNs, and LLM encoders without hardware redesign. That makes the paper less about one benchmark win and more about a systems-level pattern for end-to-end in-memory execution.

## Limitations

DARTH-PUM is still a simulation-driven paper, not a silicon prototype, so its conclusions depend heavily on the device and circuit models. The reliability story is also partial: the paper reports that ResNet-20 on CIFAR-10 preserves `75.4%` end-to-end accuracy, matching its baselines, but leaves broader chip-level variation, drift, stuck-at faults, and fabrication metrology to future work. On the architecture side, some transformer operations still require dynamic matrix updates and therefore remain in digital PUM, which is why the specialized LLM accelerator keeps an edge. The `vACore` design also forces all active analog groups within a tile to share one bit width, limiting mixed-precision flexibility.

## Related Work

- _Truong et al. (MICRO '21)_ — RACER provides the bit-pipelined digital PUM substrate that DARTH-PUM repurposes as a programmable post-processing and control companion for analog MVM arrays.
- _Shafiee et al. (ISCA '16)_ — ISAAC shows how powerful analog ReRAM MVM can be, but DARTH-PUM differs by pushing non-MVM support into nearby digital PUM instead of workload-specific analog periphery and SFUs.
- _Yazdanbakhsh et al. (MICRO '22)_ — SPRINT is a transformer-oriented in-memory accelerator, whereas DARTH-PUM aims for a reusable hybrid interface that spans AES, CNNs, and LLM encoders rather than one model family.
- _Truong et al. (HPCA '26)_ — The Memory Processing Unit generalizes the interface to end-to-end in-memory execution; DARTH-PUM is complementary in showing how such execution can be realized inside a concrete hybrid analog-digital tile organization.

## My Notes

<!-- empty; left for the human reader -->
