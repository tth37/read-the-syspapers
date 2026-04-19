---
title: "Enabling Virtual Priority in Data Center Congestion Control"
oneline: "PrioPlus maps priority to delay channels, letting end-host congestion control emulate many strict priorities inside one physical queue without switch changes."
authors:
  - "Zhaochen Zhang"
  - "Feiyang Xue"
  - "Keqiang He"
  - "Zhimeng Yin"
  - "Gianni Antichi"
  - "Jiaqi Gao"
  - "Yizhi Wang"
  - "Rui Ning"
  - "Haixin Nan"
  - "Xu Zhang"
  - "Peirui Cao"
  - "Xiaoliang Wang"
  - "Wanchun Dou"
  - "Guihai Chen"
  - "Chen Tian"
affiliations:
  - "Nanjing University"
  - "Shanghai Jiao Tong University"
  - "City University of Hong Kong"
  - "Politecnico Milano & Queen Mary University of London"
  - "Unaffiliated"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3717463"
code_url: "https://github.com/NASA-NJU/PrioPlus"
tags:
  - networking
  - datacenter
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

PrioPlus turns queueing delay into a virtual-priority namespace: each priority gets a delay channel, and a flow transmits only while RTT stays inside that channel. Added on top of Swift, it approximates strict priority inside one physical queue without changing the switch; in simulation, high-priority performance stays within 9% of ideal physical priorities while low-priority large flows often become faster after preemption.

## Problem

Data centers need more priority levels than switches can physically expose. Commodity switches usually offer only 8 or 12 priorities because DSCP/PFC namespaces are small and per-priority buffering is expensive. Those few queues are already consumed by coarse traffic-class isolation, leaving little room for finer-grained scheduling within a class even though coflows, RPCs, flow-size schedulers, and ML jobs benefit from many ranks.

Switch-side packet scheduling can emulate more priorities, but it typically requires ASIC support or programmable hardware. The paper asks whether the transport layer can do the job instead. Existing CCs fail: D2TCP still drives high- and low-priority flows through the same ECN threshold, and Swift with different delay targets drifts toward weighted sharing once queue fluctuation and target scaling enter the loop.

## Key Insight

The paper's central claim is that priority should be encoded as tolerated queueing delay. Each priority gets a delay channel. If RTT rises above a flow's `Dlimit`, that flow infers higher-priority traffic is active and yields completely; if RTT is still below a higher-priority flow's `Dtarget`, that flow can keep increasing until lower priorities are pushed out.

The hard part is making those channels stable: wide enough for CC oscillation and timestamp noise, but tight enough that high priorities do not inherit inflated latency. PrioPlus is the host-side control logic that makes that balance work.

## Design

PrioPlus adds two thresholds to a delay-based CC: a target `Dtarget` and a hard limit `Dlimit` for each priority, with higher priorities assigned larger values. Target scaling in the original CC is disabled. Below `Dtarget`, the original controller runs normally; above `Dlimit`, the flow stops sending and yields to higher priorities.

To recover bandwidth without wasting it, a yielded flow sends a 64-byte probe after roughly `delay - Dtarget + random(baseRTT)` and stays silent if the returned RTT is still above `Dlimit`. When RTT equals base RTT, PrioPlus uses linear start, increasing `cwnd` by a fixed `WLS` each RTT instead of jumping to line rate or using TCP-style slow start. When RTT lies between base RTT and `Dtarget`, it uses dual-RTT adaptive increase: estimate how much the window must grow to push delay into the target channel, cap that step at half the current window, and only do this every two RTTs because the effect of an increase is not fully visible after one RTT.

PrioPlus also tries to keep channels narrow. It estimates the number of same-priority contenders from inflight data divided by local `cwnd`, then scales additive increase and linear-start aggressiveness by that estimate so many flows do not oscillate out of channel together. It also requires two consecutive samples above `Dlimit` before yielding, which filters long-tail noise. In the Swift evaluation, the authors budget 3.2 microseconds for 150-flow fluctuation and 0.8 microseconds for timestamp noise, yielding 4-microsecond spacing between priorities.

## Evaluation

The implementation burden is small: 79 extra DPDK lines on top of Swift, plus nine variables, 13 bytes of per-flow state, and one extra timer. On a 10 Gbps testbed with about 13 microseconds RTT, four adjacent priorities preempt cleanly, and PrioPlus keeps delay near 37 microseconds while plain Swift often exceeds the 39.4 microsecond limit.

Most evidence comes from ns-3. In general flow scheduling, overall average FCT is at most 8% worse than ideal physical priority, while small and medium flows stay within 9% average and 19% p99. Low-priority large flows do better than physical priority plus Swift because they refill the link faster after preemption: 25% to 41% better average FCT and 24% to 43% better tail FCT. In coflow scheduling, PrioPlus improves overall speedup by 12% at 40% load and 21% at 70% load. In model training, it improves ResNet and VGG by 12% and 15% for 13% total acceleration, whereas physical priority yields +16%, -18%, and 9% total acceleration.

## Novelty & Impact

The paper positions PrioPlus as the first strict virtual-priority design that avoids switch support. Its contribution is to treat congestion control itself, rather than the switch scheduler, as the place where intra-queue priority is enforced.

If the result generalizes, operators can reserve hardware queues for inter-class isolation while still exposing many more ranks within a class for coflows, storage traffic, or ML jobs.

## Limitations

PrioPlus is tightly coupled to delay-based CC. The paper shows Swift and LEDBAT integrations, but not mainstream ECN-based datacenter CCs such as DCQCN or HPCC, nor receiver-driven transports such as Homa or pHost. It also assumes reasonably clean delay measurements and preferably highest-priority ACKs so reverse-path congestion does not distort RTT.

The deployment evidence is still modest. The real implementation is a small 10 Gbps DPDK testbed, and the stronger performance claims come from simulation. Channel widths, noise tolerance, and the flow-cardinality estimator are empirically tuned, and the paper studies strict priority rather than weighted sharing, so starvation and fairness across low priorities remain unresolved.

## Related Work

- _Vamanan et al. (SIGCOMM '12)_ - D2TCP changes ECN response by deadline, but high- and low-priority flows still share one congestion threshold.
- _Kumar et al. (SIGCOMM '20)_ - Swift provides the delay-based substrate that PrioPlus extends, but on its own it converges toward weighted sharing rather than strict virtual priority.
- _Montazeri et al. (SIGCOMM '18)_ - Homa relies on network priorities and receiver-driven scheduling, whereas PrioPlus tries to synthesize more priorities inside one physical queue.
- _Atre et al. (NSDI '24)_ - BBQ accelerates hardware packet scheduling, while PrioPlus avoids switch upgrades by moving the mechanism into host congestion control.

## My Notes

<!-- empty; left for the human reader -->
