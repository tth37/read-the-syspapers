---
title: "TiNA: Tiered Network Buffer Architecture for Fast Networking in Chiplet-based CPUs"
oneline: "Keeps SNC's low-latency local packet path, then spills bursts into remote-chiplet DCA buffers when local LLC ways fill, avoiding the long-burst latency cliff."
authors:
  - "Siddharth Agarwal"
  - "Tianchen Wang"
  - "Jinghan Huang"
  - "Saksham Agarwal"
  - "Nam Sung Kim"
affiliations:
  - "University of Illinois, Urbana-Champaign, Urbana, USA"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3760250.3762224"
code_url: "https://github.com/ece-fast-lab/ASPLOS-2026-TINA"
tags:
  - networking
  - hardware
  - memory
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

TiNA starts from a specific pathology of chiplet CPUs: `SNC` lowers packet-processing latency by keeping accesses inside one chiplet, but once bursts outgrow that chiplet's small `DCA` capacity, latency spikes sharply. The paper's answer is to keep packets in local-chiplet buffers by default and spill only the overflow into remote-chiplet buffers, using an enhanced NIC and DPDK stack to preserve ordering while recovering much of non-`SNC`'s effective cache capacity.

## Problem

The paper studies `us`-scale networking on Intel Sapphire Rapids, where a socket is built from four chiplets. In the default non-`SNC` mode, cores can use all LLC slices and DRAM controllers, but many accesses cross the on-package interconnect one or two times, adding tens of nanoseconds and more variance. That sounds tolerable for bulk workloads, but packet processing is dominated by short memory accesses, so the extra latency lands directly on end-to-end network tail latency.

`SNC` flips the tradeoff. It exposes each chiplet as a sub-NUMA node and keeps cores, LLC slices, DRAM controllers, and PCIe lanes mostly local. For short bursts, that is excellent: the paper reports up to 45% lower p50 and 50% lower p99 packet-processing latency than non-`SNC`. The problem is that `SNC` also shrinks the LLC and DRAM bandwidth visible to the packet-processing core to roughly one quarter of the socket. With `DDIO`/`DCA`, incoming packets are DMA-written into special LLC ways. Once the active `mbuf` footprint of a burst outgrows the local chiplet's `DCA` ways, the system suffers `DMA` leaks and bloats, and `SNC` becomes worse than non-`SNC` for long bursts.

So the central question is not whether `SNC` or non-`SNC` is better in general. It is how to keep `SNC`'s low-latency local path for the common case without falling off a latency cliff when queue buildup briefly exceeds the local chiplet's cache budget.

## Key Insight

The remembered idea is that packet placement, not CPU placement alone, should be adaptive on chiplet CPUs. Under `SNC`, a packet DMA-written to memory belonging to one chiplet is cached only in that chiplet's LLC slices. That means the network stack can treat local-chiplet and remote-chiplet packet buffers as two tiers of cache-backed receive storage.

TiNA's claim is that the best operating point is to fill local `DCA` ways first, because they minimize processing latency, and to spill only the excess traffic into remote-chiplet `DCA` ways before local overflow turns into unavoidable `DMA` leaks. In other words, TiNA does not choose between "strictly local" and "fully spread" placement once at boot. It converts the instantaneous active-`mbuf` size into a placement decision for each arriving packet, so only the packets that need extra capacity pay the remote-chiplet cost.

## Design

TiNA has two parts: `TiNA-stack` in `DPDK` and `TiNA-NIC` in the receive path. `TiNA-stack` allocates `N` descriptor buffers per processing core, where `N` is the number of chiplets. One descriptor buffer points to `mbufs` in the local chiplet and forms `Local-tier`; the remaining `N-1` descriptor buffers point to `mbufs` allocated in remote chiplets and collectively form `Remote-tier`. Because `SNC` keeps each memory region cached in the corresponding chiplet, packets written into those buffers land in local or remote `DCA` ways predictably.

Placement is driven by a simple finite-state policy over estimated active-buffer sizes. TiNA tracks `A_local` and `A_remote`, the currently active bytes in each tier, compares them with `D_local` and `D_remote`, the available `DCA` capacities, and considers the size `P` of the newly received packet batch. It begins in `local`, switches to `remote` when `A_local + P` would overflow local `DCA` ways, and can switch back when local capacity is freed or when remote placement would overflow too. The stack periodically reports the packet-consumption rate `C` to the NIC every `100 us` in the evaluated setup, letting the NIC age down its estimate of active bytes without waiting for software to reconstruct exact queue state.

The tricky part is ordering. Once packets can be split across tiers, TiNA must still deliver them to the application in receive order. The design therefore uses transport sequence numbers when available, or injects its own sequence number otherwise. `TiNA-stack` peeks only at the heads of descriptor buffers, remembers their sequence numbers, and keeps draining the buffer whose head has the smallest sequence number until another buffer should take over. The paper also batches remote placement across multiple hardware queues so a run of consecutive packets, not just a single packet, is steered together, which reduces both ordering overhead and receive-side batching loss.

The prototype is intentionally small. `TiNA-NIC` is implemented as roughly `500` lines of Verilog on a Xilinx `U280` FPGA sitting bump-in-the-wire in front of a ConnectX-6 NIC, using about `1k` LUTs and `2k` registers. `TiNA-stack` modifies only the `DPDK` library internals, not the application-facing APIs.

## Evaluation

The evaluation first establishes why the problem is real. On an SPR server, `SNC` lowers memory-access latency by about `45%` for `2-15 MB` working sets that fit inside one chiplet's LLC, but becomes up to `100%` worse for `15-60 MB` working sets because those accesses spill to DRAM much earlier. In the networking microbenchmark, `SNC` beats non-`SNC` at about `100 us` bursts, reaches a break-even point near `400 us`, and then loses beyond that as local `DCA` ways overflow. The paper shows the active `mbuf` footprint can exceed the `2 MB` local `DCA` budget frequently, and does so `20-50%` of the time in the end-to-end traces they later replay.

Against that backdrop, TiNA is effective and the reported gains line up with the mechanism. In `L2TouchFwd`, TiNA cuts p99 latency by about `8-10%` versus `SNC` for `250-400 us` bursts, then by about `5-10%` versus non-`SNC` for `400-700 us` bursts, while staying within about `2%` of the better baseline at the extreme short- and long-burst ends. Under increasing offered load, TiNA delays the onset of latency inflation and packet drops to roughly the non-`SNC` point, while still preferring local `DCA` ways long enough to beat non-`SNC` before that cliff.

The end-to-end results are the most compelling. On average across `L2TouchFwd`, `KVS`, `NAT`, `RSA`, and three hyperscaler-derived traces, TiNA reduces mean and p99 latency by `25%` and `18%` versus `SNC`, and by `28%` and `22%` versus non-`SNC`. The regime matters: `NAT`, with tiny per-packet work and small active-buffer footprints, already looks close to ideal under `SNC`, so TiNA mainly helps versus non-`SNC`. `KVS` benefits the most at the tail, with up to roughly `55%` lower p99 latency, because TiNA combines more cache capacity with lower local access latency and alleviates `DMA` bloat on the application's non-I/O state. `RSA`, which drives much larger active-`mbuf` sizes, sees smaller gains, which actually supports the paper's story: when every design is deep in the overflow regime, there is less headroom for clever placement to help.

I found the evaluation supportive of the core claim. The baselines are fair because the same platform is tested in `SNC`, non-`SNC`, and TiNA modes, and the mix of microbenchmarks plus full applications makes it clear where the design wins and where it saturates.

## Novelty & Impact

Relative to _Farshin et al. (EuroSys '19)_, TiNA does not try to place packet data in the single best LLC slice; it introduces a coarser but dynamic two-tier policy across chiplets. Relative to _Alian et al. (MICRO '22)_, it is not an inbound-data orchestration scheme inside one processor hierarchy, but a chiplet-aware buffering policy that turns `SNC`'s locality and non-`SNC`'s aggregate capacity into a runtime choice. Relative to _Smolyar et al. (ASPLOS '20)_, it does not rewire the PCIe topology to fight non-uniform DMA, but changes which chiplet-backed buffers packets target under `SNC`.

That makes TiNA feel like a real mechanism paper rather than just a measurement study. It gives future work a concrete interface between NIC steering, cache topology, and software packet buffers on chiplet CPUs. Anyone building low-latency dataplanes on post-monolithic server CPUs is likely to cite it.

## Limitations

TiNA depends on specific platform properties: `SNC`, `DCA`/`DDIO`, and enough NIC hardware queues to dedicate `N` queues per processing core. The paper evaluates only Sapphire Rapids-class hardware and a `100 Gbps` setup, so portability to other chiplet CPUs is plausible but not demonstrated.

The design also relies on estimating active-buffer sizes rather than observing them exactly at the NIC, and the update interval `I` is a tuning parameter. If processing rates changed more abruptly than the evaluated workloads, the estimator could misplace packets transiently. The ordering machinery is careful, but it adds overhead from polling multiple descriptor buffers; the paper explicitly shows that TiNA can be slightly worse, though by only about `2%`, when bursts are so small or so large that adaptive placement has little room to help.

Finally, TiNA is not a universal fix for pathological overload. When applications like `RSA` drive very large active-`mbuf` footprints, all designs incur substantial unavoidable leakage and the gains shrink. The paper also discusses a non-`SNC` version of TiNA, but concludes that split-`DMA` transactions make that version unattractive.

## Related Work

- _Farshin et al. (EuroSys '19)_ — CacheDirector maps packet headers toward the closest LLC slice, whereas TiNA dynamically spills overflow traffic into remote-chiplet `DCA` ways once local capacity is exhausted.
- _Farshin et al. (USENIX ATC '20)_ — Reexamining Direct Cache Access explains the `DMA` leak pathologies that TiNA turns into a runtime placement policy for chiplet CPUs.
- _Alian et al. (MICRO '22)_ — IDIO orchestrates inbound network data inside the cache hierarchy, while TiNA focuses on chiplet-aware tiering between local and remote receive buffers under `SNC`.
- _Smolyar et al. (ASPLOS '20)_ — IOctopus attacks non-uniform DMA by changing PCIe connectivity; TiNA keeps commodity topology and instead changes where packets are buffered and cached.

## My Notes

<!-- empty; left for the human reader -->
