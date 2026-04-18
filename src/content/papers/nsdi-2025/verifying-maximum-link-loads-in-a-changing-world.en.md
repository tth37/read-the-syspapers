---
title: "Verifying maximum link loads in a changing world"
oneline: "Velo verifies worst-case per-link load under failures and BGP route changes by reducing route states to egress choices and clustering similar traffic."
authors:
  - "Tibor Schneider"
  - "Stefano Vissicchio"
  - "Laurent Vanbever"
affiliations:
  - "ETH Zürich"
  - "University College London"
conference: nsdi-2025
category: network-verification-and-synthesis
code_url: "https://github.com/nsg-ethz/velo"
tags:
  - networking
  - verification
  - formal-methods
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Velo is the first system in the paper's framing that computes the worst-case load of every link while jointly considering internal failures and external BGP route changes. Its main move is to replace the huge space of concrete route advertisements with egress-router choices, prove that a single-egress state is enough to maximize each link under strictly isotone routing, and then compress the traffic matrix with bounded error. On large ISP-like topologies, the prototype finishes within minutes for the practical regimes the paper targets, and its approximation error stays below 1% in the evaluation.

## Problem

Operators care about worst-case link loads because overload is what turns ordinary routing churn into packet loss, delay inflation, and emergency traffic engineering. Measuring the current network is not enough: links fail, BGP routes appear and disappear, and a handful of route changes at border routers can push traffic onto very different internal paths. The paper's motivating figure shows that, on a real ISP network, allowing route changes on top of one- and two-link failures can roughly double the additional load seen by core links compared with analyzing failures alone.

That requirement breaks existing tooling in two different ways. Most network verifiers reason about functional properties such as reachability, loops, or control-plane correctness, not performance. The small set of prior systems that do reason about load typically assume external routes are fixed, which is acceptable in a tightly controlled datacenter but not for an Internet-facing ISP. Once route changes are allowed, the search space explodes: every destination may gain, lose, or modify routes; route attributes have large or unbounded domains; and failures couple destinations together because one failure shifts many forwarding paths at once. A per-destination checker is no longer enough.

## Key Insight

The key observation is that, for worst-case load analysis, Velo does not need to model full BGP advertisements. What matters is which border routers can act as egresses for each destination, because many concrete routes induce the same forwarding and therefore the same link loads. This router-based abstraction already collapses a large symbolic state space into a finite set of egress choices.

The deeper insight is structural. Under strictly isotone intra-domain routing such as shortest-path routing, the worst-case load of a given link for a given destination is attained when the entire network effectively uses one egress router for that destination. That turns an exponential search over egress subsets into a linear scan over border routers. When operators install exception paths such as MPLS traffic-engineering tunnels, the theorem no longer holds verbatim, but the search still only needs to include one ordinary egress plus the egresses that terminate those exception paths. The paper then pairs this state-space reduction with a traffic-matrix approximation: cluster destinations whose traffic is distributed similarly across ingress routers, and use the clustering error to bound the worst-case-load error.

## Design

Velo takes router configurations, the current BGP routes, a traffic matrix indexed by ingress router and destination prefix, operator constraints on route changes, and a space of failure scenarios. The traffic model is deliberately per-destination rather than per-ingress/egress pair, because BGP changes are destination-specific. Operators can further cap the number of allowed egress changes, declare some destinations stable, or restrict which border routers may advertise certain prefixes.

For a fixed topology and one destination, Velo searches over egress choices rather than over raw BGP attributes. With strictly isotone routing, it constructs a forwarding DAG rooted at each border router, pushes the destination's traffic through that DAG in topological order, and records the maximum contribution to every link. Repeating that process for all destinations yields worst-case per-link loads in polynomial time rather than over the exponential set of possible route combinations. If the network contains exception paths, Velo expands the search just enough to include combinations involving the egresses of those paths, which preserves correctness while avoiding a full blow-up.

The system also handles two practical complications. First, if operators only care about up to `k` route changes, Velo maintains for each link the `k` destinations whose worst-case state increases that link's load the most. Second, because real routing tables can contain around a million destinations, Velo compresses the traffic matrix before analysis. It groups together only destinations that share the same current egress set and identical forwarding behavior for any allowed egress choice, then runs a normalized, traffic-weighted k-means variant over their ingress distributions. The resulting smaller matrix comes with a theorem: the clustering error `ε` upper-bounds the approximation error `δ` on worst-case link loads. Traffic uncertainty is handled conservatively by letting operators specify an additional traffic budget `y`; Velo computes worst-case loads for the nominal matrix and then adds up to `y` to each link, which the paper argues is exact in the common case where some router-destination flow fully traverses that link.

## Evaluation

The prototype is about 7,000 lines of Rust and is evaluated on the 75 largest Topology Zoo networks, ranging from 80 to 1,790 links, plus both real and synthetic traffic matrices. The headline scalability result is strong for the problem regime the paper claims to target. With up to two simultaneous link failures, 30 border routers, and 300 traffic clusters, Velo computes worst-case loads for every link in the largest 1,790-link topology in about one minute for single failures and about three hours for double failures; all the other topologies finish within two minutes for up to two failures. The paper attributes the remaining cost mostly to the analysis phase rather than clustering once networks become large.

The accuracy story is also convincing. On four real traffic matrices from the Swiss research network, the theoretical error bound is around 3.5% to 5.6%, while the actual approximation error stays around 0.4% to 0.7%. On synthetic matrices generated from a gravity model, the approximation error remains below 1% even when traffic is made less skewed and therefore harder to compress. The clustering method is also much more efficient than a heavy-hitter baseline that simply keeps the top-traffic destinations: depending on the traffic shape, Velo's approximation needs 5x to 50x fewer effective destinations to provide comparable guarantees.

The comparison with QARC is important because QARC is the closest prior load-verification system. Under a no-route-change setting where both systems are comparable, Velo is several orders of magnitude faster for up to two simultaneous failures and still 10x to 100x faster for three or four failures. The paper argues that this comes from reducing the problem to repeated graph computations rather than solving an ILP. Finally, the ISP case study shows practical leverage: Velo finds that four egress changes can overload two links in a 126-router ISP, suggests extra MPLS paths that raise robustness to sixteen changes, and helps evaluate whether adding a new IXP link is better than simply upgrading capacity.

## Novelty & Impact

The main novelty is not just another link-load checker. Velo is the paper's claim that worst-case performance verification becomes tractable if route changes are abstracted at the egress-router level and paired with a theorem that collapses the worst-case search to a small state set. The traffic-clustering theorem matters as well, because it turns scalability from "works for a few important prefixes" into "works for full routing tables with explicit error guarantees."

That makes the work useful beyond offline what-if analysis. An operator can use Velo before deployment, during configuration tuning, when planning peering or capacity upgrades, or as a trigger for fast traffic-engineering reactions once a dangerous combination of egress changes begins to materialize. I expect later systems work on performance-aware control-plane verification to cite this paper primarily for that abstraction boundary: reason about egress choices and quantified traffic uncertainty, not raw BGP message space.

## Limitations

Velo's strongest theorem depends on strictly isotone intra-domain routing. The paper does extend the algorithm to exception paths, but that extension still assumes those exceptions are explicit and limited enough that their terminating egresses can be enumerated. Networks with richer policy interactions or many engineered paths may weaken the efficiency story.

The system model also excludes some real-world complications. It assumes routers eventually learn their preferred routes without iBGP visibility problems, and it requires destinations to be independent, ruling out features such as route aggregation or conditional advertisements. Velo computes load by summing routed traffic rather than simulating congestion feedback, so once a link is overloaded it does not model how downstream loads would fall after packet drops. The additional-traffic model is conservative and can overestimate some links, and the paper leaves systematic exploration of newly appearing sub-prefixes to future work.

## Related Work

- _Subramanian et al. (PLDI '20)_ - `QARC` verifies link-load violations under failures, but it assumes fixed external routes; `Velo` adds route-change reasoning and computes worst-case loads for all links.
- _Li et al. (NSDI '24)_ - `Jingubang` reasons about network traffic-load properties at production scale for specified scenarios, whereas `Velo` targets exhaustive worst-case analysis over failures plus bounded route changes.
- _Li et al. (SIGCOMM '24)_ - `YU` generalizes traffic-load verification to arbitrary `k` failures, but it still operates in the fixed-route world that `Velo` argues is insufficient for Internet-connected networks.
- _Steffen et al. (SIGCOMM '20)_ - `NetDice` can express probabilistic link-load properties, yet the `Velo` paper positions it as unable to scale to the many ingress-destination pairs required for worst-case load verification.

## My Notes

<!-- empty; left for the human reader -->
