"""Summarize the fixed mechanism run. Requires matplotlib only for figures."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics as st

from run_microbench import STAGES

CASES = ("mechanism_small", "mechanism_cycle", "mechanism_update")
TITLES = ("Small complete (24 new)", "Large SCC (192 new)", "History update (480 old + 8 new)")


def paired_ratios(rows):
    pairs = {}
    for row in rows:
        if row["stage"] not in ("LeaderBuildFull", "FollowerVerifyFull"):
            continue
        key = (row["sample"], row["process"], row["repeat"])
        pair = pairs.setdefault(key, {})
        if row["stage"] in pair:
            raise ValueError("duplicate stage in a matched pair")
        value = float(row["ns_per_op"])
        if not 0 < value < float("inf"):
            raise ValueError("ratio requires positive finite durations")
        pair[row["stage"]] = value
    result = []
    for key, pair in sorted(pairs.items()):
        if len(pair) != 2:
            raise ValueError("unmatched build/verify observation")
        result.append({"sample": key[0], "process": key[1], "repeat": key[2],
                       "rho": pair["FollowerVerifyFull"] / pair["LeaderBuildFull"]})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    env = json.loads((out / "environment.json").read_text(encoding="utf-8"))
    aux = json.loads((out / "mechanism-environment.json").read_text(encoding="utf-8"))
    if env["status"] != "complete" or aux["status"] != "complete":
        raise ValueError("refusing incomplete experiment")
    for name, digest in aux["artifacts_sha256"].items():
        if hashlib.sha256((out / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"raw artifact changed: {name}")
    with (out / "measurements.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    ratios = paired_ratios(rows)
    samples = {}
    for file in sorted(out.glob("samples-*.json")):
        samples.update(json.loads(file.read_text(encoding="utf-8")))
    states = json.loads((out / "state-rows.json").read_text(encoding="utf-8"))
    processes = env["parameters"]["processes"]
    if len(rows) != 3 * 3 * 5 * processes:
        raise ValueError("wrong measurement count")
    summary = {}
    for case in CASES:
        subset = [r for r in rows if r["sample"].endswith("/" + case)]
        metrics = [s["metrics"] for name, s in samples.items() if name.endswith("/" + case)]
        if len(metrics) != 3 or any(m != metrics[0] for m in metrics):
            raise ValueError("structure differs across seeds; report separately")
        group = {"metrics": metrics[0], "stages": {}}
        for stage in STAGES:
            obs = [r for r in subset if r["stage"] == stage]
            if len(obs) != 3 * processes:
                raise ValueError("missing stage observations")
            values = [float(r["ns_per_op"]) / 1e6 for r in obs]
            group["stages"][stage] = {"median_ms": st.median(values), "min_ms": min(values),
                "max_ms": max(values), "median_bytes": st.median(float(r["bytes_per_op"]) for r in obs),
                "median_allocs": st.median(float(r["allocs_per_op"]) for r in obs), "observations": len(obs)}
        values = [r["rho"] for r in ratios if r["sample"].endswith("/" + case)]
        group["rho"] = {"median": st.median(values), "min": min(values), "max": max(values)}
        summary[case] = group
    (out / "mechanism-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (out / "paired-ratios.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(ratios[0])); writer.writeheader(); writer.writerows(ratios)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "pdf.fonttype": 42})
    colors = ["#6588a8", "#245878", "#d8a44c", "#b96727", "#628368"]
    fig, axes = plt.subplots(1, 3, figsize=(13.2, 4.6))
    for ax, case, title in zip(axes, CASES, TITLES):
        group = summary[case]
        means = [group["stages"][s]["median_ms"] for s in STAGES]
        errors = [[m - group["stages"][s]["min_ms"] for m, s in zip(means, STAGES)],
                  [group["stages"][s]["max_ms"] - m for m, s in zip(means, STAGES)]]
        bars = ax.bar(range(5), means, color=colors, yerr=errors, capsize=3)
        ax.set_xticks(range(5), ["Graph\ncore", "Leader\nbuild", "Check\ncore", "Follower\nverify", "Commit\nfinalize"], fontsize=9)
        ax.set_title(title, fontsize=11); ax.set_ylabel("Elapsed time per replay (ms)")
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_ylim(0, max(group["stages"][s]["max_ms"] for s in STAGES) * 1.28)
        padding = ax.get_ylim()[1] * .022
        for bar, value, stage in zip(bars, means, STAGES):
            ax.text(bar.get_x()+bar.get_width()/2, group["stages"][stage]["max_ms"] + padding, f"{value:.2f}", ha="center", va="bottom", fontsize=9)
    fig.suptitle("Native Themis sorting layer: overlapping computation boundaries", fontsize=13)
    fig.text(.5, .02, f"n=20, F=4, gamma=1; 3 seeds x {processes} processes; median and observed min-max; panels have separate scales", ha="center", fontsize=10)
    fig.tight_layout(rect=(0, .055, 1, .95))
    for ext in ("png", "pdf", "svg"): fig.savefig(out / f"computation-stages.{ext}", dpi=180)
    plt.close(fig)

    timeline = [r for r in states if r["seed"] == 1 and r["scenario"] == "deferred"]
    fig, ax = plt.subplots(figsize=(8.4, 4.4))
    x = list(range(3)); retained = [r["retained_txs"] for r in timeline]
    blocked = [r["complete_but_blocked_txs"] for r in timeline]
    incomplete = [a-b for a,b in zip(retained, blocked)]
    ax.bar([i-.18 for i in x], incomplete, width=.34, label="Retained: incomplete graph", color="#b96727")
    ax.bar([i-.18 for i in x], blocked, bottom=incomplete, width=.34, label="Retained: complete but blocked", color="#d8a44c")
    ax.bar([i+.18 for i in x], [len(r["released"]) for r in timeline], width=.34, label="Released this round", color="#245878")
    ax.set_xticks(x, ["R1: A/B unspecified", "R2: complete suffix arrives", "R3: update A -> B"])
    ax.set_ylabel("Transactions"); ax.set_ylim(0, 12); ax.set_yticks(range(0, 10, 1))
    ax.set_title("Controlled state transition: 3 -> 7 -> 0 retained; 0 -> 0 -> 9 released")
    ax.legend(frameon=False, loc="upper left", fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(.5,.02,"Logical rounds, not elapsed time. Same outcome for seeds 1, 7, 19; all 20 replicas verify and agree.",ha="center",fontsize=9)
    fig.tight_layout(rect=(0,.045,1,1))
    for ext in ("png", "pdf", "svg"): fig.savefig(out / f"controlled-state.{ext}", dpi=180)
    plt.close(fig)

    report = ["# Themis 固定工作负载微基准与状态实验", "",
        "本轮只增加测试场景、状态测试和采集/分析脚本，生产协议与调度代码不变。结果属于当前仓库的 Themis 排序层，不是完整 Themis–HotStuff 性能复现。", "",
        f"基线提交：`{env['commit']}`。Go：`{env['go']}`；CPU：`{env['cpu']}`；OS：`{env['os']}`。完整工作树状态和源文件 SHA-256 在 environment.json。", "",
        f"固定 n=20、F=4、γ=1、512-byte payload；seeds=1/7/19；每 seed {processes} 个新 Go 进程，GOMAXPROCS=1，benchtime={env['parameters']['benchtime']}。共 {len(rows)} 个阶段观测。合成接收顺序和真实签名证据在计时外产生；不运行 ticker，因此没有 lo_interval/lo_size 敏感性。", "",
        "## 1. 计算结果", "", "下表是各阶段 9 个观测的中位数，单位 ms/op（默认 3 进程时）。五列有包含关系，不能相加为端到端延迟，也不是互斥的堆叠分解。", "",
        "| 工作负载 | GraphCore | LeaderBuildFull | CandidateCheckCore | FollowerVerifyFull | CommitFinalizeFull |",
        "|---|---:|---:|---:|---:|---:|"]
    for case, title in zip(CASES, TITLES):
        report.append("| " + title + " | " + " | ".join(f"{summary[case]['stages'][s]['median_ms']:.3f}" for s in STAGES) + " |")
    report += ["", "![计算阶段](computation-stages.png)", "", "| 工作负载 | 配对 Verify/Build 中位数 [min, max] | 新图节点/边/最大 SCC | 旧图数/旧交易 | 更新边/释放交易 |", "|---|---:|---:|---:|---:|"]
    for case in CASES:
        g = summary[case]; m = g["metrics"]; r = g["rho"]
        report.append(f"| {case} | {r['median']:.3f} [{r['min']:.3f}, {r['max']:.3f}] | {m['new_graph_nodes']}/{m['new_graph_edges']}/{m['new_graph_max_scc']} | {m['deferred_batches']}/{m['retained_txs']} | {m['added_update_edges']}/{m['output_txs']} |")
    report += ["", "ρ 在同一 seed、进程、repeat 的相同输入状态内配对。它描述当前实现验证重算与构造的量级，不能解释为 AUTIG 加速比，不能乘以 n−1 推导集群节省。大环和小图同时改变规模及结构，不能用二者差值单独归因于 SCC。", "",
        "所有耗时 min/max、累计分配 B/op、allocs/op 在 mechanism-summary.json；各 seed 的进程间统计在 summary.json；原始记录在 measurements.csv。B/op 是每次调用的累计分配，不是保留状态大小或峰值内存。阶段顺序固定，未做顺序平衡；本机后台活动、GC、缓存和频率变化均可能影响结果。三种 seed 改变交易 ID/排序细节，保持图规模一致，不代表三种独立网络负载。", "",
        "## 2. 独立预期与状态结果", "",
        "采用 2022 修订版，结合作者后续正文的单方出现计票定义。此配置采用 16 份证据，solid 门槛 12，建边门槛 5。期望图写在状态测试中；权重通过独立列表扫描计算，SCC 通过独立可达性计算，不调用生产构图或排序函数生成期望答案。", "",
        "| 场景/轮次 | 新节点/边/最大 SCC | 新增旧图边 | 本轮释放 | 轮后保留 | 其中完整但被阻塞 |", "|---|---:|---|---:|---:|---:|"]
    for r in [r for r in states if r["seed"] == 1]:
        m = r["new_graph"]
        report.append(f"| {r['scenario']} R{r['round']} | {m['nodes']}/{m['edges']}/{m['max_scc']} | {', '.join(r['update_edges']) or '无'} | {len(r['released'])} | {r['retained_txs']} | {r['complete_but_blocked_txs']} |")
    report += ["", "![状态轨迹](controlled-state.png)", "",
        "一致接收 ABC 产生全序并释放 3 笔。环样本的 16 份报告为 ABC×6、BCA×5、CAB×5；票数 AB:BA=11:5、BC:CB=11:5、CA:AC=10:6，形成完整三节点环，仍释放全部交易。测试允许合法 Hamiltonian 路径的旋转，同时要求各副本最终顺序一致。", "",
        "阻塞轮报告为 ABZ×4、BAZ×4、Z×4、空×4。A/B 各出现 8 次，Z 出现 12 次；AB/BA 各 4 票，均不达 5；AZ/ZA=8:4，BZ/ZB=8:4。因此两条 shaded→solid 边保留，A/B 关系未定。R2 的 4 笔完整后续交易也须等待。R3 只追加各副本未收到的旧交易和两笔新交易，保持原接收顺序，更新 AB/BA=12:4 且 A 达到 16 次出现，合法补 A→B，按 proposal 顺序释放 3+4+2=9 笔。", "",
        "15 条状态记录（3 seeds × 5 轮）均通过；每轮 20 个逻辑副本分别执行真实验证和提交并比较协议状态。它是 20 个内存服务对象，不是 20 个独立网络节点。使用固定发送者 0..15；未测试首到报告选择、恶意节点、网络或完整共识。", "",
        "## 3. 可以与不可以支持的结论", "",
        "可以作为 AUTIG 论文中的 Themis 机制补充：本实现的候选验证仍执行图重算；完整 SCC 本身不意味着 deferred；未指定关系能导致后续完整 proposal 等待，后续证据可以解除等待。状态实验说明机制的存在，不说明这种情况在单区或跨区中的发生频率，也不测等待的毫秒数。", "",
        "本次不修复或优化生产路径中的邻接表扫描、图比较、历史扫描或克隆成本。CPU profiles 仅辅助辨识本实现热点，不能把自主实现成本都归为论文算法固有缺陷。不能据此推导 TPS、公平性概率、恶意节点性能或端到端延迟。", "",
        "已有 150 ms 单区/跨区数据原样保留。因为本次不修改生产行为，这组补充实验本身不要求重跑它们；但旧数据的代码版本、运行有效性、输入饱和度和指标边界仍须单独审核。新状态测试不能追认其他旧版本的正确性，也不能把 150 ms 宣称为 Themis 官方参数或最佳性能。", "",
        "## 4. 复现与证据", "",
        "复现命令及计时边界见 [THEMIS_MECHANISM.md](../../THEMIS_MECHANISM.md)。environment.json 保存微基准命令、源码哈希、系统信息；mechanism-environment.json 保存状态/profile 命令及原始产物哈希；state-rows.json 保存逐副本实际列表、Update、完整接收历史和每轮摘要。CPU profile 单独采集，未混入计时。", "",
        "论文依据：[2022 修订版](https://eprint.iacr.org/archive/2021/1465/1669765544.pdf)，§IV / 图1–3；[作者博士论文](https://mahimnakelkar.github.io/dissertation.pdf)，第6章、印刷页138 的 Weight 定义。此前逐项核验见 benchmark/review-20260913-independent/REVIEW.md。", ""]
    (out / "RESULTS.md").write_text("\n".join(report), encoding="utf-8")
    print(out / "RESULTS.md")


if __name__ == "__main__":
    main()
