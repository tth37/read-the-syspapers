---
title: "Eva: Cost-Efficient Cloud-Based Cluster Scheduling"
oneline: "Eva packs batch tasks only when their throughput-adjusted reservation price justifies the instance, then decides when full reconfiguration is worth the migration cost."
authors:
  - "Tzu-Tao Chang"
  - "Shivaram Venkataraman"
affiliations:
  - "University of Wisconsin-Madison"
conference: eurosys-2025
category: cloud-scheduling-and-serverless
doi_url: "https://doi.org/10.1145/3689031.3717483"
project_url: "https://pages.cs.wisc.edu/~tau_chang/eva"
tags:
  - scheduling
  - datacenter
  - gpu
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Eva treats cloud batch scheduling as a joint optimization over task packing, instance selection, and reconfiguration timing. It uses throughput-normalized reservation price to decide when a colocated packing is actually cheaper than standalone placement, then chooses between full and partial reconfiguration depending on whether expected long-term savings justify migration overhead. On AWS and on Alibaba-trace simulation, that cuts total cost by 15%-42% relative to common baselines, at the price of modestly higher JCT.

## Problem

Cloud batch clusters differ from fixed-size clusters in one important way: the scheduler controls not just task placement but also which heterogeneous instances exist at all. Prior fixed-cluster schedulers mostly target queueing delay and JCT. In a pay-as-you-go cloud, the harder objective is total provisioning cost without collapsing job throughput. Giving every task its own instance is simple but expensive. Packing tasks is appealing, but cloud instance heterogeneity and interference mean that higher utilization does not automatically imply lower cost.

The paper isolates three reasons existing cloud schedulers miss that objective. First, batch jobs have diverse and weakly correlated GPU, CPU, and RAM demands, so good packings exist only if the scheduler also picks the right instance mix. Second, colocated tasks interfere through shared resources such as LLC, disk I/O, and network bandwidth even when they receive disjoint GPUs and CPUs. In the authors' measurements, pairing two workloads on the same machine can reduce throughput by anywhere from 0% to 36%, so an apparently efficient packing can still increase total cost by stretching runtime. Third, the best cluster shape changes as jobs arrive and finish, but reconfiguration is itself expensive: on AWS, instance acquisition takes 6-83 seconds, setup 140-251 seconds, checkpointing 2-30 seconds, and relaunch 1-160 seconds. A scheduler that never migrates leaves money on the table; one that migrates too aggressively burns money on idle time.

The target use case is a shared enterprise cloud cluster for long-running batch jobs, especially ML training, where multiple teams submit work to the same pool. The scheduler therefore has to keep throughput close to that of a dedicated cluster while making a real dollar-denominated decision about whether sharing and migration are worth it.

## Key Insight

Eva's key insight is that the scheduler needs one common currency for both placement and provisioning, and that currency should already reflect performance loss. The paper borrows reservation price from economics: for a task, reservation price is the hourly cost of the cheapest standalone instance that can run it. If a set of tasks has total reservation price above an instance's hourly cost, then packing them together is economically justified. Once interference enters, the same idea still works if reservation price is scaled by achieved throughput. A task whose throughput drops to 80% under co-location should only be worth 80% of its standalone reservation price.

That turns packing into a disciplined rule instead of a utilization-only heuristic. Eva can sort expensive instance types first, try to fill them with high-value tasks, and reject packings whose throughput-normalized reservation price falls below the actual instance cost. The second insight is temporal: full reconfiguration only matters if its lower provisioning cost lasts long enough to pay back migration overhead. Eva therefore compares a globally re-optimized configuration against a conservative partial update and estimates how long the new configuration is likely to survive before another event forces a rethink.

## Design

Eva's architecture separates control from execution. Users submit containerized jobs with per-task resource vectors; a Profiler can estimate standalone throughput if the user does not provide it. Every scheduling period, set to 5 minutes in the paper's discussion, the Scheduler proposes a cluster configuration, the Provisioner launches or terminates instances, the Executor launches or migrates tasks, and the ThroughputMonitor records how co-location affected progress.

The base algorithm is Full Reconfiguration. Eva sorts instance types in descending hourly cost and repeatedly tries to open an instance of the current type. It greedily adds the unassigned task that maximizes the reservation price of the packed set, stopping when no more tasks fit or when adding another task would lower the throughput-normalized value of the set. The resulting instance is kept only if the packed set's total value is at least the instance's actual hourly price. This is how Eva links task packing and instance choice instead of optimizing them separately. In a micro-benchmark with 200 tasks and 21 instance types, the heuristic achieved 1.01x the ILP's provisioning cost in 378 ms, while the ILP failed to finish within 30 minutes.

Interference awareness sits inside that same loop. Eva maintains a co-location throughput table rather than requiring exhaustive offline profiling. If an exact task set has been seen before, Eva reuses its measured throughput. Otherwise it estimates each task's throughput as the product of pairwise co-location throughputs, initializing unseen pairs to a conservative default of 0.95. That estimate is approximate, but it is cheap enough for online scheduling and lets Eva reject packings whose resource fit is destroyed by contention. For multi-task data-parallel jobs, Eva goes further: if one task straggles, the entire job slows. The ThroughputMonitor therefore attributes slowdowns carefully so it does not pessimistically blame every colocated combination and over-learn interference.

Migration awareness is the paper's second major mechanism. Full Reconfiguration ignores the current placement and may migrate many tasks. Partial Reconfiguration only repacks newly arrived tasks and tasks on instances that are no longer cost-efficient, leaving the rest of the cluster untouched. Eva runs both algorithms each round. It computes each candidate's instantaneous provisioning savings and migration cost, then estimates the expected lifetime of the configuration from event statistics: job arrivals and completions are modeled as a Poisson process, and the chance that an event triggers a future full reconfiguration yields an estimated duration `D_hat = -1 / (lambda ln(1-p))`. Eva picks the configuration whose expected savings over that horizon exceed its migration cost by more. In effect, it pays for aggressive global reshaping only when the savings will survive long enough.

## Evaluation

The implementation is about 5,700 lines of Python and targets AWS EC2, with Dockerized tasks, S3-backed shared storage, gRPC control, and a simulator that reuses measured launch, checkpoint, and interference data. The evaluation uses 21 AWS instance types from the P3, C7i, and R7i families and 10 workloads spanning ResNet18, ViT, GPT2, GraphSAGE, GCN, A3C, Diamond, and OpenFOAM. That mix matters because it exercises exactly the multi-resource heterogeneity the scheduler claims to exploit.

The strongest end-to-end result is on the Alibaba production trace with 6,274 jobs. With original Alibaba job durations, Eva reduces normalized cost to 60% of No-Packing, versus 72% for Stratus, 77% for Synergy, and 78% for Owl. It also packs more aggressively, 2.05 tasks per instance on average, while keeping normalized job throughput at 0.91. The tradeoff is visible in JCT: 10.55 hours for Eva versus 9.18 hours for No-Packing. Under the longer Gavel-style job model, the same pattern holds and Eva drops cost to 58% of No-Packing.

The physical AWS runs show the mechanism survives outside simulation. On the 120-job trace, Eva cuts cost from $536.07 to $452.40 while raising average GPU/CPU/RAM allocation from 67/77/28% to 76/85/41%. On the 32-job trace, Eva achieves $123.03 total cost versus $145.76 for Stratus, $145.80 for Synergy, and $143.75 for Owl. The simulator tracks the physical cluster closely: for Eva, simulated cost differs by only 0.6%.

The ablations support the paper's two main claims. If Eva ignores interference and uses plain reservation price, throughput falls sharply as co-location gets harsher and total cost rises because jobs run longer. With throughput-normalized reservation price, Eva maintains throughput comparable to Owl while keeping the cost benefit of packing. If Eva disables the full-versus-partial ensemble and always uses Full Reconfiguration, cost rises as migration delay increases. Conversely, using only Partial Reconfiguration can raise total cost by up to 8% when multi-GPU jobs become common. The paper also reports that ignoring multi-task-job interdependence can raise cost by up to 13%, and that Full Reconfiguration's runtime grows to 22.06 seconds at 8,000 tasks. Those results make the tradeoffs explicit rather than hand-waved.

## Novelty & Impact

Eva's novelty is not just that it packs tasks or knows about interference; prior systems already do pieces of that. The real contribution is to make instance choice, task placement, interference, and reconfiguration timing commensurable under one cost model. Reservation price gives Eva a simple rule for whether a packing is worth paying for, and the Full-versus-Partial ensemble extends that logic to temporal reconfiguration. That is a cleaner statement of the cloud batch scheduling problem than designs that optimize only utilization or only migration avoidance.

This paper should matter to researchers building cloud batch schedulers and to practitioners running internal ML platforms on public clouds. It gives them a plausible argument for shared enterprise clusters: co-location can be cheaper than per-task isolation, but only if the scheduler prices throughput loss and migration cost explicitly. It also establishes a baseline that later work on spot-aware, multi-cloud, or accelerator-heavy schedulers can build on.

## Limitations

Eva is unapologetically heuristic. Full Reconfiguration is near-optimal in the paper's micro-benchmark, but its runtime still grows roughly quadratically in the number of tasks, reaching 22.06 seconds at 8,000 tasks. The throughput table uses pairwise products and a default value of 0.95 for unseen combinations; that is pragmatic, not a principled performance model, and more exotic interference patterns could mislead the packer.

The deployment model is also narrower than the title might suggest. The experiments use a single AWS region, on-demand instances, and long-running batch jobs. Spot pricing, intercloud brokerage, and stricter latency-sensitive workloads are explicitly left orthogonal. The system also assumes that sharing across teams is acceptable because the jobs belong to one enterprise, so security and stronger multi-tenant isolation concerns are intentionally out of scope.

Finally, the multi-task extension covers one dependency pattern well: data-parallel jobs whose throughput is dragged down by a single straggler. That matters for ML training, but it is not a general model of arbitrary DAG jobs or pipeline-parallel training. If those job structures dominate the cluster, Eva's bookkeeping would need to become richer than the current throughput-attribution rules.

## Related Work

- _Chung et al. (SoCC '18)_ - Stratus minimizes cost in public-cloud container scheduling mainly by avoiding migration, while Eva argues that long-running batch jobs need more aggressive reconfiguration when the savings amortize the overhead.
- _Mohan et al. (OSDI '22)_ - Synergy packs DNN jobs to cut fragmentation in a fixed-size multi-tenant cluster, whereas Eva treats instance provisioning itself as part of the optimization in a pay-as-you-go cloud.
- _Tian et al. (SoCC '22)_ - Owl uses pre-profiled interference information to guide resource-efficient FaaS scheduling, while Eva learns co-location throughput online and plugs it into a cluster-wide cost objective.
- _Yang et al. (NSDI '23)_ - SkyPilot optimizes which cloud and instance market to rent from, whereas Eva treats procurement as orthogonal and focuses on packing plus reconfiguration inside one cloud-based cluster.

## My Notes

<!-- empty; left for the human reader -->
