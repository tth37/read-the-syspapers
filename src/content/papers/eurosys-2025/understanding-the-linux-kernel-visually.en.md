---
title: "Understanding the Linux Kernel, Visually"
oneline: "Visualinux turns live kernel state into simplified object-graph diagrams by splitting extraction into ViewCL and last-mile filtering into ViewQL."
authors:
  - "Hanzhi Liu"
  - "Yanyan Jiang"
  - "Chang Xu"
affiliations:
  - "State Key Laboratory for Novel Software Technology, Nanjing University, Nanjing, China"
conference: eurosys-2025
category: os-kernel-and-runtimes
doi_url: "https://doi.org/10.1145/3689031.3696095"
project_url: "https://icsnju.github.io/visualinux"
tags:
  - kernel
  - pl-systems
  - observability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Visualinux treats running Linux kernel state as an object graph and gives developers two DSLs: ViewCL to construct a simplified graph and ViewQL to trim or restyle that graph for a specific debugging goal. The GDB-integrated prototype recreates 21 textbook-style kernel diagrams on Linux 6.1, helps explain StackRot and Dirty Pipe, and usually renders local plots in tens to hundreds of milliseconds.

## Problem

The paper starts from a familiar kernel-debugging failure mode: existing tools such as GDB scripts, logs, tracing tools, and drgn can expose almost any state, but they expose too much of it. Real kernel objects are large, pointer-heavy, and mediated by containers, unions, and indirection. Printing them textually produces long dumps that are hard to read and even harder to mentally reshape into the actual structure a developer wants to inspect.

That matters for both debugging and plain understanding. The authors use the Linux 6.1 maple tree as the motivating example: it replaced the old red-black-tree VMA structure, but understanding it from text required custom scripts just to unwrap unions, decode compressed pointers, and recover node relationships. The same problem appears in security debugging, where bugs often span multiple subsystems and only a very small slice of the state is relevant. The obvious workaround is more ad hoc scripting, but that effort is high, session-specific, and mostly discarded once the session ends.

## Key Insight

The key insight is that developers already simplify kernel state in three recurring ways: they prune irrelevant objects and fields, flatten long pointer paths into direct conceptual links, and distill complex container layouts into simpler logical forms such as lists or sets. If those operations become first-class language constructs, kernel understanding becomes a reusable program rather than a one-off debugging stunt.

Just as important, the paper separates reusable extraction from last-mile customization. ViewCL expresses how to map kernel state into a simplified object graph, while ViewQL performs lightweight SQL-like filtering and display control on the resulting graph. That split is what keeps the system practical: experts can encode the hard kernel-specific extraction once, and ordinary users can often work only in ViewQL, or even via natural-language requests synthesized into ViewQL.

## Design

Visualinux has three layers. First is ViewCL, whose basic abstraction is a `Box` corresponding to a kernel object or a virtual object. A box can expose multiple `View`s, each composed of `Text`, `Link`, or nested boxes. This lets one object be rendered with different detail levels, such as a default `task_struct` view with only `pid` and `comm`, or a scheduler-focused view that also exposes `se.vruntime` and runqueue links. The language directly supports the paper's three simplification moves: choosing which fields and nested objects to show implements pruning, dotted field expressions implement flattening, and converter functions turn low-level containers such as red-black trees or extensible arrays into simpler sequences or sets for display.

Second is ViewQL, a deliberately small SQL-like language over the generated object graph. `SELECT` identifies objects by type and predicates; `UPDATE` changes display attributes such as `view`, `trimmed`, `collapsed`, or container `direction`. It also includes set operations and `Reachable(...)` so developers can progressively narrow a large graph. The authors' examples show the intended workflow: ViewCL extracts a runqueue, maple tree, or address-space graph once, and ViewQL then collapses slot lists, hides writable VMAs, or focuses on one suspicious node.

Third is the debugger UI. Visualinux runs as a detached front-end for GDB with pane-based interaction: primary panes show extracted graphs, secondary panes show focused subsets, and a focus operation locates the same object across multiple views. The implementation exposes three commands: `vplot` to execute ViewCL and produce graphs, `vctrl` to manage panes and apply ViewQL, and `vchat` to translate natural-language requests into either command. Under the hood, the GDB side is about 4,000 lines of Python plus about 500 lines of GDB scripts, while the visualizer is about 2,000 lines of TypeScript.

## Evaluation

The evaluation is organized around the paper's actual claim: not raw debugger throughput, but whether a programmable visual abstraction can make current Linux state understandable. The strongest evidence is the ULK revival experiment. Visualinux recreates 21 representative figures inspired by _Understanding the Linux Kernel_ on Linux 6.1. The authors argue this matters because 17 of those 21 figures are no longer timely for modern kernels, and 14 of 17 kernel-mechanism figures have undergone significant implementation changes since Linux 2.6.11. The required ViewCL deltas are modest enough to be believable, ranging from 19 to 154 lines for most entries.

The paper then checks whether the interaction model is lightweight. For 10 hypothetical debugging objectives, each customization uses fewer than 10 lines of ViewQL, and DeepSeek-V2 correctly generates all 10 ViewQL programs from natural-language descriptions. That is encouraging evidence for the ViewCL/ViewQL split, although it is still a narrow prompt set rather than a broad user study.

The two case studies are more compelling than the LLM demo. For StackRot (CVE-2023-3269), Visualinux visualizes the maple tree together with the RCU waiting list and lets the developer pin the suspicious node while trimming unrelated VMAs. For Dirty Pipe (CVE-2022-0847), about 60 lines of ViewCL plus a short ViewQL query isolate the single page shared between a file and a pipe with the erroneous `CAN_MERGE` flag. Those examples support the paper's central claim that the tool helps developers move from huge reference graphs to the small state slice that actually explains the bug.

Performance is acceptable locally but clearly workload-dependent. Across 20 representative plots, total extraction cost on local GDB+QEMU ranges from 10.1 ms to 326.0 ms. On KGDB attached to a Raspberry Pi 400, the same range becomes 17.4 ms to 20,904.3 ms, with the authors attributing the slowdown mainly to repeated C-expression evaluation and the high cost of remote object retrieval. That supports the paper's more modest conclusion: ViewQL and rendering are cheap, but large plots over slow remote debugging links can still be painful.

## Novelty & Impact

The paper's novelty is not a new debugger backend or a new kernel-analysis algorithm. It is the decomposition of kernel-state understanding into a reusable visual extraction language, a lightweight query language for last-mile customization, and a graph-oriented debugger UI. That combination is more concrete than prior calls for better interactive debugging and more useful than one-off scripts because it gives developers a way to preserve understanding work across sessions.

The likely impact is highest for three groups: kernel developers trying to understand fast-moving internal data structures, educators who need current diagrams instead of stale textbook figures, and security engineers analyzing bugs that span several subsystems. The ULK revival result is especially effective here because it frames Visualinux as a way to regenerate explanations for the current kernel rather than as just another debugger plugin.

## Limitations

The paper is honest that Visualinux is a state-visualization tool, not a full debugging replacement. It does not directly address temporal reasoning such as lock-state evolution over time, and the authors explicitly exclude some synchronization and architecture-level textbook figures for that reason. Developers still need to pause execution at the right moments and iteratively drive the session themselves.

The other major limitation is authoring cost. ViewQL is intentionally small, but ViewCL remains kernel-specific and sometimes requires helper scripts to decode containers, unions, and packed fields. The maple-tree example alone takes about 70 lines of ViewCL plus about 100 lines of GDB Python helpers. Finally, the evaluation shows utility rather than developer productivity: there is no controlled user study against drgn, plain GDB scripts, or textual debugging workflows, and large remote-KGDB plots can still take seconds to tens of seconds.

## Related Work

- _Fragkoulis et al. (EuroSys '14)_ - PiCO QL exposes Unix kernel data structures through a relational interface, while Visualinux adds explicit graph construction plus prune/flatten/distill operators for visual understanding.
- _Bissyandé et al. (ASE '12)_ - Diagnosys generates a Linux-kernel debugging interface automatically; Visualinux instead emphasizes programmable view construction and interactive graph manipulation.
- _Ko and Myers (ICSE '08)_ - Whyline helps developers ask why and why-not questions about program behavior, whereas Visualinux focuses on making the current kernel state itself readable.
- _Alaboudi and Latoza (UIST '23)_ - Hypothesizer supports iterative hypothesis testing during debugging; Visualinux contributes the domain-specific state abstraction and UI for Linux-kernel data structures.

## My Notes

<!-- empty; left for the human reader -->
