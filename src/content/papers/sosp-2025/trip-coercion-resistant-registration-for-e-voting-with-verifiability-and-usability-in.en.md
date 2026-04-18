---
title: "TRIP: Coercion-resistant Registration for E-Voting with Verifiability and Usability in Votegral"
oneline: "TRIP uses a kiosk, paper envelopes, and interactive-proof transcripts to issue real and fake voting credentials that voters can verify, but coercers cannot distinguish."
authors:
  - "Louis-Henri Merino"
  - "Simone Colombo"
  - "Rene Reyes"
  - "Alaleh Azhir"
  - "Shailesh Mishra"
  - "Pasindu Tennage"
  - "Mohammad Amin Raeisi"
  - "Haoqian Zhang"
  - "Jeff R. Allen"
  - "Bernhard Tellenbach"
  - "Vero Estrada-Galiñanes"
  - "Bryan Ford"
affiliations:
  - "EPFL"
  - "King's College London"
  - "Boston University"
  - "Harvard University"
  - "Yale University"
  - "Armasuisse S+T"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764837"
code_url: "https://github.com/dedis/votegral"
tags:
  - security
  - formal-methods
  - verification
category: embedded-os-and-security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

TRIP is the registration half of Votegral, a remote e-voting architecture that tries to make fake credentials practical without assuming trusted voter hardware at registration time. Its core move is to use a kiosk, paper envelopes, and transcripts of interactive zero-knowledge proofs so the voter learns which credential is real inside the booth, while everything they carry out later looks indistinguishable to a coercer.

## Problem

Remote voting is attractive because it avoids polling-place queues, travel, and the logistical pain of voting from abroad, but it weakens the protection that in-person voting gets almost for free from the privacy booth. A coercer, abusive partner, or vote buyer can simply watch the voter cast a ballot or demand evidence afterward. End-to-end verifiable e-voting makes that tension worse: if voters can cryptographically verify that their ballot was recorded and counted, they often also gain a receipt they can show to a coercer.

Fake credentials are a well-known answer to this problem. If voters hold both a real credential and one or more fake ones, they can appear to comply while secretly casting their true ballot later. The hard part is registration. Prior systems either rely on a trusted registrar, assume the voter already has uncompromised trusted hardware, or ask the voter to interact with multiple registrars. Those assumptions are either politically awkward, expensive, or fragile under actual coercion. The paper therefore asks for a registration design that simultaneously gives voters confidence that one credential is real, prevents them from proving which one it is later, and packages the whole process in a workflow ordinary voters can follow.

## Key Insight

The paper's key insight is that the crucial secret is not a cryptographic object the voter must memorize, but one bit of procedural knowledge: whether the kiosk committed to a proof before or after seeing the voter's challenge. TRIP encodes this by using interactive zero-knowledge proofs in Sigma-protocol form. For a real credential, the kiosk prints the commitment first, then the voter chooses an envelope whose QR code supplies the challenge. For a fake credential, the voter selects the envelope first, so the kiosk can forge an unsound transcript tailored to that challenge.

Once printed, both real and fake credentials contain only paper transcripts of an interactive proof. Structurally they look the same, and the voter leaves the booth with no transferable proof of which one was created honestly. That is the central proposition of the paper: the order of the visible physical steps can carry the non-transferable knowledge needed for individual verifiability, while the printed artifact remains deniable afterward.

## Design

Votegral's overall architecture separates registration, activation, voting, and tallying. During registration, the voter checks in with an official, enters a privacy booth, and interacts with a kiosk plus a supply of marked envelopes. A real credential is created in four steps: the voter scans a check-in ticket; the kiosk prints a symbol and QR code; the voter picks an envelope with the matching symbol and scans it; then the kiosk prints two more QR codes that complete the receipt. The voter inserts the receipt into the envelope and marks it privately as their real credential. Fake credentials are created with the opposite order: the voter picks an envelope first, then the kiosk prints the full receipt afterward, allowing it to synthesize a bogus but well-formed proof transcript.

Cryptographically, each credential has its own signing key pair, but all credentials from one session share the same public credential tag. That tag is an encryption of the real credential's public key. At check-out, the official scans any one credential through the envelope window; because every credential from the session carries the same public tag, the official learns nothing about which one is real. Later, on a trusted device, the voter activates credentials by partially sliding the receipt out of the envelope and scanning the now-visible QR codes. Votes cast with credentials authenticate as usual, but at tally time the system shuffles both registration tags and ballots, blinds them in parallel, and counts only ballots whose credential key matches a blinded registration tag. Since only the real credential key matches the encrypted real-key tag, fake votes are discarded without revealing which credential was real.

The physical design matters as much as the cryptography. Envelopes act as low-cost challenge carriers, sparing voters from generating randomness manually. Their transparent window exposes only the check-out QR code during transport, while hiding the secret material until activation. The protocol also leans on process design: the instructional video and the symbol-matching step are meant to teach voters that real credentials follow one visible order and fake credentials another. The authors' security argument then splits trust carefully. Ordinary voters need not trust the registrar for election correctness because the ledger and tally remain publicly verifiable; only voters who are actively coerced need to trust the kiosk not to collude with the coercer.

## Evaluation

The prototype focuses on the cryptographic path but is still substantial: TRIP itself is 2,633 lines of Go, while the full Votegral prototype is 9,182 lines. Registration latency is the most important practical number because this design requires an in-person booth visit. Across a point-of-sale kiosk, a Raspberry Pi 4, a MacBook Pro VM, and a mini PC, the end-to-end voter-visible registration time ranges from 15.8 seconds to 19.7 seconds. QR scanning and printing dominate that budget, accounting for at least 69.5% of wall-clock time, which means the design looks mechanically rather than cryptographically bottlenecked.

Compared with other e-voting systems, TRIP's registration cost is competitive. At a one-million-voter scale, per-voter registration latency is 1.2 ms for TRIP-Core, versus 13 ms for Swiss Post, 0.1 ms for VoteAgain, and 771 ms for Civitas. Votegral's voting path is also cheap at roughly 1 ms per voter. Tallying is slower, but still within the range of practical large-election backends: about 14 hours for one million ballots, compared with 3 hours for VoteAgain, 27 hours for Swiss Post, and an estimated 1,768 years for Civitas' quadratic filtering. The paper is candid that VoteAgain is faster because it accepts stronger trust assumptions and the usual revoting weakness that a coercer who controls the voter until polls close can still win.

The usability evidence is encouraging but not conclusive. In the main study with 150 participants, 83% successfully created and used their real credential, and the system received a System Usability Scale score of 70.4, slightly above the nominal industry average. Detection of a malicious kiosk is weaker: 47% of participants who received security education detected and reported it, versus 10% without that education. Those results support the paper's claim that the workflow is teachable, but they also show that a single-registration attack on a specific voter is not impossible; the security story is strongest when the attacker must repeat that trick many times without being reported.

## Novelty & Impact

The paper's main novelty is to make fake-credential registration concrete. JCJ-style systems introduced the idea of real and fake credentials, but left registration behind an abstract untappable channel or cumbersome trust structure. TRIP replaces that abstraction with a full socio-technical mechanism: in-person registration, paper carriers, kiosk-issued proof transcripts, public logging, activation, and usability testing. The use of paper transcripts of interactive zero-knowledge proofs to get verifiability without transferable evidence is the sharpest technical contribution.

That contribution is broader than e-voting mechanics. The paper treats election security as a systems problem spanning cryptography, physical workflow, device trust, human training, and throughput. Its discussion of proof-of-personhood and democratic computing is speculative, but credible: if a system can distinguish "the voter knows the real credential" from "the voter can prove that fact to someone else," the same pattern could matter in other settings where participation must be human and uncoerced.

## Limitations

The most obvious limitation is deployment friction. TRIP only amortizes rather than removes the need for in-person registration, and real deployments would need policies for booth supervision, device check-in, voter notification after registration, credential renewal, and support for accessibility needs. That is a large operational surface compared with ordinary web-based voting proposals.

The security model is also qualified. The paper assumes a correct voter roster, a tamper-evident public ledger, threshold trust in the tally authority, and an anonymous enough voting channel that coercers cannot simply monitor whether the voter later connects to cast a real ballot. Side channels, physical attacks, and several impersonation subtleties are pushed to appendices or future work. Finally, the user study and the formal model do not erase the residual single-voter risk: a malicious kiosk that correctly guesses the challenge envelope, or fools a voter who fails to notice the wrong step order, can still compromise that voter even if repeated attacks become statistically detectable.

## Related Work

- _Juels et al. (TTE '10)_ - JCJ introduced coercion-resistant voting with real and fake credentials, but assumed an abstract untappable registration channel; TRIP is a concrete, paper-based realization of that missing step.
- _Clarkson et al. (S&P '08)_ - Civitas reduces trust in any one registrar by requiring interaction with multiple registration tellers, whereas TRIP keeps a single in-person visit and shifts the non-transferable assurance into the kiosk-envelope workflow.
- _Krivoruchko (IAVoSS WOTE '07)_ - Robust coercion-resistant registration asks voters to generate and encrypt their own real credential on a device before registration; TRIP removes that trusted-device requirement and proves realness interactively instead.
- _Moran and Naor (CRYPTO '06)_ - Receipt-free voting also used interactive zero-knowledge proofs to avoid transferable evidence, but at ballot-casting time; TRIP repurposes that idea for registration and materializes it with paper transcripts and envelopes.

## My Notes

<!-- empty; left for the human reader -->
