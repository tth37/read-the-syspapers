---
title: "Analyzing and Enhancing ArckFS: An Anecdotal Example of Benefits of Artifact Evaluation"
oneline: "This artifact-evaluation follow-up patches rename, crash-consistency, and concurrency bugs in Trio's ArckFS while largely preserving the original performance claims."
authors:
  - "Jonguk Jeon"
  - "Subeen Park"
  - "Sanidhya Kashyap"
  - "Sudarsun Kannan"
  - "Diyu Zhou"
  - "Jeehoon Kang"
affiliations:
  - "KAIST"
  - "EPFL"
  - "Rutgers University"
  - "Peking University"
  - "KAIST / FuriosaAI"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3768291"
code_url: "https://github.com/vmexit/trio-sosp23-ae"
tags:
  - filesystems
  - persistent-memory
  - crash-consistency
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

This paper is a follow-on audit of Trio and ArckFS from SOSP 2023 rather than a new NVM file-system architecture. It clarifies the verifier rules needed for multi-inode operations and patches one rename bug, one crash-consistency bug, and four concurrency bugs in ArckFS. ArckFS+ keeps most of the original performance story: `97.23%` of ArckFS's metadata throughput at 48 threads in FxMark, and `97.1%`-`102.1%` on the paper's Filebench macrobenchmarks.

## Problem

Trio seeks both security and speed by verifying NVM-resident core state while letting each LibFS keep fast DRAM auxiliary state, so integrity checks are deferred until inode ownership changes. But that design pushes correctness into boundary cases, and the artifact left some rules implicit: a valid cross-directory rename can fail verification, file creation can persist only partially because of a missing fence, and races can crash the LibFS or create directory cycles.

## Key Insight

The paper's central claim is that Trio's architecture is salvageable if boundary transitions obey an explicit contract. By making inode-sharing, rename ordering, and persistence ordering precise, the verifier can distinguish rename from delete and preserve a connected tree at every release point, while the cost stays low because the extra synchronization sits on rare transitions rather than the steady-state data path.

## Design

Trio splits state into NVM-resident core state, which the verifier trusts, and DRAM auxiliary state, which each LibFS rebuilds for speed. ArckFS realizes that design with per-directory hash tables in DRAM, multi-tailed logs in NVM, and fine-grained locking. The key invariant is simple to state and hard to preserve: the directory hierarchy must always form a connected tree.

ArckFS+ adds two classes of fixes. First, it makes the multi-inode contract explicit. A new inode can only be committed or released after its parent is released; after moving a non-empty directory, the new parent must be committed or released before the old parent; and some renames require the new parent to be committed before the rename to break a dependency cycle. The kernel's shadow inode gains a parent pointer so the verifier can tell "renamed away" from "deleted," and successful relocation also requires that the old parent is still held, the new parent is not a descendant of the moved directory, and the LibFS holds a global rename lock.

Second, it patches implementation bugs without redesigning the fast path. ArckFS+ adds one memory fence before persisting the commit marker for inode creation; it locks all relevant inode structures during release so no thread can unmap an inode while another still uses it; it extends bucket critical sections so DRAM auxiliary-state updates cannot outrun NVM core-state updates; it uses RCU to protect directory-bucket readers from freed entries; and it adds a global rename lock plus descendant checks to rule out directory cycles.

## Evaluation

The evaluation is run on a different machine from the original Trio paper to check reproducibility: a dual-socket 48-core Xeon server with Intel Optane persistent memory. ArckFS+ is compared against ArckFS and the Trio-artifact baselines, including ext4, PMFS, NOVA, OdinFS, WineFS, SplitFS, and Strata.

The fixes cost little where Trio originally claimed wins. In single-thread metadata tests, ArckFS+ reaches `83.3%`, `92.8%`, and `92.2%` of ArckFS for open, create, and delete; the paper attributes those losses to the RCU read-side critical section and the added memory fence. Under 48-thread FxMark metadata workloads, ArckFS+ still delivers a geometric mean of `97.23%` of ArckFS throughput. On the authors' rebuilt Filebench framework, which restores the original shared-directory semantics instead of Trio's private-directory modification, ArckFS+ achieves `101.1%` and `102.1%` of ArckFS at one thread on Webproxy and Varmail, and `97.1%` and `98.8%` at 16 threads. That is strong evidence that the architecture survives the repair.

The caveat is that not every repaired path is stressed equally. None of the main workloads perform directory relocation, so rename-specific overhead is largely unmeasured, and the sharing-cost study shows that secure sharing remains expensive on some workloads relative to the faster trust-group mode.

## Novelty & Impact

The novelty here is not a new file-system mechanism but a systems-research result about what artifact evaluation can uncover after publication. Relative to _Zhou et al. (SOSP '23)_, the paper makes implicit assumptions explicit, patches the implementation, and shows the original performance claims mostly survive. That gives builders a concrete list of failure points and the community a strong example of artifact evaluation improving prior work.

## Limitations

This remains an anecdotal case study of one system family. The paper does not provide a general bug-finding method or a proof that ArckFS+ is now bug-free; some failures are demonstrated with inserted `sleep()`s or extra flushes to widen the window. Rename-heavy workloads are missing, and the trust-group results show that sharing overhead still matters unless users relax the default verification regime.

## Related Work

- _Zhou et al. (SOSP '23)_ - Trio and ArckFS are the direct target of this paper; the new contribution is to expose their missing multi-inode rules and repair the released implementation.
- _Kadekodi et al. (SOSP '19)_ - SplitFS also moves persistent-memory file-system logic into userspace, but this paper studies how to preserve metadata integrity and correctness in that setting rather than how to further shrink the trusted path.
- _Chen et al. (FAST '21)_ - KucoFS keeps security by involving trusted components on every metadata operation, whereas ArckFS+ argues for deferred verification and then documents the corner cases needed to make that strategy safe.
- _Xu and Swanson (FAST '16)_ - NOVA is a kernel persistent-memory file system baseline; this paper uses such systems as performance comparators while focusing on the correctness hazards unique to Trio's userspace-sharing architecture.

## My Notes

<!-- empty; left for the human reader -->
