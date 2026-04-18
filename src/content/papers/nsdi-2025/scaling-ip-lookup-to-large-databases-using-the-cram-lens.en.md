---
title: "Scaling IP Lookup to Large Databases using the CRAM Lens"
oneline: "CRAM models packet chips as joint TCAM+SRAM pipelines, then derives RESAIL and BSIC to scale IP lookup tables far beyond pure-TCAM designs on Tofino-2."
authors:
  - "Robert Chang"
  - "Pradeep Dogga"
  - "Andy Fingerhut"
  - "Victor Rios"
  - "George Varghese"
affiliations:
  - "University of California, Los Angeles"
  - "Cisco Systems"
conference: nsdi-2025
category: programmable-switches-and-smart-packet-processing
tags:
  - networking
  - hardware
  - smartnic
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

CRAM treats modern packet chips as a joint TCAM+SRAM lookup substrate rather than forcing old single-resource algorithms onto new hardware. Using that lens, the authors derive RESAIL for IPv4 and BSIC for IPv6, which scale much further on Tofino-2 than pure-TCAM or prior SRAM-heavy designs.

## Problem

Older IP lookup schemes were optimized either for TCAM or for RAM/DRAM. Modern packet chips such as Tofino, Pensando, and BlueField expose both TCAM and SRAM, but under stage budgets, limited per-packet table accesses, and P4 pipeline constraints. Classical designs therefore misfit the hardware even when their core idea is sound.

The stakes are practical. The paper projects IPv4 toward 2 million entries by 2033, IPv6 toward 500k even under slower growth, and notes that routers also need memory for VPN tables, NAT, and firewalls. On Tofino-2, a logical pure-TCAM design fits only about 250k IPv4 prefixes, while SRAM-heavy designs can exhaust stages or depend on off-chip DRAM.

## Key Insight

The key claim is that lookup algorithms should be designed in a CAM+RAM model, not merely implemented on top of one. CRAM extends the RAM model with TCAM lookups and an explicit dependency DAG, so algorithms can be compared by TCAM bits, SRAM bits, and the longest dependent path. In that model, a small amount of carefully placed TCAM often removes the worst space blowups of single-resource schemes.

## Design

CRAM programs consist of a parser, a deparser, and DAG nodes that each perform one exact or ternary lookup plus independent register operations. The most important idioms here are: compress wildcarded structure with TCAM, expand to SRAM when expansion is still cheaper than ternary storage, cut search structures where downstream state is minimized, and fan tables out when a packet cannot revisit the same memory.

RESAIL starts from SAIL's split between "find matching prefix length" and "fetch next hop." For IPv4 prefixes up to length 24 it keeps SAIL's bitmaps, but it moves prefixes longer than 24 into a small look-aside TCAM instead of using pivot pushing. It also compresses the next-hop arrays into one d-left hash table using bit-marked 25-bit keys, and uses match-action parallelism so bitmap lookups happen together. The `min_bmp` parameter trades parallelism against short-prefix expansion.

BSIC starts from DXR's range-search formulation. Its first table becomes a TCAM lookup on the first `k` bits of the address, which allows a much wider initial cut and is especially helpful for IPv6. The remaining search space is stored as binary search trees rather than a repeatedly accessed range table, because RMT hardware cannot keep revisiting one table. That fan-out raises SRAM consumption, but it makes the design implementable on packet pipelines.

The third design, MASHUP, is a hybrid trie that maps each node to TCAM or SRAM depending on whether prefix expansion stays below the paper's 3x threshold and then coalesces sparse nodes with tags. The authors treat it mainly as an option for stage-constrained hardware.

## Evaluation

The evaluation uses September 2023 BGP tables, an ideal-RMT simulator parameterized with Tofino-2 memory geometry, and actual P4 compilations on Tofino-2. It is mainly a resource-fit study, not a packet-throughput benchmark.

For IPv4, RESAIL is the strongest result. On ideal RMT it scales to about 3.8 million prefixes; on Tofino-2 it scales to about 2.25 million. The paper contrasts that with roughly 245,760 entries for logical pure TCAM and with SAIL, whose SRAM and stage costs make it impractical on this hardware.

For IPv6, BSIC reaches about 630k prefixes on ideal RMT and about 390k on Tofino-2, compared with about 340k for the SRAM-only baseline HI-BST on the ideal model. The important caveat is that BSIC needs 30 stages on Tofino-2, so the authors fit it only by recirculating packets, which halves available ports. That still supports the paper's main claim about capacity scaling, but it is a qualified deployment result. The CRAM model predicts the relative winners correctly, yet the paper also shows that abstract "steps" understate true stage cost once action bits, memory fragmentation, and ALU limits matter.

## Novelty & Impact

The paper's deeper contribution is the method, not just the three derived lookup structures. It turns "TCAM plus SRAM on programmable packet chips" into an algorithmic design space with named transformations and explicit cost metrics. That should matter beyond routing, including other database-heavy P4 tasks such as packet classification or in-network inference.

## Limitations

The generality claim is still mostly argued, not demonstrated. Everything concrete is built around IP lookup and Tofino-2-like RMT hardware; SmartNICs, FPGAs, and other applications are only sketched. The evaluation also says little about steady-state forwarding throughput or update throughput under churn.

The main practical weakness is BSIC's Tofino-2 fit: it relies on recirculation rather than a clean single-pass mapping. More broadly, CRAM is a useful first-order design model, but the paper itself shows that chip-specific details still matter enough to change stage counts by large constants.

## Related Work

- _Yang et al. (SIGCOMM '14)_ - `SAIL` solves IPv4 lookup with SRAM/DRAM and pivot pushing, while `RESAIL` revisits the same decomposition assuming TCAM+SRAM hardware and moves the long-prefix corner case into look-aside TCAM.
- _Zec et al. (CCR '12)_ - `DXR` frames lookup as range search with a direct-indexed front table, while `BSIC` keeps that framing but replaces the front table with TCAM and fans the remaining search into BSTs that respect packet-pipeline access rules.
- _Shen et al. (GLOBECOM '18)_ - `HI-BST` is an SRAM-only IPv6 lookup structure with efficient updates, whereas `BSIC` spends a small amount of TCAM to reduce SRAM and stage pressure on modern packet chips.
- _Bosshart et al. (SIGCOMM '13)_ - `RMT` provides the underlying programmable-switch architecture, while `CRAM` adds an algorithmic abstraction and cost model for building large lookup structures on top of it.

## My Notes

<!-- empty; left for the human reader -->
