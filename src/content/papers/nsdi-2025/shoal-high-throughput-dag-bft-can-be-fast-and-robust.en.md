---
title: "Shoal++: High Throughput DAG BFT Can Be Fast and Robust!"
oneline: "Shoal++ cuts certified DAG-BFT latency to about 4.5 message delays by fast-committing well-supported anchors, materializing more anchors, and staggering three DAGs."
authors:
  - "Balaji Arun"
  - "Zekun Li"
  - "Florian Suri-Payer"
  - "Sourav Das"
  - "Alexander Spiegelman"
affiliations:
  - "Aptos Labs"
  - "Cornell University"
  - "UIUC"
conference: nsdi-2025
tags:
  - consensus
  - fault-tolerance
  - networking
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Shoal++ is a partially synchronous DAG-BFT protocol that keeps the robust certified-DAG structure of Narwhal/Bullshark-style systems, but attacks the three latency sources that make prior DAG protocols slow: queueing, anchoring, and anchor commit. It fast-commits anchors from `2f+1` proposal-level "weak votes", makes many more nodes eligible to become anchors without letting slow anchors stall the log, and runs three staggered DAGs in parallel, reducing expected latency from Shoal's 10.5 message delays to 4.5 while preserving high throughput.

## Problem

Classic leader-based BFT protocols such as PBFT get the best possible common-case latency, but they bottleneck throughput at a single leader's network and processing capacity. DAG-BFT protocols attack that bottleneck by letting every replica propose batches and by separating data dissemination from consensus, which is why they have become attractive for large blockchain deployments. The price is latency: a transaction must wait to enter a round, wait for some future anchor to cover it, and then wait again for that anchor to become committed.

The paper makes that cost explicit. In certified DAG protocols such as Bullshark and Shoal, average end-to-end latency consists of roughly 1.5 message delays of queueing, plus anchoring latency, plus anchor-commit latency. Bullshark ends up around 12 message delays in expectation, and Shoal improves this only to 10.5. Recent uncertified DAG proposals try to save latency by removing certification, but the authors argue that this simply moves the cost: now replicas may need to fetch missing data on the critical path, which is exactly the wrong trade-off when the network is lossy or some replicas are slow.

## Key Insight

The main proposition is that certified DAGs are not inherently slow; the real problem is overly conservative anchor handling. Shoal++ keeps certification, because certified nodes make the DAG robust and let missing data be fetched off the critical path, and instead optimizes each latency component separately.

The protocol's key move is to treat the early arrival of proposals as useful evidence. If `2f+1` proposals already point to an anchor, then at least `f+1` of those links come from correct replicas and will eventually survive certification, so the anchor's fate is effectively determined before the next round finishes certifying. Combined with a more aggressive anchor schedule and multiple staggered DAGs, this lets Shoal++ approach PBFT-like latency without returning to a single leader.

## Design

Shoal++ starts from Narwhal's certified round-based DAG and Bullshark's embedded consensus. Each round, every replica proposes at most one node that references `n-f` certified nodes from the previous round. Selected nodes act as anchors; once an anchor is committed, its causal history becomes the next ordered log segment. Shoal++ modifies that basic flow in three places.

First, it adds a Fast Direct Commit rule. Bullshark commits an anchor once `f+1` certified nodes in a later round reference it, which takes at least two certified rounds. Shoal++ also counts proposal-level references as weak votes. As soon as a replica sees `2f+1` proposals linking to an anchor, it can safely fast-commit that anchor in 4 message delays: 3 to certify the anchor itself, then 1 more for the next round's proposals to arrive. Because `2f+1` weak votes can be harder to gather than `f+1` certified votes on unstable links, the original Bullshark direct-commit rule stays as a fallback and replicas use whichever condition fires first.

Second, Shoal++ tries to eliminate anchoring latency by turning almost every node into an anchor candidate. Doing this naively would serialize progress behind the slowest anchor, so the paper adds two controls. A small round timeout after the first `2f+1` nodes nudges replicas into lockstep and yields denser parent links, which makes it practical to let `GET_ANCHORS` return all `n` nodes instead of only Shoal's reputed fast subset. Then the protocol treats all but the first anchor in a round as virtual. After the current consensus instance resolves, replicas materialize only the next necessary anchor; if a later committed anchor proves that some earlier tentative anchor was skipped, Shoal++ jumps over those obsolete instances rather than evaluating every skipped Bullshark path one by one.

Third, Shoal++ cuts queueing latency by running `k` DAGs in parallel and interleaving their outputs into one total order. The implementation uses `k=3` DAGs offset by one message delay, so some DAG is ready to accept a proposal every 1 message delay instead of every 3. Each DAG commits anchors independently, and the ordered segments are appended in round-robin order. The paper also chooses inline batch dissemination instead of Narwhal's worker layer so missing data behind hash references never sits on the critical path.

## Evaluation

The evaluation is reasonably strong for the paper's main claim. Shoal++ is implemented in Aptos's Rust codebase with Tokio, BLS signatures, RocksDB persistence, and Noise authentication. The authors compare it against Bullshark, Shoal, Mysticeti, and Jolteon on 100 replicas spread across 10 Google Cloud regions with round-trip times from 25 ms to 317 ms. Clients submit 310-byte dummy transactions, batch size is 500, and execution plus ledger storage are disabled to isolate consensus. Bullshark, Shoal, and Jolteon are reimplemented in the same codebase, while Mysticeti uses its public code and notably does not persist consensus data, which makes it a favorable baseline rather than a strawman.

In the failure-free case, Shoal++ is the only system that keeps sub-second latency at 100k TPS. It reaches about 775 ms at low load and scales to roughly 140k TPS. Bullshark and Shoal top out around 75k TPS and already sit at about 1.9 s and 1.45 s latency at low load; Jolteon starts around 900 ms but saturates near 2100 TPS because the leader runs out of bandwidth. The breakdown study shows that the fast-commit rule helps, but the larger gain comes from "more anchors", which saves about 3 message delays on average by removing anchoring latency for most nodes. The parallel-DAG design then reduces queueing latency further and improves throughput by making proposal traffic look more like streaming than bursty rounds.

The robustness results support the paper's argument for certified DAGs. With 33 of 100 replicas crashed, Shoal++ and Shoal still adapt their anchor choices and only see latency rise by about 2x at high load, while Bullshark and Mysticeti degrade much more because they lack reputation-guided anchor selection. Under 1% egress message loss on 5 of 100 nodes, Mysticeti's latency spikes by about 10x, whereas Shoal++ rises by at most 1.3x because any synchronization needed to fetch missing certified nodes stays off the critical path.

## Novelty & Impact

Shoal++ is not a new BFT model so much as a carefully engineered redesign of the certified DAG-BFT fast path. Compared with Bullshark, it changes both how quickly anchors commit and how aggressively anchors are scheduled. Compared with Shoal, it takes the idea of anchor reputation and dynamic reinterpretation much further by making most nodes provisional anchors and by composing several staggered DAGs into one log. Compared with uncertified designs such as Mysticeti, it argues that robustness is worth preserving and that certification itself is not the fundamental latency bottleneck.

That makes the paper likely to matter to designers of blockchain consensus stacks and other geo-distributed BFT services that want leader-free throughput without paying the 10+ message-delay cost of earlier DAG protocols. The multiple-DAG technique also looks reusable beyond this specific protocol family.

## Limitations

Shoal++ is still a common-case optimization under partial synchrony, not a worst-case latency guarantee under strong adversarial behavior. Fast commits depend on `2f+1` weak votes arriving quickly, and low anchoring latency depends on the reputation mechanism plus short round timeouts keeping the DAG dense. The paper evaluates crashes and packet loss, but not more strategic Byzantine behaviors that might try to game reputation or create pathological weak-vote patterns.

The system also spends more CPU, memory, and disk space than Shoal because it runs multiple DAGs at once. Even its fault-free target of 4.5 message delays remains above PBFT's 3-message-delay common case unless one accepts higher-cost all-to-all communication. Finally, the experiments isolate consensus by disabling execution and the normal ledger stack, so the reported latency wins should be read as consensus-level improvements rather than full application-level end-to-end gains.

## Related Work

- _Spiegelman et al. (FC '24)_ - `Shoal` already improves Bullshark with per-round anchors and reputation-guided candidate selection; `Shoal++` extends that line with fast commits, dynamic virtual anchors, and parallel DAGs.
- _Spiegelman et al. (CCS '22)_ - `Bullshark` provides the certified DAG-BFT baseline whose commit rule and every-other-round anchor schedule `Shoal++` directly targets.
- _Danezis et al. (EuroSys '22)_ - `Narwhal and Tusk` establish the certified round-based DAG substrate that `Shoal++` inherits, but not the low-latency anchor management added here.
- _Giridharan et al. (SOSP '24)_ - `Autobahn` attacks BFT latency with a DAG-free design based on parallel data lanes, whereas `Shoal++` stays in the certified DAG-BFT design space and tries to make that line competitive on latency.

## My Notes

<!-- empty; left for the human reader -->
