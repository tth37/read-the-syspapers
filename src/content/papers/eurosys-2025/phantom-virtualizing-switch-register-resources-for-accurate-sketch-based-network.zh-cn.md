---
title: "Phantom: Virtualizing Switch Register Resources for Accurate Sketch-based Network Measurement"
oneline: "Phantom 把交换机的 recirculation lane 变成虚拟 sketch 寄存器，再由服务器按时间戳重放更新，在不降吞吐的前提下把测量精度明显拉高。"
authors:
  - "Xiang Chen"
  - "Hongyan Liu"
  - "Zhengyan Zhou"
  - "Xi Sun"
  - "Wenbin Zhang"
  - "Hongyang Du"
  - "Dong Zhang"
  - "Xuan Liu"
  - "Haifeng Zhou"
  - "Dusit Niyato"
  - "Qun Huang"
  - "Chunming Wu"
  - "Kui Ren"
affiliations:
  - "Zhejiang University"
  - "Quan Cheng Laboratory"
  - "The University of Hong Kong"
  - "Fuzhou University"
  - "Yangzhou University"
  - "Southeast University"
  - "Nanyang Technological University"
  - "Peking University"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3696077"
tags:
  - networking
  - smartnic
  - observability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Phantom 的做法很直接：把 programmable switch 里原本常被闲置的 recirculation lane 拿来保存虚拟寄存器的更新流，而不是硬挤更多 SRAM。交换机只负责生成和缓存 register update，服务器按时间戳回放这些更新来恢复最终寄存器值。这样一来，sketch 可以拿到 O(10^6) 级别的有效寄存器数，应用层测量精度最高提升 86%，同时交换机吞吐不掉。

## 问题背景

这篇论文抓住的是 sketch-based measurement 最朴素也最难绕开的事实：精度往往主要取决于寄存器够不够多。寄存器越多，hash collision 越少，单流误差越小。作者用 HashPipe 做了一个很直白的实验，寄存器数从 10^2 增长到 10^6 时，heavy-hitter detection 的 F1 从 0.01 提到 0.99，recall 从 0.61% 提到 98.99%。

麻烦在于，programmable switch 恰好最缺的就是这类寄存器资源。每个 pipeline stage 只能放很少的 register array，每个 array 的 32-bit register 数量也只有几千级，总 stage 数更是固定的。于是 sketch 同时被两道上限卡住：array 数量有限，单个 array 的长度也有限。静态分配类系统只能在现有 SRAM 里做装箱；SCREAM、NetVRM 这类动态方案改善了利用率，却没有真的增加单台交换机能提供的状态量；改芯片或依赖外部存储的办法又要么等硬件演进，要么额外吃掉太多 dataplane 资源。

因此，真正缺的是一种办法：在不牺牲线速转发、也不把交换机到监控服务器的链路打爆的前提下，把今天交换机的有效 sketch 状态做大。

## 核心洞察

Phantom 的判断是，measurement 用到的寄存器不一定非得以固定 SRAM 单元的形式存在。对 sketch 来说，真正需要被保留下来的，是定义寄存器值的那串有序更新。既然很多 programmable switch 本来就带有与正常流水线隔离的内部 recirculation lane，而且这部分带宽通常没被充分用到，那就可以把它改造成虚拟寄存器的承载体：不是存最终值，而是持续在 lane 里保存 timestamped register update。

不过，光把 update 放进去还不够，因为不少 sketch 不是单纯写入，而是 read-modify-write。Phantom 的关键补充是把逻辑拆开。交换机只做无状态部分，例如 hash 到哪个寄存器、该生成什么更新；需要看旧值才能决定新值的那部分，则交给服务器在回放 update 时执行。于是，交换机负责快路径和暂存，服务器负责拿着完整历史做正确恢复，两边各做自己最适合的事。

## 设计

Phantom 先让用户给出三类预算：可用于 recirculation 的带宽、可占用的 TM buffer 空间，以及交换机到监控服务器的导出带宽。控制平面 agent 再结合交换机的 stage 数、hash 数量、预期包速率和测量 epoch 长度，算出 sketch 最多可以拥有多少个 array、每个 array 最多多长。用户写 P4 sketch 时不用关心底层哪些寄存器是真实的，哪些是虚拟的。

真正部署时，Phantom 先标出哪些位置需要虚拟化。如果 sketch 的 array 数超过物理 array 数，多出来的整组 array 直接变成虚拟 array；如果某个 array 太长，超过单 stage 可容纳的物理上限，则该 array 末尾那部分寄存器被标成虚拟寄存器。之后 switch handler 改写更新路径：命中物理寄存器就按常规更新；命中虚拟寄存器，就生成一个包含索引、操作相关变量和时间戳的 register update。像 Elastic Sketch、UnivMon 这类 write-after-read sketch，还会把后续比较所需的 operand 一并塞进 update 里。

接着是运行时管理。switch handler 会给 recirculation 限速，保证其总速率不超过用户配置的预算；同时给 update 预留有上限的 TM buffer；只有当此刻把某个 update 发给服务器不会突破导出带宽预算时，它才真的发出去，否则这个 update 会继续在交换机内部 recirculate。由于单条 update 只有 13 字节，Phantom 还把同一个 packet 产生的多条 update 聚合成更大的包，避免交换机在处理极小包时掉出线速。

服务器端的 handler 在每个 epoch 结束时把两路数据合起来：一路是交换机导出的 physical register dump，另一路是这一轮收到的 virtual-register updates。它先按时间戳排序，再顺序回放。write-only update 直接应用；write-after-read update 则在服务器上执行延后的读、比较和写。最后得到的是物理寄存器与虚拟寄存器共同组成的完整 sketch 状态。

## 实验评估

实现基于一台 64x100 Gbps Tofino switch，switch handler 用 P4 写成，server handler 用 C++ 和 DPDK 实现。实验覆盖五种代表性 sketch：Count-Min、Count Sketch、Elastic Sketch、FlowRadar 和 UnivMon。

第一类结果是容量。在 1-3 Tbps 业务负载下，只给 100 Gbps recirculation 预算和 5 MB buffer，Phantom 就能虚拟化超过 10^5 个寄存器；在论文强调的更宽运行区间里，它能做到 O(10^6) 级别的虚拟寄存器。作者还显示，在他们的设置里，40 Gbps 的 switch-to-server 带宽就足以不成为主要瓶颈。

第二类结果是应用层收益。作者把 CAIDA trace 以 3 Tbps 回放，并用 heavy hitter、global iceberg、superspreader detection 作为最终任务。和 SwitchILP、SPEED、MTP、P4All、NetVRM 相比，Phantom 把应用层精度最高提升了 86%。更关键的是，论文还拿一个离线最优结果做参照：给 sketch 同样多的内存，但不受实时约束。Phantom 与这个最优之间的误差不到 1%，说明虚拟化机制本身并没有明显引入新的测量偏差。

第三类结果是可部署性。在 network-wide placement 实验里，Phantom 最多能多接受 84% 的 sketches，因为它做的不是把原有 SRAM 挤得更满，而是直接扩大每台交换机对 sketch 来说可用的有效寄存器预算。

最后是开销。switch handler 占用的交换机资源不到 2%；服务器处理一条 register update 只要几十个 CPU cycles，单核每秒能处理数百万条 update；在 out-of-band 设置下，直到 3 Tbps 都没有出现 packet loss 或 update loss；交换机吞吐不受影响，只额外增加 0.23 us 延迟。对一个 measurement substrate 来说，这组结果相当扎实。

## 创新性与影响

这篇论文的新意不在于又提出了一种新的 sketch，而在于把 programmable switch 的一种边角资源重新定义成了可用状态。以前的大多数工作，重点是更聪明地共享已经很稀缺的寄存器；Phantom 问的是，交换机内部是否本来就有另一条隔离资源路径，可以被换算成逻辑上的 register capacity。这个视角很有价值。它提示 sketch 设计者不必总把状态理解成固定 counter，也提示系统研究者，当 ASIC SRAM 才是硬瓶颈时，switch 和 monitoring server 的协同也许比继续在单一 dataplane 里挤资源更有效。

## 局限性

Phantom 的收益建立在一个前提上：运营者愿意拿出一部分 recirculation 带宽、buffer memory 和导出带宽给 measurement。只要这些预算设得足够紧，或者业务速率进入论文所说的更极端区间，Phantom 就会主动缩小甚至关闭虚拟化，而不是硬顶着突破预算。

它的可靠性设计也偏务实，而不是强保证。实现默认采用常见的 out-of-band collection 模式，并依靠带宽控制把 update loss 压到接近零；但对于 in-band 传输、长时间服务器失联、或者需要持久化确认的场景，论文还没有给出完整的恢复协议。作者也明确把 ACK-based durability 和更强的 loss handling 留作后续工作。

另外，实证几乎都来自 Tofino。论文论证了其他 programmable switches 也普遍支持 recirculation，但真正移植过去后会遇到什么样的编译复杂度、运维成本和性能折衷，当前还没有数据。再往根上说，Phantom 适合 epoch-based telemetry，不是把任意 stateful dataplane program 都自动扩容的通用方案；它依赖服务器端回放，因此并不适合作为任意低时延控制逻辑的直接替代。

## 相关工作

- _Moshref et al. (CoNEXT '15)_ - SCREAM 解决的是 sketch SRAM 的动态分配问题，但它始终停留在交换机原始物理容量之内；Phantom 试图做的是把有效容量本身做大。
- _Zhu et al. (NSDI '22)_ - NetVRM 在多 sketch、多交换机之间池化寄存器资源，而 Phantom 瞄准的是另一层问题：怎样绕过单台交换机的寄存器天花板。
- _Namkung et al. (NSDI '22)_ - SketchLib 让 programmable switch 上的 sketch 编程与组合更容易，而 Phantom 可以看作是在继续往下挖，处理这些 sketch 仍然会被卡住的内存瓶颈。
- _Kim et al. (SIGCOMM '21)_ - RedPlane 把交换机状态外化主要是为了容错；Phantom 则借助 switch-server 协同，把额外准确性从现有硬件里榨出来。

## 我的笔记

<!-- 留空；由人工补充 -->
