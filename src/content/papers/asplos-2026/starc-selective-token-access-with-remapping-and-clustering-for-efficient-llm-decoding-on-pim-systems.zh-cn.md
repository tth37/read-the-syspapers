---
title: "STARC: Selective Token Access with Remapping and Clustering for Efficient LLM Decoding on PIM Systems"
oneline: "STARC 将语义相近的 KV 对重排到按行对齐的 PIM 布局里，让稀疏 LLM 解码真正跳过整行访问而不明显损失相关性。"
authors:
  - "Zehao Fan"
  - "Yunzhen Liu"
  - "Garrett Gagnon"
  - "Zhenyu Liu"
  - "Yayue Hou"
  - "Hadjer Benmeziane"
  - "Kaoutar El Maghraoui"
  - "Liu Liu"
affiliations:
  - "Rensselaer Polytechnic Institute, Troy, NY, USA"
  - "University of Massachusetts, Amherst, Amherst, MA, USA"
  - "IBM Research – Ruschlikon, Ruschlikon, Switzerland"
  - "IBM T. J. Watson Research Center, Yorktown Heights, NY, USA"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790226"
code_url: "https://github.com/EPIC-RPI/STARC"
tags:
  - llm-inference
  - hardware
  - memory
  - energy
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

STARC 把稀疏 KV 检索变成一种“按行对齐”的 PIM 操作：先把语义相近的 key 聚成簇，再把对应 KV 对连续放置，并用质心分数按簇检索。通过把 `K=4` 和 64-token block 选到 AttAcc 的平衡点附近，它在保持接近 SparQ 准确率的同时，相比 token-wise 稀疏方法把 attention 层延迟和能耗最多再降 `78%` 和 `65%`，相对 full KV 则最多降 `93%` 和 `92%`。

## 问题背景

论文的出发点是 LLM 解码阶段一个很直接的错配。自回归解码每生成一个 token，都要再次访问不断增长的 KV cache，因此 attention 很快受制于内存流量而不是算力。HBM-PIM 架构通过把简单的 GEMV 计算放到 bank 附近来缓解带宽瓶颈，但它的基本执行粒度仍然是整行激活：一旦开行，就要把整行数据拉出并处理。

这使得两类常见稀疏方法都不理想。像 SparQ、InfiniGen 这样的 token-wise 方法能找到重要 token，但这些 token 在物理上分散在很多行里，所以 PIM 仍要付出大量行激活和过取代价。像 Quest 这样的 page-wise 方法更贴合硬件，因为 page 能和 row 对齐，但它按位置而不是按语义抓取内容，于是一个 page 常常只有少数 token 真正重要。STARC 要解决的正是这个缺口：既保留语义选择性，又获得行级效率。

## 核心洞察

这篇论文最值得记住的一句话是：如果可能一起被关注的 token 在物理上也被放到一起，那么 PIM 的粗粒度 row access 就不再与稀疏检索冲突。STARC 因此先按 key 的语义相似度做聚类，再把同一簇里的 KV 对连续存放，让一次行激活更可能取回一组都相关的 token。

更关键的是，作者把聚类参数和硬件平衡点绑在一起。论文分析指出，FP16 上 cosine K-means 的每轮 arithmetic intensity 大致随 `K` 线性增长，而所模拟的 AttAcc 系统的 compute/bandwidth tipping point 约为 `4 FLOPs/Byte`。因此 STARC 选 `K=4` 不是经验调参，而是让聚类本身尽量工作在硬件的平衡点附近。

## 设计

STARC 建立在 AttAcc 的行布局之上。每个 bank row 存 `1 KB`；在 FP16、head dimension 为 `128` 时，一个 key 或 value 向量占 `256 B`。论文把一个向量切到同一 bank group 的四个 bank 中，因此跨 bank group 的一整行恰好容纳 `16` 个完整向量，也就是 `blkrow = 16`。于是主块大小自然变成 `N = K * blkrow = 64`。

聚类本身直接在 HBM-PIM 内完成，而不是把 key 搬回 GPU。STARC 用 AttAcc 现有命令表达 cosine K-means：`MAC_AB` 做点积，`WRGB`/`MVGB` 负责写入和广播，`MVSB` 聚合分数，再加一个轻量的 `VNORM` 近似归一化。作者的意思很明确：normalization、assignment 和 update 复用了现有 PIM 数据通路，不需要明显新增面积；只有最后的 `argmax` 留给主机。

在线路径则采用只追加不重排的策略。prefill 后，KV cache 被切成互不重叠的 64-token block；STARC 只对 key 做聚类，随机初始化，最多跑 `16` 轮，value 继承标签。解码时，新 token 先保持未聚类并始终参与 attention；累计到 `64` 个后，只对这最新一段做一次聚类并追加到已有 clustered region。随后每个解码步都用当前 query 去打分所有质心，按分数取簇，直到达到 KV budget `B`，必要时截断最后一个簇，并把仍未聚类的最近 token 全部纳入 attention。由于旧簇永远不重聚类，开销只会随上下文长度线性增长。

## 实验评估

准确率实验覆盖 LongChat-7B-v1.5-32K、LLaMA-3.1-8B-Instruct 和 Mistral-7B-Instruct-v0.3，基准包括 LongBench、RULER 和 PG-19，对手是 Quest、InfiniGen、SparQ 和 full KV。主文采用 `1024` 的 KV budget。在这个预算下，STARC 一直明显好于 page-wise 的 Quest，同时通常非常接近最强 token-wise 基线。LongBench 平均分上，LLaMA-3.1 下 STARC 为 `39.71`，几乎贴着 SparQ 的 `39.76`，同时高于 InfiniGen 的 `39.51` 和 Quest 的 `36.38`；Mistral 下 STARC 为 `46.29`，也高于 Quest 的 `44.57`，并接近 InfiniGen 的 `46.53` 与 SparQ 的 `47.77`。RULER 上，STARC 平均分 `0.8727`，接近 full KV 的 `0.8812` 和 SparQ 的 `0.8831`，明显高于 InfiniGen 的 `0.8419` 与 Quest 的 `0.7848`。PG-19 的趋势也一致：它接近 full KV，优于 Quest 和 InfiniGen，只是略逊于 SparQ。

系统效率实验使用 AttAcc 在一个 DGX-like 平台上做模拟：`8` 张 H100、GPU 侧 `40` 个 HBM3 stack、PIM 侧额外 `40` 个 HBM3 stack，batch size `16`，序列组合为 `(2K,16K)`、`(2K,24K)` 和 `(2K,32K)`。更重要的是，作者把每种方法的 attention mask 映射到了真正的行粒度上，这正是论文主张是否成立的关键测量。

主要结果很硬。相对 full KV retrieval，STARC 在端到端解码上带来 `25%-48%` 的 speedup 和 `34%-56%` 的能耗降低；论文也把它换算成，相对 token-wise 稀疏方法，STARC 又快了 `13%-21%`，能耗再降 `11%-18%`。如果只看 attention 层，收益更大：相对 full KV，延迟和能耗最高下降 `93%` 与 `92%`；相对 token-wise 方法，也还能下降 `78%` 与 `65%`。与此同时，聚类本身的额外成本只有总延迟和总能耗的大约 `0.02%`。这正是论文最强的论据：STARC 接近了 page-wise 的硬件效率，但没有付出 page-wise 的准确率代价。

## 创新性与影响

和 AttAcc 相比，STARC 的新意不在于再做一版 dense attention 映射，而在于给 sparse attention 设计了一套面向 row-level PIM 的语义布局。和 SparQ、InfiniGen 相比，它强调“选对 token”还不够，因为只要这些 token 物理上仍然分散，PIM 就很难真正受益。和 Quest 相比，STARC 用语义 cluster 替代按位置切的 page，因此能同时保住更高 relevance 和更粗粒度的跳过能力。

因此，这篇论文会同时影响长上下文 LLM 推理和 PIM 架构两个方向。它不是纯测量论文，而是一个明确的机制设计，后续做稀疏 KV 检索、KV 重排或 GPU-PIM 协同的工作都很可能把它当成早期参考点。

## 局限性

STARC 的参数和收益都强依赖底层硬件组织。`K=4`、`blkrow=16` 和 64-token block 都来自 AttAcc 的 FP16 行布局与算带平衡，因此换到别的 head size、精度或 PIM 组织后，并不能直接照搬。论文还把 cluster 一旦形成就固定下来，这能省掉重排成本，但也意味着更老 token 的语义邻域如果后续漂移，系统不会再适配。

实验边界也需要看清。性能结果来自模拟器而不是真实 PIM 部署；STARC 只对 key 做聚类，让 value 继承标签；它优化的是固定 KV budget 下的检索效率，而不是 KV 容量管理本身。另外，基线设定里前两层保持 full KV，因为这些层的稀疏性较低，所以收益是在这个前提下得到的。

## 相关工作

- _Park et al. (ASPLOS '24)_ — AttAcc 提供了 Transformer attention 的 HBM-PIM 底座，而 STARC 在这个偏 dense 的底座上增加了稀疏布局重排与内存内聚类。
- _Lee et al. (OSDI '24)_ — InfiniGen 能动态预测哪些 token 更重要，但这些 token 在物理上仍可能分散；STARC 则进一步把它们重排成适合行级访问的语义簇。
- _Zhou et al. (HPCA '22)_ — TransPIM 关注的是内存内 Transformer 加速的 dense-style 数据流，而 STARC 把重点放在 sparse token access 和行感知的 KV 放置上。
- _Kwon et al. (SOSP '23)_ — PagedAttention 解决了 GPU 上 LLM serving 的 KV-cache 内存管理问题，但没有处理 PIM 上稀疏 token 检索应如何映射到物理行布局。

## 我的笔记

<!-- 留空；由人工补充 -->
