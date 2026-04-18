---
title: "Everything Matters in Programmable Packet Scheduling"
oneline: "PACKS combines quantile-based admission control with occupancy-aware queue mapping so programmable switches approximate both PIFO ordering and PIFO drops."
authors:
  - "Albert Gran Alcoz"
  - "Balázs Vass"
  - "Pooria Namyar"
  - "Behnaz Arzani"
  - "Gábor Rétvári"
  - "Laurent Vanbever"
affiliations:
  - "ETH Zürich"
  - "BME-TMIT"
  - "USC"
  - "Microsoft Research"
conference: nsdi-2025
category: programmable-switches-and-smart-packet-processing
code_url: "https://github.com/nsg-ethz/packs"
tags:
  - networking
  - scheduling
  - smartnic
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

PACKS is a P4 scheduler for programmable switches that approximates both parts of PIFO: keeping the packets a finite PIFO would keep, and draining them in roughly rank order. It does that with a sliding-window estimate of recent ranks, quantile-based admission, and occupancy-aware mapping onto strict-priority queues.

## Problem

PIFO is attractive because it separates rank assignment from queueing: give each packet a rank and let the switch send lower ranks first. But exact PIFO requires push-in insertion and rank-aware eviction at line rate, which current programmable-switch ASICs do not expose. Prior approximations split the problem. `SP-PIFO`-style schemes spread packets across strict-priority queues and preserve ordering reasonably well, but drops are accidental, so low-priority packets can occupy buffer space that later high-priority packets should have used. `AIFO` uses rank-aware admission on a single FIFO and therefore keeps closer to the right set of packets, but it cannot sort admitted packets. For datacenter workloads that care about both latency and loss, either compromise distorts the intended policy.

## Key Insight

The key claim is that a switch does not need true push-in hardware if it can estimate which ranks are likely to arrive soon. From a sliding window of recent packets, PACKS computes the quantile of the incoming rank and uses free buffer space to derive a threshold `rdrop`: packets above the expected capacity budget should be discarded immediately. It then sets queue bounds so the amount of rank mass mapped to each priority queue matches that queue's capacity. That second step matters because the wrong bounds cause collateral drops, where a packet admitted globally still dies because one queue overflowed. Optimizing for both admission and per-queue fit gets closer to PIFO than optimizing ordering alone.

## Design

PACKS runs on a fixed set of strict-priority FIFO queues. On each arrival it updates a sliding window `W` of recent ranks, reads current buffer occupancy, and scans queues from high to low priority. Admission is quantile based: a packet is eligible only if `W.quantile(r)` is below the free-buffer fraction, optionally relaxed by burstiness factor `k`. Mapping is also quantile based: queue `i` accepts the packet when the packet's quantile fits within the cumulative free space of queues `1..i`. If a higher-priority queue is full, the packet falls to a lower queue instead of being dropped immediately, which avoids the burst losses that hurt `SP-PIFO`.

The implementation is intentionally hardware-friendly. The authors build PACKS in 439 lines of P4 on Intel Tofino 2, using 12 pipeline stages, a 16-entry sliding window, per-packet quantile computation via comparisons against stored ranks, and a ghost thread that copies egress queue occupancy back to ingress.

## Evaluation

The evaluation combines simulation, application-style workloads, and hardware. In Netbench, the authors compare `PACKS` with ideal `PIFO`, `SP-PIFO`, `AIFO`, and FIFO across uniform, Poisson, exponential, convex, and inverse-exponential rank distributions. Under the uniform case, PACKS reduces inversions by more than `3x` over `SP-PIFO`, `10x` over `AIFO`, and `12x` over FIFO, while pushing drops toward high ranks: it starts dropping around rank 79, versus 77 for AIFO and 20 for SP-PIFO. The advantage persists under skewed distributions, where PACKS cuts inversions by about `5x-7x` relative to SP-PIFO and by more than `14x` relative to AIFO/FIFO.

The paper also shows the tradeoff behind the windowed design. `|W| = 1000` performs much better than `100`, but even `|W| = 15` still beats SP-PIFO by 30%. Abrupt distribution shifts hurt, especially negative shifts that make PACKS over-drop until the window adapts. End-to-end results on pFabric-style leaf-spine workloads are strong: small-flow average FCT stays within `5%-9%` of ideal PIFO while improving over SP-PIFO by `11%-33%` and over AIFO by `2.25x-2.6x`. Fair-queuing experiments show similar gains over FIFO, AIFO, and AFQ. A final Tofino2 test confirms that PACKS allocates bandwidth to the highest-priority flow as intended and runs at line rate.

## Novelty & Impact

The contribution is a deployable approximation of full PIFO behavior on existing programmable switches, not a new rank function. `SP-PIFO` approximated ordering and `AIFO` approximated admission; PACKS unifies both in one enqueue algorithm driven by rank quantiles and queue occupancy. That makes it useful both as a practical substrate for policies like pFabric and as a design template for future programmable schedulers.

## Limitations

PACKS works best when recent ranks are predictive. Large non-stationary shifts can pollute the window and temporarily make admission too permissive or too conservative; the paper shows this clearly, but the problem remains. The hardware implementation also depends on switch-specific mechanisms such as ghost threads, uses a small 16-packet window unless additional sampling is added, and may need coarse buffer-occupancy approximations when scaling across many queues or ports. Finally, the hardware evaluation is narrower than the simulator study: it validates bandwidth allocation on Tofino2, not full application traces.

## Related Work

- _Sivaraman et al. (SIGCOMM '16)_ - PIFO defines the ideal programmable-scheduling abstraction that PACKS tries to approximate on commodity programmable switches.
- _Gran Alcoz et al. (NSDI '20)_ - `SP-PIFO` approximates PIFO's ordering with dynamic strict-priority bounds, while PACKS adds explicit admission control and occupancy-aware fallback to preserve the right packets too.
- _Yu et al. (SIGCOMM '21)_ - `AIFO` approximates PIFO's admission behavior on a single FIFO queue, whereas PACKS combines a similar rank-aware admission idea with multi-queue ordering.
- _Gao et al. (NSDI '24)_ - `Sifter` pursues inversion-free programmable scheduling through new hardware structures; PACKS instead optimizes for immediate deployability on existing data planes.

## My Notes

<!-- empty; left for the human reader -->
