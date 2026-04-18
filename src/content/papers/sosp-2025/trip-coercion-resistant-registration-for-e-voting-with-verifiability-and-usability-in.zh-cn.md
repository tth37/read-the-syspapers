---
title: "TRIP: Coercion-resistant Registration for E-Voting with Verifiability and Usability in Votegral"
oneline: "TRIP 用 kiosk、纸质信封和交互式证明 transcript 发放真实与伪造投票凭证，让选民能验证真实凭证，而胁迫者无法区分它们。"
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

TRIP 是 Votegral 的注册阶段设计，目标是在注册时不依赖选民自带可信硬件的前提下，让 fake credential 真的可用。它的核心做法是把 kiosk、纸质信封和 interactive zero-knowledge proof 的 transcript 结合起来：选民只在 booth 内知道哪个 credential 是真的，但离开后手里的所有纸质凭证在胁迫者眼里都不可区分。

## 问题背景

远程投票之所以诱人，是因为它绕开了投票站排队、出行和海外投票等现实成本，但它也失去了线下投票 booth 自然提供的保护。胁迫者、家暴伴侣或买票者可以直接监督投票过程，或者事后要求选民拿出证据。更糟的是，end-to-end verifiable e-voting 往往会把“可验证”与“可出示收据”绑在一起：如果选民能证明自己的票被正确记录和计入，很多时候也就能向外人证明自己投给了谁。

fake credential 是经典的应对思路。只要选民同时持有一个 real credential 和若干 fake credential，就可以表面服从胁迫者，之后再秘密用真实凭证投票。难点不在投票，而在注册。现有方案通常会落入三种代价很高的假设之一：相信 registrar 完全诚实、假设选民在注册时已经拥有未被攻陷的可信设备，或者要求选民和多个 registrar 交互。这些假设要么政治上尴尬，要么昂贵，要么在真实胁迫场景里站不住脚。TRIP 因而追问的是：能否设计一种注册流程，既让选民确信其中一个 credential 的确是真实的，又让他们之后无法向任何人证明哪一个是真的，并且整个流程普通人能学会、能操作？

## 核心洞察

这篇论文最重要的洞察是，真正需要保密的并不是某个复杂的密码学对象，而是一条“过程知识”：kiosk 在看到挑战之前，还是之后，生成了证明的 commitment。TRIP 用 Sigma-protocol 形式的 interactive zero-knowledge proof 来承载这一点。对 real credential，kiosk 先打印 commitment，选民随后挑选一个信封，其 QR code 提供 challenge；对 fake credential，顺序反过来，选民先挑信封，kiosk 再根据这个 challenge 伪造一份不 sound 但外观完整的 proof transcript。

一旦打印完成，real 和 fake credential 都只是纸面上的交互式证明 transcript。它们在结构上完全相似，选民离开 booth 时也没有携带任何可转移证据来向外界说明哪个是诚实生成的。论文的核心命题正是：让“步骤顺序”承担 individual verifiability 所需的那一点不可转移知识，而把带出 booth 的纸质凭证本身做成对胁迫者可否认的对象。

## 设计

Votegral 的整体架构分成 registration、activation、voting 和 tallying 四段。注册时，选民先向官方工作人员 check-in，然后进入装有 kiosk 和一叠带标记信封的 privacy booth。real credential 通过四步生成：选民扫描 check-in ticket；kiosk 打印一个 symbol 和一个 QR code；选民挑选带相同 symbol 的信封并扫描；然后 kiosk 再打印两个 QR code，补全整张 receipt。选民把 receipt 放进信封，并用自己的私有记号把它标成真实凭证。fake credential 则故意采用相反顺序：选民先选信封，kiosk 后打印整张 receipt，因此它可以针对已知 challenge 构造一份伪造但形式正确的 proof transcript。

从密码学上看，每个 credential 都有独立的签名密钥对，但同一注册会话里所有 credential 共享同一个 public credential tag。这个 tag 是对 real credential 公钥的加密。check-out 时，工作人员透过信封窗口扫描任意一份 credential；由于同一会话下所有 credential 都携带同一个 public tag，工作人员无法据此判断哪一个是真的。之后，选民在自己信任的设备上激活 credential：把 receipt 从信封中拉出一部分，露出此前被隐藏的 QR code 再进行扫描。投票时，每个 credential 像普通认证密钥一样使用；但 tally 阶段系统会同时对 registration tag 和 ballot 做 shuffle 与 blinding，只统计那些 credential key 能与被盲化后的 registration tag 匹配的 ballot。因为只有 real credential 的公钥会匹配那个“加密后的真实公钥 tag”，fake vote 会被自动丢弃，而不会暴露哪份 credential 是真的。

这套设计里，物理载体和流程本身与密码学同等重要。信封承担了廉价 challenge carrier 的角色，避免让选民手工生成随机数；信封窗口只在 transport 阶段暴露 check-out 所需的 QR code，把 secret material 一直遮到 activation 才露出。协议还故意把“步骤顺序”做成用户可观察的训练信号：instructional video 和 symbol-matching 步骤都是为了让选民学会“真实凭证是先看到 kiosk 打印，再选信封；伪造凭证则相反”。在这个基础上，论文对信任边界做了细分：普通选民不需要信任 registrar 就能获得选举正确性的公共可验证性；只有那些真的处于胁迫中的选民，才需要信任 kiosk 不与胁迫者串通。

## 实验评估

原型主要实现了密码学主路径，但规模并不小：TRIP 本身有 2,633 行 Go，完整 Votegral 原型有 9,182 行。对实际部署最关键的数字是注册延迟，因为这套方案明确要求一次线下 booth 访问。论文在 Point-of-Sale kiosk、Raspberry Pi 4、MacBook Pro VM 和 mini PC 上测得的端到端、选民可感知注册时延为 15.8 到 19.7 秒。真正占主导的不是密码学计算，而是 QR 扫描与打印，这两项至少占 wall-clock time 的 69.5%，说明这个系统更像是被机械 I/O 而不是被加密算法拖慢。

和其他 e-voting 系统相比，TRIP 的注册成本处在有竞争力的范围。以一百万选民为例，TRIP-Core 的人均注册延迟为 1.2 ms，Swiss Post 为 13 ms，VoteAgain 为 0.1 ms，Civitas 则高达 771 ms。Votegral 的投票路径也很轻，每位选民大约 1 ms。tallying 更慢，但仍处于大规模后台系统可接受的量级：一百万张 ballot 约需 14 小时，而 VoteAgain 为 3 小时，Swiss Post 为 27 小时，Civitas 因二次复杂度被估算为 1,768 年。论文也坦率承认 VoteAgain 之所以更快，是因为它接受了更强的信任假设，并继承了 revoting 方案的经典弱点：如果胁迫者能一直控制选民直到截止时间，选民就无法翻盘。

usability 证据令人鼓舞，但还谈不上决定性。在 150 名参与者的主实验中，83% 的参与者成功创建并使用了 real credential，System Usability Scale 得分为 70.4，略高于行业平均值。对 malicious kiosk 的检测能力则弱得多：接受过安全教育的参与者中有 47% 能识别并上报问题，而未接受教育者只有 10%。这些结果说明该流程是可以教会人的，但也同时表明，对单个特定选民的定点攻击并非不可能；这套安全叙事真正强的地方，在于攻击者若要大规模重复这种欺骗，很难长期不被发现。

## 创新性与影响

这篇论文最大的创新，在于把 fake-credential registration 从抽象设想落成了完整机制。JCJ 一类方案提出了 real/fake credential 的思路，却把注册阶段留在“untappable channel”这样的抽象假设后面，或放在很笨重的信任结构里。TRIP 则用 in-person registration、纸质载体、kiosk 生成的 proof transcript、公开日志、activation 与 usability study，把这一缺口补成了完整的 socio-technical system。其中最尖锐的技术贡献，是第一次把 paper transcript of interactive zero-knowledge proofs 用在注册阶段，从而同时得到 verifiability 与不可转移证据。

这种贡献不只是 e-voting 小修小补。论文把选举安全明确当作一个系统问题来处理：密码学、物理流程、设备信任、人类训练和吞吐成本必须一起设计。它关于 proof-of-personhood 与 broader democratic computing 的延伸讨论虽然仍是展望，但并不牵强：只要一个系统能区分“参与者自己知道哪个 credential 为真”和“参与者能把这个事实证明给别人看”，这种机制就可能在其他要求“真人且不受胁迫参与”的场景中同样重要。

## 局限性

最明显的局限是部署摩擦。TRIP 只是把线下注册成本摊薄，而没有消除它；真实部署必须解决 booth 监管、设备寄存、注册后通知、credential renewal，以及无障碍支持等一整套运营问题。和典型的“网页上点一点就能投票”的远程投票想象相比，这是一套明显更重的制度与运维安排。

安全模型本身也带有明显前提。论文假设 voter roster 正确、public ledger 可防篡改、tally authority 具备 threshold trust，并且投票通道足够匿名，以至于胁迫者不能只靠监控网络行为来判断选民是否后来又去投了真实一票。side channel、physical attack 和若干 impersonation 细节都被留到 appendix 或未来工作。最后，user study 与形式化模型也无法完全抹掉单个选民层面的残余风险：如果恶意 kiosk 恰好猜中 challenge envelope，或者选民没有注意到错误的步骤顺序，该选民仍可能被成功欺骗，即使这种攻击在大规模上会逐渐变得可检测。

## 相关工作

- _Juels et al. (TTE '10)_ - JCJ 提出了 real/fake credential 的 coercion-resistant voting 思路，但把注册阶段留给抽象的 untappable channel；TRIP 则把这一步具体实现成基于纸张与 kiosk 的流程。
- _Clarkson et al. (S&P '08)_ - Civitas 通过让选民与多个 registration teller 交互来降低对单一 registrar 的信任，而 TRIP 保留一次线下访问，把不可转移的保证放进 kiosk 与 envelope 的交互顺序中。
- _Krivoruchko (IAVoSS WOTE '07)_ - Robust coercion-resistant registration 要求选民在注册前用自己的设备生成并加密真实 credential；TRIP 去掉了这一可信设备前提，改用交互式证明来让选民确认真实凭证。
- _Moran and Naor (CRYPTO '06)_ - receipt-free voting 同样利用了 interactive zero-knowledge proof 避免产生可转移证据，但发生在投票阶段；TRIP 把这一思想迁移到注册阶段，并把它物化成纸质 transcript 与信封流程。

## 我的笔记

<!-- empty; left for the human reader -->
