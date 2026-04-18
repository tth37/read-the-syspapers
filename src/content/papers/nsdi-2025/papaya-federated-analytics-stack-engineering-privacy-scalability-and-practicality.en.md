---
title: "PAPAYA Federated Analytics Stack: Engineering Privacy, Scalability and Practicality"
oneline: "PAPAYA pushes SQL-style preprocessing to devices and keeps TEEs limited to secure sum, thresholding, and DP noise so federated analytics can scale to nearly 100M phones."
authors:
  - "Harish Srinivas"
  - "Graham Cormode"
  - "Mehrdad Honarkhah"
  - "Samuel Lurye"
  - "Jonathan Hehir"
  - "Lunwen He"
  - "George Hong"
  - "Ahmed Magdy"
  - "Dzmitry Huba"
  - "Kaikai Wang"
  - "Shen Guo"
  - "Shoubhik Bhattacharya"
affiliations:
  - "Meta"
conference: nsdi-2025
tags:
  - security
  - confidential-computing
  - observability
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

PAPAYA decomposes federated analytics into three pieces: SQL-like filtering and grouping on device, a tiny SGX-based secure aggregator that only performs secure sum, thresholding, and optional differential-privacy noise, and an untrusted orchestrator around it. That separation lets Meta run privacy-preserving monitoring queries over nearly 100 million Android phones, reach about 85% coverage in 16 hours and over 96% in four days, and keep central-DP accuracy close to the non-private baseline.

## Problem

The paper starts from a practical gap. Large mobile services need continuous analytics for product monitoring, experimentation, usage reporting, and model-quality checks, but shipping raw user data to a central warehouse is increasingly unacceptable both legally and operationally. Prior federated analytics systems showed the idea is viable, yet the paper argues they usually fail along one of three axes: they lose too much utility because they rely on very noisy local privacy mechanisms, they expose only narrow query interfaces, or they do not scale well enough to millions of heterogeneous devices.

The workload here is also different from federated learning. FA wants small client messages, very few rounds, and much broader query shapes, while FL is optimized for repeated model-update rounds over relatively small client batches. A mobile analytics stack therefore cannot assume synchronized rounds, stable client availability, or heavyweight per-query code. The obvious fallback, namely bespoke secure protocols per metric or repeated multi-round searches, is too slow, too fragile under client dropout, and too hard for ordinary analysts to use. The paper's target is not a cryptographic toy problem but a production system that can answer everyday monitoring questions without breaking privacy guarantees or device budgets.

## Key Insight

PAPAYA's core claim is that federated analytics becomes practical when almost all query semantics stay on the device and almost all trusted server logic is reduced to one reusable primitive. Devices run SQL-like local transformations, turning raw local records into compact key-value summaries such as mini histograms. Once reports have already been grouped and reduced on device, the backend no longer needs to understand every analytics use case. It only needs to aggregate encrypted bucketed values, add privacy noise if requested, threshold low-support buckets, and release the anonymized result.

That is important for both privacy and engineering. Privacy improves because the device can remotely attest the exact TEE binary that will handle its report, and because the TEE code surface is intentionally tiny and auditable. Scalability improves because one-shot algorithms built around Secure Sum and Thresholding avoid long interactive protocols and tolerate clients that check in late or disappear altogether. The paper further argues that many useful analytics tasks, including counts, sums, means, heavy hitters, heatmaps, and quantiles, can be expressed with this histogram-centric view plus post-processing.

## Design

The system has three zones. The untrusted orchestrator (UO) manages query registration, query assignment, result publication, and client communication. The client runtime manages local storage, scheduling, guardrails, and execution. The trusted secure aggregator (TSA) is one enclave-backed aggregation instance per query. Analysts author a federated query in two parts: an on-device SQL-like query that extracts dimensions and metrics from local state, and a server-side aggregation specification that selects primitives such as COUNT, SUM, MEAN, or quantiles, along with privacy parameters and output configuration.

Client execution is split into selection and execution phases. During selection, a device polls the UO for active queries, checks whether it has relevant data, validates privacy parameters against hardcoded local guardrails, and may subsample itself using local randomness. During execution, the client batches multiple queries together, runs the local SQL over its on-device store, remotely attests the target TSA, establishes an encrypted channel, and uploads only the reduced report. The paper emphasizes that batching is critical because the dominant device cost is process startup and communication, not the SQL itself.

Inside the TEE, PAPAYA reduces cross-device aggregation to Secure Sum and Thresholding. Each query starts with an empty histogram. Clients send encrypted key-value pairs, the enclave decrypts and immediately folds them into the running histogram, and individual client plaintext is discarded. After enough time and enough participating devices, the enclave adds privacy noise to both bucket counts and bucket sums, removes buckets whose noisy support falls below a threshold, and releases the anonymized histogram to the UO. The same structure supports central DP, local DP, or distributed sample-and-threshold noise addition, depending on where the analyst chooses to place randomness.

The operational details matter as much as the abstraction. PAPAYA randomizes client sync and reporting schedules to smooth QPS into TEEs, batches device work to amortize overheads, shards different queries across aggregators, and snapshots intermediate aggregation state so a new aggregator-TSA pair can recover after failures. The appendix shows the same histogram abstraction extends to quantiles: instead of doing interactive binary search over many rounds, PAPAYA can collect a fixed hierarchy of histograms in one round and recover approximate quantiles from that tree later.

## Evaluation

The evaluation is a real deployment study, not a lab prototype benchmark. Queries run on a population of nearly 100 million Android phones, each using a background job with a 10-second timeout and a maximum of two runs per day. The studied tasks are representative monitoring queries: histograms of request round-trip times and histograms of request counts. The data are highly heterogeneous. Most devices contribute a single sampled value, but some contribute tens and a few contribute more than 100; network RTTs have a mode around 50 ms but stretch past 500 ms.

Collection speed is the first key result. Across three runs of the same RTT query launched 6 hours apart, the coverage curves are almost identical, showing that time of day is not the dominant factor. Coverage grows roughly linearly to about 85% over the first 16 hours, reaches about 90% by 24 hours, and exceeds 96% after 96 hours. The long tail is due to sporadically active devices rather than a system bottleneck. Coverage is also only weakly correlated with network quality: lower-RTT devices report slightly earlier, but the gap is small.

Accuracy is the second result. For the RTT and event-count histograms, the total variation distance between the federated result and a centrally collected ground truth becomes very small within hours and is negligible by the end of the run. By about 12 hours, when roughly half the clients have checked in, the histogram is already very close to the final answer. Appendix A shows the same pattern for quantiles: after 48 hours, the maximum CDF error is 0.32% for daily RTT measurements and 0.49% for hourly RTT measurements.

The privacy study is the third result and arguably the paper's strongest argument for its TEE-centered design. With privacy parameters set to `epsilon = 1` and `delta = 10^-8`, central DP and distributed sample-and-threshold remain close to the no-DP baseline, while local DP is about an order of magnitude noisier. For RTT histograms, LDP remains visibly above the other mechanisms throughout the run, whereas central DP is almost indistinguishable from the un-noised curve. Hourly event counts are harder because the signal is 34x lower than daily counts, so sample-and-threshold loses more information there. Still, the paper convincingly shows that if one can trust an attested enclave, federated analytics can preserve much more utility than a purely local-DP design.

## Novelty & Impact

No single ingredient in PAPAYA is new by itself. Secure aggregation, SGX attestation, local transforms, and differential privacy all predate this paper. The novelty is the way the paper engineers them into a production federated analytics stack with a clear trust split: analyst-authored query logic stays on device, a minimal TEE performs only reusable aggregation work, and the rest of the control plane is treated as untrusted. The system is also unusually honest about why FA should not be treated as a simple extension of federated learning.

That makes the paper useful beyond Meta's deployment. Operators building privacy-preserving telemetry can cite it as evidence that one-shot FA is viable at phone scale. Researchers working on TEEs, secure aggregation, and privacy systems can treat it as a deployment blueprint showing which parts of the trusted computing base were kept tiny, which privacy models were actually practical, and where the remaining operational pain still lives.

## Limitations

The trust model still leans heavily on SGX-style TEEs. The paper explicitly notes that one must account for known SGX attacks and apply mitigations, so the privacy story is not "cryptography only." If a reader does not accept enclave trust, then the strongest accuracy results from central DP are less persuasive, and the system falls back to weaker-utility local or distributed models.

The paper also narrows scope in ways that matter. Malicious clients trying to poison outputs are considered out of scope beyond bounded per-report contributions and separate binary-integrity controls. Privacy accounting is mostly per-query and pragmatic: the authors emphasize avoiding repeated queries over the same data more than they present a full longitudinal privacy-budget framework. Finally, the system is best suited to aggregation-style analytics. The paper shows counts, sums, means, histograms, and quantiles, but more complex analytics would either need custom code or a broader primitive set.

## Related Work

- _Bonawitz et al. (CCS '17)_ - Practical secure aggregation uses multi-party protocols among clients to hide intermediate values, while PAPAYA uses remotely attested TEEs to avoid client-client coordination and to support thresholding more directly.
- _Corrigan-Gibbs and Boneh (NSDI '17)_ - Prio computes aggregate statistics from secret-shared client reports across multiple servers; PAPAYA instead centers a histogram primitive inside one TEE-backed aggregator and focuses on production mobile deployment.
- _Roth et al. (OSDI '20)_ - Orchard provides differentially private analytics at scale without a trusted core, whereas PAPAYA accepts enclave trust in exchange for a simpler backend and stronger utility for central-DP style queries.
- _Huba et al. (MLSys '22)_ - PAPAYA for federated learning shares the privacy goal and TEE flavor, but this paper argues federated analytics needs a separate system optimized for one-shot, small-message, analyst-authored queries rather than repeated model training rounds.

## My Notes

<!-- empty; left for the human reader -->
