---
title: "Pesto: Cooking up High Performance BFT Queries"
oneline: "Pesto executes SQL over leaderless BFT replicas by synchronizing only query-relevant snapshots and validating conflicts with predicates instead of globally ordering every request."
authors:
  - "Florian Suri-Payer"
  - "Neil Giridharan"
  - "Liam Arzola"
  - "Shir Cohen"
  - "Lorenzo Alvisi"
  - "Natacha Crooks"
affiliations:
  - "Cornell University"
  - "UC Berkeley"
  - "Cornell University / UC San Diego"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764799"
code_url: "https://github.com/fsuri/Pequin-Artifact"
tags:
  - databases
  - transactions
  - consensus
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Pesto extends Basil's order-free BFT design from a key-value store to a full SQL database. It gets there by making replicas agree only on the rows relevant to a query, then validating concurrent transactions with predicate-aware checks rather than by globally ordering every request.

## Problem

The paper starts from a real gap in the BFT database landscape. If one layers a relational database over PBFT-, HotStuff-, or BFT-SMaRt-style consensus, every read, write, and commit has to pay for total order. That preserves correctness, but it destroys parallelism, stretches interactive transactions across several round trips, and makes sharding expensive because two-phase commit now sits on top of replicated shards. The result is a system that is safe but too slow for ordinary SQL applications.

The obvious alternative is Basil's style of integrated, client-driven, order-free BFT execution. Basil already shows that one can combine replication, optimistic concurrency control, and commit coordination without totally ordering requests. The catch is that Basil only exposes a key-value interface. Reads are done client-side, one key at a time, which makes joins, scans, and aggregations either awkward or outright inefficient. The join example in the paper is intentionally brutal: if the client must reconstruct a join over million-row tables using point reads, the communication and intermediate-result cost dominates.

Supporting arbitrary SQL queries introduces two harder problems. First, once execution moves server-side, the client must know that the result is valid, fresh, and correctly computed even though replicas are intentionally allowed to diverge. Second, vanilla optimistic concurrency control behaves badly on range queries because it effectively has to protect huge logical key ranges against phantom conflicts. In a Byzantine setting, lock-based fixes are even less attractive, because a malicious client can simply refuse to release locks. Pesto therefore needs a way to keep Basil's low-latency, leaderless execution model while still offering serializable, SQL-compatible queries under Byzantine faults.

## Key Insight

Pesto's central idea is that a query does not need the entire database to be consistent across replicas; it only needs the subset of rows that can affect that query's result to line up. If replicas already agree on those rows, the client can complete the query immediately. If they do not, the client can synchronize just the relevant transaction state on demand and ask replicas to re-execute on that shared snapshot.

The same "only what matters" principle drives concurrency control. Pesto does not treat every concurrent write to a scanned table as a conflict. Instead, it asks whether that write changes the predicate-defined active read set of the query. If not, aborting the transaction is unnecessary. This semantic narrowing is what lets Pesto extend Basil to SQL without falling back to globally ordered execution.

## Design

Pesto inherits Basil's basic posture: clients orchestrate transaction execution, replicas use inconsistent replication, and the system avoids a leader and avoids total order. Transactions begin with a client-generated timestamp that fixes serialization order. Writes are buffered locally until commit, but SQL updates and deletes often depend on predicates, so Pesto first issues a reconnaissance query to fetch candidate rows, then computes the actual row updates and stores them in the transaction's write set.

Point reads are the easy case. If a query names a single primary key, the client sends it to a quorum, collects committed or prepared versions, and picks the freshest valid one. Prepared versions are allowed, but then the reader records a dependency on the writer so commit cannot succeed unless that writer eventually commits first.

The distinctive mechanism is the range-read protocol. A client sends the SQL query to at least `3f+1` replicas. Each replica executes the query on versions no newer than the reader's timestamp and returns four things: the result, the active read set, any dependencies on prepared writers, and a snapshot vote consisting of transaction ids associated with the versions it used. If the client sees `f+1` matching results with matching read metadata, it is done. If not, it takes the snapshot path: it merges only transaction ids that appear in `f+1` votes from a `2f+1`-reply set, proposes that snapshot back to replicas, and replicas fetch any missing transactions from peers before re-executing the query on the synchronized state. The important detail is that synchronization is on transaction ids for relevant rows, not on full replica state.

Commit combines Basil's client-driven voting with a new `SemanticCC` check. Replicas record not only the rows a query read, but also the query predicates that determined which rows were active. Validation then checks freshness and completeness only for writes that can change those predicates' results. To keep that check finite, Pesto tracks a table-version summary and enforces monotonic writes with a grace window, so validation only needs to inspect a bounded interval of concurrent writes rather than replaying an entire table history. Replicas tentatively expose prepared writes, and the client aggregates per-shard votes into a Basil-style two-phase decision. In the common case the decision is durable in one round trip; otherwise Pesto logs the decision on one shard before asynchronous writeback.

One architectural choice matters for the paper's threat model: Pesto uses `5f+1` replicas, not `3f+1`, because Byzantine independence requires that no Byzantine client plus a colluding leader can unilaterally force outcomes. That extra replication cost is a deliberate trade.

## Evaluation

The implementation is a C/C++ prototype built from Basil and Peloton, using in-memory execution on CloudLab with `f = 1`. The evaluation is strong because it does not rely on a single friendly workload. TPC-C stresses high-contention transactional behavior with many point reads; AuctionMark and SEATS stress joins and range-heavy SQL; a YCSB-derived microbenchmark stresses the snapshot path, inconsistency, and replica failure cases directly.

On TPC-C, Pesto reaches `1784 tx/s`, essentially matching unreplicated Peloton (`1777 tx/s`) and Postgres (`1781 tx/s`), while beating the SMR baselines by up to `2.3x` in throughput and cutting latency by `2.7x` to `3.9x`. That result matters because the Peloton-SMR baselines are actually configured generously: the paper relaxes deterministic replicated execution and lets only a primary reply, so the comparison is not stacked in Pesto's favor. The reason Pesto stays competitive is that it preserves Basil's latency profile: writes are buffered, `99.9%` of range reads complete in one round trip on TPC-C, and `97%` of commits use the fast path.

AuctionMark and SEATS show the same qualitative pattern, though with smaller throughput gains because range reads require larger quorums and the systems become CPU-bound. Pesto still stays within `1.36x` and `1.22x` of unreplicated Peloton throughput, and it cuts latency against the SMR baselines by roughly `3x` to `5x`. Against Basil's simpler key-value interface, Pesto comes within `1.23x` of Basil's reported three-shard TPC-C throughput despite paying for SQL parsing, planning, and execution. More importantly, the range-read protocol delivers the functionality Basil lacks: scan latency drops by `16.6x` at a range of 10,000 rows, and by `110x` when only 1 in 100 scanned rows matches the predicate.

The stress tests expose the real cost of inconsistency rather than hiding it. Forcing every query onto the snapshot path raises latency by `1.38x` and cuts throughput by about `9%` on the uniform workload; artificially omitting writes at one third of replicas reduces throughput by only about `5%`. Under a highly contended Zipfian workload, the same mechanisms expand conflict windows and throughput falls by `32%` to `48%`. Replica crashes are comparatively benign: because the protocol is leaderless and client-driven, failures mostly hurt the fast path rather than halting progress.

## Novelty & Impact

The closest prior work is _Basil_, and Pesto's novelty is not merely "Basil, but with SQL parsing." The paper adds two mechanisms Basil did not need: query-specific snapshot synchronization so server-side execution can still return BFT-verifiable results, and semantic concurrency control so expressive queries do not degenerate into table-wide conflicts. Relative to layered SMR designs, Pesto replaces global request ordering with local optimistic validation plus on-demand rendezvous. Relative to systems like FalconDB or ChainifyDB, it targets interactive SQL transactions rather than stored procedures or single-replica query offload.

That makes the paper significant for two audiences. Systems builders working on decentralized or mutually distrustful data services get a concrete blueprint for making SQL fit a BFT setting without accepting consensus-level latency on every operation. Database researchers get a useful example of semantic conflict tracking used not as a local optimization inside one DBMS, but as the key that preserves correctness in a leaderless Byzantine protocol. This is best understood as a new mechanism and architecture paper, not a measurement study.

## Limitations

The most obvious limitation is replication cost. Pesto needs `5f+1` replicas to achieve Byzantine independence, so it is more expensive than leader-based `3f+1` BFT designs before one even counts cryptography and quorum traffic. The design also makes a deliberate optimism bet: if replicas diverge or contention is high, queries may need snapshot retries and re-execution, and the Zipfian stress tests show that this can materially reduce throughput.

`SemanticCC` is also conservative. It uses filter predicates and table versions as compact summaries of what a query "depends on," which is much cheaper than tracking every possible phantom-producing row, but it can still abort writers that happen to satisfy the predicate even when the final end-to-end query result would not have changed. The write-monotonicity rule plus grace window is another pragmatic compromise: it bounds validation cost, but "late" writers can still lose even when their work is logically harmless.

Finally, the paper is strongest on in-memory OLTP-style deployments and weaker on fully general distributed SQL execution. The range-read protocol is presented assuming the query itself can be satisfied by one shard, even though transactions may span multiple shards, and the evaluation uses `f = 1` on a single-region CloudLab setup. The paper does not specify how the design behaves with disk-backed storage, WAN-scale deployments, or larger fault thresholds.

## Related Work

- _Suri-Payer et al. (SOSP '21)_ - Basil is Pesto's direct ancestor: it already showed that BFT transactions can be client-driven and order-free, but it stopped at a key-value interface rather than full SQL query execution.
- _Peng et al. (SIGMOD '20)_ - FalconDB supports limited SQL-like querying with authenticated structures and ordered commits, whereas Pesto keeps interactive transactions and avoids globally ordering normal execution.
- _Androulaki et al. (EuroSys '18)_ - Hyperledger Fabric follows an execute-order-validate pipeline around chaincode, while Pesto aims to look like a relational database with ordinary SQL transactions.
- _Schuhknecht et al. (CIDR '21)_ - ChainifyDB supports a general SQL interface over blockchain-backed databases, but Pesto pushes replication, concurrency control, and query-specific synchronization into one BFT relational engine instead of layering around a global order.

## My Notes

<!-- empty; left for the human reader -->
