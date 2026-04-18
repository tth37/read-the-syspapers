---
title: "WorksetEnclave: Towards Optimizing Cold Starts in Confidential Serverless with Workset-Based Enclave Restore"
oneline: "WorksetEnclave 先把 SGX serverless 函数快照化，只恢复执行工作集页到小型 EDMM enclave，其余页面通过校验后的按需缺页加载。"
authors:
  - "Xiaolong Yan"
  - "Qihang Zhou"
  - "Zisen Wan"
  - "Feifan Qian"
  - "Wentao Yao"
  - "Weijuan Zhang"
  - "Xiaoqi Jia"
affiliations:
  - "Institute of Information Engineering, Chinese Academy of Sciences, Beijing, China"
  - "School of Cyber Security, University of Chinese Academy of Sciences, Beijing, China"
conference: asplos-2026
category: privacy-and-security
doi_url: "https://doi.org/10.1145/3779212.3790249"
tags:
  - serverless
  - confidential-computing
  - memory
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

WorksetEnclave 把 confidential serverless 的冷启动重写成“恢复”而不是“初始化”问题。它先对已完成初始化的 SGX 函数做快照，再只用 EDMM 重建一个很小的 enclave，先恢复执行时大概率会访问的工作集页，其余页面在真正触发缺页时再带完整性校验地补回。这样既缩短启动时间，也显著压低 EPC 占用，而且不需要修改 SGX 硬件。

## 问题背景

这篇论文抓住的是 SGX 与 serverless 之间一个非常典型的错配。机密 FaaS 需要短生命周期、低冷启动延迟、还能在突发请求下迅速扩容；但 SGX 上的函数启动恰好相反，最重的开销来自 enclave 创建和软件初始化。在 Gramine、Occlum 这类 LibOS 方案里，函数在真正执行业务逻辑前，必须先创建 enclave、度量大量 EPC 页面、把依赖库整体装进 enclave 内存。

作者指出这会带来两个问题。第一，启动延迟会达到秒级，而很多 serverless 函数真正执行的时间可能只有毫秒到秒级，冷启动就会吞掉主要时延预算。第二，初始化结束后 enclave 仍然很大，因为 enclave 不能像普通 sandbox 那样共享代码页。论文的动机实验显示，有些工作负载在稳定执行阶段实际只会访问全部 enclave 页面的约百分之一，但系统仍要一直为整个 enclave 付出 EPC 成本。已有 warm start 方法只有在平台已经保留了预热实例时才有用，一旦遇到真正的冷启动或 scale-out 扩容，它们就帮不上太多忙。

## 核心洞察

论文最重要的判断是：enclave-based serverless 函数没有必要在恢复时把“完整初始化状态”一次性全部搬回来。函数为完成启动而需要的页面集合，与它为处理一次请求而需要的页面集合，并不是同一个集合；后者往往小得多。

一旦接受这个判断，优化就自然分成两步。EDMM 让系统能够先快速创建一个很小的 enclave，而不用在创建阶段一次性准备完整 EPC；快照则让函数直接跳过昂贵的软件初始化。等系统知道了执行工作集后，恢复时只装回这一小部分页面，其余页面在运行中按需缺页恢复，并在 enclave 内做完整性验证。真正的新意不是“给 SGX 做快照”，而是“把 SGX 快照恢复拆成初始化状态与执行状态两个层次”。

## 设计

WorksetEnclave 的设计由三个核心部件组成。第一部分是 `Enclave C&R`。它先在 enclave 内部转储 enclave 内存，再把已解除 enclave 映射的宿主进程交给常规进程快照工具处理，从而把 enclave 快照和普通进程快照拼在一起。因为恢复出来的是一个全新的 enclave，线程上下文也必须显式重建。论文通过让其余 TCS 在 checkpoint/restore 期间进入 enclave 内的 spin 区域，保证状态不再变化；同时用 `EENTER` 模拟 `ERESUME`，把保存下来的 SSA 上下文重新接回新 enclave。

第二部分是安全的 EPC checkpoint/restore。系统记录页面元数据，包括虚拟地址和权限，在 enclave 内部加密页面内容，再把快照存到外部。为了避免快照只能在单机上恢复，函数通过 remote attestation 向 KDS enclave 取回密钥，而不是只依赖机器绑定的 sealing key。恢复时，enclave 负责重新创建页面、校验完整性、恢复页面属性；如果检测到篡改，就把 enclave 标记为 crashed 并拒绝后续进入。

第三部分是 workset-based restore，也是论文最关键的系统想法。离线阶段，SGX driver 会主动把 enclave 页面驱逐出去，执行一次函数，再观察哪些页面因缺页被重新装回，这些页面就构成初始工作集。在线恢复时，系统只先恢复这些工作集页。如果后续执行又访问到缺失页面，内核先用 `EAUG` 添加页面，signal handler 再把控制流转交给 enclave 内部异常处理器，由 enclave 验证该页并通过 `EACCEPTCOPY` 接收页面、用 `EMODPE` 修正权限。于是恢复过程从“先把所有东西都装回来”变成了“先恢复大概率会用到的页面，其余页面在需要时再安全补齐”。

## 实验评估

实验设计与论文主张是对齐的。作者分别在 Gramine 和 Occlum 上实现了 WorksetEnclave，把它接入 OpenWhisk，在一台配有 `4GB` PRM 的 Intel Xeon Silver 4510T 服务器上测试七个 Python 函数和两个 Node.js 函数。基线包括不开 EDMM 的冷启动、开 EDMM 的冷启动，以及不做工作集裁剪的完整快照恢复。

最亮眼的是启动时间。WorksetEnclave 把启动延迟压到了 Gramine 上低于 `600ms`、Occlum 上低于 `400ms`，相对冷启动基线在 Gramine 上获得 `1.9-14.1x` 提升，在 Occlum 上达到 `6.7-54x`。端到端时延的收益更有层次感：对 `pyaes`、`chameleon`、`linpack`、`rnn_serving` 这类较短函数，响应时间都降到 `400ms` 以下，其中 `rnn_serving` 提升 `13.7x`；而像 `image_rotate` 或 `json_serdes` 这种本身执行较长的任务，冷启动只占总体时延的一部分，所以整体加速更温和。

内存结果同样有说服力。相对启用 EDMM 的基线，WorksetEnclave 将 enclave 内存占用降低了 `13.37-94.87%`；论文特别点出 `pyaes` 可降低 `74.31%`，而 `rnn_serving`、`lr_serving` 这类初始化时要装入大量第三方库的工作负载最高可降到 `94.87%`。按需恢复带来的代价也被仔细量化了：单页缺页恢复约为 `36.41us`，第一次调用时按需恢复的页面数不到全部 enclave 页面的 `0.2%`，随着工作集根据缺页不断更新，论文报告在 `30` 次调用后已测得零缺页。这个证据链基本支持论文核心论点，不过它也意味着该方法对输入分布和执行路径的稳定性比较敏感。

## 创新性与影响

相较于 _Ustiugov et al. (ASPLOS '21)_，WorksetEnclave 不是把普通 serverless 的快照技术简单搬到 SGX，而是围绕 enclave 的受限内存模型重新设计了 selective EPC restore 与完整性校验流程。相较于 _Li et al. (ISCA '21)_，它不依赖 SGX 硬件扩展，也不要求共享可信库，而是在现有平台上用快照和工作集恢复绕开初始化成本。相较于 _Kim et al. (SoCC '23)_ 和 _Zhao et al. (USENIX Security '23)_，它更关注没有预热实例时的真实冷启动与扩容场景，而不是已有 enclave 的复用。对机密云平台和 TEE serverless 系统研究者来说，这篇论文的价值在于证明：不改硬件，也能把 confidential serverless 拉近到更可部署的延迟与密度区间。

## 局限性

这套方法明显依赖工作集的可预测性。如果后续请求会访问许多离线安装阶段或近期历史里从未触及的页面，那么系统就会退化为更多缺页和更大的工作集，主要收益也会被侵蚀。论文在自己的工作负载上展示了较快收敛，但从方法本身看，它更适合执行结构重复、热点较稳定的函数。

此外，WorksetEnclave 的工程复杂度并不低。它需要同时改 SGX driver、LibOS、signal 路径和 enclave runtime；安全模型也明确把 denial-of-service 和 SGX 微架构侧信道排除在外。论文没有和需要硬件改造的方案做实测对比，这个取舍是合理的，因为那些方案不能直接跑在现有云上，但也意味着它证明的是“在今天 SGX 约束下很实用”，而不是“在所有 confidential serverless 设计空间里最优”。

## 相关工作

- _Ustiugov et al. (ASPLOS '21)_ — REAP 为普通 serverless 函数做基于工作集的快照优化，而 WorksetEnclave 把这一思路推进到 SGX，增加了 selective EPC restore 与 enclave 内完整性处理。
- _Li et al. (ISCA '21)_ — PIE 通过 plug-in enclaves 复用可信库来降低 confidential serverless 的初始化成本，而 WorksetEnclave 不改硬件，直接用快照恢复跳过初始化。
- _Kim et al. (SoCC '23)_ — Cryonics 同样使用 enclave snapshots，但更侧重有预热实例前提下的 warm start，而不是从零实例开始的 cold-start scale-out。
- _Zhao et al. (USENIX Security '23)_ — Reusable Enclaves 通过重置已有 enclave 来加速重复请求，WorksetEnclave 则面向平台必须新建实例的更难场景。

## 我的笔记

<!-- 留空；由人工补充 -->
