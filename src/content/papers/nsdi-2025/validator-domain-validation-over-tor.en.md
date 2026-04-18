---
title: "ValidaTor: Domain Validation over Tor"
oneline: "ValidaTor sends HTTP domain validation through randomly selected Tor exits, turning fixed CA validators into an unpredictable pool with better path diversity and practical throughput."
authors:
  - "Jens Frieß"
  - "Haya Schulmann"
  - "Michael Waidner"
affiliations:
  - "National Research Center for Applied Cybersecurity ATHENE"
  - "Technische Universität Darmstadt"
  - "Goethe-Universität Frankfurt"
conference: nsdi-2025
code_url: "https://github.com/jenfrie/tova"
tags:
  - security
  - networking
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

`ValidaTor` reuses Tor exit nodes as CA validators for HTTP-based domain validation. The key move is not merely adding more vantage points, but making validator choice random and hard to target in advance. In the authors' prototype, that change cuts path overlap versus Let's Encrypt's fixed deployment, keeps median validation around 2 seconds with 5 validators, and still imposes only an estimated 0.11% load on Tor's remaining bandwidth at Web PKI scale.

## Problem

Domain validation is the weakest indispensable step in Web PKI issuance. Before signing a certificate, a CA must check that the requester controls the domain, typically by asking for a challenge value through DNS or HTTP. That exchange runs over infrastructure that is only partially protected: DNS can be poisoned, BGP can be hijacked, and an attacker that steers the CA's query to attacker-controlled infrastructure can obtain a fraudulent certificate.

The community already knows that a single validator is inadequate, which is why Let’s Encrypt and ACME moved to multi-vantage validation. But the paper argues that "more validators" is still not enough when the validator set is small and static. Prior work showed that an attacker can pre-target fixed validation nodes, or even force them toward an attacker-chosen nameserver, collapsing the defense back to a few predictable choke points. In other words, MultiVA improves robustness against naive interception, but it does not solve the adversary's planning advantage.

The deployment problem is what keeps this weakness alive. A CA could in principle build dozens of globally distributed validators, but that means paying for and operating dedicated infrastructure at scale. The authors' claim is that DV needs a validator pool large enough that exhaustive targeting becomes impractical, yet cheap and compatible enough that a CA could actually adopt it.

## Key Insight

The central proposition is that DV needs unpredictability as much as multiplicity. If the attacker cannot know in advance which validators will participate in a given validation, targeted attacks such as pre-positioned BGP hijacks or DNS manipulations become much harder to execute.

Tor provides the missing ingredient. Instead of treating Tor primarily as an anonymity system, the paper treats it as an already-deployed, massively distributed proxy fabric with more than 2,200 exit nodes, 1,221 unique exit IPs, and 280 de-aggregated BGP origins at measurement time. A CA can therefore draw a fresh random validator set per validation without deploying validators at each location itself. Because DNS resolution also happens near the exit, the system diversifies not just the HTTP fetch path but also the resolver side of the attack surface.

This works only if selection is constrained enough to avoid correlated choices. `ValidaTor` therefore combines random selection with prefix-aware exclusion and k-out-of-n agreement: the system picks validators from different network regions, starts with `k` exits, and adds more only when responses disagree. The result is a security argument built from two effects: attackers cannot pre-target the exact validators, and well-positioned ASes see fewer of the resulting paths simultaneously.

## Design

`ValidaTor` is implemented as a containerized service with four pieces: a Tor daemon, a custom circuit-management service, a web server, and a Flask application that runs the validation logic. A CA or ACME client sends the challenge URL to `ValidaTor`; worker processes then issue the fetches through Tor and aggregate the returned responses.

The hardest engineering issue is circuit control. Tor's default behavior is optimized for anonymity, not for "use distinct exits for this one validation." The authors therefore use Tor's `stem` control interface to manually build circuits and assign streams. Exit nodes are sampled uniformly from relays marked `EXIT` but not `BADEXIT`, and validators for the same domain are forced onto distinct network prefixes by excluding nodes that share a configurable `/8` prefix. To keep the selection space large without fighting Tor's own circuit lifecycle too much, the implementation maintains roughly 50-60 concurrent circuits and rebuilds them every 3 minutes.

The paper also cuts Tor's default three-hop path to two hops. Since the CA is not trying to hide its own identity, the system keeps only a guard and an exit, which reduces latency. Entry nodes are chosen from `GUARD` and `FAST` relays, weighted toward high bandwidth and shorter prefix distance from the server. Validation itself follows Let’s Encrypt's familiar pattern: start with `k` validators, compare the fetched challenge bodies, and if the first set does not agree, add validators up to a maximum `n`. If at least `k` responses match, that value is returned to the CA; otherwise validation fails.

Two practical details matter. First, the design requires no changes to the CA's existing DV logic beyond redirecting challenge fetches through the `ValidaTor` service, so adoption is operationally lightweight. Second, the system currently supports only HTTP/HTTPS validation, not DNS TXT validation, because Tor does not expose TXT lookups through its DNS interface.

## Evaluation

The evaluation is strongest because it covers both systems performance and attack resistance. On the performance side, a single container reaches `2.7` validations/s with `k=3`, `2.1` with `k=5`, and `1.6` with `k=7`. Horizontal scaling works cleanly: with 3 containers and `k=5`, throughput rises to `6.5` validations/s, and with 10 containers it reaches `11.9` validations/s. For the 5-validator setting, the median validation time is about 2 seconds and at least 95% of validations complete within 6 seconds, which is in the same operational ballpark as `certbot`.

The bandwidth results are equally important for deployability. Extrapolating from measured traffic and certificate issuance rates, the authors estimate that even if the entire Web PKI used `ValidaTor`, it would consume about `635.2 Mbit/s` across the Tor network in total, or `317.6 Mbit/s` at exit nodes. That corresponds to only `0.11%` of Tor's remaining total bandwidth and `0.15%` of the exits' remaining bandwidth. So the design is not just secure in principle; it appears affordable to the shared network it depends on.

The security evaluation compares path diversity with Let's Encrypt's present MultiVA deployment. The difference in available perspectives is dramatic: the authors observe 7 de-aggregated BGP origins for Let's Encrypt's validators, versus 280 for Tor exits, and 9 DNS-resolver origins for Let's Encrypt versus at least 174 for Tor-based validation. In path simulations, average path overlap falls by roughly 50% compared with Let's Encrypt. More concretely, the number of ASes that can intercept all validators for a domain drops by `21%` with 3 validators and by up to `27%` with 7 validators. The malicious-exit analysis is also reassuring: with staged `k`-out-of-`n` selection and prefix-aware exclusion, the probability of fraudulent validation stays below 1% even when an attacker controls roughly a quarter of Tor exits and `k=7`.

One sobering result is that about 20% of validation requests fail because destinations themselves block Tor traffic. The authors show that failures are highly correlated across validators, which suggests domain-side blocking rather than systematic suppression by transit ASes. That does not break the security claim, but it does narrow where immediate deployability is strongest.

## Novelty & Impact

The novelty is both architectural and strategic. Architecturally, `ValidaTor` is a concrete DV system that composes manual Tor circuit selection, distributed validator sampling, and k-out-of-n response aggregation into something a CA could plausibly run today. Strategically, it reframes Tor as shared open infrastructure for hardening PKI, not just as an anonymity tool.

That makes the paper more interesting than "use more validators." It shows that the real gap in current DV is the lack of a large, unpredictable validator pool. I expect this paper to matter to CA operators, ACME designers, and researchers working on BGP-resistant certificate issuance, because it turns a long-standing deployment objection into a tractable systems design.

## Limitations

The biggest limitation is scope. `ValidaTor` only supports HTTP-based validation today because Tor does not support DNS TXT lookups in the needed way. Since DNS-based DV remains common, the system is not a full replacement for every validation mode.

There is also a realism gap in the security analysis. The path-diversity results are built from real measurements plus BGP-path simulation, not from observing live adversaries. Likewise, the colluding-exit analysis depends on probabilistic modeling and assumptions about prefix distribution. Those are reasonable methods, but they are still models.

Finally, Tor is not a frictionless substrate. The implementation becomes unstable above roughly 70-80 open circuits, destination-side Tor blocking causes about one fifth of validation attempts to fail, and malicious exit nodes remain a residual risk that must be controlled by Tor's existing monitoring plus conservative choices of `k`. The paper's contribution is therefore a strong hardening mechanism, not a proof that DV over Tor is free of deployment or ecosystem constraints.

## Related Work

- _Brandt et al. (CCS '18)_ - `Domain Validation++` hardens DV against man-in-the-middle attacks, but it still assumes more conventional validator deployment rather than a large randomized public proxy fabric.
- _Birge-Lee et al. (USENIX Security '18)_ - `Bamboozling Certificate Authorities with BGP` showed how predictable multi-vantage validation can still be subverted, which is exactly the planning advantage `ValidaTor` tries to remove.
- _Cimaszewski et al. (USENIX Security '23)_ - This measurement study quantified how resilient current multiple-vantage-point DV is; `ValidaTor` extends that line by improving both validator and DNS-resolver diversity.
- _Frieß et al. (HotNets '24)_ - `ADDVent` also seeks massive distributed validation, but it crowdsources browser clients through ad networks, whereas `ValidaTor` uses Tor's existing relay ecosystem and avoids trusting an ad platform.

## My Notes

<!-- empty; left for the human reader -->
