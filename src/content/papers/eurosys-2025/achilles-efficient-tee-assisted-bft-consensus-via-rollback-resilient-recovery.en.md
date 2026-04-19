---
title: "Achilles: Efficient TEE-Assisted BFT Consensus via Rollback Resilient Recovery"
oneline: "Achilles moves TEE rollback handling to a peer-assisted recovery path, so TEE-backed BFT keeps 2f+1 fault tolerance while reaching linear messages and four-step latency."
authors:
  - "Jianyu Niu"
  - "Xiaoqing Wen"
  - "Guanlong Wu"
  - "Shenqi Liu"
  - "Jianshan Yu"
  - "Yinqian Zhang"
affiliations:
  - "SUSTech"
  - "University of British Columbia"
  - "The University of Sydney"
conference: eurosys-2025
category: security-and-isolation
doi_url: "https://doi.org/10.1145/3689031.3717457"
code_url: "https://github.com/1wenwen1/Achilles"
tags:
  - consensus
  - fault-tolerance
  - confidential-computing
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Achilles argues that TEE rollback protection should not sit on the hot path of every proposal and vote. Instead, it lets a rebooted node reconstruct its checker state from `f+1` peer replies, with the current leader supplying the highest-view reply, and then resumes only in a later view. Combined with chained commit rules that remove Damysus's prepare phase, the protocol reaches `n = 2f + 1`, `O(n)` messages, and four end-to-end communication steps.

## Problem

TEE-assisted BFT is attractive because TEE-enforced non-equivocation lets authenticated replicas tolerate a Byzantine minority instead of the classic one-third bound. The problem is rollback: a malicious OS can reboot an enclave and feed it stale sealed state, reopening the door to conflicting messages unless the protocol also tracks freshness.

Existing freshness mechanisms are expensive enough to reshape the protocol. The paper cites TPM counters at about `97 ms` per increment and `35 ms` per read, while software counters such as ROTE or Narrator need their own distributed coordination. Damysus and OneShot therefore pay rollback overhead whenever leaders propose and replicas vote; FlexiBFT reduces that pressure by relaxing the resilience target from `2f + 1` to `3f + 1`. Achilles asks whether a TEE-backed design can keep `2f + 1` tolerance while still matching CFT-style linear communication and four end-to-end steps.

## Key Insight

Rollback protection only needs to be exact when a node recovers. During normal execution, TEEs still enforce non-equivocation by signing proposals and votes. After a reboot, though, the node does not need every historical enclave state back; it only needs the latest safe frontier and a conservative rule that prevents it from speaking again in a possibly used view.

Achilles therefore reconstructs checker state from `f+1` peer replies, requires the highest-view reply from the current leader, and resumes only at `v' + 2`. That last jump is the safety valve: it guarantees the recovering node will not emit messages in a view it may already have participated in before crashing. Once rollback defense is treated as a rare recovery task, persistent counters disappear from the common path.

## Design

Achilles keeps Damysus's checker/accumulator split, but the checker now remembers the latest stored leader block even if that block is not yet prepared; the accumulator stays stateless and only proves that the leader extended the highest-view block among `f+1` new-view certificates.

Normal execution has new-view, commit, and decide phases. Replicas first send view certificates for their latest stored blocks. The leader uses `TEEaccum` to choose the highest-view parent, proposes a new block with `TEEprepare`, and replicas validate/store it with `TEEstore`. Once the leader has `f+1` store certificates, it broadcasts a commitment certificate; replicas then commit the block, execute it, and can reply to clients. Because the blocks form a chain, committing a descendant also commits its uncommitted ancestors, which is why Achilles can remove Damysus's separate prepare phase and still achieve `O(n)` communication with four end-to-end steps. If the next leader already has the previous commitment certificate, it can skip the usual new-view wait.

Recovery is the new mechanism. A rebooted node sends a nonce-bearing request, peers reply with their latest stored block state plus a signed recovery certificate, and `TEErecover` accepts `f+1` replies only if the current leader's reply is included and is highest-view. The recovering node restores checker state from that leader's block and advances by two views. The accumulator needs no recovery because it has no protocol state.

## Evaluation

The SGX prototype runs on 8-vCPU, 32-GB public-cloud VMs in both a LAN setting of about `0.1 ms` RTT and an emulated WAN of `40 ms` RTT, scaling up to `f = 30`.

The central claim is well supported. In LAN with `f = 30`, Achilles reaches `75.38 KTPS` at `5.12 ms` latency, which the paper reports as `17x`, `6x`, and `7x` the throughput of Damysus-R, FlexiBFT, and OneShot-R. WAN gains are smaller because network delay dominates, but Achilles still stays on the best throughput/latency frontier across node counts, payload sizes, and batch sizes.

Recovery does not simply move the cost elsewhere. Total reboot-plus-recovery time grows from `8.68 ms` at 3 nodes to `37.09 ms` at 61 nodes, while the recovery protocol itself accounts for only `0.61 ms` to `12.31 ms`; the rest is mostly SGX and reconnect overhead. At `f = 10` in LAN, Achilles reaches `116.9 KTPS`, versus `153.2 KTPS` for enclave-free Achilles-C and `120.1 KTPS` for BRaft, which suggests that once persistent counters leave the fast path, the remaining enclave cost is manageable.

## Novelty & Impact

Relative to Damysus, Achilles changes what trusted state is recoverable and uses that to remove an entire phase. Relative to FlexiBFT, it does not buy performance by weakening the model to `3f + 1`. Relative to OneShot, four-step commits coexist with rollback resilience instead of appearing only in favorable executions.

The broader impact is conceptual. Achilles shows that TEE-assisted BFT does not have to choose between practical performance and strong tolerance if rollback defense is treated as a recovery problem rather than a per-message obligation.

## Limitations

Achilles assumes fixed membership, no more than `f` simultaneous reboots, and TEE integrity with forking handled elsewhere. Recovery can stall if the current leader is itself unavailable, because the highest-view leader reply is mandatory. The implementation also keeps the chain-based structure of Damysus and does not explore dynamic reconfiguration or more aggressive parallel consensus schemes.

## Related Work

- _Decouchant et al. (EuroSys '22)_ - Damysus introduces the checker/accumulator split for chained TEE-assisted BFT, but it still keeps a prepare phase and does not provide rollback-resilient recovery.
- _Decouchant et al. (IPDPS '24)_ - OneShot adapts the streamlined Damysus line to get four steps in favorable executions, whereas Achilles makes four-step commits coexist with rollback resilience.
- _Gupta et al. (EuroSys '23)_ - FlexiBFT improves responsiveness and cuts TEE accesses by relaxing the resilience target to `3f + 1`; Achilles targets the same bottleneck while preserving `2f + 1`.
- _Yin et al. (PODC '19)_ - HotStuff supplies the chained, linear-communication backbone that Achilles borrows, but it does not address TEE-backed non-equivocation or rollback recovery.

## My Notes

<!-- empty; left for the human reader -->
