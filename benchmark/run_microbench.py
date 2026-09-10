"""Single-machine Themis computation sampling; standard library only.

No network experiment, deployment, protocol alternative, or cross-protocol ratio.
"""
import argparse
import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WORKLOAD_VERSION = "themis-receipts-v1"
STAGES = ("GraphCore", "LeaderBuildFull", "CandidateCheckCore",
          "FollowerVerifyFull", "CommitFinalizeFull")


def parse_benchmarks(text):
    rows = []
    for line in text.splitlines():
        if not line.startswith("BenchmarkThemisLocal/"):
            continue
        fields = line.split()
        # Go may print a name on its own before an error/skip. Never treat it
        # as a timing; completeness validation below catches missing results.
        if len(fields) < 2:
            continue
        try:
            iterations = int(fields[1])
            if iterations <= 0 or len(fields[2:]) % 2:
                raise ValueError("invalid iterations or metric pairs")
            metrics = {fields[i + 1]: float(fields[i]) for i in range(2, len(fields), 2)}
            if any(unit not in metrics for unit in ("ns/op", "B/op", "allocs/op")):
                raise ValueError("required metric missing")
            if any(not (0 <= value < float("inf")) for value in metrics.values()):
                raise ValueError("nonfinite or negative metric")
        except (ValueError, IndexError) as exc:
            raise ValueError(f"malformed benchmark: {line}") from exc
        name = re.sub(r"-\d+$", "", fields[0])
        sample, stage = name.removeprefix("BenchmarkThemisLocal/").rsplit("/", 1)
        if stage not in STAGES:
            raise ValueError(f"unknown stage: {stage}")
        rows.append({"sample": sample, "stage": stage, "iterations": iterations,
                     "ns_per_op": metrics["ns/op"], "bytes_per_op": metrics["B/op"],
                     "allocs_per_op": metrics["allocs/op"]})
    return rows


def parse_samples(text):
    result = {}
    for line in text.splitlines():
        if line.startswith("THEMIS_MICRO_SAMPLE "):
            row = json.loads(line.split(" ", 1)[1])
            if row["workload_version"] != WORKLOAD_VERSION:
                raise ValueError("workload version mismatch")
            if row["sample"] in result:
                raise ValueError("duplicate sample metadata")
            result[row["sample"]] = row
    if not result:
        raise ValueError("no structural sample metadata")
    return result


def validate_results(rows, samples, repeats):
    expected = {(name, stage) for name, sample in samples.items()
                for stage in (STAGES if sample["candidate_available"] else STAGES[:2])}
    counts = {}
    for row in rows:
        key = row["sample"], row["stage"]
        counts[key] = counts.get(key, 0) + 1
    if set(counts) != expected or any(n != repeats for n in counts.values()):
        raise ValueError(f"incomplete/duplicate measurements: expected {repeats} of {sorted(expected)}, got {counts}")


def summarize(rows):
    # Keep each seed separate and expose process-to-process variation. Iterations
    # in testing.B are not independent observations for a confidence interval.
    groups = {}
    for row in rows:
        groups.setdefault((row["sample"], row["stage"]), []).append(row)
    result = []
    for (sample, stage), observations in sorted(groups.items()):
        values = [r["ns_per_op"] for r in observations]
        processes = {}
        for r in observations:
            processes.setdefault(r["process"], []).append(r["ns_per_op"])
        means = [statistics.mean(v) for v in processes.values()]
        mean = statistics.mean(means)
        result.append({"sample": sample, "stage": stage, "observations": len(values),
                       "independent_processes": len(processes), "min_ns": min(values),
                       "median_ns": statistics.median(values), "max_ns": max(values),
                       "process_mean_ns": mean,
                       "process_cv": statistics.stdev(means) / mean if len(means) > 1 and mean else None,
                       "median_B_per_op": statistics.median(r["bytes_per_op"] for r in observations),
                       "median_allocs_per_op": statistics.median(r["allocs_per_op"] for r in observations)})
    return result


def capture(command, env=None):
    return subprocess.run(command, cwd=ROOT, env=env, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True).stdout


def cpu_description():
    if sys.platform == "win32":
        return capture(["powershell", "-NoProfile", "-Command",
                        "(Get-CimInstance Win32_Processor).Name"]).strip()
    path = Path("/proc/cpuinfo")
    if path.exists():
        for line in path.read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or "unavailable"


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--nodes", type=int, nargs="+", default=[10, 50])
    p.add_argument("--faults", type=int, default=1)
    p.add_argument("--gamma", type=float, default=.95, help="native gamma_all")
    p.add_argument("--seeds", type=int, nargs="+", default=[1, 7, 19])
    p.add_argument("--history", type=int, default=480)
    p.add_argument("--receipt-cap", type=int, default=200, help="workload receipt events/replica/round, not LO limit")
    p.add_argument("--tx-size", type=int, default=512)
    p.add_argument("--scenarios", default="low_release,history_few,history_many,cycle,no_receipts")
    p.add_argument("--processes", type=int, default=4)
    p.add_argument("--count", type=int, default=1, help="testing.B repetitions within each process")
    p.add_argument("--benchtime", default="1s", help="1x is smoke only; default time calibration 1s")
    p.add_argument("--go", default="go")
    p.add_argument("--expected-go", help="require exact go env GOVERSION, e.g. go1.22.12")
    p.add_argument("--out", type=Path, default=ROOT / "benchmark" / "micro-results" / dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if min(args.processes, args.count, args.receipt_cap, args.tx_size) < 1:
        raise SystemExit("processes, count, receipt-cap and tx-size must be positive")
    if len(set(args.nodes)) != len(args.nodes) or len(set(args.seeds)) != len(args.seeds):
        raise SystemExit("duplicate nodes/seeds are not independent samples")
    env = dict(os.environ, GOMAXPROCS="1")
    # Do not silently accept profiling/race instrumentation from GOFLAGS.
    if any(word in env.get("GOFLAGS", "") for word in ("-race", "-cover", "profile", "-gcflags")):
        raise SystemExit("remove instrumentation from GOFLAGS before collection")
    go_version = capture([args.go, "env", "GOVERSION"], env).strip()
    if args.expected_go and go_version != args.expected_go:
        raise SystemExit(f"Go mismatch: {go_version} != {args.expected_go}")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    metadata = {"workload_version": WORKLOAD_VERSION, "commit": capture(["git", "rev-parse", "HEAD"]).strip(),
                "dirty_status": capture(["git", "status", "--porcelain", "--untracked-files=all"]),
                "cpu": cpu_description(), "os": platform.platform(), "go": capture([args.go, "version"], env).strip(),
                "go_env": json.loads(capture([args.go, "env", "-json"], env)),
                "GOMAXPROCS": 1, "GOGC": env.get("GOGC", "100 (default)"),
                "GOMEMLIMIT": env.get("GOMEMLIMIT", "off (default)"), "GODEBUG": env.get("GODEBUG", ""),
                "parameters": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                "argv": sys.argv if argv is None else argv, "commands": [], "status": "running",
                "allocation_definition": "execution time and cumulative allocation per replay"}
    source_files = [ROOT / "go.mod", *sorted((ROOT / "pkg").rglob("*.go")),
                    *sorted((ROOT / "benchmark").glob("*.py"))]
    metadata["source_sha256"] = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in source_files}

    def save():
        (out / "environment.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    def run(command, name):
        metadata["commands"].append({"argv": command, "cwd": str(ROOT), "log": name, "GOMAXPROCS": "1"})
        save()
        result = subprocess.run(command, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out / name).write_text(result.stdout, encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"command failed ({result.returncode}); see {out / name}")
        return result.stdout

    all_rows = []
    all_samples = {}
    try:
        # Tests are outside every measured subprocess, including exact fixture
        # differential checks for every requested n/seed below.
        run([sys.executable, "-m", "unittest", "discover", "-s", "benchmark", "-p", "test_run_microbench.py"], "collector-tests.log")
        run([args.go, "test", "./...", "-count=1"], "go-tests.log")
        for n in args.nodes:
            for seed in args.seeds:
                flags = [f"-micro-n={n}", f"-micro-f={args.faults}", f"-micro-gamma={args.gamma}",
                         f"-micro-seed={seed}", f"-micro-history={args.history}",
                         f"-micro-receipt-cap={args.receipt_cap}", f"-micro-tx-size={args.tx_size}",
                         f"-micro-scenarios={args.scenarios}"]
                manifest = run([args.go, "test", "./pkg/ofo", "-run=^TestMicroConfigured$", "-v", "-count=1", "-args", *flags], f"samples-n{n}-seed{seed}.log")
                all_samples[n, seed] = parse_samples(manifest)
                (out / f"samples-n{n}-seed{seed}.json").write_text(json.dumps(all_samples[n, seed], indent=2), encoding="utf-8")
        # Sequential fresh OS processes. Native stages have no A/B alternatives.
        for process in range(1, args.processes + 1):
            for n in args.nodes:
                for seed in args.seeds:
                    command = [args.go, "test", "./pkg/ofo", "-run=^$", "-bench=^BenchmarkThemisLocal$", "-benchmem",
                               f"-benchtime={args.benchtime}", f"-count={args.count}", "-timeout=60m", "-args",
                               f"-micro-n={n}", f"-micro-f={args.faults}", f"-micro-gamma={args.gamma}",
                               f"-micro-seed={seed}", f"-micro-history={args.history}", f"-micro-receipt-cap={args.receipt_cap}",
                               f"-micro-tx-size={args.tx_size}", f"-micro-scenarios={args.scenarios}"]
                    log = f"raw-p{process}-n{n}-seed{seed}.log"
                    print(f"process={process} n={n} seed={seed}: {log}", flush=True)
                    rows = parse_benchmarks(run(command, log))
                    validate_results(rows, all_samples[n, seed], args.count)
                    counters = {}
                    for row in rows:
                        key = row["sample"], row["stage"]
                        counters[key] = counters.get(key, 0) + 1
                        row.update(process=process, seed=seed, repeat=counters[key], raw_log=log,
                                   workload_version=WORKLOAD_VERSION)
                    all_rows.extend(rows)
                    with (out / "measurements.csv").open("w", newline="", encoding="utf-8") as file:
                        writer = csv.DictWriter(file, fieldnames=list(all_rows[0])); writer.writeheader(); writer.writerows(all_rows)
        (out / "summary.json").write_text(json.dumps(summarize(all_rows), indent=2), encoding="utf-8")
        metadata["status"] = "complete"
        save()
        print(out)
    except BaseException as exc:
        metadata.update(status="failed", error=str(exc))
        save()
        raise


if __name__ == "__main__":
    main()
