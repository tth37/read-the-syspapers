---
title: "Unlocking ECMP Programmability for Precise Traffic Control"
oneline: "P-ECMP turns underused ECMP groups into selector-driven path policies, letting hosts fail over or steer traffic precisely without disabling ECMP."
authors:
  - "Yadong Liu"
  - "Yunming Xiao"
  - "Xuan Zhang"
  - "Weizhen Dang"
  - "Huihui Liu"
  - "Xiang Li"
  - "Zekun He"
  - "Jilong Wang"
  - "Aleksandar Kuzmanovic"
  - "Ang Chen"
  - "Congcong Miao"
affiliations:
  - "Tencent"
  - "University of Michigan"
  - "Tsinghua University"
  - "Northwestern University"
conference: nsdi-2025
tags:
  - networking
  - datacenter
  - smartnic
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

P-ECMP repurposes ECMP groups into selector-addressed rows, so hosts can move chosen packets onto a different ECMP policy without disabling ordinary ECMP. That makes re-pathing, probing, and deterministic spraying precise enough to remove failover's retry tail.

## Problem

ECMP is attractive because it is cheap in ASICs and good for aggregate load spreading. The problem is that precise traffic-control tasks need a specific path outcome now. When a flow hits a gray failure, a flapping link, or a hotspot, systems such as PRR and PLB can only perturb packet fields and hope the vendor-specific hash picks a different path. Collisions turn that into a retry loop, and the long tail appears exactly when traffic is already unhealthy.

The same randomness also hurts failure localization, MPTCP disjointness, packet spraying, and segment-routing-like steering. Fully explicit routing would cost too much state, and requiring universal programmable switches is unrealistic. The practical goal is to keep normal ECMP for most traffic while giving selected packets precise, fast overrides.

## Key Insight

Commodity switches already expose the right primitive: ECMP groups. A selector `s` chooses a row, the normal flow hash chooses a column, and the forwarding decision becomes `C[s, Hash(f)]`. If operators control the contents of those rows, they can impose deterministic structure on top of ECMP's randomness without turning ECMP off.

That yields two useful policy families. Cyclically shifted rows preserve load spreading but add a known path offset, which is enough for deterministic re-pathing. Single-port rows remove the hash from the decision and give exact next-hop control, which is enough for probing, spraying, and hop-by-hop steering. The authors' production measurements show ECMP-group SRAM is heavily underused, so this is a practical reuse of existing hardware.

## Design

P-ECMP implements path-offset control by rotating the base ECMP row. If the default row is `[p0, p1, ..., pN-1]`, the next row is `[pN-1, p0, ..., pN-2]`; changing the selector then shifts the chosen output port by a predictable offset while keeping per-flow randomness inside the row. That is the mechanism used for failover, congestion-triggered re-pathing, and keeping multipath subflows apart.

Exact-next-hop control instead collapses a row to one port. Different network tiers can read different selector bits, so a host can encode an entire ToR-leaf-spine path. This supports exhaustive path probes, deterministic packet spraying, and a segment-routing-like function without extra encapsulation.

The compiler extracts each switch's base ECMP group from the topology, then appends the rows needed for the requested policy types subject to SRAM limits. Consistency is handled by double-buffered updates: switch SRAM is split into two table versions, and hosts move selectors to the new version only after the new rows are installed. The prototype runs on SONiC across Trident and Tomahawk switches, uses DSCP to carry selectors, and patches dual-homed NIC bonding so host-side path choice is deterministic too.

## Evaluation

Resource cost is modest. Across the evaluated Clos topologies, ToR switches need 4 to 16 ECMP groups, leaf switches 4 to 128, and spines 4 to 16 groups per pod with both policy classes enabled. Offset-only control needs just 2 to 6 selector bits, so a 6-bit DSCP field is enough; combined exact-hop control can need up to 24 bits on the largest dual-homed topology.

Failover is the strongest result. P-ECMP always succeeds on the first re-path attempt, so recovery stabilizes at about 6 ms after detection regardless of whether the failure is at the ToR, leaf, or spine layer. PRR keeps the long tail from unlucky retries: for ToR failures its median recovery time is 42 ms and its 95th percentile exceeds 4.5 s. In a link-failure event, P-ECMP drives loss to zero within 65 ms versus 85 ms for PRR.

The other use cases also benefit. For PLB-style load balancing, P-ECMP cuts normalized last-flow completion time from 366.7 to 189.0 on 80% web-search load and from 1278.3 to 769.1 on Hadoop. For MPTCP, all 100K flows survive single failures once subflows are forced onto disjoint paths. Exact-next-hop control reduces failure-localization probe count by 2x to 5x, and deterministic packet spraying keeps most 99th-percentile queues at 11 KB rather than 31 KB to 70 KB. In Tencent's Cloud Block Storage deployment, P-ECMP reduces IO-jitter durations by up to 80%, 36%, and 40% for min/median/max and lowers IO-hang occurrence by up to 16%.

## Novelty & Impact

Compared with RePaC, P-ECMP avoids hash-linearity assumptions by programming the mapping stage. Compared with XPath, it uses cheap ECMP-group SRAM instead of installing explicit end-to-end paths. Compared with PRR and PLB, it turns host-triggered rerouting from probabilistic retries into a deterministic primitive. The contribution is a constrained programming model, compiler, and consistent-update runtime around an existing dataplane feature.

## Limitations

The production rollout covers offset-based failover, not the full exact-hop feature set. Exact-next-hop control is mainly developed for tiered/tree-like topologies, and large dual-homed networks may need up to 24 selector bits, so DSCP alone is insufficient. P-ECMP also assumes alternative equal-cost paths exist, and it inherits failure or congestion triggers from external systems rather than solving detection itself.

## Related Work

- _Hu et al. (NSDI '15)_ — XPath gives hosts explicit path control by preinstalling compressed paths in forwarding tables, whereas P-ECMP keeps ECMP in place and uses ECMP-group state as the control surface.
- _Zhang et al. (USENIX ATC '21)_ — RePaC exploits hash linearity to obtain relative path control, while P-ECMP avoids dependence on predictable hashing by programming ECMP-group mappings directly.
- _Qureshi et al. (SIGCOMM '22)_ — PLB re-paths on congestion but still relies on random retries, whereas P-ECMP turns the same re-path trigger into a deterministic path offset.
- _Wetherall et al. (SIGCOMM '23)_ — PRR protects flows with protective reroute after RTO-based failure detection, and P-ECMP removes the hash-collision tail that PRR still suffers.

## My Notes

<!-- empty; left for the human reader -->
