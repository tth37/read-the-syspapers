---
title: "Achieving Fairness Generalizability for Learning-based Congestion Control with Jury"
oneline: "Jury keeps DRL congestion control fair in unseen networks by learning only bottleneck-state signals, then post-processing rate changes from estimated bandwidth occupancy."
authors:
  - "Han Tian"
  - "Xudong Liao"
  - "Decang Sun"
  - "Chaoliang Zeng"
  - "Yilun Jin"
  - "Junxue Zhang"
  - "Xinchen Wan"
  - "Zilong Wang"
  - "Yong Wang"
  - "Kai Chen"
affiliations:
  - "University of Science and Technology of China"
  - "iSING Lab, Hong Kong University of Science and Technology"
  - "BitIntelligence"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3696065"
code_url: "https://github.com/tianhan4/jury"
tags:
  - networking
  - ml-systems
  - observability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Jury argues that fairness in learning-based congestion control should not be learned end to end. It feeds the DRL policy only normalized bottleneck-state signals, has the model output a rate-adjustment range, and then uses estimated bandwidth occupancy to make large flows back off more than small ones.

## Problem

Prior DRL congestion-control schemes can look fair inside training and fail outside it. The paper argues this is structural: fairness needs bandwidth-sensitive behavior, but throughput-like inputs also tie the learned policy to the absolute scale of the training environment. Astraea trained on 100 Mbps links, for example, loses fairness on a 350 Mbps link.

Simply removing those inputs does not work either. The authors retrain Astraea without throughput-related features and report that it can barely learn to converge even in training. The real problem is therefore to use bandwidth information for fairness without letting the model overfit to bandwidth scale.

## Key Insight

Jury separates generalization from fairness. The neural policy only sees normalized RTT and loss changes that describe bottleneck state and therefore look the same to all flows at the same bottleneck. Since those inputs do not encode absolute bandwidth scale, the model can output the same decision range across unseen link capacities.

Fairness then comes from a deterministic post-processor. It estimates each flow's bandwidth occupancy and assigns a smaller action to larger flows and a larger action to smaller ones. The learned model decides how aggressive the bottleneck should be overall; the post-processor decides who should yield.

## Design

Jury records action-feedback signals over control intervals. The DRL path keeps only normalized RTT and loss changes. A DDPG actor-critic model with TD3-style training tricks outputs a mean `mu` and radius `delta` rather than a single action.

A separate path uses sending-rate and throughput changes to estimate occupancy. If a rate increase produces a large throughput increase, the flow is likely small; if throughput barely moves, it is already near its fair share. Jury uses that estimate to pick a point in `(mu, delta)` and then applies multiplicative `cwnd` and pacing-rate updates. The implementation also adds moving-average smoothing, clipped outliers, forced exploration when the action is near zero, and a minimum-samples rule that behaves like a slow-start guard and lets very short flows skip most DRL overhead.

## Evaluation

The training region is deliberately narrow: 20-100 Mbps bandwidth, 10-60 ms base RTT, and up to 0.1% loss. Jury is then tested far outside it. On three homogeneous flows across 20-400 Mbps, 10-75 ms base delay, and up to 0.3% loss, it gets the best fairness among the baselines with average Jain index 0.94 and 5th percentile 0.82. In a 20-flow RTT-heterogeneous test, with half the flows at 30 ms RTT and half at 90 ms, average per-flow throughput stays close at 10.3 Mbps versus 11.1 Mbps.

Performance also generalizes well. In single-flow emulations Jury keeps high utilization and low queueing delay across bandwidth, RTT, loss, and buffer sizes far beyond training. On a satellite-style path with 42 Mbps bandwidth, 800 ms RTT, and 0.74% random loss, it still gets more than 75% of link capacity while adding only 18.2 ms over a 400 ms one-way base delay. The AWS tests between Seoul, Tokyo, and London show the same pattern: Jury forms a better throughput-latency frontier than Cubic and the other learned baselines.

## Novelty & Impact

The paper's main contribution is architectural, not just algorithmic. Instead of hoping a black-box policy internalizes fairness and generalization simultaneously, Jury constrains the learning problem so the policy only learns bottleneck state and a hand-designed post-processor preserves fairness under distribution shift. That makes it a useful template for learned control loops that need one property to remain stable across environments.

## Limitations

The guarantee is limited to Jury flows sharing one bottleneck. Friendliness against Cubic or BBR is only empirical, and the paper explicitly says generalizable friendliness remains open. The occupancy estimate is indirect and depends on noisy action-feedback signals.

The implementation also has nontrivial overhead: about 4.5 ms per inference at a 20 ms control interval, lower than Orca but much higher than classic TCP controllers. The reward weights are tuned for one throughput-delay-loss tradeoff, so new objectives require retraining. Convergence is also slower on large-BDP paths because feedback is delayed and per-interval rate changes are bounded.

## Related Work

- _Yen et al. (SIGCOMM '20)_ - Orca also combines learning with classic congestion control, but its Cubic-plus-RL hybrid still lets the learned component interfere with convergence rather than separating fairness into a dedicated post-processing stage.
- _Jay et al. (ICML '19)_ - Aurora showed that vanilla deep RL can learn useful congestion-control behavior, while Jury focuses on the missing piece Aurora does not guarantee: fairness that survives outside the training region.
- _Dong et al. (NSDI '18)_ - PCC Vivace reaches fair equilibria through online trial-and-error utility optimization, whereas Jury targets faster interval-based adaptation without spending several RTTs on each exploratory step.
- _Liao et al. (EuroSys '24)_ - Astraea injects fairness directly into multi-agent RL rewards, and Jury can be read as a reaction to Astraea's failure mode on unseen bandwidth scales.

## My Notes

<!-- empty; left for the human reader -->
