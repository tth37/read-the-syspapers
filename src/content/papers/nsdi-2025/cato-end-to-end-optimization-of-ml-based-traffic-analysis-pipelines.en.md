---
title: "CATO: End-to-End Optimization of ML-Based Traffic Analysis Pipelines"
oneline: "CATO jointly searches flow features and packet depth with Bayesian optimization, then compiles and measures serving pipelines that cut traffic-analysis latency by orders of magnitude."
authors:
  - "Gerry Wan"
  - "Shinan Liu"
  - "Francesco Bronzino"
  - "Nick Feamster"
  - "Zakir Durumeric"
affiliations:
  - "Stanford University"
  - "University of Chicago"
  - "ENS Lyon"
conference: nsdi-2025
code_url: "https://github.com/stanford-esrg/cato"
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

CATO treats traffic-analysis model development as a multi-objective search over both which flow features to extract and how much of each flow to wait for before predicting. It combines Bayesian optimization with a profiler that compiles and directly measures full serving pipelines, rather than guessing cost from feature heuristics. Across live traffic and offline traces, it finds pipelines that are often both faster and more accurate than standard feature-selection baselines.

## Problem

The paper starts from a deployment failure mode that is easy to miss in networking ML work: a model can look strong on offline traces yet still be unusable once it has to run on live traffic. For per-flow traffic analysis, the real system is not just the classifier. It includes packet capture, connection tracking, feature extraction, waiting for enough packets to arrive, and then model inference. Those stages jointly determine latency, throughput, and packet-loss behavior.

Prior work often optimizes only one slice of that stack. Some papers chase predictive accuracy with richer features or more sophisticated models; others force the system to run faster with lightweight models, hardware offload, or fixed-depth early inference. But the feature subset and the connection depth interact in non-linear ways. In the paper's motivating six-feature IoT example, exhaustive measurement over 3,200 `(feature set, packet depth)` choices already takes five days, and the authors estimate that 25 candidate features would blow up to more than 7,000 years. The practical problem is therefore not merely picking "good features," but finding Pareto-optimal pipelines under both model-performance and systems-cost objectives.

## Key Insight

The core insight is that the right optimization variable is the end-to-end traffic representation, not the model in isolation. CATO defines a feature representation as `(F, n)`: a subset of candidate features `F` plus a connection depth `n` that says how many packets, bytes, or units of time to observe before extracting them. Each such representation induces a different serving pipeline with different accuracy, latency, and throughput characteristics.

That framing makes the problem a multi-objective optimization over `cost(x)` and `perf(x)`, but only if those objectives are measured directly. The paper argues that heuristics are unreliable because packet parsing work is shared across features, feature interactions change predictive power, and traffic dynamics affect runtime cost. CATO therefore couples Bayesian optimization with a compiler/profiler loop so the search is guided by real measurements of the exact pipeline that would be deployed.

## Design

CATO has two main pieces: an Optimizer and a Profiler. The Optimizer searches the representation space with multi-objective Bayesian optimization. It uses one binary variable per feature and one numeric variable for connection depth, then minimizes systems cost while maximizing predictive performance. To make BO workable in a mixed, high-dimensional search space, CATO adds two preprocessing steps. First, it drops features whose mutual information with the target is zero. Second, it injects priors: features with higher mutual information are sampled more aggressively, while smaller connection depths are favored via a linearly decaying prior because waiting longer generally hurts serving cost.

The Profiler is what turns the search into an end-to-end systems result instead of a feature-ranking exercise. It is built on Retina and generates a custom Rust traffic-processing pipeline for each sampled representation using conditional compilation. Only the parsing and feature-extraction operations needed for that representation are compiled in, which avoids runtime branching overhead that would contaminate measurements. The paper implements 67 candidate features in about 1,600 lines of Rust and supports decision trees, random forests, and a TensorFlow DNN. Depending on the use case, `cost(x)` can be end-to-end inference latency, negative zero-loss throughput, or execution time, while `perf(x)` is F1 score or RMSE on a hold-out set.

## Evaluation

The evaluation covers three use cases: live web-application classification on a university network (`app-class`), IoT device recognition on the UNSW IoT traces (`iot-class`), and YouTube startup-delay regression (`vid-start`). The main baselines are common choices a practitioner might actually use: all features, top-10 features by recursive feature elimination, and top-10 by mutual information, each evaluated at 10 packets, 50 packets, and the full connection.

For `iot-class` and `vid-start`, CATO's Pareto front dominates the baseline solutions. On IoT classification, it reduces end-to-end latency by 11x-79x relative to 10-packet baselines, 817x-2000x relative to 50-packet baselines, and more than 3600x relative to waiting for the full connection, while keeping equal or better predictive performance. One concrete example is telling: a baseline using RFE on the first 10 packets reaches F1 0.970 at 7.9 seconds latency, while CATO finds a 3-packet solution with F1 0.979 at 0.1 seconds. On `vid-start`, CATO achieves 2.2x-2900x lower latency and also lowers regression error.

The live `app-class` results are slightly more mixed, which makes them more credible. CATO does not beat every point on raw F1, but it finds solutions with nearly the same accuracy at much lower cost; for example, it reaches F1 0.960 at 0.54 seconds, which is 2.6x faster than `MI10` at 10 packets and 19x faster than `RFE10` at 50 packets. For single-core zero-loss throughput, it improves throughput by 1.6x-3.7x over "all packets" baselines and 1.3x-2.7x over 50-packet baselines while also improving model quality. On a smaller six-feature ground-truth search space, CATO reaches hypervolume 0.98 after exploring less than 1.6% of all 3,200 points, and it converges to 0.99 hypervolume in 87 iterations on average versus 240 for the same BO framework without CATO's priors and 1,295+ for simulated annealing or random search.

## Novelty & Impact

The paper's novelty is not a new classifier but a full optimization loop for building deployable traffic-analysis systems. The closest prior system, Traffic Refinery, profiles cost-aware feature classes but still relies on manual exploration; hardware-oriented systems such as N3IC optimize the model stage but not the representation/collection stage; Homunculus uses BO for data-plane ML pipelines but is single-objective and solves a different problem. CATO's distinct contribution is to search over both feature choice and prediction timing, while grounding the search in measured end-to-end pipelines. That matters for operators who care about real-time encrypted-traffic classification, QoE inference, or anomaly detection more than about squeezing out another point of offline accuracy.

## Limitations

CATO's biggest practical limitation is that the optimization loop is expensive. The appendix reports about 9.5 hours to compute one 50-iteration Pareto front for the live `app-class` throughput experiment and about 2 hours even for the smaller six-feature IoT experiment. That is acceptable for offline design-space exploration, but not for rapid iteration.

The framework also depends strongly on the user-defined search space. If the candidate features exclude an important signal, or the maximum connection depth is set badly, CATO cannot recover it; the authors show that unbounded depth materially hurts convergence. The current Profiler targets CPU-based pipelines built on Retina, so the paper does not yet demonstrate the same end-to-end loop on SmartNICs or switches. Finally, the strongest throughput validation is only on one live classification workload, while the other tasks rely on offline traces or simulated latency components.

## Related Work

- _Bronzino et al. (POMACS '21)_ - `Traffic Refinery` also studies cost-aware traffic representations, but it requires manual exploration of feature classes and depths, whereas CATO automates the Pareto search with direct end-to-end measurements.
- _Piet et al. (SIGCOMM '23)_ - `GGFAST` automates the construction of encrypted-traffic classifiers, while CATO is broader and explicitly optimizes the full serving pipeline against systems cost.
- _Siracusano et al. (NSDI '22)_ - `N3IC` accelerates traffic-analysis inference on neural-network interface cards, whereas CATO focuses on choosing what traffic representation to collect and when to stop collecting it.
- _Swamy et al. (ASPLOS '23)_ - `Homunculus` uses Bayesian optimization to generate efficient data-plane ML pipelines, but it is single-objective and does not jointly optimize feature subsets, connection depth, and measured end-to-end serving performance.

## My Notes

<!-- empty; left for the human reader -->
