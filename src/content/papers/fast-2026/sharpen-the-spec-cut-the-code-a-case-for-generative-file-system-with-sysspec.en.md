---
title: "Sharpen the Spec, Cut the Code: A Case for Generative File System with SysSpec"
oneline: "SysSpec replaces vague prompts with structured functionality, modularity, and concurrency specs so LLMs can generate and evolve a usable file system."
authors:
  - "Qingyuan Liu"
  - "Mo Zou"
  - "Hengbin Zhang"
  - "Dong Du"
  - "Yubin Xia"
  - "Haibo Chen"
affiliations:
  - "Institute of Parallel and Distributed Systems, Shanghai Jiao Tong University"
conference: fast-2026
category: os-and-io-paths
code_url: "https://github.com/LLMNativeOS/specfs-ae"
project_url: "https://llmnativeos.github.io/specfs/"
tags:
  - filesystems
  - formal-methods
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`SysSpec` argues that LLMs can generate and evolve a nontrivial file system if developers stop prompting in free-form English and instead write a structured specification for behavior, module interfaces, and concurrency. Its prototype `SpecFS` reaches the same practical correctness level as a manual baseline on implemented functionality, and spec patches let it absorb ten `Ext4`-style features without hand-editing the C code.

## Problem

The paper starts from a point that is easy to miss in file-system research: the hard part is not only building the first version, but surviving the long tail of evolution. The authors quantify this using `3,157` `Ext4` commits from Linux `2.6.19` to `6.15`. Only `5.1%` of those commits add new features, while `82.4%` are bug fixes or maintenance. Their `fast commit` case study makes the asymmetry concrete: the feature itself took `9` initial commits, but then triggered about `80` follow-up commits for stabilization and maintenance.

That is exactly the regime where naive LLM code generation is weakest. Natural-language prompts cannot precisely state the invariants that matter in a file system: what helper functions guarantee, which shared structures other modules depend on, or which locks must be held on each path. Generating the whole file system in one shot exceeds model context and integration capacity; generating one module at a time creates interface mismatches and cross-module breakage. Even worse, LLM output is nondeterministic, so a framework for system software cannot assume the first generated implementation is trustworthy.

## Key Insight

The paper's central claim is that generative file systems become feasible when the developer writes a lightweight formal design instead of a vague prompt. `SysSpec` does not try to prove full correctness in the traditional sense, but it does force the important semantics into explicit structure: what each module does, what it relies on, and how concurrency is supposed to work.

Once that structure exists, code generation becomes regeneration. Developers edit specifications rather than patching low-level C directly, and the toolchain can re-synthesize every affected module while preserving declared interfaces and invariants. In other words, the paper treats specification as the durable artifact and generated code as a disposable projection of that artifact.

## Design

`SysSpec` has three specification layers. The functionality layer gives each module Hoare-style preconditions, postconditions, invariants, and, when necessary, a system algorithm or high-level intent. This lets the developer specify not only the required state transition but also the performance-relevant strategy the model should follow. The modularity layer breaks the file system into modules small enough to fit within model context and connects them through `Rely`/`Guarantee` contracts, so dependencies are explicit instead of implicit prompt context.

The concurrency layer is the most important engineering move. Rather than mixing functional and locking logic in one prompt, `SysSpec` separates them. The `SpecCompiler` first generates a sequential implementation, then performs a second pass that injects locks and other concurrent behavior from a dedicated concurrency specification. The `atomfs_ins` example shows why this matters: the model must understand not only which helper functions to call, but also what lock ownership those helpers require and return.

Evolution is driven by DAG-structured spec patches. Leaf nodes define self-contained additions, intermediate nodes build on guarantees introduced below them, and root nodes re-establish the old external guarantee so the new implementation can replace the old one cleanly. The paper's extent example updates data structures, low-level file operations, and inode management in this dependency order. Around that, the toolchain uses three agents: `SpecCompiler` for generation, `SpecValidator` for spec-based checking plus regression tests, and `SpecAssistant` for refining draft specifications. A retry-with-feedback loop lets a reviewer model criticize a candidate implementation and feed concrete fixes back into the generator.

## Evaluation

The prototype `SpecFS` is a concurrent in-memory `FUSE` file system generated from `SysSpec` and modeled after `AtomFS`. It contains `45` modules and about `4,300` lines of generated C. On `xfstests`, it fails only `64` of `754` cases, and the authors attribute those failures to unimplemented functionality rather than incorrect implementations of supported operations.

The strongest evidence is the synthesis accuracy study. For the `45` `AtomFS` modules, `SysSpec` reaches `100%` accuracy on `Gemini-2.5-Pro` and `DeepSeek-V3.1 Reasoning`, while the strongest oracle baseline, which even includes dependency code in context, peaks at `81.8%`. For evolution, the system implements ten `Ext4`-inspired features spanning `64` functional modules, and the reported accuracy is even higher because many feature patches modify existing specifications instead of creating modules from scratch. The ablation also supports the design: functionality plus modularity is enough for concurrency-agnostic modules, but thread-safe modules go from `0/5` correct to `5/5` only after adding explicit concurrency specs and self-validation.

The paper also shows that evolution is not just syntactic. Compared with manual implementations by graduate students, `SpecFS` improves development productivity by `3.0x` for the extent feature and `5.4x` for the concurrency-heavy rename path. Performance-oriented feature patches still have real effect: delayed allocation reduces data writes by up to `99.9%` on `xv6` compilation, while extents, inline data, pre-allocation, and red-black-tree block pools improve their target metrics in the expected direction.

## Novelty & Impact

Relative to verified file systems like `AtomFS` and `FSCQ`, the novelty is not stronger proof but a different role for specification: it becomes the interface between the human designer and the LLM toolchain. Relative to repo-level code agents, the paper's main claim is that "better prompts" are the wrong abstraction for a file system; what matters is making semantics, composition, and locking first-class design objects.

That makes the work interesting to both file-system builders and PL-minded systems researchers. If the approach scales beyond a `FUSE` prototype, it suggests a different maintenance model: edit the spec, regenerate the affected modules, and validate, instead of manually chasing cross-module fallout in C.

## Limitations

The paper is careful about the current scope. `SpecFS` is a user-space `FUSE` file system with no native storage stack, no direct disk access, and no crash-consistency story, so its performance results are mechanism-level rather than apples-to-apples comparisons against kernel file systems. The correctness argument is also pragmatic rather than formal: it combines tests, agent review, and some manual inspection instead of mechanized proof.

There is also a real cost shift. `SysSpec` saves manual implementation effort only if developers can write good specifications, and the paper does not fully resolve how difficult that will be for industrial systems with undocumented behaviors and legacy corner cases such as `Ext4` or `EROFS`.

## Related Work

- _Zou et al. (SOSP '19)_ — `AtomFS` is the closest technical ancestor: `SysSpec` reuses the idea of precise design contracts but targets LLM-driven generation and evolution rather than proof-oriented implementation.
- _Chen et al. (USENIX ATC '16)_ — `FSCQ` proves crash safety for a handcrafted file system, whereas `SysSpec` trades proof strength for broader synthesis and iterative evolution.
- _Zou et al. (OSDI '24)_ — `RefFS` continues the verified-file-system line with stronger formal reasoning, while `SysSpec` focuses on specification as the input to generation instead of verification alone.
- _Guo et al. (ICSE '25)_ — `Intention Is All You Need` refines natural-language intent for code changes, but `SysSpec` argues that file systems still require explicit modular and concurrency contracts.

## My Notes

<!-- empty; left for the human reader -->
