---
title: "Towards VM Rescheduling Optimization Through Deep Reinforcement Learning"
oneline: "VMR2L learns VM-first, PM-second rescheduling, uses sparse PM-VM attention, and picks the best sampled rollout to approach MIP-quality fragment reduction within a 5 s window."
authors:
  - "Xianzhong Ding"
  - "Yunkai Zhang"
  - "Binbin Chen"
  - "Donghao Ying"
  - "Tieying Zhang"
  - "Jianjun Chen"
  - "Lei Zhang"
  - "Alberto Cerpa"
  - "Wan Du"
affiliations:
  - "University of California, Merced"
  - "University of California, Berkeley"
  - "ByteDance"
conference: eurosys-2025
category: cloud-scheduling-and-serverless
doi_url: "https://doi.org/10.1145/3689031.3717476"
code_url: "https://github.com/zhykoties/VMR2L_eurosys"
project_url: "https://drive.google.com/drive/folders/1PfRo1cVwuhH30XhsE2Np3xqJn2GpX5qy"
tags:
  - scheduling
  - virtualization
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

VM rescheduling is unusual because solver latency changes the problem instance: by the time a slow optimizer finishes, some moves are invalid. `VMR2L` addresses that with sequential RL, two-stage VM/PM actions, topology-aware sparse attention, and best-of-many rollout selection. At `MNL = 50`, it reaches FR 0.2941 in 1.1 seconds, versus 0.2859 for MIP in 50.55 minutes.

## Problem

Clusters use fast heuristics for day-long VM scheduling, but those heuristics leave scattered CPU fragments that cannot host another 16-core VM. Rescheduling is the cleanup pass: during off-peak periods the system live-migrates a limited number of VMs to coalesce capacity again, under NUMA, CPU/memory, and migration-count constraints.

The twist is that rescheduling runs against a moving target. VMs still arrive and exit while the planner computes. On a 280-PM, 2089-VM trace, Gurobi needs 1.78 minutes for 25 migrations and 50.55 minutes for 50 migrations. Replay shows the achieved benefit stays near-optimal only if the plan arrives within about 5 seconds. That makes exact optimization operationally too slow and greedy heuristics too weak.

## Key Insight

Treat VMR as a sequence of deterministic single-migration decisions instead of one giant solve. Given a state and one migration, the next state and fragment change are exactly known, so the authors can train offline in a simulator built from snapshots.

That formulation turns the latency problem into a strength. A policy can emit legal moves in seconds, and because the simulator is exact, inference can sample several full trajectories and deploy only the best. In this setting, fast approximate control beats slow exact optimization in achieved cluster quality.

## Design

`VMR2L` models one request as up to `MNL` steps. State includes per-NUMA PM features such as remaining CPU/memory and fragment info, plus per-VM demand and source-PM context. Reward is dense: the fragment change on the source PM and destination PM after each move.

Its first main idea is two-stage actions. Stage 1 selects a VM. Stage 2 masks PMs that cannot host that VM under resource, NUMA, or service constraints, then chooses among the legal destinations. This avoids learning over a huge `(VM, PM)` product and makes hard anti-affinity easy to incorporate.

Its second main idea is sparse attention over PM-VM trees. Each PM and its resident VMs first exchange local information; only then does the model do global PM-PM, VM-VM, and VM-PM attention. This lets the policy reason about sibling VMs on the same PM and about migration chains that a flat encoder misses.

## Evaluation

Evaluation uses two anonymized real-trace datasets: Medium with up to 2089 VMs and 280 PMs, and Large with up to 4546 VMs and 1176 PMs, each with 4400 mappings split 4000/200/200. Training takes 92 hours on one RTX 3090, but the checkpoint is under 2 MB and one Medium trajectory takes 1.1 seconds.

The central result is exactly what the paper promises. At `MNL = 50`, `VMR2L` reaches FR 0.2941, only 2.86% above near-optimal MIP at 0.2859, while staying comfortably under the practical 5-second limit. It outperforms HA, `alpha`-VBPP, POP, MCTS, Decima, and NeuPlan; ablations also matter, with FR worsening to 0.3090 without sparse attention and 0.3079 without risk-seeking rollout selection.

The evidence is broader than one benchmark. The same framework handles extra resource constraints and anti-affinity, generalizes across workload regimes, and still plans in 3.8 seconds on the Large dataset. That supports the mechanism claim, though still in offline evaluation rather than live deployment.

## Novelty & Impact

The contribution is not just RL for cluster management. The paper identifies a regime where planning latency is part of solution quality, then builds around that with action decomposition, topology-aware state encoding, and simulator-based rollout selection. Relative to Decima it targets post-placement VM migration under NUMA and migration limits; relative to POP or NeuPlan it removes MIP from the online path.

That framing is useful beyond this paper: whenever a systems controller has deterministic dynamics, large action spaces, and a seconds-level decision budget, fast learned control may beat slower exact solvers in achieved outcome.

## Limitations

The biggest limitation is evaluation fidelity. The policy is tested on logged snapshots plus a simulator, not in a live cluster where migration traffic, dirty pages, and concurrent scheduling might alter results.

The main objective is also narrow: 16-core fragment rate for ByteDance-style clusters. The paper shows extensions, but not direct gains in admission success or user-visible SLOs. Finally, the design still migrates one VM at a time, depends on prior knowledge for anti-affinity/noisy-neighbor handling, and degrades when deployed on clusters whose PM count differs by more than about 20%.

## Related Work

- _Hadary et al. (OSDI '20)_ - Protean studies VM allocation at scale for initial placement, while `VMR2L` tackles the harder follow-on problem of rearranging already-running VMs under migration limits.
- _Mao et al. (SIGCOMM '19)_ - Decima also uses RL for scheduling, but for data-processing clusters; `VMR2L` redesigns the action space and state encoder around PM affiliations, NUMA structure, and legal live migrations.
- _Narayanan et al. (SOSP '21)_ - POP partitions large granular resource-allocation problems and still relies on per-partition MIP, whereas this paper argues that VMR needs to remove MIP from the online path entirely.
- _Zhu et al. (SIGCOMM '21)_ - NeuPlan uses RL to prune a search space before handing the rest to MIP; `VMR2L` is more radical in using RL as the full online decision maker because the latency budget is measured in seconds.

## My Notes

<!-- empty; left for the human reader -->
