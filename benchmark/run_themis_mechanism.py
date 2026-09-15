"""Fixed Themis-only mechanism experiment; no deployment or protocol edits."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess

import run_microbench

SCENARIOS = "mechanism_small,mechanism_cycle,mechanism_update"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--processes", type=int, default=3)
    parser.add_argument("--benchtime", default="1s")
    args = parser.parse_args()
    run_microbench.main([
        "--nodes", "20", "--faults", "4", "--gamma", "1",
        "--seeds", "1", "7", "19", "--history", "480",
        "--receipt-cap", "200", "--tx-size", "512", "--scenarios", SCENARIOS,
        "--processes", str(args.processes), "--count", "1",
        "--benchtime", args.benchtime, "--out", str(args.out),
    ])
    out = args.out.resolve()
    manifest = {"status": "running", "started": dt.datetime.now(dt.timezone.utc).isoformat(),
                "commands": [], "scope": "local computation and controlled state; no ticker/network/BFT"}
    env = dict(os.environ, GOMAXPROCS="1")

    def save():
        (out / "mechanism-environment.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def run(command, name):
        manifest["commands"].append({"argv": command, "cwd": str(run_microbench.ROOT), "log": name})
        save()
        result = subprocess.run(command, cwd=run_microbench.ROOT, env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out / name).write_text(result.stdout, encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"command failed: {name}")
        return result.stdout

    try:
        text = run(["go", "test", "./pkg/ofo", "-run=^TestThemisMechanismStates$", "-count=1", "-v"], "state-tests.log")
        rows = [json.loads(line.split(" ", 1)[1]) for line in text.splitlines() if line.startswith("THEMIS_STATE_ROW ")]
        expected = {(seed, scenario, round_) for seed in (1, 7, 19)
                    for scenario, round_ in (("unanimous", 1), ("complete_cycle", 1), ("deferred", 1), ("deferred", 2), ("deferred", 3))}
        keys = {(r["seed"], r["scenario"], r["round"]) for r in rows}
        if len(rows) != 15 or keys != expected:
            raise ValueError("state rows incomplete or duplicated")
        (out / "state-rows.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
        # Profiles are auxiliary separate runs, never included in benchmark timings.
        for scenario, stage in (("mechanism_cycle", "FollowerVerifyFull"),
                                ("mechanism_update", "FollowerVerifyFull"),
                                ("mechanism_update", "LeaderBuildFull")):
            name = scenario if stage == "FollowerVerifyFull" else scenario + "-leader"
            profile = out / f"{name}.pprof"
            run(["go", "test", "./pkg/ofo", "-run=^TestThemisMechanismProfile$", "-count=1", "-v", "-args",
                 "-micro-n=20", "-micro-f=4", "-micro-gamma=1", "-micro-seed=1",
                 f"-micro-scenarios={scenario}", f"-mechanism-profile={profile}",
                 "-mechanism-profile-duration=5s", f"-mechanism-profile-stage={stage}"], f"{name}-profile.log")
            run(["go", "tool", "pprof", "-top", "-nodecount=25", str(profile)], f"{name}-cpu-top.txt")
            run(["go", "tool", "pprof", "-top", "-cum", "-nodecount=25", str(profile)], f"{name}-cpu-cumulative.txt")
        manifest["status"] = "complete"
        manifest["artifacts_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in sorted(out.iterdir()) if p.is_file() and p.name != "mechanism-environment.json"}
        save()
    except BaseException as exc:
        manifest.update(status="failed", error=str(exc)); save(); raise


if __name__ == "__main__":
    main()
