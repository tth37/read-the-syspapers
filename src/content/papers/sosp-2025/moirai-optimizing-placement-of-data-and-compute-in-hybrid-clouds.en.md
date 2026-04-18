---
title: "Moirai: Optimizing Placement of Data and Compute in Hybrid Clouds"
oneline: "Moirai co-optimizes table replication and job routing in hybrid clouds, cutting weekly cost by up to 98% over prior placements while staying under bandwidth limits."
authors:
  - "Ziyue Qiu"
  - "Hojin Park"
  - "Jing Zhao"
  - "Yukai Wang"
  - "Arnav Balyan"
  - "Gurmeet Singh"
  - "Yangjun Zhang"
  - "Suqiang (Jack) Song"
  - "Gregory R. Ganger"
  - "George Amvrosiadis"
affiliations:
  - "Carnegie Mellon University"
  - "Uber"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764802"
project_url: "https://www.pdl.cmu.edu/Moirai/index.shtml"
tags:
  - datacenter
  - scheduling
  - storage
  - networking
category: datacenter-scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Moirai treats hybrid-cloud placement as a joint optimization over where tables live and where jobs run, rather than solving data replication and job routing separately. It builds a job-table dependency graph from production access logs, solves a cost model that includes cloud storage, cloud egress, and migration-induced data movement, and uses lightweight history-based routing for newly seen jobs. On four months of Uber Presto and Spark traces, it cuts weekly deployment cost by over 97% relative to Yugong while keeping weekly cross-site traffic under the target limit.

## Problem

Hybrid clouds are attractive because organizations want to keep some infrastructure on-premises while still using cloud elasticity, but data analytics workloads make this expensive. A job may run on one side and need tables on the other, so every placement mistake turns into cloud egress charges, dedicated-link pressure, or duplicated storage. The paper argues that early approaches sit at two bad extremes: random partitioning with no replication keeps storage cheap but makes remote reads and writes explode, while broad replication suppresses remote traffic but doubles down on storage cost.

The harder problem is that modern data lakes do not follow neat organizational boundaries. In Uber's four-month trace, 66.7 million Presto queries and Spark jobs access 13.3 EB from a 300 PB corpus, and the dependency structure is highly entangled: 85% of jobs and 77% of tables sit in the largest weakly connected component. Only 10% of read traffic stays within a project boundary, so project-level grouping, which Yugong relies on, is too coarse for this environment. At the same time, the workload is only moderately repetitive: recurring jobs account for 56% of traffic volume, meaning any static plan for known jobs will still leave a large tail of new jobs that must be routed online.

## Key Insight

The paper's central claim is that hybrid-cloud cost can be reduced only if data placement and compute placement are optimized together at the granularity of actual job-table dependencies, but that this is tractable only after exploiting workload structure to shrink the search space. In other words, the right abstraction is not "project" or "cluster" but a bipartite graph connecting jobs to the tables they read and write.

What makes this workable is that most of the optimizer's leverage comes from a small amount of carefully chosen structure. Recurrent jobs can be collapsed by query template, cold tables can be grouped without losing accuracy, and a tiny fraction of widely shared tables can be pre-selected for replication to break many dependency edges. For the remaining uncertainty, especially newly seen jobs, approximate routing based on recent per-table access volumes is good enough to stay close to an oracle.

## Design

Moirai has three main components. The `Spinner` ingests access logs and builds a weighted bipartite graph whose job nodes carry compute demand, whose table nodes carry size, and whose edges carry bytes read and written. The `Allotter` solves a mixed-integer program over that graph. Binary variables choose whether each job runs on-premises or in the cloud and whether each table is present on-premises, in the cloud, or both. The objective combines cloud storage cost, cloud egress from remote reads and writes, and the cost of moving data when placements are updated between optimization rounds. Capacity constraints bound on-prem and cloud compute, on-prem storage, and cross-site network traffic, but cloud compute reservations and dedicated links are treated as prepaid constraints rather than optimization variables.

Two reductions make the optimization practical. First, recurring jobs with the same canonicalized template are merged, and tables untouched in the previous window are grouped by database name. On Uber's weekly windows, that reduces the graph from more than 4 million jobs and more than 1 million tables to 356K jobs and 134K tables. Second, Moirai pre-selects a tiny set of tables for replication before solving the MIP. The winning heuristic is `Job Access Density`, which favors small tables touched by many jobs; replicating only 0.2% of total data removes enough edges to cut optimization time from 147 hours to about 2 hours on average.

Online routing handles the jobs the optimizer cannot pre-place. For recurring jobs, the scheduler follows the optimization output directly. For newly seen jobs, `Size Predict` examines the tables the job will touch and predicts per-table read size using the previous window's mean access volume, then routes the job to the side with the larger predicted local footprint. The design assumes jobs are stateless enough to run on either side and that each table is moved as an atomic unit, even if a job touches only part of it.

## Evaluation

The evaluation uses four months of Uber production traces from Presto and Spark. The authors compare Moirai against random partitioning without replication, Volley-style placement, recency-based replication, a traffic-aware replication heuristic, and a reimplementation of Yugong. They model a hybrid deployment with a dedicated 800 Gbps link and set Moirai's weekly traffic target to 11.5 PB, which is one-fifth of the peak to leave room for burstiness.

The headline result is that Moirai is not just cheaper than Yugong; it is cheaper by roughly an order of magnitude. Under the hardest 50% on-prem / 50% cloud split, Moirai reduces weekly cost from `$393K` for Yugong to `$12K`, and weekly traffic from `18.2 PB` to `751 TB`. Across the three tested splits, Moirai cuts cost by 97-98% relative to Yugong and lowers traffic by 96-98%. Compared with the strongest replication-heavy heuristic, `RepTop2.5%`, it is still about 94-95% cheaper because it jointly places the remaining non-replicated tables and the jobs that use them rather than treating replication as the whole solution.

The ablations explain where those gains come from. An intermediate `Moi-JobDist` variant that keeps Moirai's job distribution and first-window replication plan but places the remaining tables using Volley-style logic already beats every non-Moirai baseline, showing that joint job-and-data placement is the dominant improvement. Then 0.2% pre-replication is the best operating point: 0.1% leaves too much egress on the table, while 0.4% adds storage with little additional benefit.

For new jobs, `Size Predict` lowers egress cost by 90.3-99.8% relative to an underutilization-based router and stays generally within about 2x of the unrealizable `Size Oracular` lower bound. During phased migration, Moirai's redistribution-aware objective drives near-zero extra egress, whereas a movement-unaware optimizer can create about 150 PB of unnecessary egress and roughly 450 PB of ingress by the end of decommissioning.

## Novelty & Impact

Moirai's novelty is not a new solver in isolation; it is the combination of a hybrid-cloud cost model, a fine-grained job-table formulation, and the concrete reductions that make that formulation solvable on real traces. Yugong already showed that joint job-and-data placement matters, but it depended on project boundaries and a private-cloud objective. Moirai adapts the problem to hybrid clouds, where cloud egress, storage elasticity, and migration churn dominate the economics.

This paper will matter to teams building hybrid data lakes, migration planners, and schedulers that need to account for data gravity rather than only compute balance. It is both a systems paper and a workload paper: the first large-scale hybrid-cloud analytics trace study is part of the contribution, because the design choices are explicitly justified by the observed graph structure and recurrence properties.

## Limitations

The strongest limitation is that the evaluation is trace-driven rather than a full production deployment. Section 6 describes deployment components such as HiCam, HiveSync, and control-plane routing hooks, but the optimizer itself is not yet shown operating end-to-end in a live hybrid cloud. That means the reported savings depend on the fidelity of the trace replay and the cost model.

The modeling assumptions are also narrow. Moirai treats cloud compute and dedicated links as prepaid constraints rather than optimization variables, assumes jobs are runnable on either side, and moves tables atomically rather than at partition granularity. The current design targets a single cloud region plus one on-premises site, uses eventual-consistency replication, and optimizes for throughput rather than per-job deadlines. Even with the 0.2% pre-replication trick, solve times are still measured in hours, so this is a periodic control loop rather than a reactive scheduler. Finally, 44% of traffic comes from newly seen jobs, so Moirai still depends on a heuristic routing policy for a large part of the workload.

## Related Work

- _Huang et al. (VLDB '19)_ - Yugong also co-optimizes jobs and data, but it relies on project-level placement for private clouds; Moirai replaces those administrative groupings with table-level dependencies and a hybrid-cloud cost model.
- _Agarwal et al. (NSDI '10)_ - Volley places data near where accesses originate while assuming compute placement is fixed; Moirai additionally routes jobs and uses selective replication to reshape the graph.
- _Choudhury et al. (OSDI '24)_ - MAST jointly places training jobs and data across geo-distributed datacenters, but it targets ML training, GPU utilization, and preemption rather than analytics workloads in a hybrid cloud.
- _Park et al. (SOSP '24)_ - Macaron reduces cross-cloud or cross-region cost with caching, whereas Moirai addresses the longer-horizon placement problem of which data to replicate and where jobs should execute.

## My Notes

<!-- empty; left for the human reader -->
