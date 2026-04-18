---
title: "OS Rendering Service Made Parallel With Out-of-Order Execution and In-Order Commit"
oneline: "Spars turns sequential OS rendering into self-contained tasks that run out of order and commit in order, lifting frame rates on foldable and multi-screen devices."
authors:
  - "Yuanpei Wu"
  - "Dong Du"
  - "Chao Xu"
  - "Yubin Xia"
  - "Yang Yu"
  - "Ming Fu"
  - "Binyu Zang"
  - "Haibo Chen"
affiliations:
  - "Institute of Parallel and Distributed Systems, Shanghai Jiao Tong University"
  - "Engineering Research Center for Domain-specific Operating Systems, Ministry of Education"
  - "Fields Lab, Huawei Central Software Institute"
conference: osdi-2025
code_url: "https://github.com/SJTU-IPADS/Spars-artifacts"
tags:
  - scheduling
  - gpu
  - energy
category: kernel-os-and-isolation
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Spars is a parallel OS rendering service and Spade2D drawing engine for smart-device GUIs. Its core move is to keep a fast in-order dry run that computes complete drawing state, execute the resulting self-contained rendering tasks out of order on worker threads, and commit finished tasks in order only where overlap requires it.

## Problem

The paper targets a bottleneck that has become visible as phones and embedded devices moved from one modest screen to foldables, tri-folds, and one-chip multi-screen setups. Those devices ask the OS to render far more pixels and graphics primitives per frame, but the rendering service in systems like iOS and OpenHarmony is still largely organized as a sequential depth-first walk over a render tree. The authors show why that design stops scaling: CPU work, not GPU rasterization, dominates frame time in their 2D workloads, taking 82% of end-to-end rendering time on average.

The sequential structure is not accidental. Render-tree nodes store state relative to their parent, so a renderer normally needs a depth-first traversal to reconstruct absolute transform and clipping state. Drawing order is also semantically meaningful: overlapping foreground and background primitives must be emitted in the right order. On top of that, production 2D engines expose stateful APIs and rely on stateful optimizations such as command batching. Existing coarse-grained approaches do not solve this cleanly. Inter-frame parallelism pipelines whole frames but raises latency and is bounded by the slowest stage; multi-window parallelism only helps when there are many active windows and adds buffering/composition cost. In the authors' Mate X5 study, the render thread drives one core to about 80% utilization while most of the remaining cores stay largely idle.

## Key Insight

The paper's central claim is that OS rendering is more parallelizable than its current implementation suggests because execution itself is not what creates most dependencies. The hard dependencies mostly come from reconstructing drawing state and preserving output order. If the renderer first performs a cheap in-order preparation pass that untangles relative state into complete per-task state, then the expensive CPU work of translating primitives into GPU objects can run independently on multiple cores.

The second insight is that correctness does not require preserving the full sequential traversal, only the partial order induced by overlap. Spars therefore borrows the processor analogy in its title seriously: prepare tasks in order, execute them out of order, then commit them in order where necessary. The design works because modern GPU APIs such as Vulkan are already largely stateless, so the stateful compatibility layer can be separated from the stateless parallel execution core.

## Design

Spars divides rendering into three stages. In the in-order preparation stage, the main thread still traverses the render tree depth-first, but this pass is a dry run: it computes absolute transform matrices, clipping regions, primitive parameters, and style information for nodes that actually contain draw commands, then packages them into self-contained tasks. Unchanged absolute state can be reused across frames. The authors note that draw commands are sparse in the tree; in one desktop scenario only about 200 of 800 nodes carry draw commands, and storing absolute state adds about 2 MB in that example.

Preparation also constructs the metadata needed for correctness and optimization. Instead of building a full dependency DAG, Spars keeps tasks in a simple chain derived from depth-first order and records an axis-aligned bounding box for each task. These AABBs let the commit stage tell when two unfinished tasks could affect one another. The same pass also preserves the useful part of traditional stateful optimization: it batches neighboring commands that can share a GPU pipeline, so Spade2D often receives task batches such as a vector of rectangles rather than one primitive at a time.

Worker threads then perform out-of-order execution. Each worker pops tasks from a single-producer/multi-consumer queue and invokes the stateless Spade2D engine to turn those tasks into GPU objects such as meshes, textures, and pipelines. Spade2D is built around thread-safe resource managers, because parallel rendering can otherwise create the same image or pipeline twice. A resource can therefore be in an unprepared, preparing, or prepared state: the first task marks it as preparing and builds it, while later contenders block briefly on a condition variable instead of duplicating work. Because modern GPU APIs allow parallel creation and use of many objects, the paper argues that locking is limited and mostly off the critical path.

Finally, a commit thread performs in-order commit. It consumes finished task outputs from a multi-producer/single-consumer queue and commits them immediately if they are at the head of the chain or if no earlier unfinished task has an overlapping AABB. Otherwise it waits for the necessary background task to finish first. This is the paper's key control/data-path split: the main thread reconstructs state and batching decisions, worker threads do the CPU-heavy geometry and GPU-object generation, and the commit thread serializes only the ordering constraint that still matters at the end.

## Evaluation

The evaluation is careful about isolating the design itself. The authors implement Spars and Spade2D in C++ with a Vulkan backend, export real render trees from OpenHarmony scenarios, and compare against both the commercial renderer and a Sequential version of Spars that keeps the same codebase but uses the standard serial procedure. Across 42 representative smartphone scenarios on Mate 70, Mate X5, and Mate XT, 76% of frame time is parallelizable in Spars, suggesting theoretical speedups of 2.14x with three workers and 2.65x with five.

Measured gains are smaller but still substantial. With five worker threads pinned to medium cores, Spars reduces CPU frame-rendering time by 43.2% relative to Sequential and improves frame rate by 1.76x on average; 27 of 42 sequential baselines cannot sustain stable 120 Hz, while Spars-5 does across all tested smartphone scenarios. In heavier multi-window and picture-in-picture cases, the gain reaches 2.07x. For one-chip multi-screen setups, the average frame-rate improvement reaches 1.91x and climbs above 2x for the heaviest screen counts.

The secondary results support the paper's systems argument rather than just its benchmark story. Balanced multi-core use reduces whole-device power by 3.0% at the same frame rate, and under a fixed 120 Hz budget Spars-5 can render 2.31x as many random primitives as the sequential baseline. The evaluation is fair in the sense that clocks and cores are controlled and the sequential baseline shares the same code structure, but it is not yet a drop-in production comparison: Spars bypasses the vanilla renderer and reconstructs workloads from exported render trees.

## Novelty & Impact

The paper is novel because it parallelizes within a frame at the rendering-service level rather than depending on coarser opportunities such as frame pipelining or multiple windows. Relative to _Wu et al. (ASPLOS '25)_, D-VSync exploits slack between rendering and display to absorb fluctuating workloads, whereas Spars restructures the rendering engine so that constant heavy loads can use more cores. Relative to mobile and graphics systems that shift more work to the GPU, Spars accepts that 2D GUI rendering remains CPU-heavy and attacks the CPU-side dependency structure directly.

This makes the contribution more architectural than algorithmic. Readers who build mobile operating systems, cockpit software stacks, or graphics middleware for large-screen devices are likely to cite it because it gives a plausible path to scaling rendering without demanding faster single cores. The deeper takeaway is that OS rendering services should be designed around explicit state untangling and order-preserving commit, not around one long stateful traversal.

## Limitations

Spars is not a small patch. The authors explicitly position it as a full refactoring of both the rendering service and the drawing engine, and they estimate that a functionally complete deployment would require modifying more than one third of the code in a traditional stack. Even the memory cost is not free: thread creation dominates and Spars-5 can add up to about 50 MB of extra memory on modern devices, though the paper argues that this is acceptable for devices with at least 8 GB of RAM.

There are also evaluation and deployment caveats. Spade2D still lacks some features compared with the vanilla renderer, which is why the evaluation reconstructs render trees rather than replacing the stock service in day-to-day use. The design's gains are highest in task-rich scenes; lighter screens and simpler pages will see smaller wins. Finally, dynamic worker-count tuning is left unresolved, and the commit policy uses bounded AABB checks instead of a richer dependency graph, which is pragmatic but may leave some parallelism unused.

## Related Work

- _Wu et al. (ASPLOS '25)_ — D-VSync also targets smartphone graphics, but it exploits display/render decoupling and saved slack rather than parallelizing the rendering core itself.
- _Arnau et al. (PACT '13)_ — Parallel frame rendering pipelines whole frames on mobile GPUs, while Spars extracts parallelism within a single frame to avoid the latency cost of inter-frame staging.
- _Chen et al. (LCTES '22)_ — DSA broadens Android's dual-screen application model, whereas Spars tackles the lower-level rendering-service bottleneck exposed by larger and multiple displays.
- _Yun et al. (WWW '17)_ — Presto reduces interaction latency by relaxing synchrony in the display stack, an orthogonal scheduling idea rather than a redesign of render-tree execution.

## My Notes

<!-- empty; left for the human reader -->
