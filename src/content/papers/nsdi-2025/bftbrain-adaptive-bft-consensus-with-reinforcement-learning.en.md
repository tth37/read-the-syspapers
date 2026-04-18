---
title: "BFTBrain: Adaptive BFT Consensus with Reinforcement Learning"
oneline: "BFTBrain treats BFT protocol choice as a Byzantine-robust contextual bandit, switching online among six protocols as workloads, faults, and hardware change."
authors:
  - "Chenyuan Wu"
  - "Haoyun Qin"
  - "Mohammad Javad Amiri"
  - "Boon Thau Loo"
  - "Dahlia Malkhi"
  - "Ryan Marcus"
affiliations:
  - "University of Pennsylvania"
  - "Stony Brook University"
  - "UC Santa Barbara"
conference: nsdi-2025
category: consensus-and-blockchain
code_url: "https://github.com/JeffersonQin/BFTBrain"
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

BFTBrain wraps six leader-based BFT protocols inside one engine and chooses among them per epoch with online reinforcement learning. The key systems result is not a better single protocol, but a Byzantine-robust selection loop: replicas meter workload and fault signals locally, agree on a report quorum, aggregate with medians, and switch to the protocol that best matches current conditions. Under dynamic conditions, the paper reports 18%-119% higher throughput than fixed protocols and up to 154% better performance than prior learning-based selection under polluted data.

## Problem

The paper starts from a point that anyone deploying BFT already knows but rarely quantifies cleanly: there is no universally best protocol. Zyzzyva and SBFT look attractive when the fast path is likely, CheapBFT benefits from needing smaller quorums in some settings, and Prime or HotStuff-style designs handle slow or bad leaders better. Which one wins depends on request size, reply size, offered load, network size, client strength, and leader behavior. The authors' Table 1 makes that concrete: with 4 KB requests and no obvious faults, Zyzzyva is best; with 100 KB requests, CheapBFT overtakes it; with slow leader proposals, HotStuff-2 or Prime become the right answer depending on how severe the slowness is and how large the deployment is.

That means the common operational workflow is brittle. A team chooses one protocol during benchmarking, deploys it, and then hopes the workload and failure regime stay close to that benchmark. Existing adaptive systems do not really solve this. `Abstract` can switch protocols, but follows a predefined ordering when progress is bad; that is too rigid because the best protocol is not a simple fallback chain. `A DAPT` improves protocol choice with supervised learning, but it assumes a centralized learner, requires pre-collection of labeled data for each deployment, and misses crucial fault-related features. In a Byzantine setting, centralizing the learner is already awkward; requiring retraining for every new hardware setup is even less practical.

## Key Insight

The core insight is that protocol selection should be treated as an online contextual bandit problem, not as an offline classification problem. BFTBrain does not try to infer one timeless mapping from conditions to protocols. Instead, each epoch it asks: given the state we just observed, which protocol is worth trying next, balancing exploitation against exploration?

That only works if the state captures the mechanisms that actually separate the protocols. The paper therefore goes beyond coarse metrics such as throughput and records signals that expose why a protocol is winning or losing: fast-path ratio, messages received per slot, request and reply sizes, client sending rate, execution cost, and proposal slowness. Just as importantly, the learning path itself must tolerate Byzantine behavior. BFTBrain therefore does not trust one node to gather metrics; replicas exchange locally measured reports, run consensus over the report quorum, and take per-field medians so a bounded number of polluted values cannot drag the global state outside the honest range.

## Design

BFTBrain runs in epochs of `k` committed requests. During one epoch, the active protocol stays fixed. Each node hosts both a validator and a companion learning agent. After enough requests have executed, the learning agent summarizes the recent workload and fault state and predicts which protocol should run in the next epoch.

The state space has three parts. Workload features include average request size, average reply size, aggregate client sending rate, and execution overhead measured through CPU cycles in the executor. Fault features are more novel. To capture absent or "in-dark" replicas, BFTBrain uses fast-path ratio and the number of valid messages received per slot; these distinguish, for example, optimistic dual-path protocols from single-path ones when some replicas silently stop participating. To capture slow leaders, each node timestamps leader proposals and measures the average interval between them. Hardware and topology are not explicit features; the authors argue that online learning can absorb those effects into the model itself.

The action space is the six implemented protocols: PBFT, Zyzzyva, CheapBFT, Prime, SBFT, and HotStuff-2. The subtle modeling problem is that some observed fault features depend on the previously chosen protocol. A high proposal interval, for example, can mean a bad leader, but it can also reflect a protocol whose leader naturally does more work. To avoid that one-step dependency confusing the learner, BFTBrain trains a separate random-forest model for each `(previous protocol, next protocol)` pair and keeps separate experience buckets for those transitions. It then approximates Thompson sampling by training each model on a bootstrap resample of its bucket and choosing the next protocol with the best predicted reward, while empty buckets force exploration.

Learning coordination is the paper's other main systems contribution. After an epoch, each agent broadcasts its locally measured reward from the previous epoch and its featurized next state. A separate validated Byzantine consensus instance decides a quorum of reports. If the quorum contains `2f + 1` reports, agents take the median for each field, append the resulting state-action-reward tuple to the experience buffer, retrain, and infer the next protocol. If not enough valid reports arrive, BFTBrain keeps the current protocol rather than making a low-confidence switch. The appendix sketches safety, liveness, and robustness arguments for this coordination path.

Switching protocols relies on `Abstract`'s Backup-style idea, but BFTBrain specializes it because all epochs run on the same cluster and every epoch is a backup instance. Replicas can multicast init history asynchronously rather than waiting on clients to drive the switch. For speculative protocols such as Zyzzyva, the paper adds a special trick: the `k`th request is forced to be a `NOOP` that commits through the slow path, so replicas can deterministically tell that the epoch has ended.

## Evaluation

The implementation uses Bedrock for the BFT protocol framework, Java for the protocol runtime, and a Python/scikit-learn learning agent connected by gRPC. Experiments run mostly on CloudLab xl170 bare-metal servers with 10-core Intel E5-2640v4 CPUs, 64 GB RAM, and Mellanox ConnectX-4 NICs, with deployments of `n = 4` and `n = 13`. Throughput is the optimized reward.

The static-setting results show the expected tradeoff: BFTBrain does not beat the best fixed protocol when conditions never change, but it converges to that winner quickly and has the best aggregate behavior across settings. In representative LAN cases, it reaches stable peak throughput within 0.81 to 5.39 minutes. For example, on the authors' "Row 1" setting it achieves 13,100 tps versus Zyzzyva's 13,664 tps, and on "Row 8" it reaches 4,329 tps versus Prime's 4,527 tps. That gap is the cost of online exploration and switching, but it buys adaptability.

The dynamic experiments are the main result. On a four-hour benchmark that cycles through several workload and fault regimes, BFTBrain commits 18% more requests than the best fixed protocol, 119% more than the worst fixed protocol, 14% more than `A DAPT`, 19% more than an `A DAPT` variant with fuller features but incomplete pretraining, and 43% more than a hand-written heuristic. When conditions later return to a previously seen regime, convergence becomes much faster: about 2 seconds instead of 70 seconds. On a more aggressively randomized two-hour benchmark, BFTBrain commits 44% more requests than `A DAPT`.

The WAN and poisoning experiments strengthen the systems claim. When the same workload is moved from a LAN to a live WAN with 38.7 ms RTT and 559 Mbps bandwidth, the best fixed protocol changes from Zyzzyva to CheapBFT; BFTBrain relearns that and converges in 1.58 minutes, while `A DAPT` stays stuck on the LAN-trained choice. Under slight data pollution, BFTBrain loses only 0.7% throughput versus `A DAPT`'s 12% drop. Under severe pollution, BFTBrain loses only 0.5% while `A DAPT` can fall by 55%, producing a 154% advantage for BFTBrain. The paper's claim that decentralized median aggregation matters is therefore well supported.

## Novelty & Impact

The closest prior systems are `Abstract` and `A DAPT`. `Abstract` contributes the multi-protocol switching frame, but its fallback order is essentially a hand-coded policy. `A DAPT` adds learning, but keeps it centralized and offline. BFTBrain's novelty is combining three things into one deployable system: a carefully chosen feature set that reflects protocol mechanics rather than only outcomes, an online exploration strategy that does not require per-deployment pretraining, and a Byzantine-robust coordination path for the learner itself.

That makes the paper important for practitioners building permissioned blockchains or replicated services that run under shifting workloads, heterogeneous hardware, and adversarial behavior. It is not a new consensus protocol in the narrow algorithmic sense; it is a control plane for choosing among protocols. That framing is valuable because it treats protocol choice as a first-class systems problem instead of a one-time benchmark decision.

## Limitations

The biggest limitation is scope. BFTBrain can only choose among the six protocols that were implemented in Bedrock. If the right answer for a deployment is a protocol outside that pool, the learner cannot invent it. The evaluation therefore proves the value of adaptive selection within a strong but still bounded design space.

The modeling assumptions are also narrower than the name "reinforcement learning" might suggest. The paper formulates the problem as a contextual bandit, not a long-horizon MDP, and explicitly handles only a one-step dependency by training per-transition models. That is sensible engineering, but it means BFTBrain does not reason about longer-term switching costs or protocol histories beyond the immediately previous choice.

Finally, the experiments are convincing but not universal. Most results come from 4-node and 13-node deployments under a common Bedrock implementation rather than production implementations of each protocol. CheapBFT is modified to run with extra active replicas for switching convenience, and the reward is throughput rather than a multi-objective latency-plus-throughput metric. Those choices do not invalidate the results, but they narrow how far the numbers can be generalized.

## Related Work

- _Aublin et al. (EuroSys '10)_ - `Abstract` introduced Backup-style switching among BFT protocols, but relies on predefined progress conditions and fallback structure rather than learned online protocol choice.
- _Bahsoun et al. (IPDPS '15)_ - `A DAPT` uses supervised learning to choose protocols, whereas `BFTBrain` learns online and makes the learning path itself Byzantine-resilient through distributed reporting and median aggregation.
- _Gueta et al. (DSN '19)_ - `SBFT` represents the optimistic fast-path family that BFTBrain exploits in benign regimes but abandons when faults or quorum delays make the slow path dominant.
- _Yin et al. (PODC '19)_ - `HotStuff` shows the benefit of responsive leader replacement under slow leaders; `BFTBrain` generalizes that tradeoff by switching among several leader-management strategies instead of committing to one protocol.

## My Notes

<!-- empty; left for the human reader -->
