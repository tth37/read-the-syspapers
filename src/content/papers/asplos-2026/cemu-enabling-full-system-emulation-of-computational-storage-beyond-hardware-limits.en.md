---
title: "CEMU: Enabling Full-System Emulation of Computational Storage Beyond Hardware Limits"
oneline: "CEMU freezes VM time around host-executed CSD tasks so full-system computational-storage experiments can model device compute power independently of host hardware limits."
authors:
  - "Qiuyang Zhang"
  - "Jiapin Wang"
  - "You Zhou"
  - "Peng Xu"
  - "Kai Lu"
  - "Jiguang Wan"
  - "Fei Wu"
  - "Tao Lu"
affiliations:
  - "Huazhong University of Science and Technology, Wuhan, China"
  - "Research Center for High Efficiency Computing Infrastructure, Zhejiang Lab, Hangzhou, China"
  - "DapuStor, Shenzhen, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790137"
tags:
  - storage
  - hardware
  - virtualization
  - filesystems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

CEMU is a full-system computational-storage emulator built on QEMU and FEMU. It runs offloaded work on the host for functional fidelity, freezes guest time while that work executes, and then injects a separately modeled compute delay, so the emulated CSD can appear faster or slower than the host without losing realistic system behavior.

## Problem

The paper starts from a mismatch between the questions CSD researchers want to ask and the tools they have. Real hardware platforms such as SmartSSD preserve end-to-end behavior, but they are expensive, hard to obtain, and fixed to the compute resources of the board. That makes them poor tools for exploring hypothetical future CSDs or large multi-drive systems. Simulators have the opposite tradeoff: they are cheap and configurable, but they do not run a real software stack, so page-cache effects, host-device synchronization, and storage/compute interference disappear.

The authors argue that those missing behaviors are not cosmetic. LevelDB compaction offload can get worse because CSD execution bypasses the host page cache, and compression latency varies enough with data patterns that a constant-delay model is misleading. Existing software stacks are also fragmented, sometimes overloading ordinary calls such as `pread` to mean "execute code in the drive." The goal is therefore a platform that is configurable like a simulator, realistic like a full system, and aligned with SNIA/NVMe computational-storage interfaces.

## Key Insight

The paper's central claim is that functional fidelity and emulated compute speed do not need to come from the same physical resource. The host CPU can execute the offloaded function so the system still exercises real code paths and data movement, while the emulator separately decides how long that work should appear to take from the guest's perspective. That decoupling lets CEMU model a CSD compute engine that is weaker than the host, roughly equal to it, or much stronger.

The trick is that VM time is controllable. Once inputs are in device memory and a CSD task starts, CEMU pauses the VM, stops the virtual clock, lets the host finish the computation, and then resumes the VM after adding the modeled stall. From the guest's point of view, only the modeled delay exists. Around that mechanism, the paper builds a standards-oriented stack so the storage, memory, and compute namespaces behave like one coherent CSD.

## Design

CEMU has two halves: the emulator and the software stack. The emulator extends QEMU/FEMU with an NVMe module, a computational-storage-function (CSF) module, a scheduling module, and the FEMU storage module. The emulated device exposes three namespaces: ordinary NVM storage, a memory namespace for device-memory management, and a compute namespace for downloading and executing CSFs. CSFs can be eBPF programs, shared libraries loaded with `libdl`, or FPGA bitstreams.

Performance modeling is built around compute units and a scale factor `S_csf`. Real host execution time becomes the basis for modeled execution time, which can be stretched or shrunk to emulate different in-drive compute engines. VM freezing handles the case where the target device is faster than the host. The paper reports about `21 us` of pause/resume overhead, so very fine-grained tasks must be merged. The scheduling module is pluggable, and different compute units can emulate heterogeneous accelerators.

On the storage side, CEMU reuses FEMU for flash timing and FTL behavior, then adds PCIe transfer modeling so host-device and device-device movement are not free. For multi-drive setups it exposes each CSD's device memory through BAR space and uses PCIe peer-to-peer transfers for direct CSD-to-CSD copies. On the software side, the key abstraction is FDMFS, which maps CSD device memory to files. Applications allocate memory with `fallocate`, move data with `copy_file_range`, read results with `pread`, and launch compute through `ioctl`. The stack supports both direct and indirect SNIA-style programming models and integrates with `io_uring`.

## Evaluation

The evaluation has three layers: device-level validation, software-stack overheads, and full-system case studies. For validation, the authors calibrate CEMU against Samsung SmartSSD and ScaleFlux CSD2000 using `grep`, `kNN`, `lz4`, SQL query processing, and compression benchmarks. End-to-end error stays below `10%`, with average accuracy reported as `96%` for a single SmartSSD, `95%` for three SmartSSDs, and `97%` for CSD2000 emulation. That is a strong result because it covers both single-drive and multi-drive settings.

In the direct model, total software overhead stays below `7.5%`, and FDMFS itself is lightweight. The indirect model is faster for tiny single-chunk workloads because it avoids repeated host-device synchronization, but the gap narrows once chunking and pipelining amortize those costs. Scalability is believable rather than magical: `lz4` throughput grows almost linearly up to six CSDs, while LevelDB saturates earlier because the host still does substantial work.

The case studies are the paper's best evidence. Porting Smart-Infinity for LLM training takes about 200 lines of code changes, and CEMU aligned to SmartSSD hardware tracks the real platform within `2.4%` on average. Scaling from one to three CSDs improves training time by roughly `2x-2.5x`. But making the emulated CSD compute engine hundreds of times faster yields only up to `2.4x` additional speedup, because storage I/O becomes the bottleneck. The LevelDB study tells the same kind of systems story. With a 100% write workload and equal host/CSD compute power, LevelDB-CSD improves throughput from `501 Kops/s` to `721 Kops/s`, but mixed read-write workloads can get worse because offloaded compaction loses host page-cache benefits and creates internal flash interference. A simple I/O-priority tweak helps, and a multi-CSD layout optimization cuts P2P traffic from `17.3 GB` to `12 GB`, improving throughput by `7.4%`. The evaluation therefore supports the main claim well: CEMU is useful not only for reproducing device timing, but for surfacing full-system effects that simplified simulators would miss.

## Novelty & Impact

Relative to _Li et al. (FAST '18)_, CEMU's novelty is not SSD emulation alone, but turning an SSD emulator into a standards-aware computational-storage platform with a configurable compute subsystem. Relative to _Barbalace et al. (Middleware '20)_ and _Wilcox and Litz (CHEOPS '21)_, its main advance is to go beyond functional offload emulation and model compute performance independently of the host while still preserving full-system execution. Relative to _Yang et al. (FAST '23)_, the software contribution is to keep computational-storage operations compatible with existing I/O semantics instead of overloading ordinary reads into execution requests.

That makes the paper useful both as shared infrastructure and as a cautionary methodology paper. It gives CSD researchers a common full-system platform, but it also shows that some apparent near-storage wins disappear once page-cache effects, internal flash contention, and inter-device transfers are modeled end to end.

## Limitations

CEMU's flexibility still depends on calibration. The scale factor for each CSF must come from hardware measurements, simulation, or some other external model, so inaccurate calibration will yield inaccurate conclusions. The VM-freezing mechanism also has a floor: with roughly `21 us` pause/resume overhead, very fine-grained tasks need batching, and QEMU only supports global VM-clock freezing rather than per-vCPU time control.

There are also deployment limits. CEMU scales only within one host, so total emulated flash capacity, flash bandwidth, and CSD count are constrained by host DRAM and CPU cores. FDMFS currently requires pre-allocating contiguous device-memory ranges and recreating files to resize them. Finally, the validation set is still narrow: two hardware families and a small set of kernels, not a proof that every future CSD workload will be modeled equally well.

## Related Work

- _Li et al. (FAST '18)_ — FEMU provides cheap and accurate SSD emulation, while CEMU layers a compute subsystem, CSD scheduling, and standards-aware namespaces on top of that storage base.
- _Ruan et al. (USENIX ATC '19)_ — INSIDER is a real FPGA-based in-storage computing platform, but its simplified storage emulation and hardware dependence are exactly the constraints CEMU is designed to avoid.
- _Barbalace et al. (Middleware '20)_ — blockNDP also uses QEMU-based full-system emulation, whereas CEMU adds configurable performance modeling so host-bounded functional execution does not cap the emulated CSD's apparent speed.
- _Yang et al. (FAST '23)_ — `lambda-IO` builds a unified CSD software stack, while CEMU emphasizes SNIA/NVMe compliance and file-system-level integration with existing POSIX interfaces.

## My Notes

<!-- empty; left for the human reader -->
