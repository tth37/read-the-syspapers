---
title: "Self-Clocked Round-Robin Packet Scheduling"
oneline: "SCRR replaces DRR's fixed quantum with self-clocking virtual time, preserving fairness while cutting CPU waste and letting short bursts clear sooner."
authors:
  - "Erfan Sharafzadeh"
  - "Raymond Matson"
  - "Jean Tourrilhes"
  - "Puneet Sharma"
  - "Soudeh Ghorbani"
affiliations:
  - "Johns Hopkins University"
  - "Hewlett Packard Labs"
  - "University of California Riverside"
  - "Meta"
conference: nsdi-2025
code_url: "https://github.com/jean2/scrr"
tags:
  - networking
  - scheduling
  - kernel
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

SCRR keeps DRR's round-robin queue walk but replaces the fixed quantum with a self-clocked virtual-time rule. Lagging queues can send enough packets to catch up, newly active sparse queues can advance a little when safe, and the scheduler updates one global clock per round. On Linux testbeds, that preserves fair sharing while reducing both CPU waste and latency for short bursts.

## Problem

DRR is widely deployed because classic fair-queuing schedulers such as SCFQ and STFQ need ordered data structures whose cost grows with the number of active queues. But DRR gets its simplicity from a fixed quantum, and that quantum is exactly where modern traffic breaks the design. If the quantum is large enough to cover big packets or TSO/LRO-generated SKBs, latency-sensitive bursts wait behind long per-flow transmissions. If the quantum is small, the scheduler spends many visits accumulating enough deficit to send a large packet, wasting CPU.

The paper argues that today's Internet makes this trade-off worse than when DRR was proposed. Packet sizes are highly variable, and many applications generate short on-off bursts rather than permanently backlogged queues. Under those conditions, even DRR with Sparse Flow Optimization still helps mainly the first packet of a burst; later packets quickly fall back into the ordinary round-robin cycle and can wait a full scheduling round. The target, then, is a scheduler that keeps DRR's scalability but behaves more like fair queuing for short bursty flows without needing operator tuning.

## Key Insight

The core claim is that round-robin itself is not the problem; the fixed byte budget is. SCRR keeps the round-robin traversal of sub-queues but replaces the configured quantum with virtual clocking. Each queue tracks the virtual time of its head packet, and the scheduler tracks one global virtual clock for the current round. When a queue is behind that clock, SCRR keeps serving it until it catches up; when a queue is ahead, SCRR sends one packet and moves on. That makes the effective quantum adapt automatically to the workload, while still bounding fairness and burstiness. The same virtual-time machinery also lets the scheduler safely bias newly active sparse flows so multi-packet bursts can make progress immediately instead of one packet per round.

## Design

SCRR classifies packets into per-flow or per-class FIFO sub-queues. In the basic algorithm, a packet's virtual start time is `max(previous_finish, current_clock)`, and its virtual finish time is start time plus packet length divided by weight. Dequeue always transmits at least one packet from the current sub-queue. If the next packet's virtual time is still older than the current global clock, SCRR keeps sending from that queue; otherwise it rotates to the next active queue. The global clock advances only once per scheduling round, to the maximum virtual time of packets sent in that round. The authors prove that the clock advance per round is bounded by the maximum packet size and that SCRR achieves the same long-run fairness index as DRR.

The full system adds four implementation-oriented enhancements. No Packet Metadata computes virtual times at dequeue, removing packet tags and several memory operations on enqueue. Sparse Flow Optimization keeps newly active queues on a priority list. Initial Advance assigns a newly active queue a virtual time based on the previous round's clock so a short burst can often send multiple packets immediately. No Empty removes idle queues right away and only grants priority insertion when the queue has not already consumed more than its fair share. Together, those changes aim to make SCRR as close to DRR as possible in complexity while recovering much of STFQ's sparse-flow behavior.

## Evaluation

The authors implement SCRR as a Linux `tc` qdisc and compare it against tail-drop, PI2, STFQ, DRR, DRR+SFO, AIFO, and SP-PIFO on physical 10 Gbps and 25 Gbps testbeds. The evaluation is well matched to the paper's claims: it stresses packet-size variability via TSO and LRO, fairness via up to 20k active flows, and latency via request-response and synthetic VBR workloads that alternate between sparse and lightly backlogged behavior.

Under NIC offloads, SCRR-basic automatically tracks changing packet sizes and therefore avoids the DRR quantum dilemma. With 2,048 flows, it cuts scheduler CPU by 46% relative to STFQ and 23% relative to DRR with a 1500 B quantum. On fairness, SCRR stays in the same class as the other fair schedulers, maintaining a Jain index above 0.97 up to 20k active flows. That supports the paper's main theoretical claim that the adaptive scheduling rule does not buy latency by giving up fair sharing.

The latency results are the strongest part of the paper. In the request-response workload, SCRR achieves lower average latency than all alternatives while also using less CPU than the DRR variants; averaged over reply sizes, it improves latency by 87x over tail-drop, 1.5x over DRR+SFO-1500, and 1.18x over STFQ. In the VBR streaming experiment, it lowers frame latency by 15x, 1.4x, and 1.08x relative to tail-drop, DRR+SFO-1500, and STFQ. The appendix also shows why recent PIFO approximations are not an easy replacement: AIFO underutilizes the queue, and SP-PIFO causes enough packet reordering to trigger TCP retransmissions.

## Novelty & Impact

Relative to DRR, SCRR removes the operator-chosen quantum and replaces it with a workload-driven self-clocking rule. Relative to SCFQ and STFQ, it gives up global sorting and keeps a simple round-robin queue walk. Relative to Linux's existing SFO-enhanced fq/DRR style schedulers, it improves the handling of short multi-packet bursts rather than only the first packet after an idle period. That makes the paper a real mechanism paper, not just a measurement study: it offers a plausible drop-in direction for software switches, middleboxes, host stacks, and eventually hardware schedulers that want fair sharing without DRR's tuning cliff.

## Limitations

The strongest evidence comes from single-threaded Linux software schedulers on 10 Gbps and 25 Gbps testbeds, not from production deployment or a hardware pipeline replacement. The paper argues SCRR is hardware-friendly, but does not demonstrate an ASIC or NIC implementation. Most experiments also use equal-weight flow scheduling, so the weighted QoS story is supported mainly by the formulation rather than extensive measurements. Finally, SCRR's sparse-flow optimizations deliberately trade a little latency for continuously backlogged flows in order to help short bursts more, which is reasonable but still a workload-dependent choice.

## Related Work

- _Shreedhar and Varghese (SIGCOMM '95)_ - DRR is the direct baseline; SCRR keeps its round-robin scalability but removes the fixed quantum that makes DRR sensitive to packet sizes and burst structure.
- _Golestani (INFOCOM '94)_ - SCFQ introduced self-clocking virtual times with sorted eligibility, whereas SCRR uses similar virtual-time reasoning without global per-packet ordering.
- _Goyal et al. (ToN '97)_ - STFQ uses virtual start times to improve sparse-flow latency, and SCRR can be read as a lower-overhead round-robin approximation to that behavior.
- _Hoiland-Jorgensen (IEEE Communications Letters '18)_ - Sparse Flow Optimization improves DRR/fq for newly active flows, while SCRR extends the idea so short multi-packet bursts can continue progressing without breaking fairness bounds.

## My Notes

<!-- empty; left for the human reader -->
