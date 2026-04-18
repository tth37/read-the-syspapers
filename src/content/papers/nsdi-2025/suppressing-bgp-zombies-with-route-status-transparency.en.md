---
title: "Suppressing BGP Zombies with Route Status Transparency"
oneline: "RoST publishes signed per-interface route status and per-hop RouteIDs so ASes can detect suppressed BGP withdrawals without waiting for key rollover."
authors:
  - "Yosef Edery Anahory"
  - "Jie Kong"
  - "Nicholas Scaglione"
  - "Justin Furuness"
  - "Hemi Leibowitz"
  - "Amir Herzberg"
  - "Bing Wang"
  - "Yossi Gilad"
affiliations:
  - "School of Computer Science and Engineering, The Hebrew University of Jerusalem, Jerusalem, Israel"
  - "School of Computing, University of Connecticut, Storrs, CT"
  - "Faculty of Computer Science, The College of Management Academic Studies, Rishon LeZion, Israel"
conference: nsdi-2025
category: security-and-privacy
tags:
  - networking
  - security
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

RoST targets a blind spot in BGP security: a route can be authentic yet stale because some AS suppresses a withdrawal. The system makes route status transparent through signed per-interface status vectors and a per-hop RouteID chain carried in BGP, letting downstream ASes detect zombie routes within a batch interval without requiring BGPsec deployment.

## Problem

The paper argues that origin validation and path authentication still leave BGP without a notion of freshness. A route can have a legitimate origin and a legitimate AS-path, yet no longer be usable because some upstream AS has already withdrawn it. If an intermediate AS fails to propagate an explicit withdrawal, or suppresses an implicit withdrawal caused by a replacement announcement, downstream ASes keep believing the old path is alive. The authors call these stale yet still-cryptographically-valid paths "zombie" routes.

That gap matters operationally. Zombie routes can blackhole traffic, violate policy by making an AS believe it is using a shorter or cheaper path than the one downstream routers now follow, and in some cases even induce routing loops. The paper points to prior measurement work showing that zombie outbreaks happen daily and notes that failures inside large providers can amplify the damage far beyond a single local mistake.

Existing defenses do not really solve this. RPKI authenticates the origin, and BGPsec-style mechanisms authenticate the path but not whether the path is still current. The main previously proposed answer is key rollover, but that assumes route authentication is already deployed and imposes recurring operational work to issue certificates, revoke old ones, and refresh routes. RoST is therefore framed as a way to decouple route freshness from heavyweight key-rotation workflows.

## Key Insight

The key idea is that freshness can be checked if route status becomes transparent at every hop that exports a route. RoST does not try to infer withdrawals indirectly from missing BGP messages. Instead, each adopting AS explicitly publishes the status of the routes it currently exports to each neighbor. If a downstream AS later sees a BGP announcement whose hop-by-hop identifiers do not match that published status, then some withdrawal or replacement has been suppressed along the way.

The protocol couples two views of the same route: a transparent control-plane record stored in a repository, and a compact RouteID sequence carried as a transitive BGP attribute. A validator compares them interface by interface. If any hop has already marked the route withdrawn, or has issued a newer RouteID for the same prefix, the announcement is stale. That turns freshness into a verifiable property that is orthogonal to path authentication and can layer on top of vanilla BGP or future secure-routing extensions.

## Design

Each adopting AS runs a separate RoST agent rather than modifying router internals. The agent maintains a Route Status Vector, or RSV, for every interface `(x, y)` from the local AS to a neighbor. An RSV entry stores a prefix, a `RouteID = (BatchID, PathID)`, and a boolean status. `BatchID` identifies the reporting interval, while `PathID` counts route changes for that prefix inside the interval, so bursts are absorbed into a batch rather than forcing an ever-growing global counter.

At the end of each batch, the agent publishes a `ΔRSV-Out` containing only changed entries. To authenticate that delta, the agent builds a Merkle tree over the full interface state and signs the batch counter, interface pair, and Merkle root with the AS's RPKI-backed key. A repository stores these updates, while subscribers fetch only the interfaces and prefixes relevant to routes their router currently prefers; the repository returns `ΔRSV-In` updates plus inclusion proofs for verification.

RoST also extends BGP announcements with a transitive extended-community attribute that carries a sequence of RouteIDs. When a router exports a route, its agent prepends the current RouteID for that interface before forwarding. If AS `w` uses path `x-y-z` toward a prefix, its agent tracks `z→y`, `y→x`, and `x→w`, and compares the RouteIDs in the BGP update against the RSV data fetched from the repository. Missing state makes the route pending and triggers a subscription; a withdrawn status or a newer RouteID makes the route invalid, causing the agent to withdraw it or switch to an alternative path. The paper also sketches a practical deployment path using existing Cisco commands for BGP logging, extended communities, and route removal.

## Evaluation

The evaluation is mostly an overhead study plus a simulation of partial adoption rather than an Internet deployment. For overhead, the authors process RIPE RIS RIB snapshots and update traces from 55 vantage points across six months. Their first quantitative claim is that the extra data carried inside BGP is small: after removing AS-path prepending, the average path length is 3.86 AS hops, so carrying one 7-byte RouteID per hop adds about 27 bytes to an announcement on average.

Storage looks reasonable for agents, though the repository is substantial. Under a conservative worst-case model with 1 million IPv4 prefixes and 250 thousand IPv6 prefixes, one full `RSV-Out` is about 16.83 MiB. With the observed average of 6.43 interfaces per AS, that gives roughly 106.76 MiB of `RSV-Out` state for an agent; the `RSV-In` working set is about 65 MiB. The repository stores all `RSV-Out` data plus subscriptions and reaches about 8.1 TiB in the authors' worst-case estimate.

Bandwidth overhead is asymmetric in the expected way. With 5-minute batches, the average agent upload rate is about 1.01 Kbps for ASes with 1 to 10 interfaces, and even ASes in the largest measured bucket stay near 122.13 Kbps. Fetching updates costs an average agent only 0.21 Kbps in requests, though inbound authenticated responses rise to about 106.97 Kbps because every entry carries a Merkle proof. On the repository side that aggregates into as much as 12.63 Gbps of response traffic in the paper's worst-case accounting.

The most policy-relevant result comes from simulation on a CAIDA January 2025 AS-level topology. When a Tier-1 AS suppresses a withdrawal, the fraction of zombie ASes decreases monotonically as more ASes adopt RoST. The improvement appears well before universal deployment, and the paper notes a positive spillover effect: once an adopter filters a zombie route, it also stops re-exporting that stale route to others.

## Novelty & Impact

RoST's novelty is to treat freshness as first-class routing state rather than as a side effect of path authentication. Prior BGP security work mostly focuses on who may announce a prefix and whether the path is forged. RoST asks a different question: even if the route was once valid, is it still active on every hop that forwarded it? The answer is a new mechanism, not just a measurement or operational guideline: signed per-interface route status, batched transparency updates, and hop-by-hop RouteIDs that let validators detect suppression without waiting for global key expiration.

That makes the paper relevant to both routing-security researchers and operators who care about deployment reality. It shows a path to mitigating zombie routes before BGPsec exists at scale and makes a strong incremental-deployment argument by showing benefits under partial adoption.

## Limitations

RoST does not solve the entire interdomain attack surface. The authors explicitly exclude attackers who forge or manipulate paths; those cases still require path-authentication schemes such as BGPsec or BGP-iSec. RoST also assumes RPKI-style keys are available to sign route-status reports, so it is not a zero-dependency add-on.

The practical design still introduces new infrastructure. Agents must stay synchronized with one or more repositories, monitor BGP state, and push router configuration changes correctly. The paper discusses multiple repositories and even BFT-style synchronization, but those are deployment considerations rather than evaluated components, and the repository's worst-case outbound bandwidth is not small.

Finally, the empirical evidence is indirect. The evaluation shows plausible overheads and the simulator shows that partial adoption helps, but there is no live deployment and no measurement of false positives, delayed repository updates, or failures in the agent-to-router control loop. RoST also reacts on batch timescales, so the protection window is minutes rather than instantaneous.

## Related Work

- _Fontugne et al. (PAM '19)_ - `BGP Zombies` established that stuck routes are common and damaging in practice; `RoST` turns that diagnosis into a concrete prevention mechanism.
- _Ongkanchana et al. (ANRW '21)_ - `Hunting BGP Zombies in the Wild` broadens the measurement picture for zombie routes, whereas `RoST` focuses on authenticated detection and mitigation.
- _Cohen et al. (SIGCOMM '16)_ - `Path-End Validation` strengthens BGP path authenticity, but it does not tell a router whether a once-valid path has already been withdrawn on some downstream hop.
- _Morris et al. (NDSS '24)_ - `BGP-iSec` improves post-ROV security against path attacks, while `RoST` is orthogonal and specifically addresses route freshness under withdrawal suppression.

## My Notes

<!-- empty; left for the human reader -->
