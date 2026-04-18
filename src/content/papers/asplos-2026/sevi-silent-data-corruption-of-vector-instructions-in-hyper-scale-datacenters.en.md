---
title: "SEVI: Silent Data Corruption of Vector Instructions in Hyper-Scale Datacenters"
oneline: "Measures vector-instruction SDCs across hyperscale CPUs and uses matmul-integrated ABFT canaries to catch most faulty machines with about 1.35% overhead."
authors:
  - "Yixuan Mei"
  - "Shreya Varshini"
  - "Harish Dixit"
  - "Sriram Sankar"
  - "K. V. Rashmi"
affiliations:
  - "Carnegie Mellon University, Pittsburgh, PA, USA"
  - "Meta Platforms Inc., Menlo Park, CA, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790217"
code_url: "https://github.com/Thesys-lab/SEVI-ASPLOS26"
tags:
  - hardware
  - datacenter
  - fault-tolerance
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

SEVI measures silent data corruption in vector instructions on a hyperscale production fleet, then turns matrix multiplication into a low-overhead detector for those faults. The paper shows that FMA instructions dominate the observed failures, and that an ABFT checksum catches `88%-100%` of faulty machines with about `1.35%` overhead on `1024 x 1024` matrices.

## Problem

The paper starts from a reliability gap that is easy to miss in ordinary testing. Silent data corruption does not crash the program or raise an exception; it quietly returns a wrong value and lets the error propagate. On one machine the event rate looks negligible, but at hyperscale the aggregate rate matters operationally. Prior work had reported fleet-level incidents and simulator-based fault studies, but not a systematic picture of which vector instructions fail in production, how those faults manifest, or how to detect them without paying large amounts of dedicated test time.

Vector instructions are the right target because they dominate important workloads and appear unusually vulnerable. The paper cites them as roughly `80%` of compute instructions in AI workloads and about `50%` of residency in several hyperscale services. That sharpens the problem into three questions: which vector instructions are the real risk, what structure do their failures have, and can the fleet reuse a common production kernel as a cheap detector instead of relying only on long specialized tests?

## Key Insight

The central claim is that vector-instruction SDC is concentrated enough to support targeted detection. In SEVI's data, FMA instructions account for most observed corruption, the fault usually stays within one physical core, and `98.5%` of incidents affect only one vector lane. Matrix multiplication then becomes a useful bridge from instruction-level behavior to application-level detection because it is both FMA-heavy and widely deployed.

The second insight is that the detector does not need full replication. For `A x B`, the sum of the output matrix should equal the dot product of a row-checksum vector of `A` and a column-checksum vector of `B`. That invariant is cheap to compute compared with the matmul itself, but an SDC is unlikely to corrupt both sides into the same wrong checksum. The paper therefore repurposes ABFT from a classic HPC technique into a production fleet canary.

## Design

SEVI has two stages. First, Meta's fleet infrastructure runs both out-of-production maintenance-window tests and lightweight in-production tests to flag "SDC Suspects" while machines continue serving normal workloads. Over multiple years, this process identifies more than `2,500` suspect machines from a fleet spanning millions of servers, seven recent CPU architectures, and sixteen workload families.

Second, the paper performs long-duration diagnosis on every suspect. The instruction-level suite contains `246` AVX2, FMA3, BMI1, and BMI2 tests, each isolated to one instruction and run for `1` million rounds per logical core, twice, plus a third pass with uniform lane inputs. That yields more than `78` trillion rounds and `14` billion CPU seconds. The application-level suite uses NumPy matmul under bounded and unbounded floating-point inputs and three matrix-size caps, adding `43` billion rounds over `2.5` billion CPU seconds.

The mitigation mechanism builds on matmul's checksum invariant. For `A x B`, SEVI computes row checksums for `A`, column checksums for `B`, and compares their dot product with the sum of the output matrix. For large matrices, the paper recommends tile-level checking so a single corrupted element is not diluted away. The deployable path is this lightweight checksum, while scalar recomputation is used only as ground truth during evaluation.

## Evaluation

The measurement results are unusually strong because the fleet is large enough to turn "rare" events into statistics. At instruction level, SEVI finds `28` million incidents grouped into `400` SDC cases, implying an approximate fleet-level vector-SDC machine rate of `0.072‱`. Only `75` of `246` instruction tests ever find SDC, and the failures fall into arithmetic, FMA, gather, and permute instructions. FMA dominates, accounting for more than `75%` of SDC cases and more than `92%` of incidents. The failure shape also matters: memory-access SDC splits into about `76%` wrong-offset reads versus `24%` corrupted reads, and vector SDC stays highly localized to one physical core and usually one lane.

The application-level results connect that story to real workloads. In matmul, the authors observe `292K` incidents across `24` SDC cases on `12` machines, for an approximate fleet-level rate of `0.048‱`. Ten of those cases occur on cores that also show FMA SDC, and matmul SDC frequency tracks FMA SDC frequency with a Pearson correlation of `0.979`. Error severity is not always mild: while most wrong outputs have relative error below `1`, the tail reaches `10240` because exponent bits can flip.

The ABFT detector is practically convincing. With unrestricted floating-point inputs and max matrix dimension `10`, it detects all faulty machine cores found by the matmul study. Coverage remains `94%` at max dimension `25` and `88%` at `100`; with bounded inputs, it detects `21` of `23` faulty machines and about `99%` of incidents on the machines it catches. More than `80%` of machine cores see the first ABFT-detected SDC within `21` seconds. The overhead is about `11%` for small matrices, `3%` at dimension `100`, and `1.35%` near `1024 x 1024`, which is far below replication.

## Novelty & Impact

Relative to _Wang et al. (SOSP '23)_, SEVI is narrower but deeper: it focuses on vector instructions rather than processor SDC in general, and it resolves faults down to instruction class, bit pattern, core locality, and lane locality. Relative to _Chatzopoulos et al. (HPCA '25)_, its contribution is not microarchitectural modeling but production evidence at much larger scale. Relative to _Karystinos et al. (ISCA '24)_, the key systems move is to complement specialized tests with an in-application detector that runs during useful work.

That combination makes the paper valuable to both infrastructure teams and architecture researchers. Practitioners get a plausible deployment story for finding bad cores quickly and disabling them selectively. Researchers get a rare field dataset showing that real SDC behavior is strongly shaped by instruction class, bit width, temperature, and lane locality.

## Limitations

The fleet study is conditioned on the suspect-identification pipeline, so extremely low-frequency faults that evade first-stage screening may remain invisible. The authors argue that this should not change the qualitative story, but it is still not the same as random sampling from the whole fleet. The instruction suite also covers only AVX2, FMA3, BMI1, and BMI2 on anonymized x86 datacenter CPUs, so the paper does not generalize directly to other ISAs or accelerators.

The mitigation story is narrower than the headline. The ABFT mechanism is implemented for matmul, not arbitrary vector-heavy workloads, and the paper recommends math-library-level deployment without reporting an end-to-end production rollout. Detection quality also falls as matrices get larger unless tiling is used. Finally, because the hardware designs are proprietary, the paper offers strong operational evidence and plausible root-cause hypotheses rather than definitive circuit-level diagnosis.

## Related Work

- _Wang et al. (SOSP '23)_ — studies silent data corruption across a large production CPU population, while SEVI zooms in on vector instructions and links them to a concrete detector.
- _Hochschild et al. (HotOS '21)_ — shows that silently faulty cores exist in production fleets; SEVI classifies which vector instructions fail and how localized those failures are.
- _Karystinos et al. (ISCA '24)_ — Harpocrates generates hardware-in-the-loop CPU fault tests, whereas SEVI combines long-running fleet measurement with an in-application ABFT canary.
- _Chatzopoulos et al. (HPCA '25)_ — Veritas models likely SDC causes at the microarchitectural level; SEVI validates and complicates that picture using real hyperscale machines.

## My Notes

<!-- empty; left for the human reader -->
