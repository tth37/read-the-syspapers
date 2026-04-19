---
title: "Understanding the Linux Kernel, Visually"
oneline: "Visualinux 把运行中的 Linux kernel 当成对象图来裁剪和重排，用 ViewCL 负责抽取、用 ViewQL 负责聚焦，让复杂内核结构和漏洞现场能被直接看懂。"
authors:
  - "Hanzhi Liu"
  - "Yanyan Jiang"
  - "Chang Xu"
affiliations:
  - "State Key Laboratory for Novel Software Technology, Nanjing University, Nanjing, China"
conference: eurosys-2025
category: os-kernel-and-runtimes
doi_url: "https://doi.org/10.1145/3689031.3696095"
project_url: "https://icsnju.github.io/visualinux"
tags:
  - kernel
  - pl-systems
  - observability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Visualinux 把 Linux kernel 的运行时状态建模成对象图，再把工作拆成两步：先用 ViewCL 把图抽成适合阅读的形状，再用 ViewQL 按当前调试目标继续裁剪和改显示方式。原型直接挂在 GDB 上，既能在 Linux 6.1 上重做 21 张教材风格的内核图，也能帮开发者更快看清 StackRot 和 Dirty Pipe 这类跨子系统漏洞现场；本地生成图的开销通常只是几十到几百毫秒。

## 问题背景

这篇 paper 抓住的是 kernel debugging 里最常见、也最恼人的一个现实：不是拿不到状态，而是拿到的状态多得看不懂。GDB scripts、日志、tracing 工具、drgn 都能把内核内部掏出来，但真实的 kernel objects 体量大、指针层次深，还经常裹着 containers、unions 和各种间接关系。把这些东西按文本 dump 出来，开发者看到的是一长串字段和值，而不是自己真正想理解的结构。

这个问题既妨碍找 bug，也妨碍学内核。作者用 Linux 6.1 的 maple tree 做切入点：它替换了旧的 VMA 红黑树结构，可真正想把它看明白，单靠文本接口根本不够，开发者还得自己写脚本去拆 union、解析压缩指针、恢复节点关系。安全漏洞分析更麻烦，因为问题往往横跨多个机制，真正相关的状态只占很小一块。继续堆临时脚本当然能做事，但代价高，而且一次会话结束后，这些理解工作很容易就散掉了。

## 核心洞察

论文最关键的判断是：开发者其实一直在用三种固定动作简化 kernel state，只是过去靠脑子和脚本在手工做。第一是 prune，把和当前目标无关的 fields、objects、relations 删掉；第二是 flatten，把很长的指针链压成概念上直接相连的边；第三是 distill，把难读的底层容器形态重新表达成列表、集合这类更容易理解的逻辑结构。只要把这三件事做成语言原语，内核理解就能从一次性的脚本技巧，变成可以复用的程序。

更重要的是，它没有把所有工作塞进一种语言里。ViewCL 负责把 kernel state 抽成一个可视对象图，ViewQL 则负责在这张图上做最后一公里的筛选和显示控制。这个分层决定了工具是否真能落地：熟悉内核的人可以把复杂的抽取逻辑预先写好，普通使用者很多时候只需要写几行 ViewQL，甚至直接用自然语言让模型生成 ViewQL 就够了。

## 设计

Visualinux 的第一层是 ViewCL。它的基本单位是 `Box`，可以对应一个真实 kernel object，也可以对应一个虚拟对象。每个 box 下面又能挂多个 `View`，每个 view 由 `Text`、`Link` 和嵌套 box 组成，所以同一个对象可以同时拥有不同细粒度的展示方式。比如 `task_struct` 可以有只看 `pid` 和 `comm` 的默认视图，也可以有额外暴露 `se.vruntime` 和 runqueue 关系的 scheduler 视图。论文里那三种简化动作都能在这层落地：选哪些字段和对象相当于 prune，点连接字段表达式相当于 flatten，而把红黑树、xarray 之类底层容器转成 sequence 或 set 的 converter functions 则对应 distill。

第二层是 ViewQL。它故意做得很小，语法上接近 SQL：`SELECT` 选对象，`UPDATE` 改显示属性。可调的属性包括 `view`、`trimmed`、`collapsed` 和容器的 `direction`，再配合集合运算与 `Reachable(...)`，开发者就能在已经抽出来的对象图上不断收窄关注范围。论文里的典型用法很清楚：ViewCL 先把 runqueue、maple tree 或 address space 整体抽出来，ViewQL 再把 slot 列表折叠、把 writable VMA 隐去，或者只盯住某个可疑节点。

第三层是交互式前端。Visualinux 作为 GDB 的分离式可视化界面运行，支持 pane-based 调试：primary pane 放完整图，secondary pane 放聚焦出来的子图，还能跨多个 pane 做 focus，查看同一个对象在不同结构中的位置。实现上，系统暴露三条命令：`vplot` 执行 ViewCL 生成图，`vctrl` 管 pane 和 ViewQL 操作，`vchat` 把自然语言请求翻译成前两类命令。原型规模也交代得比较清楚：GDB 侧大约 4,000 行 Python 加 500 行 GDB scripts，前端大约 2,000 行 TypeScript。

## 实验评估

评估是围绕论文自己的主张展开的，也就是它是否真的让现代 Linux kernel state 更容易理解，而不是单纯跑一个 debugger microbenchmark。最有说服力的一组结果来自 ULK revival。作者在 Linux 6.1 上重做了 21 张受 _Understanding the Linux Kernel_ 启发的代表性图。这个结果之所以重要，是因为他们进一步指出，那 21 张旧图里有 17 张对今天的 kernel 已经不再及时，其中 17 张真正涉及内核机制的图里，又有 14 张经历了显著实现变化。换句话说，Visualinux 展示的不是怀旧复刻，而是把过时教材里的解释重新接到当前内核实现上。大多数图需要补的 ViewCL 代码量也不夸张，通常在 19 到 154 行之间。

论文还检查了交互层是否足够轻。对 10 个假设的调试目标，每个定制请求都能用不到 10 行的 ViewQL 表达；把这些自然语言描述交给 DeepSeek-V2，10 个 ViewQL 程序也都生成正确。这个结果说明 ViewCL 和 ViewQL 的分工确实合理，不过证据形式仍然偏 demo，离真正的用户研究还有距离。

两组漏洞案例比 LLM 展示更扎实。对 StackRot（CVE-2023-3269），Visualinux 同时把 maple tree 和 RCU waiting list 摆到开发者面前，再把无关的 VMA 裁掉，只保留那个可疑节点的生命周期。对 Dirty Pipe（CVE-2022-0847），作者用大约 60 行 ViewCL 加一小段 ViewQL，把文件和 pipe 之间唯一共享的 page 以及错误的 `CAN_MERGE` flag 直接挑了出来。这两组案例确实支撑了论文的主论点：它最擅长做的事情，是把庞大而杂乱的引用图压缩成真正解释 bug 的那一小片状态。

性能结果则比较克制。本地 GDB+QEMU 下，20 张代表性图的总抽取时间在 10.1 ms 到 326.0 ms 之间；换成挂在 Raspberry Pi 400 上的 KGDB，范围变成 17.4 ms 到 20,904.3 ms。作者把主要瓶颈归因于大量 C expressions 的求值，以及远程取对象本身的高延迟。这个结果说明论文没有回避代价：ViewQL 和前端渲染本身几乎不贵，但如果图很大、远程调试链路又慢，交互体验依旧会明显变差。

## 创新性与影响

这篇 paper 的创新点不在于重新做一个 debugger backend，也不在于发明新的 kernel analysis algorithm，而在于把内核状态理解拆成了三个可以组合的部件：可复用的 ViewCL 抽取语言、轻量的 ViewQL 定制语言，以及面向对象图的交互式前端。这个拆分比抽象地呼吁改进 interactive debugging 更具体，也比一次性的 GDB scripts 更有积累价值，因为开发者能把自己对某类数据结构的理解沉淀下来，留到下一次会话继续用。

它最可能影响到三类人。第一类是 kernel developers，他们面对快速变化的数据结构时，需要的往往不是更多日志，而是一眼能看懂的结构图。第二类是教材作者和教学场景，因为 ULK revival 的意义就在于把过时的解释重新绑定到现代 Linux 上。第三类是安全分析人员，尤其是在漏洞跨多个子系统、文本状态很难串起来的时候，Visualinux 这种图式化视角会比普通 dump 更接近人脑真正推理的方式。

## 局限性

论文也很清楚地承认，Visualinux 是一个 state-visualization tool，不是完整的 debugging replacement。它不直接处理时间维度上的问题，比如锁状态如何随执行演化；作者甚至明确说，某些同步章节和架构层面的教材图本来就不在它的覆盖范围内。开发者仍然得自己决定停在哪个断点、按什么节奏迭代观察。

另一类限制来自建模成本。ViewQL 很轻，但 ViewCL 依旧需要 kernel-specific knowledge，有时还要写 helper scripts 去拆 containers、unions 和压缩字段。光 maple tree 这个例子就用了大约 70 行 ViewCL 加 100 行 GDB Python helpers。再加上评估里没有把它和 drgn、纯 GDB scripts 或其他文本化流程做受控对比，论文证明的是工具有用，而不是它在开发者生产率上已经稳赢。最后，远程 KGDB 下的大图可能依旧要等上几秒甚至几十秒，这对日常使用是现实约束。

## 相关工作

- _Fragkoulis et al. (EuroSys '14)_ - PiCO QL 给 Unix kernel data structures 提供 relational access，而 Visualinux 进一步把 prune、flatten、distill 变成图式建模与可视化操作。
- _Bissyandé et al. (ASE '12)_ - Diagnosys 会自动生成 Linux kernel debugging interface；Visualinux 更强调可编程的视图构造和交互式对象图操作。
- _Ko and Myers (ICSE '08)_ - Whyline 关注的是围绕程序行为提出 why 和 why-not 问题，Visualinux 关注的则是让当前 kernel state 本身变得可读。
- _Alaboudi and Latoza (UIST '23)_ - Hypothesizer 支持调试中的假设生成与验证，Visualinux 则补上了 Linux kernel 复杂数据结构这块最缺的状态抽象和可视界面。

## 我的笔记

<!-- 留空；由人工补充 -->
