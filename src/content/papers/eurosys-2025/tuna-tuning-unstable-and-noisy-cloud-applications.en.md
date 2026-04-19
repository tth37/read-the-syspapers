---
title: "TUNA: Tuning Unstable and Noisy Cloud Applications"
oneline: "TUNA tunes cloud applications by sampling promising configs across multiple nodes, filtering unstable ones, and de-noising measurements before they reach the optimizer."
authors:
  - "Johannes Freischuetz"
  - "Konstantinos Kanellis"
  - "Brian Kroth"
  - "Shivaram Venkataraman"
affiliations:
  - "University of Wisconsin – Madison"
  - "Microsoft Gray Systems Lab"
conference: eurosys-2025
category: cloud-scheduling-and-serverless
doi_url: "https://doi.org/10.1145/3689031.3717480"
code_url: "https://aka.ms/mlos/tuna-eurosys-artifacts"
tags:
  - compilers
  - datacenter
  - databases
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

TUNA argues that cloud autotuning breaks when it treats one measurement on one node as ground truth. It evaluates promising configurations across multiple nodes, rejects configurations whose performance has unstable outliers, and uses OS metrics to predict a de-noised score for the optimizer. Across PostgreSQL, Redis, and NGINX, that usually improves both deployed performance and transferability; where it does not improve the mean, it still sharply reduces variance and crashes.

## Problem

The paper starts from a mismatch between how tuners measure performance and how cloud systems are actually deployed. Most autotuners suggest a configuration, run it once on one machine, and feed that number back to a Bayesian or Gaussian-process optimizer. That workflow assumes the tuning node is representative. In the cloud, it often is not: noisy neighbors, cache effects, memory interference, and OS-level variability can perturb the measured performance enough to distort the optimizer's search.

The authors quantify both sides of that problem. In a controlled experiment on CloudLab, injecting only 5% synthetic noise into the score reported to SMAC slows convergence to the same performance level by 2.5x; at 10% noise the slowdown grows to 4.35x. In a separate 68-week Azure study covering 43,641 VMs and more than 7 million measurements, CPU and disk variability are now quite low, but memory, cache, and OS-related operations still show meaningful CoVs of about 4.9%, 9.8%, and 14.4%. So cloud variability has narrowed, not disappeared.

The second problem is worse than mere measurement noise: some configurations are intrinsically unstable. When the authors tuned PostgreSQL on TPC-C, 39.0% of configurations seen during tuning were unstable, with throughput CoV up to 101.3%. Of the 30 best configurations transferred to fresh VMs, 13 were unstable and some degraded by more than 70%. The root cause was not random VM slowdown but query-plan bifurcation: small platform differences changed PostgreSQL's estimated costs enough to select a much slower plan. A tuner that only sees the lucky node will incorrectly promote these brittle configurations.

## Key Insight

The key insight is that robustness should be built into the sampling path, not bolted onto the optimizer afterward. TUNA does not change SMAC, Gaussian-process tuning, or the system under test. Instead, it changes what evidence the optimizer receives. The paper's claim is that if a configuration is worth keeping, it should survive evaluation across several nodes, and if cloud noise is the issue, low-level metrics can help reconstruct a more stable estimate of its true performance.

That leads to a three-part proposition. First, sample promising configurations on progressively more nodes rather than spending equal effort on every candidate. Second, treat cross-node outliers as a sign of instability and explicitly penalize them. Third, use per-run system metrics to learn how much each measurement was distorted by the platform so the optimizer sees a smoother objective. The resulting signal is intentionally conservative: TUNA would rather discard a fast-but-brittle configuration than deploy something that wins only on the tuning VM.

## Design

TUNA's budget is the number of nodes on which a configuration has been evaluated. It uses Successive Halving as the multi-fidelity policy: every configuration starts cheap, and only promising ones are promoted to higher budgets. Because higher budget means more distinct nodes, TUNA gains two things at once: a better estimate of transferability and a sample distribution rich enough to detect instability. In implementation, the system uses a fixed cluster rather than provisioning new nodes per sample. Based on their unstable-config study, the authors choose a maximum budget of 10 nodes, which gives about 95% confidence of detecting all unstable configurations seen in that workload family.

The outlier detector is deliberately simple. For a configuration's cross-node samples `x`, TUNA computes relative range `(max(x) - min(x)) / E(x)`. If that exceeds 30%, the configuration is marked unstable. The threshold comes from a sensitivity study over 1,000 configurations run on 10 nodes, where 30% sits between two peaks in the observed distribution. Once a configuration is flagged, TUNA reports a penalty score to the optimizer by halving its measured performance. The detector only asks whether an outlier exists, not how often it appeared, because even one catastrophic deployment result is enough to make a configuration unattractive.

To address ordinary cloud noise, TUNA trains a random-forest regressor online. Inputs are all available `psutil` metrics plus a one-hot worker ID; targets are each sample's percent error relative to that configuration's mean performance. The model is trained only on stable configurations that have been run at maximum budget, since those samples are the least contaminated by hidden instability. At inference time, TUNA adjusts stable samples before aggregation; unstable configurations bypass the model and keep their penalty.

Aggregation is the final, and intentionally pessimistic, step. Rather than mean or median, TUNA reports the minimum adjusted score back to the optimizer. The paper argues this is the right objective for transferability: a configuration that is excellent on two nodes and disastrous on one should be treated as dangerous. The outlier detector bounds how much uncertainty remains in that worst-case summary.

## Evaluation

The evaluation reflects the deployment story the paper cares about. Tuning runs for 8 hours on a cluster with 10 worker nodes and 1 orchestrator, usually on Azure D8s_v5 VMs with SSDv2 disks; the best learned configuration is then deployed to 10 fresh systems. The workloads span PostgreSQL on TPC-C, epinions, TPC-H, and mssales, Redis on YCSB-C, and NGINX serving the top 500 Wikipedia pages.

The most instructive result is that TUNA does not merely chase the highest average score during tuning. On PostgreSQL TPC-C, traditional sampling finds slightly higher mean throughput after deployment, 1989 TPS versus TUNA's 1925 TPS, but it does so by repeatedly selecting brittle configurations: its deployed standard deviation is 205.7 TPS versus 69.0 TPS for TUNA, and two of its chosen runs perform worse than the default configuration once transferred. On epinions, TUNA improves both objectives, reaching 34,957 TPS on average versus 32,189 TPS for traditional sampling. On the production mssales workload, TUNA is much better on both fronts: 33.2 seconds mean runtime versus 62.5 seconds, with 0.49 seconds versus 1.26 seconds standard deviation.

The cross-environment results support the paper's generality claim. In a noisier Azure region, TUNA reaches 2321 TPS versus 2239 TPS for traditional sampling, while reducing standard deviation from 267.7 TPS to 113.0 TPS. On CloudLab bare metal, TUNA reaches 5756 TPS versus 5380 TPS and reduces variability by 7.71x. Across systems, it prevents failure modes that average metrics hide: on Redis, three configurations from traditional sampling crash 30% of the time on average, while TUNA finds no crashing configuration at all; on NGINX, it reduces P95 latency from 46.6 ms to 42.6 ms and cuts standard deviation from 1.46 ms to 0.82 ms.

The ablations are also important. Removing the noise-adjuster model slows convergence by 13.3% on average and leaves substantially higher score error later in the run. Removing the outlier detector lets the optimizer find a faster-looking configuration, 2810 TPS versus 2572 TPS, but deployment variance explodes from 54.8 TPS to 550.8 TPS. That is the paper's central tradeoff in one figure: TUNA gives up some peak scores to avoid configurations that are operationally unsafe.

## Novelty & Impact

TUNA's contribution is not a new optimizer but a new measurement discipline for autotuning under cloud variability. Earlier systems mostly optimize sample efficiency under the assumption that each sample is trustworthy. TUNA instead asks what should count as a trustworthy sample when the platform itself is noisy and some configurations are unstable by design. That framing is the paper's main novelty.

The impact is likely broader than DBMS tuning. Any offline autotuning setup that evaluates configurations on shared infrastructure faces the same failure mode: the optimizer can overfit to a lucky machine. TUNA provides a concrete recipe for avoiding that overfitting without rewriting the optimizer or the system under test. Work on robust benchmarking, cloud configuration tuning, and transferable autotuning should all cite this paper because it shifts the question from "how quickly can I score a config?" to "when should I trust the score at all?"

## Limitations

TUNA depends on having a cluster available during tuning. That is cheaper than exhaustively running every configuration everywhere, but it is still a real systems cost, and the chosen cluster size of 10 is justified from the authors' observed unstable configurations rather than from a broader proof. Workloads with different instability patterns might need a different maximum budget.

The outlier detector is heuristic. Relative range with a 30% threshold is interpretable and easy to deploy, but it is still a fixed rule. Likewise, the noise-adjuster model is trained only from data within the current run, which means its benefits arrive gradually rather than immediately. The authors also note a failure mode they did not hit in evaluation: without guardrails, the model could in principle over-correct the reported score.

The deployment scope is also narrower than the paper's ambition. Most experiments are offline tuning of single-node services on Azure or CloudLab, not distributed applications with strong network effects. The paper explicitly does not address burstable or serverless nodes, where credit depletion is hard to distinguish from configuration instability. It also focuses on static-workload tuning rather than online adaptation under continuously shifting production demand.

## Related Work

- _Kanellis et al. (VLDB '22)_ - LlamaTune improves sample efficiency for DBMS knob tuning, while TUNA asks whether those samples remain trustworthy when cloud noise and unstable configurations distort the measured score.
- _Van Aken et al. (VLDB '21)_ - OtterTune studies ML-based DBMS tuning services on real systems, but TUNA focuses on transferability across nodes and adds cross-node sampling plus de-noising to avoid brittle configurations.
- _Li et al. (VLDB '19)_ - QTune uses deep reinforcement learning for query-aware database tuning, whereas TUNA is optimizer-agnostic and targets robustness of the sampling process itself.
- _Zhang et al. (SIGMOD '19)_ - CDBTune automates cloud database tuning with deep RL and parallel execution, but the TUNA paper argues that parallelism alone is insufficient unless the tuner also models noise and instability.

## My Notes

<!-- empty; left for the human reader -->
