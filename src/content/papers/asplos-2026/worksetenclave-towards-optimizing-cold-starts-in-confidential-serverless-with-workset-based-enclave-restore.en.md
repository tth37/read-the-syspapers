---
title: "WorksetEnclave: Towards Optimizing Cold Starts in Confidential Serverless with Workset-Based Enclave Restore"
oneline: "WorksetEnclave snapshots SGX serverless functions, restores only execution workset pages into a small EDMM enclave, and loads the rest on verified page faults."
authors:
  - "Xiaolong Yan"
  - "Qihang Zhou"
  - "Zisen Wan"
  - "Feifan Qian"
  - "Wentao Yao"
  - "Weijuan Zhang"
  - "Xiaoqi Jia"
affiliations:
  - "Institute of Information Engineering, Chinese Academy of Sciences, Beijing, China"
  - "School of Cyber Security, University of Chinese Academy of Sciences, Beijing, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790249"
tags:
  - serverless
  - confidential-computing
  - memory
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

WorksetEnclave treats confidential serverless cold start as a restore problem rather than an initialization problem. It checkpoints a fully initialized SGX function, recreates only a small EDMM-enabled enclave, restores just the pages likely to be touched during execution, and brings the rest back through verified page faults. That cuts both startup time and EPC footprint without requiring SGX hardware changes.

## Problem

The paper starts from an awkward mismatch between SGX and serverless. Confidential FaaS wants short-lived, bursty functions with low cold-start latency and high instance density, but SGX startup is dominated by enclave creation and software initialization. In LibOS-based systems such as Gramine and Occlum, every function must create an enclave, measure many EPC pages, and load all required libraries into enclave memory before doing useful work.

The authors show that this hurts in two distinct ways. First, startup can take seconds, which is especially bad because serverless functions are often latency-sensitive and may run only briefly once started. Second, EPC usage stays large even after initialization, because enclaves cannot share code pages the way normal sandboxes often can. In their motivating measurements, some workloads use only around one percent of enclave pages during steady-state execution, yet still keep the whole enclave resident. Warm-start systems help only when prewarmed instances already exist; they do not remove true cold starts during scale-out.

## Key Insight

The paper's central claim is that enclave-based serverless functions do not need to restore their full initialized state eagerly. The pages required to boot an SGX function and the pages required to execute one request are materially different sets, and the latter is often much smaller.

That observation enables a two-part optimization. EDMM lets the system recreate a small enclave quickly instead of paying full enclave-creation cost up front, and snapshotting lets it skip expensive software initialization entirely. Once the system knows the execution workset, it can restore only that subset initially, then recover missing pages on demand with integrity checks. The key idea is not just "snapshot SGX," but "snapshot SGX in a way that separates initialization state from execution state."

## Design

WorksetEnclave has three core mechanisms. The first is `Enclave C&R`, which checkpoints and restores enclave-backed functions by dumping enclave memory from inside the enclave, then pairing that dump with a conventional process snapshot after the enclave region has been unmapped. Because a restored enclave is newly created, the system also has to reconstruct thread state carefully. The paper handles multi-threading by forcing other TCSs into an enclave spin region during checkpoint/restore, and it simulates `ERESUME` with `EENTER` so saved SSA context can be re-established in the fresh enclave.

The second mechanism is secure EPC checkpoint/restore. The enclave records page metadata such as virtual addresses and permissions, encrypts page contents inside the enclave, and stores the snapshot externally. To avoid machine-bound sealing, the function obtains a key from a KDS enclave through remote attestation, so snapshots can move across machines. During restore, the enclave recreates pages, verifies integrity, reapplies attributes, and marks the enclave crashed if verification fails.

The third mechanism is workset-based restore. During offline profiling, the SGX driver proactively evicts enclave pages, runs the function, and observes which pages are brought back through faults; those pages become the initial workset. At online restore time, only workset pages are loaded. If execution later touches a missing page, the kernel uses `EAUG` to add it, a signal handler transfers control to an in-enclave exception handler, and the enclave verifies the page before accepting it with `EACCEPTCOPY` and fixing permissions with `EMODPE`. This is the paper's main systems contribution: it converts SGX restore from "load everything now" to "load likely pages now, prove the rest later."

## Evaluation

The evaluation is broad enough for the paper's claim. The authors implement WorksetEnclave in both Gramine and Occlum, integrate it with OpenWhisk, and test seven Python functions plus two Node.js functions on an Intel Xeon Silver 4510T machine with `4GB` PRM. Baselines include cold start with and without EDMM and full snapshot restore without workset filtering.

The startup numbers are the headline result. WorksetEnclave reduces startup latency to under `600ms` on Gramine and under `400ms` on Occlum, delivering `1.9-14.1x` speedups on Gramine and `6.7-54x` on Occlum relative to the cold-start baselines. The end-to-end results are more nuanced but still favorable: for short functions such as `pyaes`, `chameleon`, `linpack`, and `rnn_serving`, response time drops below `400ms`, and `rnn_serving` improves by `13.7x`. For longer operations like `image_rotate` and `json_serdes`, startup is a smaller share of total latency, so gains are naturally smaller.

The memory story is also strong. Compared with EDMM-enabled baselines, WorksetEnclave cuts enclave memory by `13.37-94.87%`; the paper highlights `74.31%` reduction for `pyaes` and up to `94.87%` for large-library workloads such as `rnn_serving` and `lr_serving`. The tradeoff is on-demand recovery, but the measured cost is small: one recovered page takes about `36.41us`, the first invocation faults on fewer than `0.2%` of total enclave pages, and after workset updates the paper reports zero page faults after `30` invocations. I found that evidence fairly convincing, though the workset is learned from prior executions, so stability across evolving inputs matters a lot.

## Novelty & Impact

Relative to _Ustiugov et al. (ASPLOS '21)_, WorksetEnclave is not just another snapshotting paper; it adapts snapshotting to SGX's restricted memory model and uses workset-guided selective restore instead of full recovery. Relative to _Li et al. (ISCA '21)_, it does not depend on SGX hardware changes or shared trusted libraries; it works on today's platforms. Relative to _Kim et al. (SoCC '23)_ and _Zhao et al. (USENIX Security '23)_, its novelty is the focus on true cold starts and scale-out rather than prewarmed reuse. That makes the paper likely to matter to confidential-cloud systems work, especially for people building practical TEE-backed serverless stacks.

## Limitations

The approach depends on workset predictability. If future invocations touch many pages not seen during installation or recent executions, the system falls back to more page faults and progressively larger worksets, so the main optimization weakens. The paper reports this stabilizes quickly on its workloads, but the method seems best suited to functions with repetitive execution structure.

There are also deployment caveats. WorksetEnclave adds nontrivial complexity to the SGX driver, LibOS, signal path, and enclave runtime. Its security model excludes denial-of-service and SGX microarchitectural side channels, and its evaluation omits comparisons with hardware-modified systems because those cannot run on commodity clouds. That is a fair scope choice, but it means the paper demonstrates practicality under today's SGX model rather than a universally best confidential-serverless design.

## Related Work

- _Ustiugov et al. (ASPLOS '21)_ — REAP uses working-set-aware snapshots for conventional serverless functions, while WorksetEnclave extends that idea into SGX with selective EPC restore and enclave-specific integrity handling.
- _Li et al. (ISCA '21)_ — PIE speeds confidential serverless by reusing trusted libraries through plug-in enclaves, whereas WorksetEnclave keeps stock hardware and instead skips initialization with snapshot-based restore.
- _Kim et al. (SoCC '23)_ — Cryonics also uses enclave snapshots, but it mainly optimizes warm starts with preloaded working sets rather than cold-start scale-out from no live instance.
- _Zhao et al. (USENIX Security '23)_ — Reusable Enclaves accelerates repeated requests by resetting existing enclaves, while WorksetEnclave targets the harder case where the platform must create fresh instances.

## My Notes

<!-- empty; left for the human reader -->
