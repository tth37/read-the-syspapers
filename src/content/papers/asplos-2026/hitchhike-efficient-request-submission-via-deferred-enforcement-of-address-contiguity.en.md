---
title: "Hitchhike: Efficient Request Submission via Deferred Enforcement of Address Contiguity"
oneline: "Batches non-contiguous reads as one kernel request, then reconstructs contiguous NVMe commands only in the driver to cut submission overhead."
authors:
  - "Xuda Zheng"
  - "Jian Zhou"
  - "Shuhan Bai"
  - "Runjin Wu"
  - "Xianlin Tang"
  - "Zhiyuan Li"
  - "Hong Jiang"
  - "Fei Wu"
affiliations:
  - "Huazhong University of Science and Technology, Wuhan, China"
  - "University of Texas at Arlington, Arlington, Texas, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790173"
code_url: "https://github.com/haslaboratory/Hitchhike-AE"
tags:
  - storage
  - kernel
  - filesystems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Hitchhike argues that Linux pays too much per-request overhead because it enforces address contiguity all the way from the syscall layer down to NVMe, even though the hardware only needs contiguous LBAs at the final command boundary. It therefore lets one kernel request carry many non-contiguous offsets and buffers, then reconstructs ordinary contiguous NVMe commands only inside the driver.

## Problem

The paper starts from a mismatch between modern SSD hardware and the software path feeding it. NVMe drives expose deep parallelism, and modern storage engines keep many reads outstanding, but Linux still treats each non-contiguous range as an independent request. The same core therefore repeatedly pays for validation, translation, bio preparation, buffer pinning, submission, and completion handling even when the requests are logically just one batch against the same file.

The authors make that concrete with two measurements. A PCIe 5.0 SSD can be saturated by one core at about 60% CPU for `128 KB` sequential reads, but `4 KB` random reads need `2-4` cores, with the kernel stack consuming more than `80%` of CPU cycles. Even when four `4 KB` requests are later merged in the block layer, "scatter submission" still takes `3.27x` the submission time of issuing one `16 KB` request directly and reaches only `34.2%` of the chunked-submission throughput. Existing interfaces reduce some costs, but they preserve the same one-request-per-contiguous-range abstraction.

## Key Insight

The core claim is simple: strict address contiguity is only necessary at the device boundary, not throughout the whole stack. If the kernel delays the "must be contiguous" check until the NVMe driver, it can batch many random reads together and amortize all work that is not actually tied to one specific address.

That is why Hitchhike is more than a batching API. Address-dependent steps still iterate per offset, but generic steps are paid once per merged request. The paper's Amdahl-style model predicts a `2.34x` speedup for `4 KB` random reads with merge size `64`; the measured result is `2.29x`.

## Design

Hitchhike introduces a new request abstraction, the Hitchhike I/O (`hio`). One `hio` groups many ordinary requests, called hitchhikers, as long as they share one file descriptor. Each contributes an offset and a buffer, so the merged request carries both an offset vector and a buffer vector. The same-`fd` restriction is deliberate and lets the design degrade gracefully when requests fan out across files.

Inside the kernel, Hitchhike marks merged requests with a flag. Access checks, offset translation, DMA mapping, and tag allocation iterate over the vector, while request checks, bio preparation, and bio submission are paid once for the whole merged request. The last step is deferred metadata binding in the NVMe driver: the driver pairs DMA addresses, translated LBAs, and tags, then emits one conventional NVMe command per LBA segment. Completion is coalesced similarly: per-command resources are freed first, but the full callback waits until all hitchhikers finish.

The paper integrates Hitchhike into both `libaio` and `io_uring`, plus FIO, Blaze, and LeanStore. Because `libaio`'s `iocb` is only 64 bytes, the implementation adds a `struct hitchhiker` for offset metadata; `io_uring` gets new flags and shared-memory support. The current scope is asynchronous, direct-I/O, read-heavy workloads.

## Evaluation

The evaluation is strong on the paper's intended bottleneck. The setup uses Linux `6.5`, two Xeon Gold 6430 CPUs, and three NVMe SSDs, with most results on the Dapustor H5300. The key operating point is high-concurrency `4 KB` random reads, and the best configuration is merge size `64` with Hitchhike concurrency at least `4`; below queue depth `8`, there is little work to merge.

On the raw block path, the headline number is `2.8 M` IOPS for single-threaded `hitchhike-uring`, versus `0.8 M` for `libaio`, `1.1 M` for `io_uring-fb`, and about `2.0 M` for SPDK. The paper also reports up to `75%` fewer CPU cores needed to saturate NVMe bandwidth. On the file path, `hitchhike-uring` reaches `1.6 M` IOPS on the H5300, beating `libaio` by `2.6x` and `io_uring` by `2.3x`. The low-level measurements line up with the story: amortized submission latency falls to `169 ns` on raw I/O and `315 ns` on file I/O, while interrupt processing drops to `226 ns`. Blaze improves end-to-end execution time by `30-66%`, and LeanStore improves YCSB throughput by `17-34%` on A/B/C/F. I found that evidence convincing for read-heavy, high-QD asynchronous storage engines; that scope limit is my inference from the workloads and parameters, not a sentence the paper states explicitly.

## Novelty & Impact

Relative to SPDK, I/O Passthru, and other bypass-oriented work, Hitchhike's novelty is that it keeps the ordinary kernel stack and changes the request abstraction instead of escaping the stack. Relative to storage-stack optimization papers that tune queue scheduling, interrupts, or block-layer internals, its key move is earlier: it questions why the stack insists on one request per contiguous offset range in the first place.

That makes this paper likely to matter to people building storage engines, graph systems, and high-IOPS kernel paths on commodity Linux. Even if later systems choose different APIs, the "defer contiguity until the layer that truly requires it" idea feels reusable.

## Limitations

The design is intentionally scoped. Hitchhike only merges requests that share one file descriptor, so workloads scattered across many files lose merge opportunities and eventually degrade back to normal I/O. The strongest wins also require enough queue depth and enough same-file outstanding requests; the paper itself shows little benefit below queue depth `8`.

The implementation is narrower than the general idea. It focuses on asynchronous direct I/O and mostly on reads. Buffered I/O is future work because page-cache behavior adds another policy layer, and SPDK still holds latency better under multi-threaded scaling.

## Related Work

- _Yang et al. (CloudCom '17)_ — SPDK removes kernel overhead by moving the storage stack to user space, whereas Hitchhike keeps kernel semantics and merges non-contiguous requests inside the normal stack.
- _Zhong et al. (OSDI '22)_ — XRP bypasses parts of the kernel with eBPF, while Hitchhike changes the submission unit instead of adding a bypass path.
- _Joshi et al. (FAST '24)_ — I/O Passthru exposes a more direct `io_uring` path to the driver for block devices, but Hitchhike still supports file-system traversal and removes redundant work above the driver.
- _Hwang et al. (OSDI '21)_ — Rearchitecting Linux Storage Stack optimizes specific components, whereas Hitchhike changes the request model that causes repeated work for random reads.

## My Notes

<!-- empty; left for the human reader -->
