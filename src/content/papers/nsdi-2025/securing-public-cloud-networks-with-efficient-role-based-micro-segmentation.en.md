---
title: "Securing Public Cloud Networks with Efficient Role-based Micro-Segmentation"
oneline: "ZTS infers endpoint roles from cloud flow telemetry to auto-segment deployments and keeps continuous monitoring near a 0.5% VM-cost surcharge."
authors:
  - "Sathiya Kumaran Mani"
  - "Kevin Hsieh"
  - "Santiago Segarra"
  - "Ranveer Chandra"
  - "Yajie Zhou"
  - "Srikanth Kandula"
affiliations:
  - "Microsoft"
  - "Rice University"
  - "University of Maryland"
conference: nsdi-2025
category: security-and-privacy
tags:
  - security
  - networking
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

ZTS is an end-to-end micro-segmentation system for public clouds. Its main move is to infer endpoint roles from communication graphs using deployment-specific features plus a partially supervised autoencoder, then generate and maintain segmentation policies from those roles. Across 11 real deployments, it improves average clustering accuracy well beyond prior role-inference baselines, and its graph-generation pipeline is 7.5x faster and 21.5x more cost-efficient than the paper's Apache Flink implementation.

## Problem

The paper starts from a real operational mismatch. Zero-trust style micro-segmentation is attractive because it limits lateral movement after a breach, but building the segments is hard in public clouds. Existing commercial systems largely ask administrators to label every endpoint manually. That is plausible for a small deployment, but not for environments with thousands to millions of resources, shifting workloads, and many teams changing software behavior independently. In the authors' study, only 12% to 23% of nodes had useful existing hints such as tags, function names, or machine-role metadata, so a human-driven labeling workflow is both incomplete and fragile.

Observation alone is also expensive. A usable micro-segmentation system needs near-real-time visibility into who talks to whom so it can propose policies, detect drift, and re-segment as deployments evolve. The paper argues that this visibility cost is the main economic obstacle to adoption: vendor pricing already adds 16% to 71% of VM cost, and the authors' first attempts with off-the-shelf analytics engines like Flink and Spark still added more than 10% to VM expenses. So the real problem is not just "find communities in a graph." It is how to infer meaningful workload roles and maintain communication graphs cheaply enough that segmentation can be left on continuously.

## Key Insight

The key claim is that micro-segmentation should be built around inferred deployment roles, not around raw IPs and not around graph structure alone. In a cloud deployment, many endpoints play the same functional role even if they do not have identical neighbors or identical traffic volume. Purely structural clustering therefore misses the semantic regularities administrators care about. ZTS instead treats role inference as a deployment-specialized representation-learning problem: combine graph structure with domain features such as ports, traffic statistics, graph motifs, and whatever partial labels or operator feedback already exist, then learn a compact embedding that makes same-role endpoints cluster together.

The systems counterpart to that insight is equally practical. The paper does not chase richer but costlier telemetry. It argues that cloud-provided connection summaries are already sufficient if the analytics pipeline is built around their actual format and scale. By batching, preprocessing, and then using SQL-based heavy-hitter graph construction instead of general stream processing, ZTS turns "always-on segmentation visibility" into something cheap enough to deploy broadly.

## Design

ZTS has three main pieces: a communication-graph generator, a role-inference trainer, and a policy enforcer. The telemetry source is the flow-summary logging already available in large public clouds. These summaries are typically gathered by programmable NICs or the host networking stack with very low interference on tenant VMs, and they are also harder for compromised guests to tamper with than in-VM agents.

The graph generator is designed around the awkward realities of that telemetry. Providers emit many small nested JSON files, each carrying delimited flow summaries. ZTS therefore splits ingestion into two phases. A scalable pre-processor first parses and batches the raw files. A batch SQL system then aggregates those batches into communication graphs enriched with IPAM and virtual-network metadata. To keep costs bounded, the graph builder collapses remote IPs and ephemeral ports that contribute less than 0.1% of bytes, packets, or connections, and uses CTE-heavy query optimization to avoid expensive intermediate materialization. The goal is explicitly economic: roughly 1000 VMs worth of telemetry processed with only a handful of VMs worth of resources.

On top of the resulting featured IP graph, ZTS defines an adjacency matrix `A` and a node-feature matrix `X`. It first runs PCA separately on both to remove noise and redundancy while preserving 99% of the variance, then concatenates the reduced representations. Those vectors feed an autoencoder regularized by a contrastive loss. The contrastive term uses partial labels `h`, derived from domain rules or operator feedback, to pull known same-role nodes together and push known different-role nodes apart. After training, ZTS takes the encoder output as a node embedding and runs hierarchical agglomerative clustering to infer roles. Those roles become the proposed micro-segments. A policy enforcer maps segment-level policies back to concrete IP-level rules in cloud security controllers and continuously updates them as new endpoints appear or existing roles shift.

## Evaluation

The evaluation is unusually strong on the role-inference side because it uses 11 real first-party and third-party deployments rather than a single toy graph. These datasets range from roughly 100 to 25,000 nodes and up to 165,000 edges in the summarized graphs used for accuracy evaluation. Against Jaccard, SimRank, GAS, and CloudCluster, ZTS achieves an average Adjusted Rand Index of 0.77, versus 0.33, 0.43, 0.39, and 0.34 for the baselines. The only dataset where ZTS is not outright best is Deployment C, where it scores 0.96 and the best baseline scores 0.97 because the ground truth is partially derived from Jaccard itself. That exception actually makes the evaluation more credible.

The policy-authoring experiment is also important because it connects clustering quality to the real use case. On five larger deployments, policies derived from ZTS's inferred roles produce only 0.1% to 2.1% violation rates four days later, while baseline-derived policies range from 2.1% up to 38.4%. That result supports the paper's practical claim: better role inference directly translates into fewer broken or overly permissive segmentation rules.

For telemetry analytics cost, ZTS is compared with a Flink implementation built by the authors. ZTS runs on infrastructure costing $845 per month, while the Flink setup costs $2406 per month. On regional datasets, ZTS processes one hour of telemetry in 78 to 109 seconds versus 344 to 590 seconds for Flink. On a 10x scaled dataset, ZTS finishes in 765 seconds while Flink takes 5748 seconds. The paper's headline summary is therefore fair: 7.5x faster at 35% of the cost, or 21.5x better cost efficiency. What the evaluation does not show is live deployment during active incidents; it is an authoring-and-monitoring paper, not an enforcement-under-attack paper.

## Novelty & Impact

The paper's novelty is not a new packet-filtering mechanism. It is the combination of two ideas that are usually treated separately: role inference for segmentation policy authoring, and a cloud-native telemetry pipeline cheap enough to keep that authoring loop continuously informed. CloudCluster and other graph methods already cluster communication structure, but ZTS argues that segmentation needs embeddings shaped by domain features and human hints, not just topology. At the same time, the graph generator treats cost as a first-class systems constraint rather than an afterthought.

That combination makes the work useful to public-cloud security teams. If the role inference generalizes, ZTS lowers the human burden of creating micro-segments and makes policy maintenance less brittle as deployments change. I expect the paper to be cited both by systems researchers working on security policy synthesis and by practitioners building zero-trust controls over east-west cloud traffic.

## Limitations

ZTS still depends on deployment-specific feature engineering and partial supervision. The method is more flexible than static baselines, but it is not magic: if the available labels, ports, or metadata are poor, the clustering quality will fall. The paper also relies on developer interviews to define ground-truth roles, which is reasonable but inevitably subjective for some services.

The graph generator's cost numbers are compelling, but they are relative to the authors' own Flink design and to cloud-managed SQL infrastructure. The paper does not show whether a hand-tuned custom streaming engine could close that gap, nor does it count all telemetry collection and storage costs inside the main comparison because it treats those as common across solutions. Finally, the policy-violation study explicitly does not claim full automation. Even with good inferred roles, policies still need operator review, and rare or newly emerging communication edges can violate rules built from past traces.

## Related Work

- _Pang et al. (NSDI '22)_ - `CloudCluster` also clusters cloud communication graphs, but it relies on structural similarity alone, whereas `ZTS` injects domain features and partial labels into the embedding itself.
- _Hsieh et al. (NSDI '24)_ - `NetVigil` uses east-west traffic telemetry to detect security anomalies in datacenters; `ZTS` uses similar telemetry earlier in the workflow to define roles and author micro-segmentation policies.
- _Arzani et al. (NSDI '20)_ - `PrivateEye` analyzes cloud telemetry for compromise detection, while `ZTS` focuses on proactive containment by synthesizing segmentation boundaries before incidents occur.
- _Mogul et al. (NSDI '20)_ - `MALT` studies multi-level network topology modeling for operators, whereas `ZTS` reconstructs communication graphs specifically to derive workload roles and security policies.

## My Notes

<!-- empty; left for the human reader -->
