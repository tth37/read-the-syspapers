---
title: "Revealing the Unstable Foundations of eBPF-Based Kernel Extensions"
oneline: "DepSurf analyzes compiled kernel images and eBPF objects together, showing that source changes, configs, and compiler rewrites make most eBPF programs far less portable than CO-RE suggests."
authors:
  - "Shawn (Wanxiang) Zhong"
  - "Jing Liu"
  - "Andrea Arpaci-Dusseau"
  - "Remzi Arpaci-Dusseau"
affiliations:
  - "University of Wisconsin-Madison"
  - "Microsoft Research"
conference: eurosys-2025
category: os-kernel-and-runtimes
doi_url: "https://doi.org/10.1145/3689031.3717497"
code_url: "https://github.com/ShawnZhong/DepSurf"
project_url: "https://github.com/ShawnZhong/DepSurf-dataset"
tags:
  - ebpf
  - kernel
  - observability
  - security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

DepSurf argues that eBPF portability breaks at the dependency surface between a program and a compiled kernel image, not just at the C source or CO-RE layer. By extracting that surface from shipped kernels and matching it against an eBPF program's dependency set, it finds both explicit failures and silent errors that ordinary portability mechanisms miss.

## Problem

eBPF is sold as a safe way to extend Linux without patching the kernel, and CO-RE strengthens the expectation that one binary can run across versions and configurations. In practice, serious eBPF tools attach to unstable internals: ordinary kernel functions, tracepoints, system calls, helper-accessed structs, and even architecture-specific `pt_regs` fields. Those dependencies shift for three different reasons: source evolution changes signatures and removes hooks, kernel configurations omit or redefine constructs, and the compiler inlines, duplicates, or transforms functions after the source already looks stable.

CO-RE only relocates known field accesses at load time. It cannot rescue a program when recompilation on the target kernel would fail, when the hook is gone, or when a function signature silently changes underneath a kprobe. The paper's `biotop` case study, which took roughly two years to unwind, is presented as representative rather than exceptional.

## Key Insight

The paper's key claim is that portability must be analyzed against compiled kernel images, not abstract source interfaces. The authors define a kernel's dependency surface as the functions, structs, tracepoints, and syscalls that eBPF programs can actually depend on, and a program's dependency set as the subset it uses. With that framing, mismatches become concrete and classifiable.

It also explains why source diffs alone are insufficient. A declaration that still exists in the tree may have vanished through full inline, become only partly observable through selective inline, or changed calling convention through compiler transformation. DepSurf makes those image-level effects first-class and maps them to concrete failure modes.

## Design

DepSurf has two stages. First it analyzes dependency surfaces from kernel images. Given `vmlinux` plus debug info, it extracts declarations for functions, structs, tracepoints, and system calls, and records function status such as full inline, selective inline, transformation, duplication, and name collision. The implementation mixes DWARF parsing, symbol-table inspection, and data-section decoding: it walks the kernel's ftrace event array to recover tracepoints, reads `sys_call_table` to resolve syscall names, and then compares images to build a dataset of additions, removals, and definition changes.

Second, it analyzes an eBPF program's dependency set from the object file. Hook names come from section names, while struct and field accesses come from the `.BTF.ext` relocation metadata already used by CO-RE. Querying the program's dependency set against the image dataset yields a per-kernel report. Missing fields predict compilation or relocation failures, missing hooks predict attachment errors, signature or compatible-type changes predict stray reads, and selective inline or duplication predict incomplete results because probes only observe some call sites.

## Evaluation

The evaluation studies real shipped kernels rather than source-only diffs. The authors analyze 25 Ubuntu kernel images spanning 17 versions across eight years, five architectures, five flavor configurations, and 14 compiler versions, then apply the resulting dataset to 53 real eBPF programs from BCC and Tracee.

Between consecutive LTS releases, up to 24% of functions and structs are added, 10% and 4% are removed, and 39% of tracepoints are added while 5% are removed. Even among surviving constructs, 6% of functions, 18% of structs, and 16% of tracepoints change definition. Configuration mostly changes presence rather than type, with roughly a quarter of functions and structs disappearing under some builds and 34% of tracepoints absent in some configurations. Compilation adds another layer: 36% of functions are fully inlined, 11% selectively inlined, 16% transformed, and 12% duplicated.

Those rates show up in real programs. Forty-two of 53 programs, or 83%, hit at least one mismatch across the examined kernels; only 9 are mismatch-free. Among function-using programs, 14 encounter selective inline, 14 signature changes, and 14 compiler transformation. Among tracepoint users, 18 of 25 see tracepoint changes. The authors also cross-reference many findings with BCC bug reports and fixes, including the `biotop` and `readahead` case studies. The main caveat is scope: this is a deep Ubuntu-centric sample, not a proof about every distro or future toolchain.

## Novelty & Impact

The novelty is not a new eBPF runtime mechanism, but a sharper statement of where portability really fails: at the binary-image boundary between a program and the kernel it meets in deployment. Prior CO-RE work provides a relocation mechanism, but DepSurf identifies the cases relocation cannot cover. Prior verifier and safety work asks whether eBPF code is valid; this paper asks whether a valid program still means the same thing on another kernel. That distinction matters for BCC and Tracee maintainers, distro builders, and kernel developers, because it turns the vague norm of "don't break userspace" into a concrete pre-release check for internal hooks that real users now depend on.

## Limitations

DepSurf does not understand semantics, only exposed constructs and their types, so it will miss hooks whose shape stays the same while behavior changes. The study also does not enumerate every distro, configuration combination, or compiler setting. Diagnosis is not repair either: some mismatches can be handled with fallbacks or better tracepoints, but others still require manual redesign of the eBPF program or new stable hooks from kernel maintainers.

## Related Work

- _Cantrill et al. (USENIX ATC '04)_ - DTrace offered a stable probing model over kernel internals; DepSurf shows that modern eBPF lacks an equivalent compatibility layer and therefore needs image-level diagnosis.
- _Tsai et al. (EuroSys '16)_ - This study of Linux API usage and compatibility stays at the system-call boundary, whereas DepSurf moves below that boundary to unstable in-kernel functions, structs, and tracepoints.
- _Jia et al. (HotOS '23)_ - This paper argues that kernel extension verification is itself difficult; DepSurf complements that view by showing how even valid eBPF extensions break as kernels evolve.
- _Deokar et al. (SIGCOMM eBPF Workshop '24)_ - Their empirical study documents developer pain in building eBPF applications; DepSurf explains that pain in terms of specific dependency-surface mismatches and their consequences.

## My Notes

<!-- empty; left for the human reader -->
