---
title: "FailureMiner: A Joint Key Decision Mining Scheme for Practical SSD Failure Prediction and Analysis"
oneline: "FailureMiner keeps boundary-case healthy SSDs, then mines compact joint threshold rules that predict and explain production SSD failures better than prior RF- and LSTM-based baselines."
authors:
  - "Shuyang Wang"
  - "Yuqi Zhang"
  - "Haonan Luo"
  - "Kangkang Liu"
  - "Gil Kim"
  - "JongSung Na"
  - "Claude Kim"
  - "Geunrok Oh"
  - "Kyle Choi"
  - "Ni Xue"
  - "Xing He"
affiliations:
  - "Samsung R&D Institute China Xi'an, Samsung Electronics"
  - "Tencent"
  - "Samsung Electronics"
conference: fast-2026
category: flash-and-emerging-devices
tags:
  - storage
  - observability
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

FailureMiner combines boundary-preserving downsampling with joint decision mining. Instead of shipping a full random forest, it extracts a few threshold combinations that both predict SSD failures and explain them. On Tencent's production telemetry, those rules reach `82.2%` precision and `29.6%` recall, outperforming RF, CNN-LSTM, WEFR, and MVTRF.

## Problem

Enterprise SSD failure prediction is hard because failures are rare, logs are noisy, and operators care more about false alarms than marginal recall. Naive downsampling removes exactly the healthy samples closest to failure patterns, so the model loses the examples it most needs to learn the boundary. Feature selection can also discard auxiliary attributes that matter only in combination, while attribute-level explanations still do not tell operators which threshold combinations correspond to which failure modes or how urgent those modes are.

## Key Insight

The paper's main claim is that the right unit of simplification is a decision set, not a feature. FailureMiner keeps healthy samples that resemble each failure cluster so the model learns the subtle distinction between "failing" and "looks suspicious but is fine," then mines the trained forest for threshold decisions that are both high-impact and repeatedly co-occur on true-positive paths. That preserves useful weak signals, suppresses frequent but low-value splits, and naturally produces named patterns such as NAND `UECC` spikes, spreading DRAM ECC errors, or collapsing `CapHealth`.

## Design

FailureMiner first generates temporal features `Delta_w A` over `3`, `7`, and `15` day windows. It then clusters only failed SSD samples, using JIC-selected attributes and K-means with a default of `50` clusters. Each cluster boundary is the maximum failed-sample distance to the centroid. Healthy samples are added to a cluster only if they fall within that boundary, plus a small random set to avoid overfitting. A separate random forest is then trained per cluster using all raw Telemetry attributes and all temporal features.

The second stage inspects only RF paths that correctly classify failed SSDs. Each split receives a decision-level impact score derived from SHAP, and splits above the threshold become candidate key decisions. An Apriori-like expansion then forms co-occurring decision sets, scoring each set by average impact times co-occurrence frequency. This removes noisy high-frequency splits and keeps small joint rules; on Tencent, `117,404` original tree decisions collapse to just three strong rules.

## Evaluation

The main evaluation uses Tencent's production Telemetry trace: more than `70` million logs from over `350,000` Samsung PM9A3 SSDs collected across about two years, plus `788` reported failures. Training uses months `1-13`; testing uses months `14-23`. The paper also checks generality on Alibaba's public SMART dataset with more than `10` million logs from `20,000` SSDs. Baselines are RF, CNN-LSTM, WEFR, and MVTRF.

On Tencent, FailureMiner reaches `82.2%` precision, `29.6%` recall, and `0.61` `F0.5`, versus `55.4%` / `20.4%` / `0.41` for RF and `68.1%` / `19.6%` / `0.46` for MVTRF. The paper summarizes this as average gains of `38.6%` in precision and `80.5%` in recall over prior methods. Ablation shows both components matter: boundary-preserving downsampling alone adds `21.7%` precision and `13.7%` recall over RF, while joint key extraction alone adds `20.4%` and `25.5%`. The rules are also cheap to run: reported prediction time is `6` seconds, versus `167` for RF, and Tencent says the deployed rules predicted more than one hundred SSD failures online over more than a year.

## Novelty & Impact

The paper's novelty is not a new classifier. It is a reframing of failure prediction around deployable, human-readable joint rules. Compared with prior RF- or LSTM-based predictors, interpretability is the primary output rather than an after-the-fact diagnostic. Compared with WEFR-style feature pruning, the paper argues that models should remove bad decisions, not necessarily bad features. The result is a concise rule set tied to concrete mechanisms such as NAND defects, DRAM defects, and capacitor or `PLP` degradation.

## Limitations

The method depends heavily on rich telemetry and on attribute semantics that humans can understand. It is strongest on Tencent's Samsung Telemetry data; on Alibaba's SMART trace, the extracted rules degrade into predicates over fields like `r198` and `r174`, which weakens interpretability even if accuracy remains good. Recall is also still limited: `29.6%` is strong for a precision-first setting, but most failures are still missed by the strong rules. Finally, the thresholds are learned from two datasets and effectively one main SSD family, so other sites would need retraining and revalidation.

## Related Work

- _Alter et al. (SC '19)_ - studies SSD failures in the field with RF-style prediction models, while FailureMiner keeps RF but compresses it into operator-readable joint rules.
- _Lu et al. (FAST '20)_ - SMARTer emphasizes temporal features and deep models, whereas FailureMiner centers boundary-preserving sampling and decision-level interpretability.
- _Xu et al. (DSN '21)_ - WEFR removes noisy attributes through ensemble feature ranking; FailureMiner argues that useful auxiliary signals are better preserved and pruned at the decision level instead.
- _Zhang et al. (FAST '23)_ - MVTRF uses multi-view temporal features to explain what and when failures happen, while FailureMiner mines co-occurring threshold combinations that directly encode failure patterns.

## My Notes

<!-- empty; left for the human reader -->
