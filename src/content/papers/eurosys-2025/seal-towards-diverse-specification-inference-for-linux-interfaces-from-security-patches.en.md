---
title: "Seal: Towards Diverse Specification Inference for Linux Interfaces from Security Patches"
oneline: "Seal learns value-flow specifications for Linux interfaces from security patches, then checks other implementations and API uses for the same latent bugs."
authors:
  - "Wei Chen"
  - "Bowen Zhang"
  - "Chengpeng Wang"
  - "Wensheng Tang"
  - "Charles Zhang"
affiliations:
  - "The Hong Kong University of Science and Technology, China"
  - "Purdue University, USA"
conference: eurosys-2025
category: os-kernel-and-runtimes
doi_url: "https://doi.org/10.1145/3689031.3717487"
code_url: "https://github.com/harperchen/SEAL.git"
tags:
  - security
  - kernel
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Seal argues that Linux interface specifications should be inferred from security patches, not from majority behavior or hand-written patterns. It represents those specifications as value-flow properties over interaction data, then uses path-sensitive reachability checks to find violations in other implementations and API usages. On Linux v6.2, that yields 167 previously unknown bugs from 12,571 security patches, with 71.9% bug-report precision.

## Problem

The paper starts from a real weakness in Linux's programming model. Subsystems communicate through APIs and function pointers, but the kernel usually guarantees only type compatibility, not the latent rules for how returned values, parameters, globals, and side effects should be handled. Those missing interface specifications are exactly where bugs like missing checks, wrong error propagation, use-after-free, and resource leaks hide.

That gap hurts both developers and static analyzers. Documentation often describes what an interface does, but not how interaction data must flow across callers and implementations. The paper's motivating example is a `buf_prepare` implementation that calls `dma_alloc_coherent`; the allocation failure is checked locally, but the function returns the wrong status to its caller, which later dereferences corrupted state and triggers a null-pointer dereference. Prior inference approaches either hard-code reusable patterns, assume the majority behavior is correct, or model only one narrow form such as API post-handling. The authors' empirical study over 158 historical patches found 11 bug types and showed that only 34.8% of bug traces stay inside the patched function, so any useful method must reason across function boundaries and over more than one bug shape.

## Key Insight

The key insight is that a security patch is a proof that some interaction-data behavior was wrong, and the changed value-flow paths reveal what the missing specification should have been. Instead of encoding a specification as a specialized tuple, Seal encodes it as a value-flow property: a constraint over which values may reach which uses, under what conditions, and in what order.

That formulation is expressive enough to cover the paper's three canonical examples. A patch can require an API failure like `-ENOMEM` to propagate back through a function-pointer return path. It can forbid dereferencing `arg2.block` of `smbus_xfer` when `arg2.len > MAX`. It can also express that `put_device` must happen only after the final dereference of `pdev->dev`. The important move is abstraction: the inferred rule keeps the source value, sink use, relevant condition, and relative order, but drops patch-specific local variables and intermediate statements so the rule can transfer to sibling implementations.

## Design

Seal has a four-stage pipeline. First, it builds pre- and post-patch program dependence graphs that include data, control, and flow edges. Second, it slices those graphs around changed interaction data to collect changed interprocedural value-flow paths. Each path comes with a source, a sink, a path condition `Psi`, and an execution-order map `Omega`.

Third, Seal classifies the changed paths into four buckets: removed paths, added paths, paths whose conditions changed, and paths whose use-site order changed. Those differences become intermediate relations over concrete program variables. A domain-mapping step then lifts those concrete relations into interface-level objects such as function-pointer arguments, API returns, dereference sites, and outgoing values. Quantifiers are inferred from how relations disappear or appear across the patch, which lets Seal express both must-exist and must-not-exist behaviors. This is why the same framework can capture wrong error-code propagation, missing checks, and disordered API usage.

Fourth, Seal applies the inferred specifications to other implementations of the same function pointer, or to other usages of the same API when no function-pointer elements are involved. Bug finding is a flow-, context-, field-, and path-sensitive reachability search over the PDG, with path conditions checked during traversal to prune infeasible paths. For scalability, the implementation is careful: PDGs are generated on demand, slicing is memoized at function boundaries, analysis runs on LLVM SSA, satisfiability checks use Z3, and indirect calls are resolved with type analysis.

## Evaluation

The evaluation is substantial and mostly aligned with the paper's claim. Seal targets Linux v6.2 and mines 12,571 security patches as inputs. From those patches it infers 12,322 relations over interface behavior and emits 232 bug reports, of which 167 are manually validated as true bugs, giving 71.9% precision. The result is not just a driver-only curiosity: 146 bugs are in drivers, 13 in networking, 7 in filesystems, and 1 in the core subsystem. Maintainers confirmed 95 bugs and 56 were fixed by the authors' patches; the discovered bugs had been latent for 7.7 years on average, and 29% were older than 10 years.

The comparison to prior systems is also strong. APHP, the closest patch-based baseline, reports 28,479 bugs but only 60 true positives because its specification form is limited to API post-handling and its path analysis is less precise. CRIX, a deviation-based missing-check detector, reports 3,105 bugs with 44 true positives and overlaps with Seal on only one bug. Seal's evidence therefore supports the paper's central claim that patch evidence plus a richer specification language finds more bug classes with much better precision.

The caveat is that specification quality is lower than final bug precision. In a random sample of 1,000 inferred specifications, only 57.8% are judged correct. The authors argue, plausibly, that incorrect specifications are less likely to be violated in extensible ways, but this still means the abstraction step is noisy. Efficiency is decent for an offline mining pass: patch processing over all 12,571 patches takes 30h39m, about 8.78 seconds per patch, while bug detection takes 5h25m for PDG generation plus 1h48m for path searching.

## Novelty & Impact

The paper's main novelty is not just using patches, but using patches to infer a specification language expressive enough to describe diverse Linux interface behaviors. Earlier patch-based work mainly learned post-handling rules; earlier deviation-based work depended on the majority being correct. Seal instead treats patches as high-quality supervision and value-flow properties as the common representation. That combination is the real contribution.

This matters because Linux static analysis often fragments by bug type. Seal offers a reusable middle layer: mine interface-level rules once, then check the rest of the codebase for the same reachability, condition, or ordering violation. The paper is likely to matter to researchers working on kernel analysis, specification mining, and patch-guided bug detection, especially because it couples an expressive formulation with maintainer-confirmed bugs rather than stopping at synthetic benchmarks.

## Limitations

Seal is only as good as the patches it mines. The paper itself notes that security patches can be obsolete, incomplete, or even wrong, and its own sampled specification precision of 57.8% shows the input signal is imperfect. A representative failure case is when a patch touches a value influenced by multiple APIs, causing Seal to conservatively infer the wrong paired operation.

The scope of the formulation is also narrower than the headline suggests. Seal handles multi-API behaviors, but not collaborative specifications spanning multiple function pointers. Its bug detection stays within implementations of the same function pointer to control cost, which misses bugs that require broader calling context. The PDG also does not model concurrency directly, so races and other synchronization bugs remain out of scope unless the graph is extended with lock or happens-before relations.

## Related Work

- _Lin et al. (USENIX Security '23)_ - APHP also mines specifications from patches, but it models only API post-handling, while Seal generalizes to path reachability, conditions, and use-site ordering.
- _Lu et al. (USENIX Security '19)_ - CRIX detects missing-check bugs by cross-checking semantically similar code, whereas Seal uses patch-backed specifications and reaches bug types beyond missing checks.
- _Yun et al. (USENIX Security '16)_ - APISan compares API usages statistically under a majority-is-correct assumption; Seal avoids that assumption by treating security patches as authoritative evidence of a violation.
- _Min et al. (SOSP '15)_ - Juxta cross-checks implementations to infer latent semantic rules, while Seal mines transferable interface constraints directly from bug-fixing history.

## My Notes

<!-- empty; left for the human reader -->
