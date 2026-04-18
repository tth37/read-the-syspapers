---
title: "ClubHeap: A High-Speed and Scalable Priority Queue for Programmable Packet Scheduling"
oneline: "ClubHeap clusters heap nodes and fully pipelines PIFO operations, reaching one replace per cycle while scaling in queue depth, priority range, and logical partitions."
authors:
  - "Zhikang Chen"
  - "Haoyu Song"
  - "Zhiyu Zhang"
  - "Yang Xu"
  - "Bin Liu"
affiliations:
  - "Tsinghua University"
  - "Futurewei Technologies"
  - "Fudan University"
conference: nsdi-2025
category: programmable-switches-and-smart-packet-processing
code_url: "https://github.com/ClubHeap/ClubHeap"
tags:
  - networking
  - smartnic
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

ClubHeap is a clustered binary heap for implementing PIFO packet schedulers. By storing multiple ordered elements per node and hoisting each child cluster's minimum into the parent, it removes the long dependency chain that kept prior heap-based designs above one replace every cycle; the FPGA prototype reaches about 200 Mpps while scaling to large queues, wide priorities, and many logical PIFOs.

## Problem

Programmable switches and SmartNICs need a queueing primitive that can realize many packet-scheduling algorithms, from WFQ and HPFQ to deadline- and slack-based policies. PIFO has become the standard abstraction for that job because it lets the scheduler insert an element by rank while only dequeuing from the head. The difficulty is that a practical PIFO queue must satisfy three requirements at once: high throughput, scalability in the number of stored elements and priority levels, and logical partitioning so one physical block can host many logical queues in a hierarchical scheduler.

Existing implementations each miss one of those requirements. Linear structures such as shift-register or systolic-array PIFOs can be fast for small queues, but they require parallel comparison across many elements, so hardware cost and timing degrade quickly as the queue grows. Bucket-based designs such as BBQ scale in the number of elements, but they spend dedicated state per priority level, which makes wide rank ranges and many logical PIFOs expensive. Prior heap-based designs scale better in principle, yet they run into inter-operational data dependency: after one pop, the next pop depends on which deeper element rises to the root, forcing bypass paths and wide comparisons that inflate latency and keep cycles-per-replace above the theoretical lower bound of one.

## Key Insight

The paper's main idea is to order clusters, not individual nodes. In ClubHeap, each binary-tree node stores up to `K` sorted elements instead of one, and the heap invariant is defined over whole clusters. The crucial extra trick is that for a non-root node, the minimum element of its cluster is stored in the parent node rather than locally.

That change breaks the dependency chain that hurts ordinary heaps. After one pop, the next candidate minimum is already available at the current level because the parent carries the children's minima. Consecutive operations therefore touch different elements inside a cluster rather than waiting for a deeper-level winner to travel all the way back to the root. With `K >= 2`, ClubHeap can pipeline operations level by level using only adjacent-level communication, which is what makes CPR=1 feasible without giving up heap-style scalability.

## Design

ClubHeap is a clustered binary heap. Each node holds a sorted array of up to `K` elements; empty slots are treated as `+infinity`. The heap condition is defined as `E(x) <= E(y)` for parent and child clusters, meaning every element in a parent cluster is no larger than every element in its child cluster. A useful corollary is that elements stay concentrated near upper levels, because if a node is not full then all of its children must be empty. That concentration matters for logical partitioning: many logical PIFOs can share deep storage without each queue reserving a complete binary tree.

Operations are variants of heap insertion and promotion. A push inserts directly into the root if there is free space; otherwise the maximum element of the root cluster is evicted downward, and a difference field on each node chooses the less populated subtree to keep insertion balanced. A pop removes the root minimum and promotes the smaller of the two child minima upward. Replace, the common case in a scheduler after a flow is popped and reinserted with a new rank, is handled as a specialized pop-push pair.

The hardware pipeline is the paper's most important systems contribution. At each level, every operation goes through READ, CMP, and WRITE stages in different cycles. Different operations overlap across those stages, so one new operation can enter every cycle. Sibling nodes are stored together so one memory access can read both candidates for the next level. Each non-leaf node stores four kinds of information: its local ordered cluster, the minima of its two child clusters, a subtree-size difference field, and, on dynamically allocated levels, a pointer to child storage.

The memory organization is hybrid. Shallow levels use static allocation because a complete tree is still cheap there. Deep levels use dynamic allocation with a free-list stack, because ClubHeap's concentration bound means the actual number of occupied nodes can be far smaller than a full tree when multiple logical PIFOs share the structure. The implementation is written in 919 lines of Chisel and parameterized by `K`, queue capacity `N`, priority range `P`, and logical-PIFO count `M`.

## Evaluation

The prototype is implemented on a Xilinx Alveo U280 FPGA and compared against RPU-BMW from BMW-Tree and BBQ, all under the same FPGA toolflow. The headline result is throughput: ClubHeap is the first scalable heap-based PIFO queue to achieve CPR=1, so at roughly comparable clock frequency to BMW-Tree it delivers about 3x the throughput. For a configuration with up to `2^17` elements, the FPGA runs at about 190 to 207 MHz depending on `K`, which translates to roughly 200 Mpps and is enough for worst-case 100 GbE line rate.

Against BBQ, the comparison shows why the authors emphasize scalability rather than one operating point. For small queues, ClubHeap and BBQ have similar throughput. As the queue grows to `N = 2^17`, ClubHeap becomes 63% faster with `K=2` and 72% faster with `K=16`, while also using 33% to 39% fewer BRAMs. The reason is that BBQ's bucketed representation becomes dominated by memory access as the state grows.

The priority-range experiment is also strong. When priority precision increases from `2^16` to `2^20`, ClubHeap's clock frequency drops by less than 3%, and at `P = 2^20` its throughput is 3.28x BBQ's. BBQ cannot be synthesized at larger `P` on the target FPGA because it runs out of BRAM, whereas ClubHeap scales up to `P = 2^32` with only a 5.5% frequency reduction. For logical partitioning, ClubHeap supports up to `2^8` logical PIFOs in the prototype; when `M` grows to `2^8`, the `K=2` design loses only 16.7% frequency and the `K=16` design shows no frequency drop. The paper also reports 45 nm ASIC synthesis results in which ClubHeap uses only 17.7% to 22.6% of BBQ's area for the same single-PIFO specification.

Overall, the evaluation supports the central claim. The paper isolates the priority-queue block, compares against the right baselines, and shows that ClubHeap is the only design that remains simultaneously competitive in throughput, element count, priority width, and logical partitioning.

## Novelty & Impact

Relative to _Sivaraman et al. (SIGCOMM '16)_, the novelty is not a new scheduling abstraction but a new concrete implementation point for PIFO. Relative to _Yao et al. (SIGCOMM '23)_, the contribution is the clustered-heap structure that removes the inter-operational dependency barrier and reaches the theoretical lower bound of one replace per cycle while still supporting logical partitioning. Relative to _Atre et al. (NSDI '24)_, ClubHeap gives up bucket-style simplicity in exchange for much better scalability in priority precision and multi-queue sharing.

That makes the paper important to researchers and vendors building programmable traffic managers. If PIFO is to be practical in switches or SmartNICs, the data structure underneath it must be fast enough and compact enough to instantiate many times. ClubHeap is a new mechanism, not just a better measurement study, and it is likely to be cited by later work on programmable scheduling hardware, virtualized PIFO blocks, and switch or NIC traffic-manager design.

## Limitations

ClubHeap improves PIFO implementation, but it does not remove PIFO's abstraction limits. The paper explicitly notes that it does not directly support extended abstractions such as PIEO or CIPO; it can only serve as their PIFO component. Likewise, algorithms with dynamic ranks remain outside plain PIFO's expressiveness.

The evaluation is also focused on the queue block rather than an end-to-end traffic manager. The prototype shows synthesis, timing, and simulated throughput, but not deployment inside a full switch ASIC or SmartNIC scheduler with real control-plane integration. And while roughly 200 Mpps is enough for worst-case 100 GbE, the paper itself notes that high-radix switches still need a mesh of PIFO queues rather than a single instance. Finally, the parameter `K` introduces a real tradeoff: larger clusters raise clock frequency by reducing levels, but they also consume more LUTs, FFs, and BRAM.

## Related Work

- _Sivaraman et al. (SIGCOMM '16)_ — PIFO introduced the programmable packet-scheduling abstraction that ClubHeap is designed to implement more efficiently.
- _Bhagwan and Lin (INFOCOM '00)_ — `P-Heap` showed early heap-based packet scheduling, but ClubHeap revisits the direction with clustered nodes and a pipeline tailored to PIFO replace operations.
- _Yao et al. (SIGCOMM '23)_ — `BMW-Tree` is a scalable heap-based PIFO queue, yet it still needs CPR=3 and does not support logical partitioning the way ClubHeap does.
- _Atre et al. (NSDI '24)_ — `BBQ` is a strong bucket-based integer priority queue, but its resource cost grows with priority range and logical partitioning, which is exactly where ClubHeap pulls ahead.

## My Notes

<!-- empty; left for the human reader -->
