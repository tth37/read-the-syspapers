---
title: "HEPIC: Private Inference over Homomorphic Encryption with Client Intervention"
oneline: "Moves only HE ciphertext management to the client, then pipelines and schedules those interventions to beat both fire-and-forget HE and hybrid MPC private inference."
authors:
  - "Kevin Nam"
  - "Youyeon Joo"
  - "Seungjin Ha"
  - "Hyungon Moon"
  - "Yunheung Paek"
affiliations:
  - "Dept. of ECE & ISRC, Seoul National University, Seoul, Republic of Korea"
  - "Ulsan National Institute of Science and Technology, Ulsan, Republic of Korea"
conference: asplos-2026
category: privacy-and-security
doi_url: "https://doi.org/10.1145/3779212.3790170"
tags:
  - security
  - ml-systems
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

HEPIC argues that HE-based private inference does not have to be purely fire-and-forget. It moves only ciphertext-management steps such as refresh, scheme switching, parameter switching, and data realignment to the client, then pipelines and schedules those interventions so the server still does the actual inference over ciphertexts. The result is a middle ground that beats both server-only HE and prior hybrid PI baselines.

## Problem

The paper starts from the gap between two standard private-inference designs. Fire-and-forget HE keeps the client passive after it uploads the encrypted input, but that means the server must perform every expensive ciphertext-management step itself: bootstrapping, scheme conversion, parameter conversion, and encrypted rotations. Systems such as LOHEN improve the accuracy-performance trade-off with layer-wise switching, yet the server still pays for all of that work through larger parameters, more compute, and more memory pressure.

Hybrid MPC systems move work back to the client and can replace some expensive HE kernels with cheaper cryptographic subprotocols, but they introduce their own problems: heavy communication, large preprocessing footprints, and frequent stalls because client and server speeds differ and the protocols have strict dependencies. The systems question is whether one can preserve HE's accuracy benefits while introducing only the interaction that is actually worth it.

## Key Insight

The key claim is that ciphertext management is the right boundary for client intervention because it has the same semantics on both sides. HEPIC can therefore move only those operations to the client without changing the inference algorithm. Unlike MPC, the interaction is programmable rather than mandatory: developers can choose where interventions happen and how often, trading server computation against communication and parameter size.

This matters because once the server does not need to perform every refresh locally, it can use smaller ciphertexts, which lowers per-operation cost and exposes more ciphertext-level parallelism. The hard part is preventing interaction from recreating MPC-style stalls. HEPIC's real insight is to make interventions polynomial-granular, streamable, and selective so they overlap with server work instead of serializing it.

## Design

HEPIC keeps the standard flow: the client encrypts the input, the server evaluates the network, and only the client decrypts the final result. Arithmetic layers use coefficient encoding inspired by Cheetah, and non-arithmetic layers use BFV-PBS. The new move is that selected intermediate ciphertexts are returned to the client for re-encryption-based management: client-side refresh instead of server-side bootstrapping, decrypt-and-re-encrypt for scheme or parameter switching, and plaintext-domain reordering instead of encrypted rotations. Before sending those values, the server masks them with additive one-time-pad noise as in prior semi-honest hybrid PI designs.

The implementation relies on overlap. If a ciphertext is about to be sent to the client, HEPIC skips relinearization because the ciphertext will not be multiplied again before re-encryption. That exposes polynomial-level pipelining: the client can process the first polynomial before the full ciphertext is ready, and the server can resume earlier on returned data. Smaller parameters also create more ciphertexts, enabling inter-kernel overlap across independent operations. Streaming transfers then avoid repeated stop-and-go round trips.

Two schedulers make the system practical. The Cache-Aware Task Allocator (CATA) chooses the coarsest parallel granularity that still fits cache, falling back from ciphertext-level work to polynomial, RNS-limb, or coefficient-level work only when necessary. The Cost-Aware Client Intervention Scheduler (CACIS) searches over ciphertext size `N` and a parameter `d`, the number of server-side bootstraps allowed between client interventions, to minimize the slowest of client compute, server compute, and communication.

## Evaluation

The evaluation uses an asymmetric setup: an Intel Atom tablet as client, and either a Xeon Gold CPU server or an NVIDIA A6000 GPU server. The workloads cover six CNNs on CIFAR-10 and ImageNet, with 1,000 validation queries per model. Baselines include LOHEN as the strongest HE system, NeuJeans and SHE as single-scheme HE systems, and a hand-built `Hybrid+` that combines optimizations from Swift, Cryptonite, and Cheetah. All systems are aligned to roughly 40-bit precision and the same stated security target.

The headline result is that HEPIC improves end-to-end latency by `2.20x-41.93x` over LOHEN and by `1.09x-10.42x` over `Hybrid+`, while keeping accuracy within `0.1` percentage points of the unencrypted models. The WAN result is especially important: `Hybrid+` slows by `2.03x` on average from LAN to WAN, while HEPIC slows by only `1.20x`, which supports the claim that streaming and selective intervention blunt the normal cost of interaction. HEPIC also benefits from stronger servers: from CPU to GPU it improves by `3.70x` on average, larger than `Hybrid+`'s `1.66x`, because CACIS changes the intervention schedule instead of keeping it fixed.

The memory numbers reinforce the same story. On the hardest `IMO` workload, `Hybrid+` peaks at `128GB` client and `412GB` server memory, LOHEN at `26.4MB` and `52.8MB`, and HEPIC at `13.6MB` on the client and `23.2-47.8MB` on the server. The ablations then map gains back to design choices: CATA delivers `2.12x-3.34x` speedups under constrained cache budgets, and CACIS adds another `1.07x` on CPU or `3.28x` on GPU over non-selective intervention choices.

## Novelty & Impact

Relative to _Nam et al. (USENIX Security '25)_, HEPIC's novelty is not another better layer-wise HE configuration, but breaking the fire-and-forget assumption while keeping the computation fundamentally HE-based. Relative to _Huang et al. (USENIX Security '22)_ and _Fu et al. (TIFS '25)_, it does not adopt full hybrid MPC/HE execution; it isolates just the ciphertext-management boundary that can move without changing semantics. Relative to _Garimella et al. (ASPLOS '23)_, it takes realistic client/server asymmetry seriously but answers it with selective intervention and scheduling rather than heavier MPC engineering.

The likely impact is opening a third design point between passive HE and fully interactive MPC, where interaction is optional, tunable, and used only where the semantics line up cleanly.

## Limitations

The paper still assumes a semi-honest model and inherits the usual masked-intermediate assumption from prior hybrid PI work, so it is not a full answer for malicious-client or malicious-server settings. The evaluation is also limited to CNN inference; the paper argues that the design should generalize, but it does not validate transformers or RNNs.

There are practical limits as well. CACIS depends on reasonably accurate latency models for the client, server, and network, and those models are backend-specific. The design also assumes the client stays available and can keep up with selective re-encryption plus streaming. Finally, if future FHE accelerators make server-side bootstrapping much cheaper, the balance that motivates HEPIC may shift.

## Related Work

- _Nam et al. (USENIX Security '25)_ — LOHEN optimizes layer-wise scheme and parameter switching inside fire-and-forget HE inference, while HEPIC questions whether those ciphertext-management steps should stay server-only at all.
- _Huang et al. (USENIX Security '22)_ — Cheetah provides efficient arithmetic building blocks for two-party private inference; HEPIC reuses coefficient encoding ideas but avoids committing the whole design to MPC-style interaction.
- _Garimella et al. (ASPLOS '23)_ — Cryptonite highlights realistic client/server asymmetry and memory pressure in hybrid PI; HEPIC addresses the same deployment concern from the HE side with selective interventions and lightweight client state.
- _Fu et al. (TIFS '25)_ — Swift speeds up hybrid PI through optimized arithmetic and MPC handling of non-arithmetic layers, whereas HEPIC tries to recover HE's cleaner execution model while introducing only the interaction it can justify.

## My Notes

<!-- empty; left for the human reader -->
