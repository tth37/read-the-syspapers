---
title: "MettEagle: Costs and Benefits of Implementing Containers on Microkernels"
oneline: "MettEagle builds container-style compartments on L4Re, using capability-based isolation instead of Linux hardening and matching many Linux container workloads with faster startup."
authors:
  - "Till Miemietz"
  - "Viktor Reusch"
  - "Matthias Hille"
  - "Lars Wrenger"
  - "Jana Eisoldt"
  - "Jan Klötzke"
  - "Max Kurze"
  - "Adam Lackorzynski"
  - "Michael Roitzsch"
  - "Hermann Härtig"
affiliations:
  - "Barkhausen Institut, Germany"
  - "Leibniz-Universität Hannover, Germany"
  - "Kernkonzept GmbH, Germany"
  - "Technische Universität Dresden, Germany"
conference: osdi-2025
tags:
  - kernel
  - isolation
  - security
  - serverless
  - datacenter
category: kernel-os-and-isolation
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

MettEagle asks whether container isolation becomes simpler and safer if the underlying OS is a capability-based microkernel instead of a monolithic kernel. Its answer is yes in architecture and mostly yes in practice: on L4Re, container-style compartments do not need Linux-style seccomp and namespace hardening, the trusted computing base is much smaller, and startup time is materially better than runC while end-to-end serverless workloads usually stay close to Linux containers.

## Problem

The paper starts from an uncomfortable fact about mainstream containers: on Linux they are not a fundamentally different abstraction from processes, but rather processes that have to be retroactively sandboxed. Because a monolithic kernel gives applications substantial ambient authority by default, container runtimes need extra machinery to claw that authority back. Seccomp-bpf filters system calls, namespaces virtualize visibility, and cgroups bound resource use. All three mechanisms are useful, but they also increase kernel complexity and enlarge the shared attack surface between mutually distrusting tenants.

That leads to the paper's core question. If a microkernel already enforces the principle of least authority, can container-grade isolation be built as a thinner layer on top of ordinary processes? The challenge is that microkernels are usually associated with embedded deployments, not large server-class machines running dynamic cloud workloads. So the problem is not just conceptual security. The authors also need to show that a capability-based design can support practical container features, run real software stacks, and remain performance-competitive in settings such as FaaS.

## Key Insight

The key claim is that most of what Linux containers add as special-purpose isolation machinery can be re-expressed on a microkernel as controlled capability delegation to ordinary processes. If tasks begin with no authority and only receive capabilities for the services they are allowed to use, then interface restriction, visibility restriction, and much of resource control stop being kernel-wide hardening features and become session-construction problems.

That reframing matters for both security and structure. Security improves because compartments only trust the microkernel plus the specific services they actually use, not one large shared kernel image with many unrelated subsystems. Implementation also becomes more modular: instead of teaching one kernel about every resource type through namespaces, seccomp, and cgroups, MettEagle builds service-specific sessions whose IPC endpoints expose only the narrow control or data path each compartment should see.

## Design

MettEagle runs on top of L4Re and consists of two main pieces. The low-level compartment service is the analogue of a Linux low-level runtime such as runC: it launches and tears down isolated execution environments. The high-level runtime, Phlox, offers a FaaS-oriented interface that prepares resources and requests compartment startup. Around that core the authors build a compartment environment with native L4Re services, including SPAFS for writable in-memory files, LUNA for networking, LSMM for parallel memory management, and PROMFS for a parallelized boot file system.

The compartment life cycle follows capability flow. When a new compartment is requested, Phlox first creates sessions with the needed system services. Each session returns a capability to an IPC gate, plus resource restrictions attached to that gate. Phlox then hands the collected capabilities to the compartment service, which delegates them into the tasks of the new compartment, launches those tasks, and later revokes remaining capabilities to reclaim resources. This is the paper's concrete translation of container setup into a capability system.

The most interesting part is how Linux container mechanisms map onto L4Re. Visibility restriction is implemented by giving all tasks in a compartment a chosen set of capabilities and a private namespace that maps names like `"/usr"` to those capabilities. Because L4Re has no global PID space or shared-memory keys, some virtualization layers that Linux needs simply disappear. System-call restriction does not need a seccomp analogue: services expose different IPC gates for control-plane and session data-plane operations, and untrusted compartments only receive the narrow session gates. Resource control is likewise pushed into per-service sessions, where limits such as memory, CPU placement, or network bandwidth are expressed as service-specific quotas rather than one universal cgroup framework.

The implementation section shows that this design still requires serious systems work. The authors avoid putting an L4 Linux VM under every compartment because that would bloat the TCB and erase the point of lightweight isolation. Instead they port a 10 Gbit NIC driver and a simple UDP/IP stack, add Python 3 support through a cross-compilation path, parallelize L4Re memory and boot-file services, and redesign hot paths to avoid capability revocation and thread creation on the critical path.

## Evaluation

The evaluation combines security arguments with systems measurements. On the security side, the authors report a trusted computing base of 89,271 lines of code for the MettEagle stack, versus about 2.7 million for the Linux kernel plus NIC driver, containerd, and runC in their comparison. They then study 33 high- or critical-severity Linux CVEs relevant to seccomp-bpf, namespaces, and cgroups. Their classification is intentionally qualitative, but still informative: 12 are judged fully mitigated by MettEagle's design, 16 partially mitigated, and 5 not mitigated. The strongest cases are seccomp and eBPF vulnerabilities, which largely disappear because capability-based access control replaces kernel-resident filter interpreters. The weaker cases are namespace- or resource-provider bugs that could still reappear in userspace services.

Performance results are mixed in the way a convincing prototype paper should be. Cold-start latency for one empty compartment is about 1 ms on L4Re, much faster than roughly 70 ms for runC, though still slower than a plain Linux process. Under 64 parallel launches, L4Re rises to about 100 ms while runC reaches about 200 ms. For networking, UDP ping latency is roughly 40 microseconds on all platforms. Single-thread bandwidth is lower on L4Re, about 350 MiB/s versus 900 MiB/s on Linux, because the prototype lacks features such as receive-side scaling and uses one core for driver processing; with many sockets in parallel, however, L4Re reaches line rate while Linux throughput drops.

The application benchmark uses SeBS with Python functions, which is a deliberately hostile workload for a microkernel because it triggers many file operations, allocations, and dynamic loads. Even so, for most sequential benchmarks MettEagle is within 15% of runC end-to-end, and on the HTML benchmark it is about 10% faster. In burst mode with 16 parallel invocations, empty functions and HTML remain close to runC, while ZIP and graph workloads are one to two times slower. The authors trace most of that loss to file-system overhead, not to compartment isolation itself: for example, `stat` takes around 4 microseconds on L4Re versus about 460 nanoseconds on Linux.

## Novelty & Impact

The novelty is not merely "containers on a microkernel." The paper systematically shows how the three canonical ingredients of Linux containers map onto a capability system, then backs that mapping with both a prototype and comparative measurements against runC and Firecracker-based Kata. Relative to work such as _Shen et al. (ASPLOS '19)_ and _Li et al. (ATC '22)_, MettEagle does not add more layers to compensate for Linux's security model; it argues that the base process abstraction can be made safe enough that many hardening layers become unnecessary. That makes the paper relevant to cloud isolation, serverless runtime design, and the long-running debate over whether microkernels can be practical on large machines.

## Limitations

The paper's limits are real. Its security evidence is based on proxy metrics, not formal proofs of exploit resistance, and five of the 33 studied CVEs are explicitly classified as not mitigated. The implementation also relies on a simple native service stack: no OCI image compatibility, no warm-start optimization, no disk-backed file system, and no `fork` support for workloads that expect it. Several important bottlenecks remain in capability map/unmap operations, file-system latency, and single-lock portions of `moe`, so some good results are more "the design can work" than "the platform is finished."

There are also open concerns the paper mostly discusses rather than resolves. Timing-based attacks are argued to be easier to control on L4Re because the kernel is smaller and real-time capable, but the paper does not empirically validate that claim. The networking stack reaches line rate only after parallelism hides a weak single-core fast path. And although per-compartment service instances can improve isolation, they may also raise memory cost, which the paper leaves for future work.

## Related Work

- _Biggs et al. (APSys '18)_ - This paper argued broadly that microkernel-based systems improve security; MettEagle turns that thesis into a concrete container architecture with measurements.
- _Manco et al. (SOSP '17)_ - Unikernel-based lightweight VMs also shrink TCB and startup cost, but they collapse OS and application into one guest, whereas MettEagle keeps process-level compartmentalization inside the OS.
- _Shen et al. (ASPLOS '19)_ - X-Containers improves Linux container performance and isolation by restructuring layers around containers, while MettEagle changes the underlying OS model so processes start from least authority.
- _Van't Hof and Nieh (OSDI '22)_ - BlackBox protects containers from an untrusted OS with virtualization and sanitization, whereas MettEagle tries to reduce the privileged OS attack surface directly.

## My Notes

<!-- empty; left for the human reader -->
