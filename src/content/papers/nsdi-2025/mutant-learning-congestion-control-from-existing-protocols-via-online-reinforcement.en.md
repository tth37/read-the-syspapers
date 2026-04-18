---
title: "Mutant: Learning Congestion Control from Existing Protocols via Online Reinforcement Learning"
oneline: "Mutant switches among existing in-kernel congestion controllers online, using contextual bandits and top-k protocol selection to improve throughput-delay tradeoffs."
authors:
  - "Lorenzo Pappone"
  - "Alessio Sacco"
  - "Flavio Esposito"
affiliations:
  - "Saint Louis University"
  - "Politecnico di Torino"
conference: nsdi-2025
code_url: "https://github.com/lorepap/mutant"
tags:
  - networking
  - kernel
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Mutant treats congestion control as online selection among existing kernel protocols rather than as learning a new cwnd function. A Linux kernel wrapper plus a contextual bandit lets it switch among a small top-k pool quickly enough to keep high throughput while cutting delay.

## Problem

No single controller dominates across stable, low-bandwidth, high-RTT, and abruptly changing paths. Cubic, BBR2, Vegas, and other well-known schemes each win in some regimes and lose badly in others, so choosing one fixed controller is effectively a bet that the future will resemble the conditions it was tuned for.

Prior ML-based proposals try to learn a better universal policy, but they usually depend on long offline training and large trace collections. That leaves them exposed to distribution shift when real paths deviate from the training set. The paper asks whether a sender can adapt online by reusing the expertise already baked into existing controllers instead of training a monolithic policy from scratch.

## Key Insight

The key insight is that the action space should be "which protocol should run next?" rather than "what exact cwnd update should I emit?" Existing controllers already represent useful local policies; a learner only needs to infer which one matches the current network state.

That only works if the candidate set is small. Mutant therefore couples online protocol switching with an explicit top-k selection stage, arguing that too many candidate protocols waste time on exploration and reduce reward.

## Design

Mutant has a kernel `Protocol Manager` and a user-space `Learning Module`. In the kernel, Mutant wraps `tcp_congestion_ops`, so it can load as one congestion controller while internally switching among 11 in-kernel schemes including Cubic, BBR2, Hybla, Westwood, Veno, Vegas, YeAH, Bic, HTCP, Highspeed, and Illinois. On each switch it saves the outgoing protocol's state, restores the incoming one, and hands over the current congestion window so the transition does not restart from scratch.

The user-space learner receives ACK-driven statistics over netlink and runs a LinUCB contextual bandit. Its raw context contains 55 signals such as `snd_cwnd`, RTT, smoothed RTT, minimum RTT, loss, retransmissions, inflight packets, throughput, and current/previous protocol ID, with short-, medium-, and long-window aggregates for selected fields. A pretrained GRU encoder compresses this to 16 dimensions. Reward favors high delivery rate and low delay/loss, while ADWIN-based normalization adjusts for capacity shifts. Before online learning, `Mutant Protocol Team Selection` (MPTS) performs top-k elimination over the available controllers and supplies the small protocol pool that the bandit explores.

## Evaluation

The authors test Mutant on emulated wired and cellular paths, modified Mahimahi 5G traces, and real Fabric WAN paths. Across these settings, Mutant usually lands near the throughput-delay Pareto frontier instead of excelling only in one regime. In the step-change bandwidth scenario, it adapts faster than Cubic and tracks available capacity more closely.

The most concrete real-world result is delay: Mutant reports 3.85% lower delay than BBR2 and 3.60% lower delay than the average of Sage, Orca, Indigo, and Antelope while keeping high throughput. The paper also shows that pool selection matters: once the candidate set grows beyond about eight protocols, exploration overhead dominates. Their default `k = 6` configuration beats random or hand-mixed protocol pools across six environments.

Fairness is evaluated with the "harm" metric rather than Jain's index. Mutant shows low harm to Cubic, BBR2, Hybla, Vegas, and another Mutant flow, with reported throughput-harm between 0.094 and 0.310 and delay-harm between 0.015 and 0.097. A trace against Cubic shows it converging toward fair sharing instead of staying aggressively overprovisioned.

## Novelty & Impact

Mutant's novelty is the combination of state-preserving kernel switching, contextual bandits, and explicit top-k protocol selection. Relative to Aurora, Orca, Owl, and Sage, it assumes existing controllers already encode useful expertise and focuses on choosing among them online rather than training a new universal controller.

That framing lowers deployment risk. An operator can restrict the action space to known kernel protocols and still get adaptive behavior, which makes the paper relevant to future work on congestion-control portfolios and lightweight online learning in transport stacks.

## Limitations

Mutant cannot outperform the envelope defined by its pool: if none of the available protocols is good in some regime, switching cannot invent the missing behavior. The system is also not entirely offline-free, since the encoder is pretrained, reward coefficients are hand-set, and MPTS requires a budgeted preselection phase.

The evaluation is broad but still mostly centered on single-flow or small-competition settings. The paper gives less evidence about behavior under large shared bottlenecks with many heterogeneous senders or about operational overhead from continuous cross-protocol mutation in production.

## Related Work

- _Jay et al. (ICML '19)_ - `Aurora` learns congestion control with deep RL from scratch, whereas `Mutant` narrows the action space to selecting among existing protocols online.
- _Abbasloo et al. (SIGCOMM '20)_ - `Orca` augments a Cubic-style controller with RL-generated behavior, while `Mutant` preserves protocol-specific kernel implementations and switches among them at runtime.
- _Sacco et al. (INFOCOM '21)_ - `Owl` also applies RL to congestion control, but `Mutant` emphasizes lightweight contextual bandits plus explicit top-k protocol selection instead of a larger end-to-end learned controller.
- _Yen et al. (SIGCOMM '23)_ - `Sage` learns from heuristic designs through heavy offline training, whereas `Mutant` argues that online mutation among existing schemes can match or beat pretrained models with far less training dependence.

## My Notes

<!-- empty; left for the human reader -->
