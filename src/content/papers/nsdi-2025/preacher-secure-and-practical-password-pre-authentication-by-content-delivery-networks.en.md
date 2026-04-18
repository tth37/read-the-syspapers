---
title: "PreAcher: Secure and Practical Password Pre-Authentication by Content Delivery Networks"
oneline: "PreAcher lets a CDN pre-authenticate password logins with OPRF plus LSH, filtering ADoS traffic while hiding the password from the CDN."
authors:
  - "Shihan Lin"
  - "Suting Chen"
  - "Yunming Xiao"
  - "Yanqi Gu"
  - "Aleksandar Kuzmanovic"
  - "Xiaowei Yang"
affiliations:
  - "Duke University"
  - "Northwestern University"
  - "University of Michigan"
  - "University of California, Irvine"
conference: nsdi-2025
category: security-and-privacy
code_url: "https://github.com/SHiftLin/NSDI2025-PreAcher"
tags:
  - security
  - networking
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

`PreAcher` moves the first stage of password login to the CDN without revealing the password to it. It combines OPRF with locality-sensitive hashing so the CDN can reject obviously wrong passwords, while the origin server still performs the final ordinary password check; on the paper's testbed it sustains 97 successful logins per second under a 400 req/s ADoS attack that collapses the baseline to zero.

## Problem

Password login is easy to deploy and familiar to users, but secure password storage makes the login path expensive. Servers must run slow hashing such as `PBKDF2` or `Argon2`, which means an attacker does not need volumetric DDoS traffic to cause trouble: a modest stream of login attempts can saturate CPU and deny service to legitimate users. The paper shows this directly with a proof-of-concept deployment behind a commercial CDN, WAF, and bot-detection service. Using rotating proxy IPs, only 150 login requests per second with random credentials are enough to keep a 4-vCPU server at nearly 100% CPU for an hour.

Existing defenses do not satisfy all three requirements at once: block login-path ADoS, keep passwords secret from the CDN, and remain practical for today's web. Rate limits, CAPTCHA, and 2FA either hurt usability or still leave the server doing the first password check. Delegated authentication offloads work, but many sites cannot trust a third party with their primary login flow. Meanwhile, current CDN bot filtering is statistical rather than deterministic, and because websites commonly share TLS private keys with CDNs, the CDN can often see the password payload itself. The paper therefore asks for something narrower and more deployable: let the CDN filter bad password attempts before they hit the origin server, but do so without giving the CDN the password.

## Key Insight

The crucial idea is that the CDN does not need to know whether a password is exactly correct. It only needs a cheap test that separates obviously wrong passwords from passwords similar enough to deserve a full check at the origin server. `PreAcher` therefore weakens what the CDN learns on purpose: instead of exact correctness, it learns only whether the supplied password maps to the same locality-sensitive bucket as the real one.

That distinction is what makes the security story work. If the CDN could fully verify passwords, then a passive but curious CDN could run offline dictionary attacks from its own logs and state. `PreAcher` combines OPRF with locality-sensitive hashing so similar passwords collide to the same pseudo-password `p'`, which is enough for pre-authentication but insufficient for offline confirmation of the exact password. In effect, the system trades exactness at the edge for bounded ambiguity, forcing any serious password guessing back into online interaction with the origin server.

## Design

`PreAcher` has a registration phase and a two-round login phase. During registration, the client and origin server derive a secret `d'` from `LSH(p)` and a per-user OPRF secret `k_u`. The client then generates a public/private key pair `pk'_u` and `sk'_u`, encrypts `sk'_u` into an envelope `e'_u` using `d'`, and gives the server the information needed for conventional full authentication as well. The origin server stores the usual salted password hash for later full authentication, but it also sends `k_u`, `pk'_u`, and `e'_u` to the CDN so the CDN can participate in future pre-authentication. This split is deliberate: the server side stays compatible with existing website login stacks, while the CDN gets only the minimum material needed to reject bad attempts early.

Login begins with the client interacting with the CDN to reconstruct `d'`. The client computes `LSH(p)`, runs the OPRF exchange with the CDN, and uses the resulting `d'` to decrypt `e'_u` and recover `sk'_u`. In the second round, the client signs the CDN's challenge `C` with `sk'_u` for pre-authentication, and in parallel encrypts the real password to the origin server's public key for full authentication. The CDN verifies the signature with stored `pk'_u`. If that check fails, the request dies at the edge; if it succeeds, the CDN forwards only the encrypted password blob to the origin server, which decrypts it and performs ordinary salted-password verification. The server still sees the password, because the threat model trusts the origin server and the authors want to avoid an extra RTT and preserve compatibility.

The LSH design is the other core mechanism. `PreAcher` uses weighted K-mer MinHash over lowercased passwords, hashing K-mers with `HMAC-SHA256` and the username so that mappings vary across users. Small edit-distance variants therefore collide to the same `p'`, which blurs the CDN's ability to distinguish the exact password offline. At the same time, random brute-force passwords collide only with probability `1/c^K`. With the paper's example parameters `K=4` and alphabet size `c=66`, fewer than `10^-7` random guesses should pass pre-authentication. The paper contrasts this with `DuoHash`, an intuitive double-hash alternative that still requires slow password hashing on the CDN and therefore defeats the performance goal.

## Evaluation

The evaluation checks both the security tradeoff and the systems cost. For the offline-guessing side, the authors take 5,000 users from the 4iQ leak, treat one historical password as known to the CDN, and use `pass2path` to generate 10,000 guesses per account. Without LSH, the CDN can crack about 8.42% of accounts offline. With LSH plus the paper's default detection threshold `Q=20` and `K=4`, the undetected cracking rate falls below 0.20% while the random-guess pass probability remains below `10^-7`. That is the paper's central balance: preserve enough collisions to frustrate CDN-side inference, but not enough to let random attack traffic through.

For ADoS resilience, the testbed sends 100 valid logins per second plus 400 attack logins per second. The baseline serves 100 successful logins per second without attack and 0 under attack. `PreAcher` serves 100 without attack and 97 under attack. `DuoHash` and the SGX-based strawman both degrade badly because slow hashing overloads the CDN itself. The mechanism-level numbers line up with that result: on the testbed, `PreAcher` handles 948 rejected pre-authentication requests per second at 23% CPU, versus 99 req/s for `DuoHash` and 91 req/s for SGX-CDN, both at 100% CPU.

The costs are visible but reasonable for a login path. On the testbed, median CDN pre-authentication CPU time is only 0.16 ms for `PreAcher`, but on Cloudflare it rises to 8.3 ms because the deployed edge logic uses JavaScript rather than the prototype's C++. The protocol also adds a second client-to-CDN RTT. Across six Azure regions, the median successful-login latency overhead is typically 42-72 ms relative to the baseline, with a larger outlier in Johannesburg because Cloudflare routes the request to a farther edge location. The paper's practical claim is therefore credible: `PreAcher` is not free, but its overhead is small enough for login traffic and far lower than the edge-side hashing alternatives.

## Novelty & Impact

The novelty is not merely "use a CDN for authentication." The paper's contribution is a three-party architecture that gives the CDN enough authority to shed abusive load without giving it enough information to verify passwords exactly. OPAQUE-style PAKEs motivate the OPRF-and-envelope structure, but they do not solve the middlebox case by themselves. The added LSH layer is what makes the CDN useful without turning it into a password oracle.

That makes the work important for large websites already fronted by CDNs and already exposed to credential-stuffing or login-flood pressure. The deployment story is unusually pragmatic: a login-page JavaScript library on the client, server-side changes at the origin, and edge code on existing CDN serverless platforms. No browser changes, CDN hardware changes, or new trust anchor are required. I expect the paper to matter both to web-security researchers and to practitioners who want a deployable defense for password login abuse.

## Limitations

The paper's security model assumes a passive honest-but-curious CDN attacker. It explicitly does not solve the case where a compromised CDN can actively tamper with protocol messages, though the authors argue that external integrity mechanisms could be combined with `PreAcher`. Registration is also assumed to be ADoS-resistant, which is plausible for one-time onboarding or high-friction sign-up flows, but it is still an assumption. More broadly, `PreAcher` protects only passwords on the login path; it does not hide arbitrary post-login application traffic or cookies from the CDN.

There is also a real tuning tradeoff in the LSH parameters. Smaller `K` makes CDN-side cracking harder but lets more near-passwords through to the server; larger `K` sharpens filtering but reveals more to a curious CDN. The paper chooses `K=4` and `Q=20` from simulations, yet it does not study typo-heavy real user populations or long-term operational false positives. The evaluation is strong as a prototype study, but it is still a prototype study rather than a production deployment over months of real login behavior.

## Related Work

- _Jarecki et al. (EUROCRYPT '18)_ - `OPAQUE` is a two-party asymmetric PAKE; `PreAcher` borrows the OPRF-and-envelope structure but extends it to a CDN-mediated three-party login.
- _Lin et al. (CCS '22)_ - `InviCloak` builds an end-to-end confidential channel through a CDN, whereas `PreAcher` narrows its scope to password secrecy and ADoS filtering on the login path.
- _Xin et al. (PAM '23)_ - This measurement study quantifies how often third-party CDNs can see user passwords; `PreAcher` turns that exposure into a concrete defensive architecture.
- _Herwig et al. (USENIX Security '20)_ - `Conclaves` uses TEEs to protect CDN-hosted TLS processing, while `PreAcher` avoids special hardware and focuses on filtering abusive password logins.

## My Notes

<!-- empty; left for the human reader -->
