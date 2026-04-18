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
  - observability
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

SEVI studies silent data corruption in vector instructions on a production fleet large enough that rare faults become measurable rather than anecdotal. Its main result is twofold: fused multiply-add instructions dominate the observed corruption landscape, and a lightweight ABFT checksum inside matrix multiplication can detect most faulty machines while adding only about `1.35%` overhead on `1024 x 1024` matrices.

## Problem

The paper starts from a reliability gap that hyperscalers already know is real but still poorly characterized. SDCs are dangerous precisely because they do not crash the program or trip a hardware exception; they quietly return wrong values and let those values flow upward into application state. At single-machine scale that looks like a vanishingly rare event, but at datacenter scale the aggregate rate becomes operationally meaningful. Prior work had shown isolated incidents, broad fleet-level case studies, and simulation-based fault-injection results, yet there was still no systematic picture of which vector instructions fail in practice, how those failures manifest, or how to detect them without burning enormous amounts of dedicated test time.

Vector instructions are the right place to look because they sit on the hot path of many important workloads and were already suspected to be unusually vulnerable. The paper cites them as roughly `80%` of compute instructions in AI workloads and about `50%` of residency in several hyper-scale services. That makes the systems question sharper than "how often do CPUs suffer SDC?": it becomes "which vector operations are the real fleet risk, what are their observable failure modes, and can we turn a common workload into a cheap continuous canary?" The obvious alternative, long specialized fleet tests, gives coverage only by paying pure overhead.

## Key Insight

The paper's central claim is that vector-instruction SDC is concentrated enough, and structured enough, to support a targeted detection strategy rather than a generic one. In the authors' data, most observed incidents come from FMA instructions, most corruptions stay localized to one physical core and usually one vector lane, and many application-level failures in matrix multiplication line up tightly with FMA-level faults. That concentration means a single widely used vector-heavy kernel can act as a representative detector for a large fraction of the real problem.

The second insight is that the detector does not need duplication of the full workload. Matrix multiplication already has a strong algebraic invariant: the sum of all outputs equals the dot product of a row-checksum vector of `A` and a column-checksum vector of `B`. Computing those checksums is much cheaper than recomputing the whole product, yet an SDC is unlikely to perturb both sides into the same wrong answer. The paper therefore turns ABFT from a classic HPC protection technique into a fleet-level canary mechanism for production datacenters.

## Design

SEVI uses a two-stage study method. First, Meta's infrastructure continuously searches the production fleet for "SDC Suspects" using both out-of-production maintenance-window tests and lightweight in-production tests co-located with normal workloads. Those tests use vendor suites and snippets from sixteen workload families. Machines that look suspicious are not removed from service immediately; instead, they are virtually flagged so they can be reserved later for long-duration diagnosis while still running the same software and workload mix as the rest of the fleet.

Second, the paper performs deep testing on every suspect machine. The instruction-level suite contains `246` AVX2, FMA3, BMI1, and BMI2 test cases, each isolated to one instruction and run for `1` million rounds per logical core, then repeated twice plus a third pass with uniform lane inputs. In total, that produces over `78` trillion rounds and `14` billion CPU seconds. The application-level suite uses NumPy matmul with bounded and unbounded floating-point inputs and multiple matrix-size caps, adding another `43` billion rounds over `2.5` billion CPU seconds. This design gives the authors both breadth and the per-machine dwell time needed to expose sub-`10^-5` faults.

The mitigation mechanism builds on the same matmul focus. For `A x B`, SEVI computes a checksum over rows of `A`, a checksum over columns of `B`, and compares their dot product against the sum of the output matrix. The paper recommends tile-level checks for larger matrices so the relative error from one bad element is not diluted too much. In evaluation, scalar recomputation serves as the ground-truth verifier, but the deployed design is the lightweight checksum path rather than full replication.

## Evaluation

The instruction-level findings are the strongest part of the paper. SEVI observes `28` million SDC incidents grouped into `400` SDC cases, corresponding to an approximate fleet-level vector-SDC machine rate of `0.072‱`. Only `75` of `246` instruction tests ever find SDC, and those cases span arithmetic, FMA, gather, and permute instructions. FMA dominates: it accounts for more than `75%` of the SDC cases and more than `92%` of the incidents. The paper also surfaces useful failure-shape details: memory-access SDC splits into about `76%` wrong-offset reads versus `24%` corrupted reads, and `98.5%` of all vector SDC incidents affect only a single lane. Those are not just curiosities; they are the empirical basis for the later canary design.

The application-level study ties the instruction story to real workload behavior. In matmul, the authors find `292K` incidents across `24` SDC cases on `12` machines, for an approximate fleet-level rate of `0.048‱`. Ten of those cases occur on cores that also show FMA SDC, and the matmul SDC frequency tracks the FMA SDC frequency with a Pearson correlation of `0.979`, which strongly supports the claim that FMA faults are the main application-level driver. Error severity is also mixed in an important way: most wrong outputs have relative error below `1`, but a meaningful tail reaches `10240` because exponent bits can flip, contradicting the comforting idea that floating-point SDC mostly stays in low-order mantissa bits.

The ABFT results are practically convincing. With unrestricted floating-point inputs and maximum matrix dimension `10`, the method detects all faulty machine cores found by the matmul study. Coverage remains `94%` at max dimension `25` and `88%` at `100`; with bounded inputs, it detects `21` of `23` faulty machines and about `99%` of incidents on the machines it does catch. More than `80%` of machine cores see the first ABFT-detected SDC within `21` seconds. The overhead numbers are also good: about `11%` for tiny matrices, dropping to `1.35%` around `1024 x 1024`, far below the replication baseline. I find the evidence supportive of the paper's central claim, with the caveat that the detector is strongest when workloads already look like the matmul regime the authors optimized for.

## Novelty & Impact

Relative to _Wang et al. (SOSP '23)_, SEVI is narrower but deeper: it does not ask about general processor SDC in a large CPU population, but about vector instructions specifically, with enough instruction-level resolution to expose concrete fault modes. Relative to _Chatzopoulos et al. (HPCA '25)_, its contribution is not microarchitectural modeling but production evidence at much larger scale, plus validation that some long-assumed numerical patterns are incomplete. Relative to _Karystinos et al. (ISCA '24)_, the paper's important move is to complement specialized tests with an in-application detector that can run during useful work instead of consuming dedicated test time.

That combination makes the paper valuable to both infrastructure teams and architecture researchers. For practitioners, it offers a deployable story: use production workloads as canaries, identify bad cores quickly, and decommission or disable them selectively. For researchers, it contributes a rare field dataset showing that real SDC behavior is heavily shaped by instruction class, bit width, temperature, and lane locality. The work is therefore both a measurement paper and a systems-design paper, not merely one wrapped around the other.

## Limitations

The paper is candid about several limits. The fleet study starts from machines already flagged as SDC suspects, so extremely low-frequency faults that escape the first-stage screens may remain invisible. The authors argue that this should not change the qualitative conclusions, but it still means the measurements are conditioned on the detection pipeline rather than on perfectly random fleet sampling. Similarly, the instruction suite covers AVX2, FMA3, BMI1, and BMI2 on x86 datacenter CPUs; it does not claim anything about other ISAs or accelerators.

The mitigation story is also narrower than the headline might suggest. The ABFT mechanism is implemented for matmul, and the paper says deployment should happen at the math-library level, but it does not report a live end-to-end rollout inside production applications. Detection quality also declines as matrices get larger unless tiling is used, which means the low-overhead claim depends partly on choosing the right granularity. Finally, the paper cannot fully explain root causes because the underlying hardware designs are proprietary and the CPU architectures are anonymized. What it delivers is strong operational evidence and plausible hardware hypotheses, not definitive circuit-level diagnosis.

## Related Work

- _Wang et al. (SOSP '23)_ — studies silent data corruption across a large production CPU population, while SEVI zooms in on vector instructions and connects those faults to a concrete detection mechanism.
- _Hochschild et al. (HotOS '21)_ — shows that silently faulty cores exist in production fleets; SEVI extends that line by classifying which vector instructions fail and how localized those failures are.
- _Karystinos et al. (ISCA '24)_ — Harpocrates generates hardware-in-the-loop CPU fault tests, whereas SEVI combines long-running fleet measurement with an in-application ABFT canary.
- _Chatzopoulos et al. (HPCA '25)_ — Veritas models likely SDC causes at the microarchitectural level; SEVI validates and complicates that picture using real hyperscale machines.

## My Notes

<!-- empty; left for the human reader -->
