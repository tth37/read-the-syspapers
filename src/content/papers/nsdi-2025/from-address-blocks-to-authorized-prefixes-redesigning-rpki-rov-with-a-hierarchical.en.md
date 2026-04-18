---
title: "From Address Blocks to Authorized Prefixes: Redesigning RPKI ROV with a Hierarchical Hashing Scheme for Fast and Memory-Efficient Validation"
oneline: "h2 ROV replaces address-block checks with prefix-granular hashed authorization bitmaps, making RPKI origin validation faster and smaller without changing outcomes."
authors:
  - "Zedong Ni"
  - "Yinbo Xu"
  - "Hui Zou"
  - "Yanbiao Li"
  - "Guang Cheng"
  - "Gaogang Xie"
affiliations:
  - "Computer Network Information Center, Chinese Academy of Sciences"
  - "School of Cyber Science & Engineering, Southeast University"
  - "University of Chinese Academy of Sciences"
  - "Purple Mountain Laboratories"
conference: nsdi-2025
category: security-and-privacy
code_url: "https://github.com/FIRLab-CNIC/h-2ROV"
tags:
  - networking
  - security
  - verification
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

The paper argues that the main bottleneck in RPKI Route Origin Validation is not just data-structure choice, but the address-block validation model itself. It replaces address-block rules with exact authorized prefixes, proves the new model is outcome-equivalent to the standard one, and implements that idea as `h2 ROV` using hierarchical bitmap-backed hash tables. On real ROA and BGP traces, the design cuts IPv4 validation time by 1.7x to 9.8x and memory by 49.3% to 86.6%, while also reducing routing-convergence penalties during update bursts.

## Problem

ROV is the only standardized, production-ready defense against BGP origin hijacking, but operators still deploy it unevenly. The paper cites a gap between more than 50% ROA coverage of BGP prefixes and only about 12% of ASes actually enforcing ROV, with efficiency concerns identified as a primary reason. That concern is concrete: every incoming route needs to be checked against a large and growing ROA set, and bursts of updates directly slow BGP convergence. If validation becomes too expensive, operators face a bad tradeoff between routing security and control-plane responsiveness.

The authors argue that existing optimizations attack the wrong layer of the problem. Hash-based schemes reduce memory, but they still need repeated probes to resolve super-prefix containment. Trie-based schemes speed lookup, but they pay with large memory footprints. Both inherit the same underlying AB model, where each rule is `(prefix, maxLength, ASN)`. To classify a route, the router first searches for covering address blocks and then checks whether any covering rule also matches the route prefix length and origin ASN. That means the common case does not actually get simpler as RPKI deployment grows. In fact, when more routes become valid, the amount of work inside existing schemes can increase.

## Key Insight

The central claim is that ROV should be phrased around exact authorized prefixes rather than around address blocks. If an ROA authorizes prefix `pfx` up to `maxLength`, the router can conceptually expand that object into the set of concrete prefixes it authorizes and store rules as `(authorized-prefix, ASN)`. Then validation naturally separates into two questions: is this exact route prefix authorized for this ASN, and if not, is the route prefix at least covered by any authorized prefix? That split changes the cost structure of ROV, because valid routes can now be answered by a direct match instead of by searching through covering address blocks.

The second insight is that this reformulation is not an approximation. The paper proves that the AP model and the conventional AB model always produce identical `valid`, `invalid`, and `notFound` outcomes when derived from the same ROAs. Once that equivalence is established, the system can redesign the fast path around exact matches without weakening correctness. The authors' cost analysis then explains why this matters operationally: as RPKI deployment increases, the AP model benefits because valid routes become cheaper, whereas the AB model becomes more burdened by the growing volume of covered and valid routes.

## Design

`h2 ROV` instantiates the AP model with hierarchical bitmap encoding derived from Hanging ROA. Each encoded rule is represented as `(id, bm, ASN)`, where `id` names a subtree rooted at a hanging level and `bm` marks the authorized prefixes inside that subtree. The design uses two hash tables. The Subtree-Origin Table (`SOT`) is keyed by `(subtree id, ASN)` and answers the exact-match question. Given a route `(rp, ro)`, the router computes the subtree containing `rp`, derives the bit position of `rp` inside that subtree, and checks whether the corresponding bit is set in `SOT[id, ro]`. If yes, the route is immediately `valid`, with O(1) lookup.

If `SOT` misses, `h2 ROV` consults the SubTree Table (`STT`), keyed only by subtree id and storing the bitwise OR of all authorized prefixes present in that subtree regardless of ASN. `STT` answers the coverage question. The router checks whether any authorized prefix in the current subtree covers the route. If so, the route is `invalid`; if not, the algorithm backtracks through ancestor subtrees until it either finds coverage or reaches the root and returns `notFound`. This is the core algorithmic shift: matching and covering are handled by different structures instead of being interleaved inside a single address-block search.

The paper then adds two important optimizations. For IPv4, `h2 ROV` builds Level Bitmaps (`LB`) for hanging levels 5, 10, 15, and 20, marking which subtree roots are covered. That lets the validator avoid most `STT` backtracking and gives O(1) validation for prefixes of length 24 or shorter; longer prefixes need at most three `STT` probes plus one `LB` access. For IPv6, dense bitmap arrays are too expensive, so the design introduces a cover-flag bit and a binary-search procedure over ancestor subtrees after inserting placeholder entries for missing ancestors. That reduces the worst-case lookup from O(|rp|) to O(log |rp|), but it is still weaker than the IPv4 fast path.

The implementation also handles pathological ROAs. If `delta = maxLength - |prefix|` is large, expanding a single ROA would create too many authorized-prefix rules, so such ROAs are classified as wide ROAs and stored in a separate Wide ROA Trie (`WRT`) rather than exploded into the main hash tables. The full system is integrated into FRRouting and BIRD by adding an encoder and parser around the existing RTR/BGP paths and replacing the legacy validator logic with the `h2 ROV` validator.

## Evaluation

The evaluation uses real ROAs from RIPE NCC and real BGP updates from RIPE RIS collectors, with comparisons against LPFST (`RTRLib`), `HT`, `HT+PT` (`BIRD`), and Patricia (`BGP-SRx`). In IPv4, `h2 ROV` reaches 8.1 to 12.9 million validations per second and is 6.8x to 9.8x faster than LPFST, 4.3x to 6.2x faster than `HT`, 1.7x to 2.4x faster than `HT+PT`, and 2.2x to 2.9x faster than Patricia. Its IPv4 memory footprint is 8.5 MB, a 49.3% to 86.6% reduction relative to the baselines. Those numbers support the paper's core argument that changing the validation model, not just the index, changes the asymptotic behavior in the practical regime.

The IPv6 story is more mixed, and the paper is appropriately explicit about that. `h2 ROV` reaches 3 to 5.96 million validations per second, beating LPFST, `HT`, and `HT+PT`, but it is slightly slower than Patricia on most collectors. Its IPv6 memory footprint is 12.6 MB: better than `HT+PT` and Patricia, but worse than LPFST and `HT`. Update costs remain small, with ROA insertions and deletions completing in under 1 microsecond, so the authors argue route validation, not ROA churn, is the real bottleneck.

The most compelling results are the system-level ones. Integrated into FRRouting and BIRD, `h2 ROV` introduces the smallest average decision-process delay under normal operation: 19.8% in FRRouting and 5.9% in BIRD. During a replayed 340K-update burst, it yields the lowest peak processing delay, reducing that delay by 48.8% to 83.2% in FRRouting and 46.9% to 70.9% in BIRD versus the other schemes. In emulated AS topologies, routing-convergence inflation during bursts stays within 3.8% to 8.5%, and the resulting reduction in ROV-induced convergence delay reaches 30.4% to 64.7% on real-world topologies. Those experiments directly test the operational consequence the paper cares about: whether a faster validator actually preserves convergence behavior under stress.

## Novelty & Impact

The closest technical precursor is _Li et al. (INFOCOM '22)_, which introduced Hanging ROA as a bitmap encoding scheme. This paper's novelty is to turn that encoding idea into a new validation model instead of using it as a compact representation for the old one. Compared with existing ROV implementations such as RTRlib, BIRD's hash/trie hybrid, and BGP-SRx's Patricia tree, the key change is conceptual: `h2 ROV` matches exact authorized prefixes first and asks about covering prefixes only afterward. That is why its performance improves in the regime where the authors expect future RPKI deployment to move the Internet.

The likely impact is practical rather than purely theoretical. The paper gives operators and router implementers a reason to revisit the assumption that ROV must impose a significant control-plane penalty. It also provides a migration path that works with today's routers: software control planes can adopt the AP model immediately through local encoding, and future RTR protocol changes could remove even that extra step. If ROV deployment has been held back partly by perceived router cost, this paper weakens that objection with a concrete, measured alternative.

## Limitations

The largest limitation is IPv6. The paper's best optimization applies only to IPv4, because dense level bitmaps are feasible there but not across the sparse 128-bit IPv6 space. The cover-flag and binary-search design helps, but it does not fully close the gap to the best trie baseline, and the paper openly reports that Patricia can still be faster in some IPv6 settings.

There are also deployment and complexity tradeoffs. The AP model needs rule expansion, threshold tuning for wide ROAs, separate maintenance of `SOT`, `STT`, `LB`, and `WRT`, and more complicated ROA update logic than legacy validators. The incremental deployment story is reasonable but incomplete: unless bitmap-encoded RTR PDUs become available, routers still have to encode ROAs locally. Finally, the evidence is strongest for software-router implementations, replay-based experiments, and emulations. That is enough to support the paper's systems claim, but it is not the same as a long-running production deployment across diverse hardware routers.

## Related Work

- _Li et al. (INFOCOM '22)_ - `Hanging ROA` supplies the bitmap encoding primitive that `h2 ROV` builds on, but it does not redesign route validation from address blocks to exact authorized prefixes.
- _Wählisch et al. (CSET '13)_ - `RTRlib` is the classic RPKI validation library the paper treats as an LPFST baseline; `h2 ROV` beats it mainly by changing the validation model rather than by micro-optimizing the same workflow.
- _Li et al. (IMC '23)_ - `ROVista` measures real-world ROV enforcement and helps motivate why router efficiency matters, but it studies adoption rather than accelerating the validation algorithm itself.
- _Qin et al. (NDSS '24)_ - this deployment study shows operators cite efficiency as a barrier to enforcing ROV, while `h2 ROV` supplies a concrete mechanism intended to remove that barrier.

## My Notes

<!-- empty; left for the human reader -->
