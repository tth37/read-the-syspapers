---
title: "Ladder: A Convergence-based Structured DAG Blockchain for High Throughput and Low Latency"
oneline: "Ladder moves block ordering into a lower-chain convergence step, keeping valid PoW forks while simplifying confirmation and resisting balance attacks."
authors:
  - "Dengcheng Hu"
  - "Jianrong Wang"
  - "Xiulong Liu"
  - "Hao Xu"
  - "Xujing Wu"
  - "Muhammad Shahzad"
  - "Guyue Liu"
  - "Keqiu Li"
affiliations:
  - "Tianjin University"
  - "Jd.Com, Inc"
  - "North Carolina State University"
  - "Peking University"
conference: nsdi-2025
tags:
  - consensus
  - fault-tolerance
  - security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Ladder is a permissionless block-DAG design that separates parallel PoW block production from block ordering. Upper-chain miners keep producing blocks in parallel, while a lower-chain convergence node serializes each round's surviving forks and a HotStuff committee replaces missing or faulty lower-chain decisions. On the paper's 80-node testbed, that structure raises median throughput from Conflux's 2823 TPS to 4506 TPS and cuts confirmation latency from 43 seconds to 34 seconds.

## Problem

The paper starts from a familiar complaint about block-DAG systems: keeping more parallel blocks than a single longest-chain protocol should improve throughput, but the bookkeeping quickly becomes expensive and fragile. Systems such as Conflux and PHANTOM preserve more work than Bitcoin, yet every node still has to sort competing blocks, reconcile different local views, and infer a pivot chain from the evolving DAG. As concurrency rises, that independent sorting work becomes redundant overhead rather than useful decentralization.

The confirmation path is also messy. If transactions live in multiple concurrent blocks, nodes need extra references, votes, or weight accumulation to decide when a transaction is final. Slow convergence therefore hurts latency and expands the window in which different nodes can disagree about which branch matters.

Finally, the pivot-chain rule itself can be an attack surface. When several candidate branches remain close in weight, an adversary can try to maintain balance between them and delay convergence. Prior systems defend against this with probabilistic weighting or recursive ordering, but those mechanisms either still leave balance-attack room or impose more computation on every node. Ladder's target is therefore not "more parallelism at any cost," but a block-DAG that keeps valid parallel work while restoring a cheap, explicit convergence step.

## Key Insight

Ladder's core claim is that a permissionless DAG does not need every node to continuously rediscover the global order of parallel blocks. It is enough to let PoW determine which blocks are valid candidates, then appoint one convergence node per round to publish the authoritative ordering decision for that round. Once ordering becomes an explicit artifact in the protocol, fork handling and confirmation both simplify.

That idea only works if the convergence step stays decentralized and survives adversarial behavior. Ladder gets the first property by assigning the lower-chain role to the miner of the previous round's standard upper-chain block, so the right to converge flows from ordinary PoW success rather than a fixed leader. It gets the second property by adding a HotStuff-based super-block fallback whenever the lower-chain block is missing or faulty. The paper's broader point is that the expensive part of block-DAG execution is not parallel mining itself; it is duplicated ordering logic. Centralizing that logic per round, while keeping leader selection tied to PoW and recovery tied to BFT, captures most of the performance benefit without giving up the permissionless setting.

## Design

Ladder is a twin-chain DAG. The upper chain contains transaction blocks produced with PoW. In each round, miners can produce multiple valid upper-chain blocks; one becomes the standard upper-chain block and the rest remain as forked upper-chain blocks rather than being discarded. The lower chain contains one ordering block per round, generated without PoW by the miner whose block became the previous round's standard upper-chain block. That lower-chain block records which current-round upper-chain block is standard, which ones are forked, and the sequence numbers needed to reconstruct a total ledger order.

This structure makes ledger generation explicit. Standard upper-chain blocks receive the even serial number for their round, lower-chain blocks receive the next odd serial number, and forked upper-chain blocks keep suffixed serials for the same round. Nodes therefore do not need to re-run a recursive DAG sort to replay history; they traverse the two chains and follow the lower chain's ordering metadata. The paper treats this as the main reason Ladder removes redundant sorting work and simplifies confirmation.

The lower-chain generator does more than publish metadata. It gathers upper-chain blocks for a waiting interval, discards faulty ones, selects the standard block according to Ladder's Hardest Chain Principle, and references the remaining valid blocks as forks. The Hardest Chain Principle extends GHOST-style subtree weighting by using cumulative difficulty rather than descendant count alone. The authors argue that this makes ties between competing sides of a fork rarer and makes balance attacks harder, because an attacker must produce enough difficulty to outweigh the honest subtree.

When the designated convergence node misbehaves or stalls, Ladder switches to its recovery path. If nodes detect conflicting transactions in referenced upper-chain blocks, or if a lower-chain block fails to arrive before the timeout despite valid upper-chain blocks being present, a committee formed from recent standard-block producers runs HotStuff and emits a super block. The committee leader is selected with a VRF, and the super block replaces the missing or faulty lower-chain decision while preserving the current round's upper-chain progress. This means upper-chain mining can keep going even when the ordering path falls back to BFT, which is important because Ladder's performance argument depends on not stalling PoW work whenever convergence has a problem.

## Evaluation

The evaluation compares Ladder against GHOST, Inclusive, PHANTOM, and Conflux on an 80-node testbed. Each machine has an Intel i5-4590 CPU and 8 GB RAM, nodes connect to roughly ten peers, inter-node latency is set to 80-120 ms, and blocks use PoW with difficulty 18 and 1000 payment transactions of about 300 bytes each. The paper also keeps the confirmation rule aligned with Conflux by waiting for six subsequent upper-chain blocks. The setup is explicitly adversary-free, so the results isolate the protocol's performance path rather than attacked behavior.

The headline result is straightforward: Ladder reaches a median 4506 TPS with 34-second confirmation latency, while Conflux, the strongest baseline, reaches 2823 TPS and 43 seconds. That is the reported 59.6% throughput gain and 20.9% latency reduction. The supporting sweeps are consistent with the paper's thesis. With block sizes between 1000 and 1750 transactions, Ladder stays roughly in the 4000-5300 TPS band before dropping at 2000 because propagation overhead dominates. As the network grows from 10 to 80 nodes, throughput rises from 1043 TPS to 4506 TPS and median confirmation latency falls from 47 seconds to 34 seconds, suggesting that the extra compute from more miners outweighs the extra propagation cost.

The difficulty sweep shows the same pattern: higher PoW difficulty slows everyone down, but Ladder still leads at every tested level and peaks at 5314 TPS at difficulty 10. The paper also includes two scale-out checks. In a simulation up to 12,000 nodes, Ladder improves throughput by 34.2% over Conflux. In a heterogeneous Alibaba Cloud deployment, throughput rises from 2011 TPS at 10 Mbps to 4652 TPS at 30 Mbps before PoW becomes the bottleneck. Finally, the committee fallback is evaluated separately: with a 300-node committee including 99 Byzantine nodes, HotStuff consensus costs 3.25 seconds on average. That supports the claim that fallback is viable, but it also makes clear that the fast path matters because the recovery path is materially slower than normal lower-chain propagation.

## Novelty & Impact

Ladder's novelty is not a new cryptographic primitive; it is a new decomposition of the permissionless block-DAG problem. Compared with Conflux, it replaces "every node sorts and weighs the DAG" with "one PoW-selected node converges the round, and a committee repairs failures." Compared with PHANTOM, it avoids recursive ordering across the whole DAG by recording the order incrementally in the lower chain. Compared with systems such as Prism, it keeps transactions in upper-chain blocks and uses the lower chain only for convergence metadata.

That makes the paper useful as a systems design point. Anyone building a permissionless blockchain that wants total transaction ordering, smart-contract compatibility, and better utilization of parallel mining can cite Ladder as an example of how to shift complexity off the hot path. Even if future systems replace PoW or use different committee logic, the basic lesson is durable: block-DAG performance improves when the protocol makes convergence explicit instead of treating it as a side effect of local recursive sorting.

## Limitations

The biggest limitation is that Ladder's security argument is probabilistic twice over. The upper chain still depends on PoW assumptions, and the lower-chain recovery path depends on the committee containing fewer than one-third malicious nodes. The paper is explicit that this cannot be guaranteed in every round; it can only be made very likely by assuming the adversary has less than 30% of total compute and by choosing a large committee. Their own parameter study shows why this matters: committee safety improves sharply with size, and they settle on 300 members partly because smaller committees leave noticeably higher risk.

The evaluation also does not stress the system along its most security-sensitive axis. All main experiments are adversary-free, use payment-style transactions, and compare against mostly older block-DAG baselines. The committee path is benchmarked in isolation rather than inside an end-to-end run with repeated faults or strategic attackers. That means the paper convincingly demonstrates better benign-case throughput and latency, but it does not fully show the performance cost of frequent fallbacks, targeted attacks on convergence timing, or richer smart-contract workloads.

There is also an architectural tradeoff in the design itself. Ladder removes network-wide sorting, but it still reintroduces a special per-round convergence node. If that node is slow, honest-but-late, or attacked, the system pays timeout plus HotStuff cost before the lower chain catches up. The paper's 3.25-second committee result suggests that this path is practical, yet it is still far from free and could become more visible under unstable networks.

## Related Work

- _Li et al. (USENIX ATC '20)_ - `Conflux` also keeps parallel PoW blocks in a block-DAG, but it leaves pivot-chain evaluation and ordering to every node, whereas `Ladder` records the round's convergence decision explicitly in a lower-chain block.
- _Sompolinsky et al. (AFT '21)_ - `PHANTOM GHOSTDAG` gives a total order for block-DAGs through recursive sorting, while `Ladder` trades that fully distributed ordering logic for a designated convergence node plus BFT fallback.
- _Bagaria et al. (CCS '19)_ - `Prism` separates voting from transaction blocks to approach physical limits, whereas `Ladder` keeps transactions in upper-chain blocks and uses the lower chain only to serialize and confirm forks.
- _Yu et al. (IEEE S&P '20)_ - `OHIE` improves throughput with parallel chains, but each chain remains linear and can still orphan valid work; `Ladder` instead uses a DAG upper chain so losing the standard position in a round does not automatically waste a valid block.

## My Notes

<!-- empty; left for the human reader -->
