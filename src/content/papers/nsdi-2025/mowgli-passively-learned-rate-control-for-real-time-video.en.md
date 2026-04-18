---
title: "Mowgli: Passively Learned Rate Control for Real-Time Video"
oneline: "Mowgli learns video bitrate control from GCC telemetry logs, then uses conservative offline RL to reorder GCC-like actions and beat GCC without training on users."
authors:
  - "Neil Agarwal"
  - "Rui Pan"
  - "Francis Y. Yan"
  - "Ravi Netravali"
affiliations:
  - "Princeton University"
  - "University of Illinois Urbana-Champaign"
conference: nsdi-2025
category: datacenter-networking-and-transport
tags:
  - networking
  - observability
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Mowgli learns a real-time video rate-control policy entirely from telemetry logs produced by GCC, instead of exploring on live users. It treats GCC's delayed but directionally correct bitrate changes as reusable training data, then uses conservative offline RL and a distributional critic to pick better-timed actions. On emulated and real cellular networks, it beats GCC without paying the QoE cost of online RL training.

## Problem

The paper focuses on a deployment problem. Prior RL-based rate-control schemes can outperform Google Congestion Control on dynamic networks, but they learn by trial and error during real calls. In the authors' experiments, that training process makes 62% of calls lose average bitrate, makes 43% of calls freeze more often, and can worsen freeze rate by 79% or bitrate by 77%. For production conferencing systems, that training cost is a nonstarter.

Training only in simulation is not a clean escape hatch because prior work reports a simulation-to-reality gap once codec behavior and real network variance matter. Tuning GCC's parameters is not enough either, since GCC still reasons from a narrow set of handcrafted rules. The practical question is therefore whether a better controller can be learned without ever exposing users to an untrained policy.

## Key Insight

Mowgli's core claim is that GCC's logs already contain many of the right actions, just at the wrong times. When bandwidth drops, GCC eventually moves down to a safer bitrate; when bandwidth recovers, it eventually ramps back up. A learned controller can therefore improve QoE by reordering and reusing actions that already appear in logs, rather than inventing completely new behavior.

The catch is uncertainty. Offline learning has no direct feedback for alternate action sequences, so aggressive extrapolation can send the policy into unsupported parts of the state-action space. At the same time, the same bitrate decision can end differently because of codec behavior or stochastic networks. Mowgli addresses both issues directly: it learns conservatively near logged behavior and models return as a distribution rather than a single expected value.

## Design

Mowgli has three stages. First, it converts existing telemetry into `(state, action, reward)` trajectories. The state is a one-second window of transport and application statistics sampled about every 50 ms, including sent and acknowledged bitrate, delay and jitter signals, RTT, loss, previous action, minimum RTT, and feedback staleness. The action is the next target bitrate. The reward is a normalized combination of throughput, delay, and loss: `2 * throughput - delay - loss`.

Second, it trains a lightweight Soft Actor-Critic policy offline. A GRU embeds the time window before actor and critic layers, with two 256-unit hidden layers and a 32-unit GRU state. The important change is not SAC itself but the two safeguards around it. Mowgli uses Conservative Q-Learning so unsupported actions are penalized unless the logs justify them, which keeps the actor from chasing overestimated Q-values; the paper sets `alpha = 0.01`. It also makes the critic distributional, using quantiles and Quantile Huber loss, so the model can represent that the same action may have multiple outcomes under noisy network conditions.

Third, deployment is intentionally simple. Training happens centrally on logs only, then the learned weights are shipped to clients. A WebRTC sender process streams telemetry to a Python subprocess and gets back the next bitrate. The final policy is small, about 316 kB with roughly 79k parameters, and CPU inference takes about 6 ms.

## Evaluation

The emulation testbed extends AlphaRTC/WebRTC and replays 87 hours of FCC broadband and Norway 3G traces with Mahimahi. Traces are split into one-minute chunks, RTT is randomized across 40, 100, and 160 ms, and nine prerecorded videos are used. The main baselines are GCC, an in-house online RL implementation following prior work, behavior cloning, and CRR.

The main result is strong and consistent. Across reported percentiles on emulated traces, Mowgli improves average bitrate by 14.5-39.2%, reduces freeze rate by 59.5-100%, and raises frame rate by up to 35.3%, while keeping end-to-end frame delay within the 400 ms interactivity target. Its P75 and P90 freeze rates are 0.77% and 2.87%, versus 2.09% and 7.09% for GCC, and only slightly above online RL's 0.66% and 2.41%. The paper also shows that Mowgli comes within 6% of an approximate oracle bitrate upper bound built from GCC's logged action set.

The results line up with the paper's thesis about dynamic networks. On traces with higher bandwidth variation, Mowgli improves bitrate by 10.8-43.8% and cuts freezes by 47.4-100%. Behavior cloning is too conservative and can lose bitrate relative to GCC; CRR performs worse than GCC on both bitrate and freezes, supporting the claim that single-policy logs need stronger uncertainty handling than generic offline RL gives.

The real-world evaluation is smaller but still useful. Mowgli is tested over LTE calls across four U.S. cities, using more than 8 hours of GCC logs for training and more than 4 hours of alternating GCC/Mowgli evaluation per scenario. Bitrate rises by 3.0% to 2.1x on same-city scenarios and by 2.0% to 20.8% on new-city scenarios. Freeze events are too rare for the paper to claim a statistically significant difference there.

## Novelty & Impact

Mowgli's novelty is its deployment story as much as its model. It shows that better real-time video rate control can be learned from the passive telemetry of one already-deployed heuristic, not from unsafe online exploration and not from a simulator. The key technical combination is log-based action reordering, conservative critic regularization, and distributional value modeling for noisy production telemetry.

That makes the paper relevant to both RTC operators and ML-for-networking researchers. It reframes the goal from maximizing raw controller quality to learning a controller that is safe enough to train and ship under real production constraints.

## Limitations

Mowgli only generalizes well when deployment conditions are represented in its logs. The paper shows this explicitly: a policy trained on LTE/5G traces transfers poorly to wired/3G traces, so meaningful distribution shift requires retraining and drift monitoring.

The prototype scope is also limited. It targets unidirectional video without audio and disables WebRTC degradation preference to isolate rate control. More broadly, Mowgli still reasons counterfactually from logs; conservative learning reduces the risk of hidden confounders and sparse coverage, but it does not remove them. The strongest freeze-rate evidence also comes from emulation rather than the smaller real-world study.

## Related Work

- _Zhang et al. (MobiCom '20)_ - OnRL learns rate control online during mobile video telephony, whereas Mowgli removes user-facing exploration by training entirely from historical logs.
- _Zhang et al. (MobiCom '21)_ - Loki also uses learning for real-time video adaptation, but Mowgli focuses on practical offline training from incumbent-controller telemetry rather than online policy improvement in deployment.
- _Yen et al. (SIGCOMM '23)_ - Sage learns congestion control offline, but it relies on data from many expert TCP policies; Mowgli shows that one deployed RTC policy's logs can still support improvement if the learner is conservative enough.
- _Fouladi et al. (NSDI '18)_ - Salsify co-designs codec and transport for low-latency video, while Mowgli leaves the broader stack intact and replaces only the bitrate-control logic.

## My Notes

<!-- empty; left for the human reader -->
