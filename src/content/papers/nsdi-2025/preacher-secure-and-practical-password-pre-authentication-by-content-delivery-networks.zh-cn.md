---
title: "PreAcher: Secure and Practical Password Pre-Authentication by Content Delivery Networks"
oneline: "PreAcher 用 OPRF 加 LSH 让 CDN 先筛掉大多数错误密码登录，在缓解 ADoS 的同时不把密码暴露给 CDN。"
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

`PreAcher` 把 password login 的第一道筛选前移到 CDN，但不把密码交给 CDN。它把 OPRF 和 locality-sensitive hashing 组合起来，让 CDN 在边缘拦掉明显错误的密码，而 origin server 仍执行最终的常规密码校验；在论文的测试床上，即便同时承受 400 req/s 的 ADoS 流量，它仍能保持 97 次成功登录/秒，而 baseline 会跌到 0。

## 问题背景

密码登录部署简单、用户也熟悉，但安全的密码存储方式让登录路径天生昂贵。服务器必须运行 `PBKDF2`、`Argon2` 这类慢哈希，因此攻击者并不需要制造巨量 DDoS 流量，就能让系统失去可用性：只要持续发送一小股登录请求，就足以把 CPU 压满。论文用一个直接的实验说明了这一点：在商业 CDN、WAF 和 bot detection 的保护之后，攻击者仍可借助轮换代理 IP，以每秒 150 个随机凭证登录请求，把一台 4 vCPU 服务器压到接近 100% CPU，并持续一小时。

现有方案很难同时满足三个目标：挡住利用登录接口的 ADoS、避免 CDN 看见密码、并且能在今天的 Web 生态里立即部署。rate limit、CAPTCHA 和 2FA 要么牺牲可用性，要么仍然让服务器执行第一道密码校验；delegated authentication 虽然能卸载工作量，但许多站点无法把核心登录流程交给第三方；而现有 CDN 的 bot filtering 本质上是统计式判断，不是确定性过滤，并且由于网站往往会把 TLS 私钥分享给 CDN，CDN 常常可以直接看到密码负载。论文因此把目标收窄成一个更现实的问题：让 CDN 在请求到达源站前先筛掉坏密码，但又不能把密码本身交给 CDN。

## 核心洞察

这篇论文最关键的判断是：CDN 不需要知道密码“是否完全正确”。它只需要一个廉价测试，把明显错误的密码与那些“足够接近、值得交给源站再查一次”的密码区分开。`PreAcher` 因此故意削弱 CDN 获得的信息：CDN 不知道精确正确性，只知道输入密码是否落入与真实密码相同的 locality-sensitive bucket。

这也是它安全性的核心。如果 CDN 能完整验证密码，那么一个被动但好奇的 CDN 完全可以凭借自己看到的日志和状态离线跑 dictionary attack。`PreAcher` 把 OPRF 和 locality-sensitive hashing 结合起来，让相似密码映射到同一个 pseudo-password `p'`。这足以支撑 pre-authentication，却不足以让 CDN 在本地确认“哪一个候选密码才是真正的密码”。换句话说，系统用边缘侧的有意模糊，换回了对离线猜测的抑制，把真正的密码枚举重新逼回到必须经过源站的在线交互里。

## 设计

`PreAcher` 包含一个 registration 阶段和一个两轮的 login 阶段。注册时，client 和 origin server 通过 `LSH(p)` 与每用户 OPRF 密钥 `k_u` 共同导出一个秘密 `d'`。随后 client 生成公私钥对 `pk'_u` 和 `sk'_u`，再用 `d'` 把 `sk'_u` 加密成 envelope `e'_u`。与此同时，origin server 仍保存常规 full authentication 所需的 salted password hash；但它还会把 `k_u`、`pk'_u` 和 `e'_u` 发给 CDN，以便 CDN 在后续登录中参与 pre-authentication。这个拆分是刻意设计的：源站侧仍保留兼容现有网站登录栈的传统状态，而 CDN 只拿到足够早筛请求的最小材料。

登录的第一轮是让 client 重新拿回 `d'`。client 先计算 `LSH(p)`，再和 CDN 完成一次 OPRF 交互，得到 `d'` 后解开 `e'_u`，取回 `sk'_u`。第二轮中，client 一边用 `sk'_u` 对 CDN 的 challenge `C` 做签名，完成 pre-authentication；一边把真实密码用 origin server 的公钥加密，作为 full authentication 的输入。CDN 用已存的 `pk'_u` 验证签名，失败就直接在边缘拒绝；成功才把加密后的密码消息转发给 origin server。源站解密后再执行传统的 salted-password 校验。论文之所以保留这一步常规校验，是因为 threat model 信任源站，而且这样能避免再增加一个 RTT，也更兼容现有网站实现。

另一个关键机制是 LSH 本身。`PreAcher` 采用的是 weighted K-mer MinHash：先把密码转成小写，用长度为 `K` 的滑动窗口切成 K-mer，再把 K-mer 连同出现次数和用户名一起送入 `HMAC-SHA256`，最后取最小值作为映射结果。这样一来，编辑距离较近的密码会落入同一个 `p'`，从而降低 CDN 在离线场景中区分精确密码的能力；与此同时，随机暴力生成的密码与真实密码碰撞的概率只有 `1/c^K`。在论文给出的例子里，`K=4`、字母表大小 `c=66` 时，随机攻击流量通过 pre-authentication 的概率低于 `10^-7`。论文还把这一设计与更直观的 `DuoHash` 对比：后者虽然也能做边缘筛选，但仍要在 CDN 上执行慢哈希，性能上很难成立。

## 实验评估

实验同时评估了安全权衡和系统开销。针对离线猜测，作者从 4iQ 泄露数据中取出 5,000 个用户，把其中一个历史密码视为 CDN 已知，再用 `pass2path` 为每个账户生成 10,000 个候选密码。没有 LSH 时，CDN 可以离线攻破约 8.42% 的账户；引入 LSH 之后，在论文默认参数 `K=4`、检测阈值 `Q=20` 下，未被服务器发现的攻破率降到 0.20% 以下，同时随机猜测通过 pre-authentication 的概率仍低于 `10^-7`。这正是论文想要的平衡点：保留足够多的碰撞来阻止 CDN 精确推断，但又不至于让随机攻击流量穿透到源站。

针对 ADoS 韧性，测试床同时发送 100 次有效登录/秒和 400 次攻击登录/秒。baseline 在无攻击时能提供 100 次成功登录/秒，但在攻击下直接跌到 0；`PreAcher` 在无攻击时也是 100，而在攻击下仍有 97。`DuoHash` 和基于 SGX 的 strawman 都明显退化，因为慢哈希本身先把 CDN 压垮了。更底层的机制数据也支持这个结论：在测试床上，`PreAcher` 的边缘 pre-authentication 吞吐达到 948 req/s，CPU 仅占 23%；而 `DuoHash` 只有 99 req/s，SGX-CDN 只有 91 req/s，二者都已经吃满 100% CPU。

这些收益并不是免费的，但对 login path 来说仍算合理。在测试床上，`PreAcher` 的 CDN pre-authentication 中位 CPU 时间只有 0.16 ms；部署到 Cloudflare 后，由于边缘逻辑必须用 JavaScript 而不是原型里的 C++，这个数字上升到 8.3 ms。协议还额外引入了一次 client-to-CDN RTT。论文在六个 Azure 区域测得，相比 baseline，成功登录的中位延迟通常增加 42 到 72 ms；Johannesburg 的开销更大，是因为 Cloudflare 把请求转发到了更远的边缘节点。整体来看，论文“能实用部署”的结论是可信的：`PreAcher` 不是零成本，但它对登录路径的额外代价足够小，而且远低于需要在 CDN 上做慢哈希的替代方案。

## 创新性与影响

这篇论文的创新点并不只是“让 CDN 参与认证”。真正的新意在于，它构造了一个三方架构：CDN 拿到的能力足以在边缘卸掉恶意负载，却又拿不到足以精确验证密码的信息。OPAQUE 一类 PAKE 的确启发了 OPRF 加 envelope 的结构，但它们本身并不能解决“中间多了一个 CDN”这个问题。真正让三方拆分成立的，是叠加在其上的 LSH 层。

这使得 `PreAcher` 对已经依赖 CDN、又长期承受 credential stuffing 或 login flood 压力的大型网站很有现实意义。它的部署路径也相当务实：client 侧是登录页里的 JavaScript library，origin server 侧做少量改造，CDN 侧运行现有 serverless 平台上的 edge code。整个方案不要求修改浏览器、不要求 CDN 换硬件，也不要求引入新的信任根。我预计它会同时影响 Web security 研究者和那些真正想在生产系统里缓解 password login 滥用的工程团队。

## 局限性

论文的安全模型只考虑被动的 honest-but-curious CDN attacker。它并不解决 CDN 被攻陷后主动篡改协议消息的情形，作者只是指出可以和外部完整性机制结合。registration 还被假设为 ADoS-resistant；对于一次性开户、高摩擦注册流程或线下开户，这个假设是合理的，但它毕竟仍是一个假设。更广泛地说，`PreAcher` 保护的对象仅限于登录路径上的密码，并不隐藏登录后的普通应用流量或 cookie。

LSH 参数本身也带来真实的调参权衡。更小的 `K` 会进一步压低 CDN 侧猜中的概率，但也会让更多“近似密码”流入源站；更大的 `K` 则能提升过滤精度，却会把更多信息泄露给好奇的 CDN。论文用仿真选择了 `K=4` 和 `Q=20`，但并没有研究真实用户大量输错密码、频繁 typo 或长期运营过程中的误报问题。实验作为 prototype study 很扎实，但它仍然是 prototype，而不是跨数月生产流量的长期部署报告。

## 相关工作

- _Jarecki et al. (EUROCRYPT '18)_ - `OPAQUE` 是两方 asymmetric PAKE；`PreAcher` 借用了 OPRF 加 envelope 的结构，但把它扩展到了 CDN 介入的三方登录流程。
- _Lin et al. (CCS '22)_ - `InviCloak` 通过 CDN 构建端到端保密信道，而 `PreAcher` 则把目标收窄为登录路径上的密码保密与 ADoS 过滤。
- _Xin et al. (PAM '23)_ - 这篇测量论文量化了 third-party CDN 暴露用户密码的程度；`PreAcher` 则把这种暴露转化成了一个具体的防御架构。
- _Herwig et al. (USENIX Security '20)_ - `Conclaves` 用 TEE 保护 CDN 侧的 TLS 处理，而 `PreAcher` 避免依赖专用硬件，重点放在过滤滥用的 password login 上。

## 我的笔记

<!-- 留空；由人工补充 -->
