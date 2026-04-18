---
title: "NDD: A Decision Diagram for Network Verification"
oneline: "NDD lifts BDD-based network verification to the field level, atomizes each field separately, and removes the worst atom-explosion bottlenecks."
authors:
  - "Zechun Li"
  - "Peng Zhang"
  - "Yichi Zhang"
  - "Hongkun Yang"
affiliations:
  - "Xi'an Jiaotong University"
  - "Google"
conference: nsdi-2025
category: network-verification-and-synthesis
code_url: "https://github.com/XJTU-NetVerify/NDD"
project_url: "https://xjtu-netverify.github.io/papers/2025-ndd-a-decision-diagram-for-network-verification"
tags:
  - networking
  - verification
  - formal-methods
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

NDD replaces whole-header, bit-level BDD reasoning with a two-layer decision diagram that branches by network field and labels edges with per-field BDDs. It also computes and updates atoms inside the library, so existing verifiers stop paying the worst memory and recursion costs of global atom computation. Across five BDD-based verifiers, the paper reports about two orders of magnitude improvement in both memory and runtime on the workloads where field locality matters.

## Problem

The paper starts from a mismatch between how networks are specified and how BDD-based verifiers encode them. Network devices reason about fields such as destination IP, source port, communities, or link-failure bits, and most rules touch only a few of those fields. BDDs, however, flatten everything into one ordered bit vector. That loses the notion of field, so two packet sets that share large substructure on some fields but differ on others still end up with separate nodes.

This hurts memory first. When verifiers compute equivalence classes, or atoms, over the whole network state, the per-field combinations cross-product into many more global atoms. The paper shows this can overflow BDD node tables on multi-layer networks. It hurts time as well, because BDD logical operations recurse one bit at a time, and operands defined over different variables need extra recursive work just to align their bit positions. On wide headers and route attributes, that becomes a bad inner loop.

BDD libraries also do not natively understand network-verification tasks such as computing atoms, incrementally updating them after changes, or handling packet transformers. Existing verifiers therefore implement their own atom-management logic on top of BDD and still inherit the same scalability pathologies.

## Key Insight

The central claim is that network verification should preserve field structure all the way down to the symbolic representation. If reduction and logical operations are restricted to BDDs within the same field, the verifier can remove partial redundancy that ordinary BDDs cannot, and it can skip an entire field in one recursion instead of walking every bit.

NDD realizes that idea with a two-layer diagram. The outer decision diagram branches on fields, while each outgoing edge is labeled by a BDD that describes the allowed values of that field. After that, atoms are computed per field rather than globally. That keeps BDD compactness where it is useful, but avoids the cross-product explosion that appears when all fields are forced into one monolithic bit-level structure.

## Design

An NDD is a rooted DAG with terminal `true` and `false` nodes plus non-terminal nodes keyed by fields rather than single bits. Each node's outgoing edges are mutually exclusive and exhaustive for that field, and each edge carries a BDD predicate together with a successor node. The reduced ordered form adds a third reduction rule beyond ordinary ROBDDs: no two edges from the same NDD node may point to the same successor. That lets the library merge field predicates that diverge locally but reconverge downstream. The paper proves canonicity for a fixed field order, so equality and memoization remain well defined.

The main logical operator is `apply`, which generalizes BDD `and`, `or`, and `diff`. Instead of recursing only on low and high branches, NDD enumerates overlapping edge pairs, combines their successors recursively, and merges the pairs that end at the same successor by OR-ing their labels. Existential quantification similarly eliminates one field by OR-ing over its outgoing edges. The authors argue this is efficient in practice because most NDD nodes have few edges after reduction.

The second major mechanism is atomization. `atomize` collects all edge labels for each field, computes a separate atom set for each field, and replaces each BDD edge label with the set of atoms it covers. After atomization, many verifier operations become set intersections and unions over field-local atoms rather than expensive boolean operations over whole-header BDDs. `update` handles incremental changes: if a new predicate `δ` is known to imply an existing atomized NDD `a`, the library only splits the atoms that actually intersect `δ` along reachable paths instead of recomputing everything.

The implementation is intentionally pragmatic. The NDD library is about 2K lines of Java on top of JDD, plus a small JavaBDD factory so tools like Batfish can switch over. The API keeps `createVar`, `apply`, `not`, and `exist`, then adds `atomize` and `update` for verifier-specific work. Internally it uses per-field hash-based unique tables, keeps an operation cache, and drops edges to the `false` terminal because those edges often carry the heaviest BDD labels and largest atom sets.

## Evaluation

The evaluation covers virtualized datacenter networks with packet transformers, real WAN and campus networks, and fat-tree control-plane simulations. The strongest results appear on field-rich workloads. On VXLAN-based datacenter snapshots, APKeep(NDD) is the only version that finishes all seven dataset sizes up to 500 leaf routers; APKeep(BDD) and KatraR(BDD) either time out after 24 hours or exhaust more than 256 GB of RAM. Even on the smallest 6-leaf case, memory drops from 4.36 GB to 0.01 GB and the atom count drops from 28,077 to 112.

Packet transformers show the same pattern. After adding NAT and twice-NAT rules to Purdue, APKeep(NDD) is already about 10x faster with four NAT rules and about 100x faster with forty. The BDD version runs out of memory after eighty NAT rules, while the NDD version still completes with two thousand. On control-plane verification, replacing BDD with NDD lets SRE finish a 500-node fat tree under single-link failures where SRE(BDD) aborts because the BDD table overflows.

The paper is also honest about where gains shrink. On Stanford and Internet2, where most predicates effectively live on one field, NDD is only comparable to or modestly faster than BDD. Batfish also sees limited improvement for the same reason. That makes the evaluation credible: NDD wins exactly when field locality is strong, which is the paper's stated precondition.

## Novelty & Impact

The contribution is not another specialized verifier for one task. It is a new symbolic substrate for a whole family of existing verifiers. The authors re-implement AP Verifier, APT, APKeep, SRE, and Batfish with relatively small code changes, mostly by deleting custom atom-handling logic rather than adding new verifier-specific machinery. That is the clearest evidence that NDD is meant as a drop-in replacement for BDD in network verification.

Compared with structures such as MDD, IDD, or CDD, NDD keeps BDDs inside each field instead of replacing them with one edge per value or a large set of intervals or constraints. That combination of field-level structure plus per-field BDD compactness is the paper's real novelty. I expect its main impact to be on future verifiers that still want canonical symbolic reasoning but can no longer afford whole-state BDDs.

## Limitations

NDD depends on field locality. The paper explicitly shows that if more and more ACL rules are rewritten so every rule matches all five fields, the advantage disappears and BDD can even look better. So NDD is not a universal substitute for bit-level symbolic reasoning; it is a representation tuned to the way network policies are usually written.

The paper also leaves some generalization questions open. Packet headers and route attributes are natural fields, but other symbolic states may need heuristic grouping. The control-plane results are strongest for SRE and weaker for Batfish, which suggests the payoff depends on how naturally a verifier's state decomposes into fields. The authors suggest NDD may help outside network verification, but that claim is still exploratory.

## Related Work

- _Yang and Lam (ICNP '13)_ - `AP Verifier` builds network reachability on BDD-based atomic predicates, while `NDD` internalizes atom computation per field and avoids the same whole-header atom explosion.
- _Zhang et al. (NSDI '20)_ - `APKeep` engineers incremental atom maintenance on top of BDD, whereas `NDD` exports `atomize` and `update` so the library owns that complexity.
- _Beckett and Gupta (NSDI '22)_ - `Katra` reduces multi-layer verification blowups with partial equivalence classes, while `NDD` attacks the same scaling pain underneath the verifier by changing the symbolic representation itself.
- _Zhang et al. (SIGCOMM '22)_ - `SRE` uses BDDs to jointly encode failures and packet state for control-plane reasoning, and this paper shows the same style of verifier can scale further with field-partitioned decision diagrams.

## My Notes

<!-- empty; left for the human reader -->
