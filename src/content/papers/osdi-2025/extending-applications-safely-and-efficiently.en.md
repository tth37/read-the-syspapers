---
title: "Extending Applications Safely and Efficiently"
oneline: "EIM models extension privileges as capabilities over host state, functions, and resources, while bpftime enforces them with eBPF verification, MPK isolation, and concealed hooks."
authors:
  - "Yusheng Zheng"
  - "Tong Yu"
  - "Yiwei Yang"
  - "Yanpeng Hu"
  - "Xiaozheng Lai"
  - "Dan Williams"
  - "Andi Quinn"
affiliations:
  - "UC Santa Cruz"
  - "eunomia-bpf Community"
  - "ShanghaiTech University"
  - "South China University of Technology"
  - "Virginia Tech"
conference: osdi-2025
code_url: "https://github.com/eunomia-bpf/bpftime"
tags:
  - ebpf
  - isolation
  - security
  - pl-systems
category: kernel-os-and-isolation
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

The paper splits userspace extensibility into interface design and runtime enforcement. EIM states exactly which host state, functions, and resources an extension may use, and bpftime enforces that contract with eBPF-style verification, MPK-based isolation, and concealed hooks.

## Problem

Applications need extensions for observability, security, and customization, but the usual implementation choices are all flawed. Native plugins and binary instrumentation are fast but inherit the host's full privilege. Sandboxed runtimes and SFI-based tools provide some isolation, yet often force the host to enforce safety manually or add enough runtime checking to be expensive on hot paths. Subprocess-style isolation is safer, but paying context-switch-like overhead at every hook is hard to justify.

The deeper issue is that extensions need different privileges at different hook points. A monitoring probe may only need to read request state, while a firewall must modify a response but should not inspect unrelated internals. Existing systems do not give an extension manager a clean deployment-time way to express those least-privilege tradeoffs per entry.

## Key Insight

The paper's central claim is that extension safety should be described as a capability interface over everything an extension might consume: host variables, host functions, and ordinary resources such as instructions or memory. Once that interface is explicit, policy enforcement can be separated from isolation: the verifier proves the allowed behavior, and lightweight hardware protection preserves extension integrity at runtime.

The second insight is operational: an extension point that no deployment uses should impose zero runtime cost. bpftime therefore reinjects hooks only for entries that actually have a loaded extension.

## Design

EIM has two layers. The development-time specification, written by the application developer, enumerates the extension surface: state capabilities, function capabilities with constraints, and extension entries. The deployment-time specification, written by the extension manager, groups those into extension classes that grant a precise allowed capability set for one entry. That is how the model captures per-hook least privilege.

bpftime keeps the eBPF programming model. Extensions are written as eBPF programs and loaded through normal eBPF-related syscalls, but a userspace loader interposes on those calls and turns EIM rules into verifier constraints. It parses DWARF from the host, derives BTF-like type information, replaces host-function capabilities with generated mock kfuncs, inserts assertions for function constraints, and then reuses the kernel verifier before JIT-compiling the extension.

At runtime, bpftime combines binary rewriting with in-process isolation. The rewriter injects only the extension entries that are actually in use, using ordinary trampolines for function hooks and a zpoline-style rewrite for syscall hooks. The runtime then uses ERIM-style Intel MPK domains so extension code is non-writable and extension memory is only accessible while the extension executes.

## Evaluation

The evaluation matches the paper's claim because it stresses real hot-path hooks across six use cases rather than one synthetic loop. For an Nginx module, bpftime adds 2% throughput overhead, versus 11% for Lua, 12% for WebAssembly, 11% for ERIM, and 9% for RLBox. For DeepFlow, porting the existing eBPF probes to bpftime improves monitored microservice throughput by at least 1.5x over eBPF uprobes. For sslsniff, the worst-case throughput drop falls from 28.06% with eBPF to 7.41% with bpftime.

A delayed-fsync Redis extension with fast notify reaches 65k requests/s, over 5x Redis's always-on durability mode and only about 10% slower than everysec, while reducing possible crash-time data loss by five orders of magnitude relative to everysec. A FUSE metadata-cache extension cuts latency by up to 2.4 orders of magnitude. Syscount highlights concealed entries: eBPF monitoring slows both targeted and untargeted processes by about 10%, whereas bpftime slows only the monitored process by 3.36% and leaves untargeted ones unchanged.

The microbenchmarks explain why. bpftime is over an order of magnitude faster than eBPF for uprobe and uretprobe hooks, though it is about 1.5x slower for syscall tracepoints. Compatibility is also strong: 17 existing BCC and bpftrace tools run unchanged, and bpftime fails only one bpf-conformance test. The main caveat is that the non-eBPF baselines are not policy-equivalent replacements, so those results show practical overhead differences more than a controlled security comparison.

## Novelty & Impact

The novelty is the combination, not any single mechanism: a capability-style interface model for userspace extensions, an eBPF-compatible verification pipeline, MPK-based in-process isolation, and concealed hooks. Compared with Orbit, RLBox, and ERIM, the paper packages those ideas around deployment-time extension privileges rather than around generic sandboxing.

Its likely impact is practical: operators get a path to move eBPF-style tooling into userspace applications without paying uprobe trap costs or granting every plugin the full authority of the host.

## Limitations

The trust model is narrower than the title suggests. The paper assumes trusted but fallible application and extension developers, an infallible extension manager, and host control-flow integrity, so it mainly protects against buggy extensions and compromised hosts that try to tamper with extension state, not against adversarial extension authors.

The prototype also has sharp engineering limits. Development-time specifications depend on annotations and currently support only C/C++ hosts. Isolation is implemented only on Intel x86 via MPK, the runtime supports only one extension per entry point, and the paper explicitly notes exposure to syscall-based attacks known from ERIM-style designs. The trusted computing base remains substantial: the kernel verifier, binary rewriter, operating system, and hardware protection mechanism all have to work correctly.

## Related Work

- _Jing and Huang (OSDI '22)_ - Orbit isolates auxiliary execution, not deployment-time extension points.
- _Narayan et al. (USENIX Security '20)_ - RLBox sandboxes components, not capability-restricted extension hooks.
- _Vahldiek-Oberwagner et al. (USENIX Security '19)_ - ERIM provides the MPK substrate, not EIM or concealed hooks.
- _Bijlani and Ramachandran (USENIX ATC '19)_ - ExtFuse accelerates FUSE through a more invasive kernel path.

## My Notes

<!-- empty; left for the human reader -->
