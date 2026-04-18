---
title: "Eden: Developer-Friendly Application-Integrated Far Memory"
oneline: "Eden adds a few hints at hot faulting sites so most far-memory misses are handled in user space with read-ahead and priority reclaim instead of pervasive software guards."
authors:
  - "Anil Yelam"
  - "Stewart Grant"
  - "Saarth Deshpande"
  - "Nadav Amit"
  - "Radhika Niranjan Mysore"
  - "Amy Ousterhout"
  - "Marcos K. Aguilera"
  - "Alex C. Snoeren"
affiliations:
  - "UC San Diego"
  - "Technion, Israel Institute of Technology"
  - "VMware Research"
conference: nsdi-2025
code_url: "https://github.com/eden-farmem/eden"
tags:
  - memory
  - disaggregation
  - kernel
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Eden asks developers to annotate only the few code sites that generate most far-memory faults. Those hints let the runtime fetch pages in user space, overlap RDMA with Shenango user threads, and attach read-ahead or eviction-priority metadata. It beats Fastswap by 19.4-178% and often approaches AIFM with far fewer code changes.

## Problem

Far memory had split into two unattractive extremes. Transparent paging systems such as Infiniswap, Fastswap, and Hermit keep local accesses cheap and require no application rewrite, but their miss path is expensive: a page fault traps into the kernel, costs around a microsecond before the transfer starts, and in the paper's RDMA cluster the remote fetch itself takes another 5-6 microseconds. Fastswap therefore busy-waits, and kernel-only paging gives little room for application-specific prefetch or reclaim.

App-integrated systems such as AIFM and Carbink avoid much of that fault overhead by moving memory management to user space and operating at object granularity. But they require remotable pointers, pervasive software guards, and substantial code changes; even compiler-assisted approaches like TrackFM and Mira still instrument broad parts of the program and pay guard overhead on local accesses. Eden's key empirical motivation is that performance-critical faults are sparse: across 22 applications, the median program needs only 12 code locations to cover 95% of faults. That makes a middle ground plausible.

## Key Insight

Eden's claim is that software guards are useful only at the few sites that usually lead to remote misses. A hint tells the runtime which page or region is about to be touched and whether it will need write access; optional fields such as `rdahead`, `ev_prio`, and `seq` expose simple application knowledge without forcing an object-based API.

Once a hint fires, Eden can check page metadata in user space, detect an impending miss before a hardware fault occurs, start the RDMA fetch itself, and run another Shenango user-level thread while waiting. Everywhere else, the program still uses ordinary page-based memory, so local accesses avoid the steady-state cost of remotable-pointer guards.

## Design

Eden runs on Shenango with application cores plus a dedicated control core. Application cores execute lightweight user-level threads and invoke `hint_fault(...)` before likely-remote accesses. The runtime page-aligns the address, checks per-page metadata, and returns immediately if the page is present. If the page is missing, it blocks the current user thread, issues an RDMA read, runs another thread, and finally maps the page with `UFFDIO_COPY`; write faults relax protection with `UFFDIO_WRITEPROTECT`.

Unhinted faults still trap through hardware page faults. Eden registers memory with a single `userfaultfd`, and the control core handles those events. Per-page metadata tracks presence, dirtiness, locks, and the core currently serving a miss. Page locks ensure that concurrent faults on the same page trigger only one fetch, and fault stealing lets other cores or the control core resolve stuck or imbalanced work.

Reclaim is hybrid too. Eden supports default, second-chance, LRU, and priority-based eviction. Dirty pages are write-protected, copied out, RDMA-written back, and finally unmapped with `madvise(MADV_DONTNEED)`. Because standard Linux interfaces batch only contiguous ranges, Eden adds vectorized variants of `UFFDIO_WRITEPROTECT` and `madvise` for non-contiguous pages so TLB shootdown and kernel-crossing overhead do not dominate eviction throughput.

## Evaluation

The paper evaluates Eden on three 100 Gbps servers with four end-to-end applications plus microbenchmarks. The developer-effort story is concrete. For DataFrame, 11 one-line hints cover 97.3% of faults, whereas the prior AIFM port changed 1,192 lines. More broadly, the 22-application study reports that 2-32 hints were enough to cover 95% of faults.

On DataFrame, Eden has about 12% fully local overhead versus roughly 30% for AIFM, because it avoids per-dereference remotable-pointer checks. At 22% local memory, vectorized eviction plus targeted read-ahead reduce Eden's normalized runtime to 1.75x baseline, close to AIFM's 1.67x and 37% better than Fastswap. On the synthetic Web service, priority reclaim protects hot hash-table state and yields the paper's best result, 178% over Fastswap, while remaining competitive with AIFM down to about 40% local memory.

The weak regime is equally important. When the workload consists of tiny objects with poor spatial locality, Eden's page granularity amplifies I/O and it falls behind AIFM under severe pressure. Memcached shows the opposite case: user-level latency hiding dominates, and at 10% local memory Eden reaches 1.31 MOPS versus Fastswap's 0.54 MOPS, a 104% gain. Microbenchmarks reinforce the mechanism story: vectorized write-protect and unmap improve throughput by roughly 5.4-6.6x and 3.7-5.7x, while hinted fetches deliver 38-88% more throughput than Fastswap. So the evaluation supports the central claim, but mostly for workloads with hot paths or scan structure rather than tiny-object random access.

## Novelty & Impact

Eden's contribution is a new middle point between transparent paging and object-based app integration. Compared with Fastswap, it shifts the common miss path into user space and lets access sites carry policy intent. Compared with AIFM, it keeps a page-based programming model and asks for sparse annotations instead of data-structure rewrites.

That framing should matter to far-memory and memory-disaggregation work. The paper turns the debate from "transparent or integrated?" into a more useful question: how much benefit can sparse, high-information access sites recover?

## Limitations

Eden is not transparent. Developers still need to trace fault sites and add hints, and the approach will degrade if faulting behavior is diffuse, workload-dependent, or hidden inside opaque libraries.

The deeper limit is page granularity. Small-object workloads with poor locality suffer cache and network I/O amplification, exactly as the synthetic Web service shows. Eden's miss path also still depends on kernel page tables and `userfaultfd`, so the unhinted path can be slower than pure app-integrated systems and even some paging-based designs. Finally, the AIFM and TrackFM comparisons are normalized across published artifact environments, not same-hardware head-to-head runs.

## Related Work

- _Ruan et al. (OSDI '20)_ - AIFM also exposes far memory to applications and supports application-specific policies, but it does so with remotable pointers and pervasive software guards, whereas Eden keeps paging and uses sparse hints at hot fault sites.
- _Amaro et al. (EuroSys '20)_ - Fastswap represents the transparent paging end of the design space; Eden inherits page-based compatibility but avoids many kernel-mediated misses by letting hints trigger user-space fetches first.
- _Qiao et al. (NSDI '23)_ - Hermit improves transparent far memory with feedback-directed asynchrony, while Eden accepts small developer annotations in exchange for lower miss overhead and more direct policy input.
- _Tauro et al. (ASPLOS '24)_ - TrackFM uses compiler-inserted software guards to automate app integration, but it still instruments many dereferences and pays that overhead on local accesses, which is exactly the cost Eden tries to avoid.

## My Notes

<!-- empty; left for the human reader -->
