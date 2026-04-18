---
title: "LESS is More for I/O-Efficient Repairs in Erasure-Coded Storage"
oneline: "LESS layers a few RS-coded extended sub-stripes so repairs access far less data than RS without Clay's explosion in I/O seeks."
authors:
  - "Keyun Cheng"
  - "Guodong Li"
  - "Xiaolu Li"
  - "Sihuang Hu"
  - "Patrick P. C. Lee"
affiliations:
  - "The Chinese University of Hong Kong"
  - "Shandong University"
  - "Huazhong University of Science and Technology"
conference: fast-2026
category: reliability-and-integrity
code_url: "https://github.com/adslabcuhk/less"
tags:
  - storage
  - fault-tolerance
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`LESS` layers a small number of extended `RS`-coded sub-stripes across each stripe, so one failed block can usually be rebuilt inside one extended sub-stripe instead of by reading `k` whole blocks. It gives up a little repair-I/O optimality versus `Clay`, but keeps sub-packetization linear and seek counts low enough to win in real wall-clock repairs.

## Problem

The paper starts from a systems fact: in modern erasure-coded storage, repair latency is often limited by local I/O, not by network bandwidth or coding arithmetic. A conventional `(n,k)` `RS` repair reads `k` full helper blocks, so both accessed data and wall-clock time scale badly.

Existing repair-friendly codes each leave a gap. `Clay` minimizes repair I/O for general `MSR` settings, but its exponential sub-packetization causes many scattered reads. `LRC`-style schemes cut repair work by adding redundancy and giving up `MDS` optimality. Other `MDS` variants such as `Hitchhiker`, `HashTag`, and `ET` improve only some repairs or still leave too much I/O overhead. The paper's problem statement is therefore two-dimensional: a practical code has to reduce bytes read and the number of I/O seeks at the same time.

## Key Insight

The key claim is that near-optimal repair I/O plus low seek counts is better than byte-optimal repair with pathological fragmentation. `LESS` achieves that by layering `alpha + 1` overlapping extended sub-stripes on top of an `(n,k,alpha)` stripe, with `alpha` kept small and configurable between `2` and `n-k`.

That structure guarantees that every failed block can be repaired inside one extended sub-stripe that is itself an `RS`-coded object. The repair path therefore stays local to one coding view, while the overall construction still preserves the deployment-friendly properties of `RS`: `MDS`, systematic form, and general `(n,k)` parameters.

## Design

`LESS` first partitions the `n` blocks into `alpha + 1` nearly equal block groups. It then builds `alpha + 1` extended sub-stripes. For each `z <= alpha`, `X_z` contains all sub-blocks in group `G_z` plus all sub-blocks at sub-stripe position `z` across the stripe; a final `X_{alpha+1}` contains the last group's sub-blocks plus a diagonal set whose group index matches sub-stripe index. Each sub-block appears in exactly two extended sub-stripes.

The code chooses distinct Vandermonde coefficients so every extended sub-stripe satisfies an `RS` parity equation and tolerates `n-k` sub-block failures. Only the first `alpha` extended sub-stripes are explicitly encoded; the last one is implied by the others. In the paper's `(6,4,2)` example, one failed block is repaired from six helper sub-blocks rather than four full `RS` blocks, a `25%` I/O reduction.

Repair follows the grouping structure. If block `B_i` in group `G_z` fails, `LESS` repairs it inside `X_z`, reading same-group helper sub-blocks first because they are contiguous. That yields repair I/O of roughly `k + (alpha-1)|G_z|` sub-blocks and exactly `k + alpha - 1` seeks. Since the groups differ in size by at most one, data and parity blocks see nearly the same benefit. `LESS` also helps some multi-block failures: it can jointly repair up to `floor((n-k)/alpha)` failed blocks if they lie in the same group; otherwise it falls back to conventional repair.

## Evaluation

The analysis section makes the tradeoff concrete. For the default `(14,10)` setting, `LESS (alpha=4)` averages `4.64` blocks of repair I/O with `13` seeks. `RS` needs `10` blocks, `Hitchhiker` `7.50`, `HashTag-4` `6.04`, and `ET-4` `5.86`. `Clay` still wins on pure repair I/O at `3.25` blocks, but it explodes to `286` average seeks. On a wide stripe such as `(124,120)`, `LESS (alpha=4)` reduces repair I/O from `120` blocks for `RS` to `48.6` while keeping seeks at `123` versus `120` for `RS`. That is the paper's point in one line: `LESS` gives up a little byte optimality to avoid request amplification.

The HDFS/OpenEC prototype shows the same effect end to end. The authors add `8.7 KLoC` of C++ to `OpenEC`, run on a 15-machine cluster with quad-core `i5-7500` hosts, `16 GiB` RAM, `7200 RPM` SATA HDDs, and configurable `1-10 Gbps` networking, and compare against `RS`, `Clay`, `Hitchhiker`, `HashTag`, and `ET`. On `(14,10)`, `LESS (alpha=4)` reduces single-block repair time by `50.8%` versus `RS`, `35.9%` versus `Hitchhiker`, `21.5%` versus `HashTag-4` and `ET-4`, and `33.9%` versus `Clay`; full-node recovery drops by `48.3%`, `34.3%`, `17.8%`, `19.4%`, and `36.6%`, respectively.

The sensitivity studies support the same interpretation. At `10 Gbps`, where network cost matters less, `LESS (alpha=4)` beats `Clay` by `83.3%` on single-block repair time because `Clay`'s seek overhead dominates. At `128 KiB` packets, `LESS` also stays ahead because its sub-packetization remains small. The main cost is encoding throughput: at `256 KiB`, `RS` reaches `2.8 GiB/s` while `LESS (alpha=4)` reaches `1.6 GiB/s`. For the paper's HDD-bound setting, that cost appears acceptable and does not overturn the repair-time gains.

## Novelty & Impact

`LESS` is not just a better implementation of an existing code. It is a new code family that explicitly treats seek count as a first-class repair metric while keeping the practical properties of `RS`. Compared with `Clay`, its novelty is accepting slightly higher repair I/O to avoid exponential sub-packetization and fragmented access; compared with `LRC`, it preserves `MDS` optimality instead of adding redundancy.

That makes the paper useful to both coding theorists and practitioners. It argues, convincingly, that wall-clock repair performance can improve even when a construction is not byte-optimal in the narrow coding-theory sense.

## Limitations

`LESS` is a tradeoff, not a free lunch. It does not beat `Clay` on pure repair I/O, so its advantage may shrink when random access is cheap and the network dominates. Multi-block repair gains are also conditional: they appear only when failed blocks land in the same block group; otherwise the system reverts to conventional repair.

The evaluation is also scoped to `HDFS/OpenEC` and common parameter ranges such as `(14,10)` with parity counts up to `4`. The paper proves that suitable coefficients exist for sufficiently large fields and tabulates feasible primitive elements for common cases, but it does not deeply explore much larger parameter ranges. Lower encoding throughput than `RS` could matter more on CPU-rich, SSD-heavy systems than it does on the authors' HDD cluster.

## Related Work

- _Vajha et al. (FAST '18)_ - `Clay` codes minimize repair I/O for general `MSR` settings, while `LESS` deliberately spends a bit more repair I/O to collapse sub-packetization and seek overhead.
- _Rashmi et al. (SIGCOMM '14)_ - `Hitchhiker` reduces repair cost with piggybacking over two `RS` sub-stripes, but it mainly helps data-block repairs rather than balancing data and parity repairs.
- _Huang et al. (ATC '12)_ - `Azure-LRC` improves locality for single-block repairs, whereas `LESS` stays `MDS` and systematic instead of adding extra redundancy for local recovery.
- _Tang et al. (INFOCOM '23)_ - `Elastic Transformation` also exposes a configurable repair tradeoff, but `LESS` uses layered extended sub-stripes to achieve lower repair I/O with similarly small `alpha`.

## My Notes

<!-- empty; left for the human reader -->
