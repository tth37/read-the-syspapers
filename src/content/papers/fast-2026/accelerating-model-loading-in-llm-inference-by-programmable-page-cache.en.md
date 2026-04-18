---
title: "Accelerating Model Loading in LLM Inference by Programmable Page Cache"
oneline: "PPC makes page-cache policy programmable, and MAIO uses per-service I/O templates to cut LLM model-loading latency by up to 79% without kernel or framework changes."
authors:
  - "Yubo Liu"
  - "Hongbo Li"
  - "Xiaojia Huang"
  - "Yongfeng Wang"
  - "Hanjun Guo"
  - "Hui Chen"
  - "Yuxin Ren"
  - "Ning Jia"
affiliations:
  - "Huawei Technologies Co., Ltd."
conference: fast-2026
category: ai-era-storage
tags:
  - llm-inference
  - filesystems
  - caching
  - storage
  - memory
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

The paper argues that LLM startup is bottlenecked more by page-cache policy than by raw SSD speed. PPC makes the page cache programmable without kernel surgery, and MAIO uses per-service I/O templates to prefetch, place, and evict model pages, cutting model-loading latency by up to `79%` with sufficient memory and `74%` when memory is constrained.

## Problem

The target is MaaS-style elastic inference, where startup delay hurts QoS and utilization. In the authors' production platform, launching `DeepSeek-R1-671B` takes one hour, and model loading from storage accounts for more than `70%` of that time. Prior accelerators such as ServerlessLLM and BlitzScale can be fast, but they require framework changes, special hardware, or other assumptions that hurt deployability. The paper instead aims to work with existing inference stacks, upstream kernels, and commodity accelerator nodes.

The default kernel policy fails on the main bottlenecks. Average SSD bandwidth during loading is only about `17%` of peak. NUMA/XPU-aware placement can reduce loading latency by about `20%`, but the kernel does not know the destination XPU of prefetched data. Under memory pressure, eviction is wrong: when available page cache is about `45%` of model size, loading slows by `38%` because the kernel cannot tell that pages already copied into device memory are cold on the host.

## Key Insight

Model loading should not be handled by generic readahead and LRU heuristics. Once the model and runtime parameters are fixed, the loading I/O pattern is reproducible per service, so a template-driven policy can predict access order and page lifetime much better than a popularity-based cache. PPC supplies the mechanism, and MAIO supplies the policy: replace implicit cache inference with an explicit service-level schedule.

## Design

PPC has a kernel-side `RFS` and a userspace `CPRT`. `RFS` is a read-only stacked file system that mirrors the underlying namespace and intercepts cache misses on `read` and `mmap` page faults, emitting a non-blocking `UPC` event with the file handle, offset, length, and PID. `CPRT` loads a policy as a dynamic library exposing hooks such as `ppc_init`, `ppc_prefetch`, and `ppc_evict`. Its cache manager uses `fadvise(..., POSIX_FADV_DONTNEED)` for eviction and a thread-pool loader plus `ioctl` for controlled page loading. The loader is both interruptible and XPU-aware.

MAIO derives a service ID from model and runtime parameters and associates it with an I/O template. If no template exists, MAIO generates one by logging miss events and mapping each PID to the XPU worker that issued it; otherwise it reuses the existing template. At runtime, MAIO maps each miss to a worker-specific I/O group and applies three mechanisms: interruptible prefetching from the current miss to the end of the group, with cancellation when the front-end stream moves ahead; XPU affinity loading into the NUMA node nearest the destination XPU; and `Burn-after-Reading` (`BAR`) eviction, which drops pages behind the miss position once they are likely resident in device memory while keeping a `1 GB` safety gap.

## Evaluation

The main testbed has four `48`-core Kunpeng 920 CPUs, eight Ascend 910B2 NPUs, `1 TB` DRAM, and a `3.75 TB` SSD, running Linux `5.10` and `vLLM-Ascend 0.9.2`. The authors evaluate five Qwen and Llama models from `7B` to `72B` and compare MAIO against `Native`, `EagerLoad`, `PreCache`, and an NPU port of ServerlessLLM. MAIO reduces model-loading latency by up to `79%` with sufficient memory and `74%` with only `64 GB` available for loading. End-to-end startup latency improves by up to `38%` and `51%` in the same two settings. Ablations also line up with the design: interruptible prefetching gives the largest gain, XPU affinity adds another `6-8.5%`, and `BAR` eviction matters mostly under memory pressure, where it adds about `19-23%`.

The systems cost is modest. PPC adds up to `3.7%` overhead on EXT4 and `6.4%` on XFS in a `memcpy-after-mmap` microbenchmark, versus `14-15%` for RFUSE, and uses about `30 MB` of memory. In `Intelligence BooM`, MAIO cuts cold-start loading of `DeepSeek-R1-671B` from `649 s` to `452 s`, even beating full DRAM caching (`561 s`) because it overlaps I/O with other startup work. The ServerlessLLM comparison is limited to sufficient-memory runs and a Transformers-based stack.

## Novelty & Impact

Relative to _Fu et al. (OSDI '24)_ and _Zhang et al. (OSDI '25)_, the novelty is pushing model-loading optimization below the inference framework and into the file-system cache path. Relative to _Cao et al. (ATC '24)_ and _Yelam et al. (ATC '25)_, PPC chooses a stacked file system plus userspace runtime rather than in-kernel eBPF hooks. The practical result is that AI teams can treat model loading as a cache-policy problem instead of a framework fork, and OS researchers get a reusable mechanism broader than MAIO itself.

## Limitations

MAIO works best when model-loading order is stable and I/O dominates startup. If the framework changes its loading sequence often, or if startup is dominated by tensor formatting rather than storage, the value of template-guided prefetch shrinks. PPC is also narrower than the name may suggest: `RFS` is read-only and only intercepts `read` and `mmap` faults, the `BAR` gap is an empirical `1 GB` constant, and multi-service contention is mostly deferred to cgroup-based QoS rather than fully evaluated. The hardware study is also concentrated on Huawei NPU nodes, so the portability of exact tuning across GPUs, SSDs, and host topologies remains open.

## Related Work

- _Fu et al. (OSDI '24)_ — ServerlessLLM optimizes loading inside the inference framework; MAIO keeps the framework a black box.
- _Zhang et al. (OSDI '25)_ — BlitzScale depends on hardware-assisted sharing, while MAIO targets local file-system loading on commodity nodes.
- _Cao et al. (ATC '24)_ — FetchBPF customizes prefetching with eBPF, but PPC is designed for richer userspace policy logic.

## My Notes

<!-- empty; left for the human reader -->
