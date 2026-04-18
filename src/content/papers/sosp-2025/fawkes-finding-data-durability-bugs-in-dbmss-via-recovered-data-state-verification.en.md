---
title: "Fawkes: Finding Data Durability Bugs in DBMSs via Recovered Data State Verification"
oneline: "Fawkes crashes DBMSs at filesystem and kernel interaction points, then checks recovered state against a checkpoint-rectified graph to catch durability bugs other testers miss."
authors:
  - "Zhiyong Wu"
  - "Jie Liang"
  - "Jingzhou Fu"
  - "Wenqian Deng"
  - "Yu Jiang"
affiliations:
  - "KLISS, BNRist, School of Software, Tsinghua University, China"
  - "School of Software, Beihang University, China"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764841"
tags:
  - databases
  - storage
  - crash-consistency
  - fuzzing
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Fawkes tests DBMS durability by crashing the system while SQL execution is inside filesystem or kernel-facing code, then checking whether recovery reconstructs the committed state that should survive the latest checkpoint. The key move is an oracle based on checkpoint-rectified recovered state, which lets it catch data loss and inconsistency bugs that availability-oriented fault injectors usually miss.

## Problem

The paper targets data durability bugs (DDBs): implementation errors that let committed SQL effects disappear, reappear incorrectly, corrupt logs, or leave the DBMS unrecoverable after a crash. From 43 real DDBs across PostgreSQL, MySQL, IoTDB, and TDengine, the authors find four dominant manifestations after recovery: data loss, data inconsistency, log corruption, and system unavailability. Most root causes are in crash recovery or data flushing logic, and 86% of the studied bugs are triggered when SQL execution is inside filesystem or other kernel-level calls.

That combination defeats existing testing. Manual durability tests are expensive and shallow. Generic fault injectors such as Jepsen, Mallory, CrashFuzz, and CrashTuner inject faults too coarsely or check the wrong thing: they mostly ask whether the service comes back or whether replicas stay consistent. For a single-node DBMS, that is not enough. The difficult bugs sit in narrow execution windows and manifest as silently wrong recovered state, not obvious downtime.

## Key Insight

Fawkes treats DDB detection as two coupled problems: crash the DBMS where durability logic actually runs, and verify the state recovery was supposed to reconstruct. The first part follows the paper's empirical finding that filesystem and kernel interaction points are where most relevant failures become visible. The second part uses the latest checkpoint plus recovery logs to compute the state that should exist after restart. That changes the oracle from "did recovery finish?" to "did recovery rebuild the right committed state?".

## Design

Fawkes has three main pieces. First, context-aware fault injection analyzes the DBMS call graph during compilation and marks code regions whose call chains reach glibc, filesystem, JVM, or other OS-facing libraries. These regions become fault-injection sites, tracked in a fault location bitmap. At runtime, Fawkes hooks library calls such as `open`, `read`, `write`, and `malloc`, records which site is active, and injects one of seven fault classes drawn from the bug study, including power failure, memory exhaustion, process kill, kernel crash, disk I/O failure, and software exception.

Second, functionality-guided fault triggering decides when to fire those faults. Fawkes maintains a fault-functionality table that maps source files to the SQL grammar features most likely to reach their durability-critical paths. If a file still has poorly covered sites, the workload generator biases future schemas and queries toward the corresponding SQL features. This is more specific than generic coverage guidance: the goal is not maximal branch coverage everywhere, but deeper exploration of crash-sensitive durability paths.

Third, checkpoint-based data graph verification provides the oracle. Fawkes does not snapshot the whole database; instead it maintains a compact graph of metadata such as tables, columns, row counts, indexes, and constraints. After a crash, it reads recovery logs, finds the latest checkpoint, rolls the graph back to that point, then rectifies it with the committed SQL statements that recovery should replay. Uncommitted post-checkpoint transactions are removed. Once the DBMS restarts, Fawkes checks recovery logs for system unavailability or log corruption, compares recovered metadata with the rectified graph, and checks whether committed rows and updates after the checkpoint actually survived.

## Evaluation

The implementation spans roughly 10k lines of C++ plus Rust, C, Java, and grammar support. On eight DBMSs, two weeks of testing found 48 previously unknown DDBs; 16 were fixed by paper time and 8 received CVEs. In the main 72-hour comparison, Fawkes covered 320,848 branches and found 29 DDBs, versus 174,604/2 for Jepsen, 216,985/4 for CrashFuzz, 218,135/6 for Mallory, and 188,810/1 for CrashTuner. The rediscovery experiment is also strong: on historical buggy versions of four DBMSs, Fawkes rediscovered 39 of the 43 studied DDBs within two weeks, including 34 in the first week.

The ablations explain where that gain comes from. Moving from random-style injection to context-aware injection raises bug count from 2 to 5; adding functionality-guided triggering raises it to 8; enabling data-graph verification raises it to 29, even though it reduces executed test cases. That is credible evidence that the oracle matters as much as the triggering strategy. The main caveat is that the baselines were not designed for single-node recovered-state checking, so the comparison is not a pure engineering contest; it is evidence that Fawkes is solving a more specific problem.

## Novelty & Impact

The novelty is not a new SQL fuzzer or a new crash model in isolation. It is the combination of targeted durability-path fault placement, SQL-feature-guided exploration, and an oracle that reasons about checkpoint-consistent recovered state instead of mere availability. That makes the paper useful for DBMS developers working on WAL, flushing, checkpoints, and replay logic, and it makes a broader systems point: crash testing gets much more valuable once the checker models what recovery should preserve.

## Limitations

The scope is narrower than the title may suggest. The study explicitly focuses on fault-induced crash bugs, not durability failures caused by optimizer logic or other non-fault scenarios. The data graph is intentionally compact, so the oracle is strongest for metadata, row presence, and tracked updates rather than arbitrary semantic invariants over the full database. The system is also costly to engineer and run: it needs source-level analysis, DBMS-specific grammar adaptation, and custom library hooks, and continuous fault injection cuts executed test cases substantially. The paper also notes that tuning choices such as checkpoint frequency can affect throughput and thus bug-finding rate.

## Related Work

- _Zheng et al. (OSDI '14)_ - Torturing Databases for Fun and Profit simulates power failures to expose ACID violations, whereas Fawkes adds targeted fault placement and a checkpoint-based recovered-state oracle for modern DBMS durability logic.
- _Pillai et al. (OSDI '14)_ - ALICE studies crash-consistency testing for filesystem applications, while Fawkes moves the oracle up into DBMS recovery semantics and SQL-visible state.
- _Lu et al. (SOSP '19)_ - CrashTuner uses meta-information analysis to find crash-recovery bugs in cloud systems, but Fawkes specializes this idea to DBMS durability paths and verifies recovered data state directly.
- _Meng et al. (CCS '23)_ - Mallory greybox-fuzzes distributed systems, whereas Fawkes targets single-node DBMS durability bugs whose symptoms are often recovered-state corruption rather than replica divergence.

## My Notes

<!-- empty; left for the human reader -->
