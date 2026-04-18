---
title: "Coyote v2: Raising the Level of Abstraction for Data Center FPGAs"
oneline: "Coyote v2 makes data-center FPGAs look more like shared accelerators by combining reconfigurable services, multi-stream interfaces, and cThreads in one shell."
authors:
  - "Benjamin Ramhorst"
  - "Dario Korolija"
  - "Maximilian Jakob Heer"
  - "Jonas Dann"
  - "Luhao Liu"
  - "Gustavo Alonso"
affiliations:
  - "ETH Zurich"
  - "AMD Research"
  - "ETH Zurich and The University of Tokyo"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764845"
code_url: "https://github.com/fpgasystems/Coyote"
tags:
  - hardware
  - networking
  - memory
category: gpu-and-accelerator-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Coyote v2 argues that data-center FPGAs should look more like shared accelerators than raw boards. Its three-layer shell moves reusable services into a dynamically reconfigurable layer, exposes a generic multi-stream interface, and uses `cThreads` to keep pipelined hardware busy across multiple clients.

## Problem

The paper starts from a practical bottleneck: too much FPGA effort is still spent on infrastructure. The authors cite prior work estimating that roughly 75% of development goes into DMA, memory, networking, and control plumbing rather than application logic. Worse, that infrastructure is often tightly bound to one design and hard to reuse on the next FPGA or workload.

Existing shells improve matters, but the authors argue they still fail three deployment requirements. Services are usually static, so switching from one network stack or MMU configuration to another can require taking the board off-line. Application interfaces are also too narrow: neural inference may need direct host-to-model streaming, while something as simple as vector addition needs multiple independent input streams, yet many shells force extra copies or host-side packing. Finally, large FPGAs are underused when a dependency-limited pipeline serves only one client at a time. If FPGAs are to act like real data-center accelerators, the platform must support reusable services, direct host/network integration, and dynamic workload changes without full reprovisioning.

## Key Insight

The key idea is to minimize the static region and move reusable services into a dynamic shell that can be partially reconfigured at run time. That makes the shell, rather than the raw FPGA image, the main unit of reuse. Applications can then be linked against a pre-routed shell checkpoint instead of forcing every build to resynthesize networking, memory, and control logic.

The second half of the insight is interface design. A shell only raises the abstraction level if applications can see the same generic primitives regardless of workload: multiple host/card/network streams, hardware-issued DMA, interrupts, and software support for multiplexing several clients onto one vFPGA. Coyote v2 combines both ideas so that deployment changes become shell operations instead of bespoke hardware rewrites.

## Design

Coyote v2 has three hardware layers. The static layer handles platform-specific mechanics: XDMA-based CPU-FPGA communication, shell control, host streaming, memory migration, writeback, interrupts, and ICAP-based reconfiguration. It is intentionally narrow and hidden behind AXI4 interfaces so the same shell structure can target multiple AMD boards. Reconfiguration is driven by a streaming ICAP controller rather than traditional single-word methods.

The dynamic layer holds reusable services. The memory subsystem extends Coyote's shared-virtual-memory model with configurable TLB size, associativity, and page size, including 1 GB huge pages. TLBs are on-chip, while misses fall back to the host driver, giving the system a GPU-like fault-and-migrate model across CPU DDR and FPGA HBM. The same layer can expose HBM/DDR controllers with striping across banks. Networking is provided by BALBOA, a 100G RoCEv2-compatible stack that shares the shell's virtual-memory abstractions, so RDMA traffic is translated through the same MMU/TLB machinery.

Applications run inside vFPGAs. Each vFPGA gets a control bus, interrupt path, parallel host/card/network streams, and send/completion queues so hardware can issue DMA directly. For shared PCIe and network links, the shell packetizes transfers into 4 KB chunks, interleaves them round robin, and uses per-vFPGA credits so one slow tenant cannot deadlock the rest of the system. On top of that interface, the software API adds `cThreads`, which map multiple software threads to one vFPGA pipeline. That is what lets Coyote v2 keep sequential pipelines busy without forcing software to manually interleave fine-grained chunks. The paper's traffic-sniffer service is a good example of the composition model: a filter sits between the network stack and CMAC, timestamps traffic in the application layer, stores it in HBM, and later exports a PCAP trace.

## Evaluation

The evaluation is strongest where it measures whether the abstractions actually remove concrete bottlenecks. At the reconfiguration layer, Coyote v2's ICAP controller reaches about 800 MB/s, versus 19 MB/s for AXI HWICAP, 128 MB/s for PCAP, and 145 MB/s for MCAP. End-to-end shell reconfiguration then lands between 536 and 929 ms depending on the scenario, while full reprovisioning through Vivado takes about 56-71 seconds. On the build side, compiling only the application against a pre-routed shell cuts synthesis-plus-implementation time by about 15-20%.

The data-path results are also aligned with the design. A simple pass-through benchmark on a U55C scales nearly linearly with the number of HBM streams at first and reaches 12.3 GB/s with six streams. For AES-ECB deployed as several independent vFPGAs, total bandwidth stays close to the host-memory limit at about 12 GB/s while being shared fairly across tenants. For AES-CBC, where a single client would leave a 10-stage pipeline mostly idle, one `cThread` reaches about 280 MB/s at a 32 KB message size, but throughput scales linearly as more `cThreads` share the same pipeline.

The case studies show that the shell is not limited to toy kernels. A HyperLogLog accelerator matches the original Coyote baseline closely while keeping total resource use around 10%, and loading the HLL kernel by partial reconfiguration takes 57 ms on average. The `hls4ml` integration is the most user-facing result: neural-network accelerators can be compiled and deployed from fewer than ten lines of Python, and the paper reports about an order-of-magnitude speedup over the baseline backend with similar resource usage. The caveat, which the authors acknowledge, is that the baseline is handicapped by copying inputs through FPGA HBM instead of streaming them directly from host memory.

## Novelty & Impact

The paper's novelty is not a new FPGA kernel, but a stronger systems abstraction. Relative to the original Coyote and related shells, Coyote v2 makes service-level reconfiguration, multi-stream data movement, fair sharing, and software-visible pipeline multiplexing part of the platform itself. That makes it relevant both to systems researchers building new accelerators and to practitioners trying to make FPGA deployments look less like one-off hardware integrations and more like reusable data-center infrastructure.

## Limitations

The largest limitation is portability. The layered design is pitched as general, but the implementation and evaluation are tightly tied to AMD boards, AMD IP such as XDMA and ICAP, and the authors' own services. The paper argues that the split should ease ports, yet it does not show one outside that ecosystem.

There are also boundaries on the abstractions. Reconfiguration is far faster than full reprovisioning, but hundreds of milliseconds is still not fine-grained. Applications remain linked to compatible shell configurations. The MMU has no prefetching, and the paper explicitly notes that some peak-bandwidth HBM workloads may still bypass it. Isolation is strongest across vFPGAs, not within a single vFPGA where `cThreads` share memory state unless the application partitions streams carefully. Finally, the evaluation is mostly microbenchmark-driven, so long-running production mixes and adversarial tenants remain open questions.

## Related Work

- _Korolija et al. (OSDI '20)_ - The original Coyote introduced OS-like abstractions for FPGAs; Coyote v2 keeps that direction but moves services into a dynamically reconfigurable shell and broadens the application interface.
- _Khawaja et al. (OSDI '18)_ - AmorphOS supports sharing and protection on reconfigurable fabric, but Coyote v2 emphasizes direct host streaming, richer services such as RoCEv2, and a more generic multi-stream execution interface.
- _Vaishnav et al. (TRETS '20)_ - FOS offers a modular FPGA OS for dynamic workloads, while Coyote v2 focuses more explicitly on reusable services, shared virtual memory, and service-level reconfiguration alongside application reconfiguration.
- _Li et al. (ASPLOS '25)_ - Harmonia pushes portability through reusable building blocks across heterogeneous FPGA acceleration, whereas Coyote v2 adds shared virtual memory, integrated networking, and a software model for transparent pipelined multi-client execution.

## My Notes

<!-- empty; left for the human reader -->
