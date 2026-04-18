---
title: "SEVI: Silent Data Corruption of Vector Instructions in Hyper-Scale Datacenters"
oneline: "Measures vector-instruction SDCs across a hyperscale fleet and embeds ABFT checks into matmul to catch 88%-100% of faulty machines with up to 1.35% overhead."
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
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790217"
code_url: "https://github.com/Thesys-lab/SEVI-ASPLOS26"
tags:
  - hardware
  - datacenter
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

SEVI studies silent data corruption (SDC) in vector instructions using production machines at hyperscale, not synthetic fault injection alone. It shows that FMA instructions dominate the observed failures, that those failures are highly localized to one physical core and usually one vector lane, and that matmul-integrated ABFT can catch `88%-100%` of faulty machines with as little as `1.35%` overhead on large matrices.

## Problem

The paper starts from a failure mode that ordinary testing handles badly. Silent data corruption does not crash the machine or raise an exception; it simply returns a wrong value and lets downstream software consume it. On one machine the rate can look negligible, but at datacenter scale the aggregate rate matters, as prior incidents at Google, Meta, and Alibaba already showed.

The missing piece was a production-grounded answer to three questions: which vector instructions dominate the risk, whether their failures have exploitable structure, and whether operators can detect the important SDCs without spending large amounts of pure overhead on specialized fleet tests. Vector instructions are the right focus because the paper says they account for about `80%` of compute instructions in AI workloads and about `50%` of execution residency in several hyperscale services, while prior work already suggested they are especially SDC-prone.

## Key Insight

The key claim is that vector-instruction SDC is concentrated enough to support targeted detection. In SEVI's measurements, FMA instructions account for most incidents, faults stay localized to one physical core, and `98.5%` of incidents affect only one vector lane. The fleet therefore does not need a universal detector for every CPU pathology before it can get useful coverage.

The bridge from measurement to mitigation is matmul. Because matrix multiplication is pervasive and FMA-heavy, the paper treats it as a natural canary for vector SDC. For `A x B`, the sum of the output matrix must equal the dot product of a row-checksum vector of `A` and a column-checksum vector of `B`; that checksum relation is far cheaper than full duplication, yet unlikely to fail identically on both sides.

## Design

SEVI has two stages. First, Meta's infrastructure runs both out-of-production maintenance tests and lightweight in-production tests built from vendor suites plus snippets from sixteen workload families. Suspicious machines are flagged as `SDC Suspects` but remain in production, which keeps the later measurements close to real deployment conditions. Over multiple years, this pipeline identifies more than `2,500` suspects across a fleet with millions of servers and seven recent CPU architectures.

Second, the paper performs long-duration characterization on all suspects. The instruction-level suite isolates `246` AVX2, FMA3, BMI1, and BMI2 test cases, each run `1` million rounds per logical core, then repeated twice more, with the third pass using uniform lane inputs. This yields more than `78` trillion rounds over `14` billion CPU seconds. The application-level study adds NumPy matmul under bounded and unbounded inputs and three matrix-size bounds, totaling another `43` billion rounds over `2.5` billion CPU seconds.

The mitigation mechanism is an in-application ABFT check for matmul. For `A x B`, SEVI computes row and column checksum vectors and compares their dot product with the sum of the output matrix. This adds `O(mn + np)` work on top of `O(mnp)` multiplication. During evaluation, scalar recomputation serves only as ground truth; the deployable detector is the checksum path. For large matrices, the paper recommends tiling with tile sizes below `100` to preserve sensitivity.

## Evaluation

The measurement study turns rare events into repeatable statistics. At instruction level, SEVI observes `28` million incidents grouped into `400` SDC cases, corresponding to an approximate fleet-level vector-SDC machine rate of `0.072‱`. Only `75` of the `246` instruction tests ever trigger SDC, all in arithmetic, FMA, gather, or permute instructions. FMA dominates, contributing more than `75%` of SDC cases and more than `92%` of incidents. The fault patterns are structured: `76%` of memory-access incidents are wrong-offset reads, `24%` are corrupted reads, SDC appears on only one physical core per affected machine, and `98.5%` of incidents touch a single vector lane.

The application-level results justify the matmul choice. The authors observe `292K` incidents across `24` matmul SDC cases on `12` machines, for an approximate fleet-level rate of `0.048‱`. Ten of those cases occur on cores that also show FMA SDC, and matmul SDC frequency tracks instruction-level FMA SDC frequency with a Pearson correlation of `0.979`. `75%` of matmul SDC cases fail within `8` seconds, and while most wrong results have relative error below `1`, the tail reaches `10240`, consistent with exponent-bit corruption.

The ABFT detector is the practical payoff. With unrestricted floating-point inputs and maximum matrix dimension `10`, it detects all `24` faulty machine cores found in the matmul study. Coverage remains `94%` at dimension `25` and `88%` at `100`. With bounded inputs, it detects `21` of `23` faulty machines and about `99%` of incidents on the machines it catches. More than `80%` of machine cores see the first ABFT-detected SDC within `21` seconds. The overhead is `11%` for dimensions `10` and `25`, `3%` at dimension `100`, and only `1.35%` near `1024 x 1024`, far below replication. That makes the evidence persuasive for the paper's stated regime, though it stops short of a full production rollout.

## Novelty & Impact

Relative to _Wang et al. (SOSP '23)_, SEVI is narrower but deeper: it focuses on vector instructions rather than processor SDC in general, and it resolves the behavior down to instruction class, bit pattern, core locality, and lane locality. Relative to _Chatzopoulos et al. (HPCA '25)_, the contribution is not a better microarchitectural model but much larger-scale field evidence. Relative to _Karystinos et al. (ISCA '24)_, the key systems move is to complement specialized tests with an in-application detector that runs during useful work.

That makes the paper useful to both infrastructure teams and reliability researchers. Practitioners get a credible path for turning common math-library calls into canaries that help localize bad cores quickly. Researchers get a rare field dataset showing that real SDC behavior is strongly shaped by instruction class, bit width, temperature, and lane locality.

## Limitations

The fleet study is conditioned on the suspect-identification pipeline, so extremely low-frequency faults that evade first-stage screening may remain invisible. The authors argue this should not materially change the qualitative picture, but it is still not the same as unbiased random sampling from the whole fleet. The instruction suite also covers only AVX2, FMA3, BMI1, and BMI2 on anonymized x86 datacenter CPUs, so the conclusions do not automatically transfer to other ISAs or accelerators.

The mitigation story is narrower than the headline if read too broadly. The ABFT mechanism is implemented for matmul, not arbitrary vector-heavy workloads, and the paper recommends math-library-level deployment without reporting an end-to-end production rollout. Detection quality degrades for larger matrices unless tiling is introduced, and the proprietary hardware prevents definitive circuit-level diagnosis.

## Related Work

- _Wang et al. (SOSP '23)_ — studies silent data corruption across a large production CPU population, while SEVI zooms in on vector instructions and links them to a concrete detector.
- _Hochschild et al. (HotOS '21)_ — shows that silently faulty cores exist in production fleets; SEVI classifies which vector instructions fail and how localized those failures are.
- _Karystinos et al. (ISCA '24)_ — Harpocrates generates hardware-in-the-loop CPU fault tests, whereas SEVI combines long-running fleet measurement with an in-application ABFT canary.
- _Chatzopoulos et al. (HPCA '25)_ — Veritas models likely SDC causes at the microarchitectural level; SEVI validates and complicates that picture using real hyperscale machines.

## My Notes

<!-- empty; left for the human reader -->
