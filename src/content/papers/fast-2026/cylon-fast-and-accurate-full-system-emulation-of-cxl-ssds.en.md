---
title: "Cylon: Fast and Accurate Full-System Emulation of CXL-SSDs"
oneline: "Cylon remaps EPT entries so CXL-SSD hits execute as direct loads and misses fall through FEMU, making full-system CXL-SSD studies both fast and policy-extensible."
authors:
  - "Dongha Yoon"
  - "Hansen Idden"
  - "Jinshu Liu"
  - "Berkay Inceisci"
  - "Sam H. Noh"
  - "Huaicheng Li"
affiliations:
  - "Virginia Tech"
conference: fast-2026
category: flash-and-emerging-devices
code_url: "https://github.com/MoatLab/FEMU"
tags:
  - storage
  - memory
  - caching
  - hardware
  - virtualization
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Cylon is a full-system CXL-SSD emulator that makes the fast path look like real memory and sends only misses through SSD emulation. Its core move is Dynamic EPT Remapping plus shared EPT metadata, which cuts QEMU's per-access trap overhead enough to reproduce sub-microsecond hits, tens-of-microseconds misses, and cache-policy behavior on unmodified software stacks.

## Problem

Samsung's CMM-H shows the promise of a CXL-attached SSD: small DRAM absorbs hot accesses while large NAND provides cheap byte-addressable capacity. But such prototypes are scarce and opaque, so researchers cannot systematically study eviction, prefetching, or host-device cooperation. Trace-driven and cycle-accurate simulators model internals but are too slow or too detached from real OS behavior for end-to-end studies. Upstream QEMU can run unmodified guests, yet every CXL access goes through MMIO and VM exits, pushing latency into the `10-15 us` range and erasing the sub-us hit path that defines a CXL-SSD. The missing platform is a full-system emulator that keeps real software in the loop while preserving memory-like hits and SSD-like misses.

## Key Insight

A CXL-SSD emulator should split hit and miss handling at second-stage address translation. If a page is resident in the emulated DRAM cache, the CPU should reach it through the ordinary memory path; if not, the access should trap, fetch through the SSD backend, and then flip residency. That single idea removes most hypervisor overhead on hits without giving up analyzable miss timing, and it makes cache residency explicit enough to study policies, observability, and application hints inside one platform.

## Design

Cylon exposes a CXL 2.0 Type-3 device whose visible capacity equals the backend SSD, while the cache stays hidden. Dynamic EPT Remapping gives each page a `Direct` or `Trap` state. In `Direct`, the EPT entry points at host DRAM reserved as the CXL-SSD cache, so guest loads and stores complete as normal memory accesses. In `Trap`, permissions are cleared, forcing an EPT violation that hands the request to KVM and then FEMU.

On a miss, Cylon maps the guest physical address to an SSD offset, reads the page through FEMU, inserts it into the cache, and rewrites the EPT entry so later accesses bypass the emulator. Clean evictions simply flip back to `Trap`; dirty evictions write back first. To keep these transitions cheap, Cylon batches targeted `INVEPT` and `INVVPID` invalidations and pre-allocates leaf EPT entries in a contiguous region shared by KVM and userspace. FEMU can then update residency by logical page number through compact descriptors instead of paying a KVM ioctl and a page-table walk on every fill or eviction.

Above that fast path, Cylon provides pluggable eviction and prefetch modules, hit-side observability via accessed-bit sampling or PEBS, and an application control plane for prefetch, pin, evict, tuning, and statistics. Because the backend and policy layers are modular, the same framework can also study designs beyond CMM-H.

## Evaluation

The low-level numbers show why the design matters. On the authors' machine, local DRAM is about `90 ns` and remote NUMA DRAM about `150 ns`. With cache hits forced to `100%`, Cylon delivers `0.16 us`, essentially remote-DRAM speed, while QEMU's MMIO CXL path takes `14.74 us`. On the miss path with NAND latency disabled, the initial ioctl-based design costs `23.04 us`, and Shared EPT Memory cuts that to `16.27 us`. In pointer chasing with an `8 GB` working set over a `4.8 GB` cache, Cylon shows the right bimodal behavior, with average hit-side latency of `977 ns`, while QEMU collapses everything into a single `14.6 us` mode.

The hardware comparison against Samsung's CMM-H is done with normalized working-set size, since CMM-H has a `48 GB` DRAM cache and `1 TB` backend. The trend match is good: both systems stay in the nanosecond regime when the working set fits in cache, then move into tens or hundreds of microseconds once it spills to NAND. Bandwidth tells the same story. Cylon holds remote-NUMA bandwidth until its cache saturates; CMM-H degrades somewhat earlier because of prototype controller overhead; both converge once they become NAND-bound. Redis YCSB-C and GAPBS follow the same transition, with Cylon only modestly faster in the cache-resident regime because its hit path is closer to ideal DRAM.

The policy experiments show the point of the platform. Eviction choice matters under locality: in microbenchmarks, `Stride-4096` hit rate moves from `0%` under FIFO to `60%` under LIFO. Prefetch helps only when spatial locality exists: for the same pattern, Next-`N` lifts hit rate from `18%` at `N=0` to `86%` at `N=8`, while random access stays near `25%`.

## Novelty & Impact

Relative to upstream QEMU, the novelty is moving the hit path out of MMIO and into second-stage page translation. Relative to trace-driven or cycle-accurate CXL-SSD simulators, Cylon trades some microscopic controller detail for a platform that can boot stock kernels, run real workloads, and still preserve the hit-versus-miss asymmetry that policy work depends on. That makes it useful to both architecture researchers exploring new CXL-SSD organizations and systems researchers studying eviction, prefetching, and cooperative host-device caching on unmodified software stacks.

## Limitations

Cylon is closer to an idealized CXL-SSD than to a perfect clone of Samsung's prototype. It intentionally models hits as remote-NUMA DRAM, about `150 ns`, while measured CMM-H hit latency is closer to `800 ns`. The backend is also partly idealized: capacity is currently backed by host DRAM plus FEMU timing, and the SPDK/NVMe backend is future work. Finally, the application interface is mostly an enabling mechanism rather than a deeply evaluated co-design case study, and many-core scalability is argued more than exhaustively measured.

## Related Work

- _Yang et al. (ATC '23)_ - MQSim-CXL offers configurable trace-driven CXL-SSD simulation, while Cylon keeps the host software stack live and unmodified.
- _Chung et al. (MASCOTS '25)_ - OpenCXD enables hybrid experimentation with real devices, but it depends on specialized hardware and abstracts away NAND timing.
- _Li et al. (FAST '18)_ - FEMU is the SSD timing backend Cylon builds on, but FEMU alone does not expose CXL.mem semantics or a no-VM-exit hit path.
- _Wang et al. (TCAD '25)_ - CXL-DMSim pushes full-system CXL simulation toward cycle accuracy, whereas Cylon targets real-time execution for policy and workload studies.

## My Notes

<!-- empty; left for the human reader -->
