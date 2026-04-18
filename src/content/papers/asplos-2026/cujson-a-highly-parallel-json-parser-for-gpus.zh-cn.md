---
title: "cuJSON: A Highly Parallel JSON Parser for GPUs"
oneline: "cuJSON 把 UTF 检查、tokenization 和括号配对改写成分支更少的位图、scan 与 sort 原语，从而在 GPU 上解析标准 JSON。"
authors:
  - "Ashkan Vedadi Gargary"
  - "Soroosh Safari Loaliyan"
  - "Zhijia Zhao"
affiliations:
  - "University of California, Riverside"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3760250.3762222"
code_url: "https://github.com/AutomataLab/cuJSON"
tags:
  - gpu
  - databases
  - observability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

cuJSON 证明，JSON parsing 可以被改写成适合 GPU 的位图、scan 和 sort 计算，而不必依赖充满分支的 stack parser。它把 UTF-8 validation、tokenization 和嵌套结构识别都搬到 GPU 上，并输出保留层次的 pairing index。对于足够大的标准 JSON 和 JSONL，这已经足以超过强基线 CPU parser。

## 问题背景

论文针对一个实际瓶颈展开：JSON 已广泛存在于日志、文档数据库、Web 服务和分析流水线中，而 parsing 往往占据主要成本。已有 CPU 工作如 simdjson 和 Pison 已经把 SIMD 用到很深，但 GPU 侧仍然不足。现有 GPU parser 通常只支持 JSONL、常把结果规整成会丢失层次的表结构，而且核心逻辑仍过于依赖分支或 stack。cuJSON 因而瞄准更难的问题：在支持标准 JSON、保留层次结构并完成 UTF-8 validation 的前提下，把 parsing 重新表达成足够并行的 GPU 计算。

## 核心洞察

论文的核心洞察是：JSON parsing 中最贵的部分，可以从“分支很多的语法机”改写成“对位图和索引数组做并行变换”。一旦完成这种改写，GPU 就适合执行这项工作，因为底层操作变成了 CUDA 擅长的字节级比较、population count、scan 和 stable sort。

这一洞察贯穿三个阶段。UTF-8 validation 被写成跨相邻 word 的无分支检查；tokenization 被写成位图流水线，用来消除字符串内部的伪结构字符并维护 quote parity；结构识别则不再依赖串行 stack，而是变成深度标注加排序。配套的关键输出是 structural index 与 pairing index：它们既适合并行构造，又足以让查询快速跳过整棵不匹配子树。

## 设计

系统既接受标准 JSON，也接受 JSONL；对 JSONL，会先把所有行包装成一个大数组并把换行改成逗号。若估算内存超出 GPU 容量，系统会直接报错，而不是流式处理。

第一阶段是 UTF-8 validation。cuJSON 先检查是否存在非 ASCII 字节；若没有，就跳过重路径。否则，每个线程查看相邻 32-bit word，用 GPU 原生的字节级比较和位运算去检测 malformed、overlong、surrogate 和 too-large 序列。

第二阶段是 tokenization。系统为六种结构字符、反斜杠和双引号建立位图，并用 backward counting 解决 escape dependency，用 quote 计数、exclusive scan 和模拟 prefix-XOR 解决 parity dependency。完成字符串掩码后，它提取 structural index 和只包含括号、花括号的 open-close 数组。

第三阶段是结构识别。cuJSON 把 opening 和 closing delimiter 映射成带符号值，先 scan 得到深度，再修正 opener 深度并按深度 stable sort，让匹配项彼此相邻。之后再验证括号和花括号是否真的合法配对，最后展开成 pairing index。实现层面还加入了 kernel fusion 和 pinned memory 上的 multi-streaming，以减少 launch 与传输开销。

## 实验评估

实验把 cuJSON 与 RapidJSON、simdjson、Pison 这些 CPU parser，以及 cuDF、GPJSON、MetaJSON 这些 GPU parser 做了比较，数据集为六个真实世界语料，大小约 `842 MB-1.2 GB`，平台覆盖 Quadro P4000 桌面机和 A100 服务器。

在标准 JSON 上，cuJSON 对大输入能稳定赢过 CPU 基线。论文报告，在不同数据集和两台机器上，即使把 host-device 传输时间算进去，它相对第二名 parser（通常是 Pison）仍有大约 `1.3x-2.8x` 的加速。但结论是有边界的：当文件小于大约 `8 MB` 时，GPU 开销会压过收益，simdjson 更快。

在 JSONL 上对比已有 GPU parser 时，cuJSON 的优势更明显：平均来看，相对 cuDF 快 `117.9x`，相对 GPJSON 快 `14.8x`，相对 MetaJSON 快 `3.2x`。时间分解显示 validation 最便宜，主要计算成本集中在 tokenization 和 structure recognition，而 host-to-device copy 往往是最大单项开销。峰值 GPU memory 约为输入的两到三倍，与其他 GPU parser 相当甚至更低。

查询结果也很有边界感。pairing index 让 cuJSON 在 object-specific query 中能快速跳过子树，因此比 Pison 更快；但它仍然落后于 simdjson 和 RapidJSON 这类带直接指针的树式结果。对于 JSONL 上的 all-object query，GPJSON 更强，因为 cuJSON 目前仍主要在 CPU 上查询。这说明论文的强项首先是 parser 本身，而不是通用最强查询引擎。

## 创新性与影响

相对 _Langdale and Lemire (VLDB '19)_，cuJSON 的创新点不在于再次证明 SIMD JSON parsing 有效，而在于把解析子问题改写成适合 GPU intrinsics 的形式，而不是照搬 CPU shuffle 指令。相对 _Jiang et al. (VLDB '20)_，它用 GPU 友好的位图流水线与 scan-and-sort 括号匹配，替代 CPU 多核上的依赖切分方式。相对 cuDF、MetaJSON 和 GPJSON 这类更早的 GPU 系统，它最强的结果是：标准 JSON、层次保留和完整 UTF validation 可以与高 GPU 性能同时成立。

这让论文同时影响半结构化数据分析系统研究者，以及希望把 parsing 从 CPU 热路径中拿掉的 GPU 数据流水线工程团队。

## 局限性

cuJSON 并不是所有 JSON 工作负载的通解。对小文件，它会输给 CPU parser，因为在论文给出的 breakeven point 以下，传输和 kernel launch 的固定成本太高。对标准 JSON，输入必须完整放进 GPU memory；若超限，当前实现会直接报错而不是流式处理。同时，这个 parser 是只读的，不支持 in-place mutation。

它的输出结构也带来查询取舍。由于 cuJSON 保存的是原始字节数组上的索引，而不是完全物化的树，一些查询仍然需要在 CPU 上扫描 structural information，这也是 simdjson 和 RapidJSON 在某些模式下更快的原因。GPU-accelerated querying 和更易修改的输出格式都被留给未来工作，所以它目前最适合的仍是 parse-heavy 分析场景。

## 相关工作

- _Langdale and Lemire (VLDB '19)_ — simdjson 展示了在 CPU 上用低分支、SIMD 风格做 JSON parsing 的上限，而 cuJSON 将这种思路迁移到了 GPU 可用的原语上。
- _Li et al. (VLDB '17)_ — Mison 把位图式 JSON parsing 引入分析型场景，cuJSON 则把这种设计哲学推进到 GPU 上，并保留层次化输出。
- _Jiang et al. (VLDB '20)_ — Pison 解决的是单个大 JSON 在 CPU 多核上的依赖拆分问题；cuJSON 面对同类问题，但依赖的是 GPU 上的位图、scan 和 sort。
- _Kaczmarski et al. (DSAA '22)_ — MetaJSON 证明了 GPU 上做 JSON parsing 的可行性，但它偏向 schema-driven normalization，而不是 cuJSON 这种通用、保层次的解析输出。

## 我的笔记

<!-- 留空；由人工补充 -->
