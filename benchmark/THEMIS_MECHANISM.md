# Themis 机制补充实验：固定输入的计算成本与状态迁移

本实验只改动 `*_test.go`、实验脚本和文档。生产接收、签名、图计算、验证、提交、
`lo_size`/`lo_interval`、AUTIG、AWS 配置均不改变。适用于补充机制证据；不是新的端到端性能比较。

## 本机复现

在仓库根目录运行，Python 采集器只依赖标准库；分析/画图需要 matplotlib。
输出目录必须不存在。不要与其他基准、编译、安装依赖任务同时运行。

```powershell
python benchmark/run_themis_mechanism.py --out benchmark/mechanism-results/my-run --processes 3 --benchtime 1s
python -m unittest discover -s benchmark -p test_analyze_themis_mechanism.py
python benchmark/analyze_themis_mechanism.py benchmark/mechanism-results/my-run
```

缺少 matplotlib 时，先在独立 Python 环境安装，再开始采样。本次环境安装在系统临时目录，
没有修改仓库或全局 Python 依赖。仅复核状态，无需 matplotlib：

```powershell
go test ./pkg/ofo -run '^TestThemisMechanismStates$' -count=1 -v
```

采集流程先运行既有采集器测试和 `go test ./... -count=1`，再核验各 seed 的精确工作负载，
运行 9 个顺序启动的基准进程；之后单独输出状态日志及 3 个 5 秒 CPU profile。
profile 包围大 SCC 和历史更新的 FollowerVerifyFull、历史更新的 LeaderBuildFull 对应调用和摘要，
排除工作负载生成和预检，不混入基准计时。
失败运行保留日志并标为 failed，分析器拒绝不完整或已改动的原始产物。

## 固定参数和三组样本

`n=20,F=4,γ=1`，16 份有效证据，solid=12，edge threshold=5，512-byte payload，
seeds=1/7/19，GOMAXPROCS=1，正常 GC。没有攻击节点，没有参数扫描。

| 样本 | 新图 | 测量前保留状态 | 当前轮效果 |
|---|---|---|---|
| mechanism_small | 24 笔，一致全序，276 边，最大 SCC=1 | 无 | 输出24 |
| mechanism_cycle | 192 笔，三组块旋转接收顺序，18336 边，最大 SCC=192 | 无 | 输出192 |
| mechanism_update | 8 笔，一致全序，28 边 | 480 笔、4 个 proposal，首图一对关系未定 | 补1边，释放488 |

以上三个样本新增到既有 `makeMicroFixture`，没有改变既有样本、默认参数或五个计时函数。
样本形成使用真实 admission、List/Update 签名、构建、验证和提交。每个样本均先完成3笔交易，
所以微基准的 completed ID history 非空；状态测试是另外的独立小例，不含该预热。

每副本每轮最多200个新投递事件仅约束测试生成器，绝不截断 LocalOrder/Update。
mechanism_update 的更新列表可达480个 ID，来自真实保留历史。
本实验直接控制逻辑接收顺序及调用轮次，未启动 ticker；构造器的兼容参数不参与调度。
因此它不证明取消生产 `lo_interval` 可行，也不改变旧150ms结果的调度语义。

## 计时边界和统计

原有 [MICROBENCHMARKS.md](MICROBENCHMARKS.md) 列出了精确函数边界：

- GraphCore：构图、分类、剪枝、旧图 FairUpdate。
- LeaderBuildFull：从已收集签名证据开始，验签、复制、构图/更新、构造候选和摘要。
- CandidateCheckCore：Core 图计算和候选图/状态/更新比较。
- FollowerVerifyFull：原生 VerifyProposal 完整重算核验，另计候选摘要。
- CommitFinalizeFull：已验候选的暂存复制、应用更新、SCC/Hamiltonian 排序、按高度释放和清理；恢复基准快照不计时。

这些边界重叠，不能将五个数相加为总成本。FairUpdate 的**计算**在构建/验证中，
提交阶段负责**应用**边和 finalize。所有 Full 均不表示整个分布式协议。
不计客户端、生成 List/Update、签发证据、收集等待、网络、BFT 共识和完整 hosting 路径。

图给出3 seeds×3进程的9个观测的中位数和全部 min/max；这不是置信区间。
`summary.json` 保留各 seed 的进程间统计，不把 testing.B 的循环次数当独立样本。
ρ=FollowerVerifyFull/LeaderBuildFull 按相同 sample/进程/repeat 配对后汇总，
只能支持当前实现和这些输入的计算量级结论，不能外推集群CPU节省或跨协议加速比。
阶段按固定顺序测量，未做顺序平衡。大图和小图规模及结构都不同，不构成 SCC 单因素实验。

## 状态测试的独立预期

`mechanism_test.go` 不调用生产算法生成预期图。直接扫描输入计票，显式写出应有图与状态，
用独立的可达性闭包统计 SCC。完整环只要求有效 Hamiltonian 路径及副本间一致性。
这是少量定向正确性测试，不能代替全面算法证明。

1. 一致接收 ABC：完整 DAG，释放全部3笔。
2. ABC×6、BCA×5、CAB×5：形成 A→B→C→A 完整环，最大 SCC=3，仍释放3笔。
3. ABZ×4、BAZ×4、Z×4、空×4：AB/BA=4/4，均低于5；A/B shaded，Z solid；保留 A→Z、B→Z，无输出。
4. 所有副本接收 D0..D3：新的完整 proposal 也被旧图阻塞，保留总数从3到7。
5. 只追加各副本遗漏的 A/B/Z 和 E0/E1：AB/BA=12/4，A 出现16次，补 A→B，按 proposal 顺序输出9笔，保留清空。

每个 seed 独立创建20个内存服务对象；固定采用0..15发送者，全部20个服务执行验证和提交。
没有消息乱序选择、停发、恶意签名、网络延时或公平性概率估计。
状态轨迹的横轴是轮次；不能转换为毫秒，也不能估计该轨迹在 WAN 中的出现概率。

依据：2022版 Themis §IV 图1–3，作者2025博士论文第6章印刷页138的单方出现计票澄清。
版本链接与审查细节见 [独立审查](review-20260913-independent/REVIEW.md)。
