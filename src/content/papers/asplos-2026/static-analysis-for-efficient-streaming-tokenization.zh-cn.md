---
title: "Static Analysis for Efficient Streaming Tokenization"
oneline: "先静态判定词法规则是否支持有界前瞻流式 tokenization，再用无回溯的一趟 `StreamTok` 在小内存下执行 maximal munch。"
authors:
  - "Angela W. Li"
  - "Yudi Yang"
  - "Konstantinos Mamouras"
affiliations:
  - "Rice University, Houston, Texas, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790227"
tags:
  - compilers
  - pl-systems
  - formal-methods
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

这篇论文把流式 tokenization 分成两类：有些 grammar 在 maximal-munch 语义下天生需要无界等待，有些只需要有限前瞻。作者用 maximum token neighbor distance（max-TND）刻画这条边界，先静态算出它，再据此构造单趟、无回溯的 `StreamTok`。在常见数据格式 grammar 上，`StreamTok` 通常比 `flex` 快 `2x-3x`，而内存占用保持在 KB 量级。

## 问题背景

论文关注 maximal-munch 语义下的流式 tokenization。对编译器、半结构化数据系统、在线日志分析这类场景来说，tokenization 往往是解析、过滤、转换、校验之前的第一步。难点在于 maximal munch 不允许过早输出：只有确认当前 token 不会再被延伸成更长匹配时，词法器才安全。到了流式场景，这不只是性能问题，也会直接变成内存问题，因为系统可能必须长时间缓存“还不敢发出去”的输入。

作者先证明了这个困难不是实现细节，而是问题本身的性质：有些 grammar 在最坏情况下确实需要 `Omega(n)` 空间。只要一个 token 还有可能在未来被延伸成更长 token，算法就没有安全的输出点。这意味着不存在对所有 grammar 都通用、且始终只用常数内存的 maximal-munch 流式算法。真正的问题因此变成：哪些 grammar 适合有界内存 streaming，以及如何利用这种结构做出比 `flex` 更高效的实现？

## 核心洞察

论文的核心洞察是：决定 streamability 的，不是 grammar 大小或 regex 写法，而是“还要再看多少字符，才能确认当前 token 已经不能继续延伸”。作者把这个量定义为 token neighbor distance，对整个 grammar 取最大值得到 max-TND。若 max-TND 无界，词法器就可能无限期推迟输出；若它被某个 `K` 有界，那么判断当前 token 是否 maximal 只需要再看后面 `K` 个字符。这个量因此同时解释了 `flex` 式回溯为何会变坏，也说明何时真正的一趟流式算法是可能的。

## 设计

设计分成两部分。第一部分是 DFA 上的静态分析。论文先证明一个关键二分结论：对正则语言，max-TND 要么是无限大，要么至多是最小 DFA 状态数 `m` 加一，因此有界情况只需搜索有限窗口。作者也证明了相关问题是 PSPACE-hard，同时给出 polynomial-space 上界，以及一个在 DFA 大小为 `M` 时运行时间为 `O(M^2)` 的实用分析算法。

第二部分是运行时 `StreamTok`。如果 `K = 1`，只需一张小的 token-extension table，判断当前终态在再读一个字符后是否仍可能延伸。对一般有界 `K`，论文构造一个 token-extension automaton，汇总长度不超过 `K` 的所有可能延伸路径。运行时让它始终比普通 tokenization DFA 超前 `K` 个字符；当普通 DFA 到达某个终态 `q` 时，前方 automaton 的状态就告诉系统：在接下来的 `K` 个字符里，是否还存在从 `q` 出发的合法延伸。若不存在，当前 token 就已经 maximal，可以立刻输出。于是整套系统真正做到左到右单趟扫描、每个字符只做常数工作，并且只需要一个大小为 `K` 的有界延迟缓冲。

## 实验评估

实验先回答“这种 grammar 是否常见”。在 `2669` 个去重后的 GitHub grammar 中，约 `68%` 具有有界 max-TND；其中 `53%` 的有界样本 max-TND 恰好是 `1`。常见数据格式也很友好：JSON 是 `3`，CSV 是 `1`，TSV 是 `2`，XML 是 `6`；而实验中的 C、R、SQL grammar 则是无界的。静态分析本身也足够快：`99.4%` 的 grammar 在 `100 ms` 内完成，`99.96%` 在 `1 s` 内完成。

性能结果同样支持核心主张。对对抗性 grammar 家族 `r_k = (a{0,k}b)|a`，`StreamTok` 对 `k` 保持常数级，而先前面向 streaming 的基线会随着 `k` 增大而接近 `Theta(k)` 每字符代价。在 CSV、JSON、TSV、XML、YAML、FASTA、DNS zone file 和日志等实际工作负载上，`StreamTok` 相比显式支持 streaming 的 `flex` 通常有 `2x-3x` 的提升。内存优势更明显：对 `1000 MB` 输入，`StreamTok` 约为 `0.1 MB`，而离线 `ExtOracle` 约为 `2003-2019 MB`。在日志解析、JSON minify、格式转换、CSV 校验等更高层应用里，仅替换底层 tokenizer，就能带来约 `2.5x-5.39x` 的端到端加速。

## 创新性与影响

相对 _Li and Mamouras (OOPSLA '25)_，这篇论文的新意不在于再提出一个离线无回溯 tokenizer，而在于把 streaming 可行性本身变成可静态判定的 grammar 属性。相对 _Reps (TOPLAS '98)_，它用 grammar 侧的分析和有界前瞻 automaton 替代了随输入增长的 memo 结构。相对 `flex`，它则把“回溯为何会恶化”解释成 grammar 的语义性质，而不是黑盒实现现象。

这让论文同时服务两类人。对做 JSON、CSV、XML、日志流处理的工程实践者，它提供了一条从 grammar 规格直接走到低内存 tokenizer 的路径。对 PL 和编译研究者，max-TND 则是一个可复用的抽象，用来区分哪些 grammar 天生不适合在线输出，哪些 grammar 只是还缺一个更好的运行时机制。

## 局限性

最直接的局限就是作者自己强调的：`StreamTok` 只适用于 max-TND 有界的 grammar。这个覆盖面对数据格式已经很有价值，但无法替代通用编程语言词法器，因为论文里分析的 C、R、SQL grammar 都是无界的。另一个现实约束是，运行时依赖针对固定 grammar 预生成 automata 和查表结构，因此它更适合生成式 lexer，而不是运行时频繁改 grammar 的场景。

CSV 例子还说明了一个更细的工程问题：RFC 风格 quoted-field 规则本身是无界的，所以作者改用“闭引号可选”的变体，再用额外的偶数引号检查恢复 well-formedness。这是可行的折中，但说明最快的 streaming 路径有时需要重写 grammar 并附加 side condition。还有一个基于论文构造的 reviewer-style 推断是：token-extension automaton 仍来自 subset-style 构造，因此理论上的状态爆炸并未被彻底排除，只是实验里没有成为主要问题。

## 相关工作

- _Li and Mamouras (OOPSLA '25)_ — ExtOracle 和 TokenSkip 对所有 grammar 都能去掉回溯，但它们是离线算法，必须先拿到完整输入；`StreamTok` 的目标则是一开始就支持真正的 streaming。
- _Barenghi et al. (IPDPS '21)_ — Plex 用并行 prescanning 提升 lexing 吞吐，而这篇论文关注的是借助 grammar 语义界限来实现单趟、有界内存的流式 tokenization。
- _Egolf et al. (CPP '22)_ — Verbatim++ 重点在可验证的 derivative-based lexer generation，而这篇论文的重心是静态判定 streamability，并把 maximal-munch tokenization 做得更快。
- _Tan and Urban (ITP '23)_ — bit-coded derivative-based POSIX lexing 关注标准词法语义的实现与证明，但没有讨论这些语义何时能在有界内存下流式执行。

## 我的笔记

<!-- empty; left for the human reader -->
