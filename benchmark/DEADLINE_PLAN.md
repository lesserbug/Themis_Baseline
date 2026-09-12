# 截稿前的最小实验计划

本次仅增加实验有效性保护、轻量诊断和日志追溯。不改 FairPropose / FairUpdate /
FairFinalize，不截断完整列表，不优化邻接查询，不增加 proposer 或网络 worker。

## 先确认复现范围

- 当前是自主实现的 Themis 排序层加简化 hosting gate，不是作者完整的 HotStuff 实现。
- 当前 `lo_size` 是无效兼容字段，不能继续作为 Themis 敏感性横轴。
- 原论文评测有 proposal blocksize β（50、400），当前实现没有这个可配置边界。
  不能把 `lo_size` 改成局部列表截断来宣称复现了 β。
- 实际完整列表规模、proposal 图节点数会影响耗时；没有 size 上限不等于没有规模效应。
- `batchReadyChanSize=256` 是队列容量，每个队列元素含 n-f 个 replica reports，
  不是每个 proposal 的交易数。公平性定义中的 Condorcet batch 也不是配置上限。
- README 的部分接收列表权重解释问题仍未解决；测试通过不能证明完整复现论文。
  如果主结论需要在任意部分接收场景下声称论文公平性，此问题必须先澄清；
  若无法按期澄清，应缩小声明并标注实现限制，不能当作论文固有缺点。

作者来源：[Themis 章节 §6.4、§6.5.1](https://mahimnakelkar.github.io/dissertation.pdf#page=154)。
§6.5.1（印刷页153）明确说明 β 表示 proposal 的交易数。

## 接下来按顺序做

1. 保存这次代码及版本，并让远程实际构建该版本。当前 fab remote 从 settings 的远程
   Git 分支构建，不自动上传本地源码。核对日志 THEMIS BUILD 中 revision/modified。
   本地 settings 不是之前 n=10 实验的完整记录；重新确认 n=10、f=1、γ、交易大小、
   机器、区域、时长，所有比较固定一致。n=10/f=1 要满足 γ>0.7；不要顺便改变 γ。
2. 先做 50/150 ms × 输入 500/700 TPS，每组合3次，共12次。保持原测量时长
   （若原来60秒就继续60秒），不要用短跑证明稳定。如果700过载，保留并标记该现象。
3. 每次核对 actual_offered_rate、所有发送/验证失败、最终状态一致性、completion_ratio、
   outstanding 随时间走势。不能只看最终平均 TPS 和完成交易的平均延迟。
4. 出现 `BENCHMARK INVALID: evidence queue exhausted` 时，保留失败日志，标注本实现
   队列资源耗尽；不将此次 TPS 纳入有效性能平均，也不悄悄重跑直到成功。
   这个保护不保证过载稳定，不证明该点是论文算法的饱和容量。
5. 看诊断：list mean/max 是否变大、build 与 hosting 各花多久、batch_queue 是否累积。
   `build_nil` 不是纯粹的旧列表丢弃计数，不能据它独自推断原因。
6. 若50 ms在相同资源下重复表现更好且有效，就将它作为独立校准后的 Themis 配置，
   主曲线统一用它重跑；不混用不同 interval 的最好单次结果。若结果不一致，再补600 TPS，
   不扩展整套扫描。必要时用更长的一次运行确认所选工作点没有持续积压。

## 论文中实验的取舍

| 项目 | 截稿前建议 |
|---|---|
| AUTIG 自身的参数敏感性 | 继续做真正进入执行路径的参数 |
| Themis lo_size | 取消，当前参数无效 |
| Themis lo_interval | 可作为本实现上报间隔的敏感性；优先仅保留上述校准，正文不必独立成节 |
| Themis proposal blocksize β | 当前没有复现，不能声称已做其敏感性 |
| Themis 主 TPS/延迟比较 | 用统一、经校准的配置和同一代码版本；报告重复波动及无效运行 |
| Themis γ | 时间紧时不新增；相同数值不自动等于 AUTIG 的同一公平性保证 |

已有 lo_size 数据不再用于 size 敏感性结论。旧 interval 结果保留作探索记录；
主结论优先来自有完整日志、明确版本且通过有效性检查的新运行。
若只能完成这12次校准，也不要把它们称为完整的容量测定或作者结果复现。
