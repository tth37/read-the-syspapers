---
title: "Demeter: A Scalable and Elastic Tiered Memory Solution for Virtualized Cloud via Guest Delegation"
oneline: "Demeter moves VM memory tiering into the guest, using EPT-friendly PEBS and virtual-address ranges to place hot pages while a double balloon preserves cloud elasticity."
authors:
  - "Junliang Hu"
  - "Zhisheng Hu"
  - "Chun-Feng Wu"
  - "Ming-Chang Yang"
affiliations:
  - "The Chinese University of Hong Kong"
  - "National Yang Ming Chiao Tung University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764801"
tags:
  - memory
  - virtualization
  - datacenter
category: memory-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Demeter argues that VM tiered memory should stop being a hypervisor algorithm and become a guest OS responsibility. It uses guest-visible EPT-friendly PEBS to sample guest virtual addresses, classifies hotness as ranges instead of isolated pages, and leaves the hypervisor with only elastic per-tier provisioning via a double-balloon mechanism. That split removes the worst virtualization overheads and improves performance over both hypervisor-managed and prior guest-managed baselines.

## Problem

Cloud providers increasingly need tiered memory because DRAM capacity is scaling more slowly than core counts, while PMEM and CXL.mem offer a cheaper slow tier. The difficulty is not the hardware, but deciding which pages deserve scarce fast memory when many VMs share a machine. Existing VM-oriented systems mostly solve that problem from the host side, letting the hypervisor inspect page-table state and move guest pages between tiers.

The paper shows why that design is ill-suited to modern hardware virtualization. Under two-dimensional paging, hypervisor-side access tracking depends on PTE access/dirty bits, and resetting those bits requires destructive TLB flushes. Worse, the hypervisor mostly sees guest physical addresses and loses the application locality that still exists in guest virtual address space. The obvious fix, using PEBS like recent kernel-tiering work, was widely assumed to be unavailable or unsafe for guests, and naive in-guest reuse of prior systems still wastes too much CPU when many VMs run concurrently. Demeter therefore has to solve two problems at once: make hotness tracking cheap and accurate inside the guest, while still preserving the elasticity and QoS control that cloud operators expect from the host.

## Key Insight

The paper's core proposition is that the boundary between guest and hypervisor is misplaced in prior VM tiering systems. If the hypervisor only provisions how much fast and slow memory a VM currently owns, and the guest performs the full tracking-classification-migration pipeline itself, the system regains exactly the information and mechanisms the host lacks: guest-virtual-address locality and direct access to EPT-friendly PEBS.

This works because the guest sees memory in the same layout that applications create, rather than in the fragmented guest-physical layout produced by lazy page allocation and host remapping. Demeter therefore treats hotness as a property of ranges in guest virtual address space, not of unrelated physical pages, and feeds those ranges with PEBS samples captured directly in the guest. That eliminates page-table walks for every sample, avoids repeated TLB-flush cycles, and lets the hypervisor focus on the one thing it can do well: elastic resource sizing across tenants.

## Design

Demeter splits the system into two components. Inside each VM, a guest module performs tiered memory management. In the hypervisor, a separate provisioning mechanism exposes two memory tiers and resizes them on demand. The host presents fast and slow memory as two virtual NUMA nodes via ACPI and encodes their relative distance so the guest can reconstruct the tier topology without any new application-facing abstraction.

The guest-side classifier is the paper's main algorithmic move. Demeter starts with two coarse ranges, one for the heap and one for the `mmap` region, while intentionally excluding code, data, and stack because those regions are small and predictably hot. It then maintains a segment-tree-like hierarchy of ranges that split when one region becomes significantly hotter than its neighbors and merge again after accesses decay away. Counts are halved every epoch so old heat fades naturally. The minimum split granularity is 2 MiB, which preserves hugepage-scale TLB efficiency. Ranges are ranked by access frequency normalized by size, with age used as a recency tiebreaker, so the system can fit as many genuinely hot regions as possible into fast memory.

Access tracking uses guest-visible EPT-friendly PEBS rather than scanning PTE bits. PEBS samples already contain guest virtual addresses, so Demeter can feed them directly into the range classifier instead of translating every sample back through page tables like prior PEBS systems. To keep CPU cost bounded, it uses a fixed sampling period rather than aggressive dynamic sampling and drains PEBS buffers on process context switches through a lock-free channel, avoiding dedicated polling threads and minimizing PMI overhead. For media-agnostic tracking across DRAM, PMEM, and future CXL tiers, it uses the load-latency event `MEM_TRANS_RETIRED.LOAD_LATENCY` and filters out cache hits with a 64 ns threshold.

Migration is organized as balanced relocation. After ranking ranges, Demeter builds a promotion list of pages that are in hot ranges but currently live in slow memory, and a demotion list of equal length from the coldest ranges that still occupy fast memory. It then batch-unmaps, swaps contents directly, and remaps both lists, which avoids temporary buffers, reduces lock hold times, and cuts TLB flushes. On the provisioning side, Demeter introduces a page-granular double-balloon design, one balloon per virtual NUMA tier, so a VM can move smoothly between all-fast and all-slow compositions. A VirtIO statistics queue exposes per-tier usage and pressure to the host, keeping policy decisions such as QoS and rebalancing outside the guest mechanism.

## Evaluation

The evaluation uses a dual-socket 36-core Xeon 8360Y server with DRAM and Optane PMem, plus an emulated CXL.mem setup based on remote DRAM. Each VM has 4 vCPUs and 16 GiB of tiered memory with a default 1:5 fast-to-slow ratio. The microbenchmark story is strong. Demeter balloon matches static allocation while delivering 68% higher GUPS throughput than a tier-unaware VirtIO balloon. Its access-tracking primitive costs 0.64% CPU, versus 3.08% for PTE.A/D-bit scanning and 14.61% for PML-based tracking. In the end-to-end guest comparison, Demeter's PEBS draining consumes only 3 seconds of CPU time, compared with 49 seconds for Memtis, and its migration overhead is only 28% of TPP's.

The application results are also convincing. Across seven workloads spanning databases, scientific computing, graph processing, and machine learning, Demeter improves execution time by up to 2.2x overall and beats the next-best guest design, TPP, by 28% on geometric mean. It is especially strong on static or shifting hotspots such as XSBench, LibLinear, and Silo. Against a hypervisor-based TPP variant, Demeter wins on six of seven workloads and averages 16% better performance even though the hypervisor baseline is given extra DRAM headroom. The latency-sensitive Silo experiment is a useful addition: Demeter reduces 99th-percentile latency by 23% relative to TPP. The evidence is not universal, though. PageRank remains a bad case, where the fine-grained interleaving of hot and cold graph data lets TPP do better and causes Demeter to lose in the guest-versus-hypervisor comparison.

## Novelty & Impact

Demeter's novelty is not just another page-migration heuristic. It changes who is responsible for memory tiering in a virtualized cloud. Relative to hypervisor-based systems such as RAMinate and vTMM, it argues that the host should stop trying to infer guest locality through page tables. Relative to kernel systems such as Memtis and TPP, it shows how their core ideas need to be reworked for multi-tenant VM scalability and cloud elasticity.

That makes the paper important for both systems and cloud infrastructure. It appears to be the first paper to treat guest-visible EPT-friendly PEBS as a practical primitive for VM memory tiering, and it pairs that hardware insight with a software split that cloud operators can actually deploy: guest-side TMM plus host-side provisioning. If future clouds expose more heterogeneous memory through CXL, this guest-delegated structure is a plausible template for keeping the control plane elastic without paying hypervisor-side tracking costs on every memory epoch.

## Limitations

The paper is clear about two technical limits. First, Demeter does not address intra-hugepage skewness below its 2 MiB minimum granularity, so workloads with hot and cold data tightly mixed inside a hugepage may still be misplaced. Second, its range logic does not naturally cover the file page cache, because those pages are managed in physical address space rather than the guest virtual regions Demeter tracks.

There are also deployment and evaluation caveats. Demeter depends on guest kernel support and modern PEBS virtualization support, so it is not a drop-in improvement for arbitrary guest images. The host QoS story is intentionally policy-agnostic: the mechanism exports statistics, but the paper does not build or evaluate a real cluster-level controller. Finally, the performance picture is broad but not universal. PageRank is a visible counterexample, and the security discussion is mostly design argument rather than adversarial evaluation.

## Related Work

- _Hirofuchi and Takano (SoCC '16)_ - RAMinate also performs VM tiering from the hypervisor, whereas Demeter argues that the hypervisor is exactly the wrong place to recover access locality.
- _Sha et al. (EuroSys '23)_ - vTMM keeps management in the host and uses a guest helper for page-table discovery; Demeter instead moves the whole TMM pipeline into the guest and leaves only provisioning in the host.
- _Lee et al. (SOSP '23)_ - Memtis showed that PEBS is a strong hotness source for kernel tiering, but Demeter redesigns the sampling path for virtualized guests and multi-VM scalability.
- _Al Maruf et al. (ASPLOS '23)_ - TPP proactively places pages for CXL-enabled tiered memory in the kernel, while Demeter adds guest-virtual range classification and cloud-oriented elasticity for VM settings.

## My Notes

<!-- empty; left for the human reader -->
