from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from json import dump, dumps, load, loads
from pathlib import Path
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError
from fabric import Connection, task


BENCHMARK_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCHMARK_DIR.parent
SETTINGS_FILE = BENCHMARK_DIR / "settings.json"
BUILD_DIR = BENCHMARK_DIR / ".build"
RUNTIME_DIR = BENCHMARK_DIR / ".runtime"
LOG_DIR = BENCHMARK_DIR / "logs"
RESULT_DIR = BENCHMARK_DIR / "results"
GO_VERSION = "1.22.12"


def _run_id(mode, parameters, run):
    """One identity shared by raw logs and the result, including repeat sweeps."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return (
        f"{mode}-n{parameters['nodes']}-f{parameters['faults']}"
        f"-r{parameters['rate']}-i{parameters['lo_interval']}"
        f"-run{run}-{timestamp}-{uuid4().hex[:8]}"
    )


def _settings():
    with SETTINGS_FILE.open("r", encoding="utf-8") as source:
        settings = load(source)
    for key in ("key", "port", "repo", "instances", "benchmark"):
        if key not in settings:
            raise RuntimeError(f"settings.json is missing {key!r}")
    for mode in ("local", "remote"):
        if mode not in settings["benchmark"]:
            raise RuntimeError(f"settings.json benchmark section is missing {mode!r}")
    return settings


def _testbed(settings):
    return settings.get("testbed", "themis")


def _binary(name="themis"):
    suffix = ".exe" if os.name == "nt" else ""
    return BUILD_DIR / f"{name}{suffix}"


def _build_local():
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["go", "build", "-o", str(_binary()), "./pkg"],
        cwd=REPO_ROOT,
        check=True,
    )


def _validate_parameters(parameters):
    n = int(parameters["nodes"])
    f = int(parameters["faults"])
    gamma = Decimal(str(parameters["gamma"]))
    if n <= 0 or f < 0 or f >= n:
        raise RuntimeError("Themis requires 0 <= f < n")
    if not Decimal("0.5") < gamma <= 1:
        raise RuntimeError("Themis requires gamma_all in (1/2, 1]")
    if n * (2 * gamma - 1) <= 4 * f:
        raise RuntimeError("Themis requires n > 4f/(2*gamma_all-1)")
    if int(parameters["tx_size"]) < 16:
        raise RuntimeError("tx_size must be at least 16 bytes")
    for name in ("rate", "lo_interval", "lo_size", "duration"):
        if int(parameters[name]) <= 0:
            raise RuntimeError(f"{name} must be positive")
    tolerance = float(parameters["offered_rate_tolerance"])
    if tolerance < 0:
        raise RuntimeError("offered_rate_tolerance must be non-negative")


def _prepare_runtime(nodes, addresses):
    if len(addresses) != nodes:
        raise RuntimeError(f"expected {nodes} addresses, got {len(addresses)}")
    if RUNTIME_DIR.exists():
        shutil.rmtree(RUNTIME_DIR)
    RUNTIME_DIR.mkdir(parents=True)
    config = {"nodes": {str(i): address for i, address in enumerate(addresses)}}
    with (RUNTIME_DIR / "config.json").open("w", encoding="utf-8") as target:
        dump(config, target, indent=2)


def _command(parameters, node_ids, config="config.json", binary=None):
    binary = str(binary or _binary())
    ids = ",".join(str(i) for i in node_ids)
    return [
        binary,
        "-config", config,
        "-nodes", ids,
        "-f", str(parameters["faults"]),
        "-gamma", str(parameters["gamma"]),
        "-lo-interval", str(parameters["lo_interval"]),
        "-lo-size", str(parameters["lo_size"]),
        "-tx-rate", str(parameters["rate"]),
        "-tx-size", str(parameters["tx_size"]),
        "-sim-duration", str(parameters["duration"]),
    ]


def _duration_ms(value):
    if value == "N/A":
        return None
    units = {"ns": 0.000001, "us": 0.001, "µs": 0.001, "ms": 1, "s": 1000, "m": 60000, "h": 3600000}
    parts = re.findall(r"([0-9.]+)(ns|us|µs|ms|s|m|h)", value)
    if parts and "".join(number + unit for number, unit in parts) == value:
        return sum(float(number) * units[unit] for number, unit in parts)
    raise RuntimeError(f"unknown Go duration {value!r}")


def _parse_log(path):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if any(marker in text for marker in ("BENCHMARK INVALID", "panic:")):
        raise RuntimeError(f"{path} reports a failed benchmark")
    patterns = {
        "measurement_duration": r"Measurement Duration:\s*(\S+)",
        "submitted": r"Total Submitted:\s*(\d+)",
        "finalized": r"Total Finalized:\s*(\d+)",
        "tps": r"Average TPS:\s*([0-9.]+)",
        "offered_rate": r"Actual Offered Rate:\s*([0-9.]+)",
        "failed_send_attempts": r"Locally Failed Transaction Send Attempts:\s*(\d+)",
        "latency": r"Mean Completed-Transaction Latency:\s*(\S+)",
        "latency_samples": r"Latency Samples:\s*(\d+)",
        "outstanding": r"Outstanding:\s*(\d+)",
        "completion_ratio": r"Completion Ratio:\s*([0-9.]+)",
    }
    matches = {name: re.search(pattern, text) for name, pattern in patterns.items()}
    missing = [name for name, match in matches.items() if match is None]
    if missing:
        raise RuntimeError(f"{path} is missing final metrics: {', '.join(missing)}")
    if "Gamma Semantics: Themis all-replica premise" not in text:
        raise RuntimeError(f"{path} does not identify Themis all-replica gamma semantics")
    return {
        "measurement_duration_ms": _duration_ms(matches["measurement_duration"].group(1)),
        "submitted": int(matches["submitted"].group(1)),
        "finalized": int(matches["finalized"].group(1)),
        "average_tps": float(matches["tps"].group(1)),
        "actual_offered_rate": float(matches["offered_rate"].group(1)),
        "locally_failed_transaction_send_attempts": int(matches["failed_send_attempts"].group(1)),
        "mean_completed_transaction_latency_ms": _duration_ms(matches["latency"].group(1)),
        "latency_samples": int(matches["latency_samples"].group(1)),
        "outstanding": int(matches["outstanding"].group(1)),
        "completion_ratio": float(matches["completion_ratio"].group(1)),
        "locally_failed_local_order_send_attempts": text.count("BENCHMARK LOCAL SEND FAILURE: LocalOrder"),
        "locally_failed_candidate_send_attempts": text.count("BENCHMARK CANDIDATE SEND FAILURE"),
        "locally_failed_benchmark_commit_send_attempts": text.count("BENCHMARK COMMIT SEND FAILURE"),
        "proposal_verification_failures": text.count("THEMIS PROPOSAL VERIFICATION FAILED"),
        "order_extraction_failures": text.count("THEMIS ORDER EXTRACTION FAILED"),
        "follower_candidate_rejections": text.count("BENCHMARK FOLLOWER REJECTED CANDIDATE"),
        "hosting_commit_rejections": len(re.findall(r"BENCHMARK HOSTING .*COMMIT REJECTED", text)),
        "replica_states": {
            replica: (seq, state, digest)
            for replica, seq, state, digest in re.findall(
                r"BENCHMARK STATE replica=(\d+) seq=(\d+) state=([0-9a-f]{64}) fragment=([0-9a-f]{64})", text
            )
        },
        "log_paths": [str(Path(path).resolve())],
        "build_metadata": [loads(value) for value in re.findall(r"^THEMIS BUILD (\{[^\n]+\})$", text, re.MULTILINE)],
        "diagnostics_samples": [loads(value) for value in re.findall(r"^THEMIS DIAGNOSTICS (\{[^\n]+\})$", text, re.MULTILINE)],
    }


def _write_result(mode, parameters, run, metrics):
    states = metrics["replica_states"]
    if set(states) != {str(i) for i in range(parameters["nodes"])} or len(set(states.values())) != 1:
        raise RuntimeError("replicas did not report the same final committed sequence, state and fragment")
    cutoff_seconds = metrics["measurement_duration_ms"] / 1000
    configured_rate = int(parameters["rate"])
    actual_rate = metrics["submitted"] / cutoff_seconds
    tolerance = float(parameters["offered_rate_tolerance"])
    if configured_rate == 0:
        # A nonzero observation has no relative deviation from a zero target.
        # Use JSON null rather than Infinity, and flag the unexpected workload.
        relative_deviation = 0.0 if actual_rate == 0 else None
        rate_within_tolerance = actual_rate == 0
    else:
        relative_deviation = abs(actual_rate - configured_rate) / configured_rate
        rate_within_tolerance = relative_deviation <= tolerance
    metrics["average_tps"] = metrics["finalized"] / cutoff_seconds
    metrics["actual_offered_rate"] = actual_rate
    metrics["configured_offered_rate"] = configured_rate
    metrics["offered_rate_relative_deviation"] = relative_deviation
    metrics["offered_rate_tolerance"] = tolerance
    metrics["offered_rate_within_tolerance"] = rate_within_tolerance
    failure_metrics = (
        "locally_failed_transaction_send_attempts",
        "locally_failed_local_order_send_attempts",
        "locally_failed_candidate_send_attempts",
        "locally_failed_benchmark_commit_send_attempts",
        "proposal_verification_failures",
        "order_extraction_failures",
        "follower_candidate_rejections",
        "hosting_commit_rejections",
    )
    for key in failure_metrics:
        if metrics[key] != 0:
            raise RuntimeError(f"benchmark reports {metrics[key]} {key}")
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc)
    result = {
        "protocol": "themis-ordering-layer",
        "gamma_semantics": "all-replica",
        "mode": mode,
        "timestamp": timestamp.isoformat(),
        "run": run,
        **parameters,
        **metrics,
    }
    result["run_id"] = parameters.get("run_id") or _run_id(mode, parameters, run)
    filename = result["run_id"] + ".json"
    with (RESULT_DIR / filename).open("x", encoding="utf-8") as target:
        dump(result, target, indent=2)
    if not rate_within_tolerance:
        deviation = "undefined (zero configured rate)" if relative_deviation is None else f"{relative_deviation:.2%}"
        print(
            f"WARNING: actual offered rate {actual_rate:.2f} differs from configured "
            f"rate {configured_rate}; relative deviation {deviation}, tolerance "
            f"{tolerance:.2%}. Saved this run with offered_rate_within_tolerance=false; "
            "use actual_offered_rate for load plots and inspect generator capacity.",
            file=sys.stderr,
        )
    print(dumps(result, indent=2))


def _local_parameters(settings):
    parameters = dict(settings["benchmark"]["local"])
    parameters.pop("runs", None)
    return parameters


def _remote_parameters(matrix, nodes, rate):
    return {
        "nodes": int(nodes),
        "faults": int(matrix["faults"]),
        "gamma": float(matrix["gamma"]),
        "rate": int(rate),
        "tx_size": int(matrix["tx_size"]),
        "lo_interval": int(matrix["lo_interval"]),
        "lo_size": int(matrix["lo_size"]),
        "duration": int(matrix["duration"]),
        "offered_rate_tolerance": float(matrix["offered_rate_tolerance"]),
    }


def _aws_records(settings, states=("running",)):
    records = []
    for region in settings["instances"]["regions"]:
        client = boto3.client("ec2", region_name=region)
        response = client.describe_instances(
            Filters=[
                {"Name": "tag:Name", "Values": [_testbed(settings)]},
                {"Name": "instance-state-name", "Values": list(states)},
            ]
        )
        for reservation in response["Reservations"]:
            for instance in reservation["Instances"]:
                records.append(
                    {
                        "region": region,
                        "id": instance["InstanceId"],
                        "public": instance.get("PublicIpAddress"),
                        "private": instance.get("PrivateIpAddress"),
                    }
                )
    records.sort(key=lambda record: (record["region"], record["id"]))
    return records


def _spread(records, regions):
    grouped = {region: [] for region in regions}
    for record in records:
        grouped[record["region"]].append(record)
    ordered = []
    offset = 0
    while True:
        added = False
        for region in regions:
            if offset < len(grouped[region]):
                ordered.append(grouped[region][offset])
                added = True
        if not added:
            return ordered
        offset += 1


def _connection(record, settings):
    if not record["public"]:
        raise RuntimeError(f"instance {record['id']} has no public IP")
    key_path = settings["key"].get("path", "").strip()
    if not key_path:
        raise RuntimeError("settings.json key.path is empty")
    return Connection(
        record["public"],
        user=settings.get("user", "ubuntu"),
        connect_kwargs={"key_filename": key_path},
    )


def _parallel(records, function):
    with ThreadPoolExecutor(max_workers=max(1, len(records))) as executor:
        futures = [executor.submit(function, index, record) for index, record in enumerate(records)]
        for future in futures:
            future.result()


def _require_repo(settings):
    url = settings["repo"].get("url", "").strip()
    if not url:
        raise RuntimeError("settings.json repo.url is empty; set it before fab install/remote")
    return url


def _update_remote(records, settings, install_packages=False):
    url = _require_repo(settings)
    name = settings["repo"]["name"]
    branch = settings["repo"]["branch"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise RuntimeError("repo.name contains unsupported shell characters")
    quoted_url, quoted_branch = shlex.quote(url), shlex.quote(branch)

    def update(_, record):
        connection = _connection(record, settings)
        commands = []
        if install_packages:
            commands.extend(
                [
                    "sudo apt-get update",
                    "sudo apt-get install -y build-essential git tmux curl",
                    f"curl -fsSL https://go.dev/dl/go{GO_VERSION}.linux-amd64.tar.gz -o /tmp/themis-go.tgz",
                    "sudo rm -rf /usr/local/go",
                    "sudo tar -C /usr/local -xzf /tmp/themis-go.tgz",
                ]
            )
        commands.extend(
            [
                f"if [ -d {name}/.git ]; then (cd {name} && git fetch origin && git checkout {quoted_branch} && git pull --ff-only origin {quoted_branch}); else git clone --branch {quoted_branch} {quoted_url} {name}; fi",
                f"cd {name} && export PATH=/usr/local/go/bin:$PATH && go build -o themis ./pkg",
            ]
        )
        connection.run(" && ".join(commands), hide=False)

    _parallel(records, update)


def _upload_remote(records, settings):
    name = settings["repo"]["name"]
    config = RUNTIME_DIR / "config.json"

    def upload(_, record):
        connection = _connection(record, settings)
        remote = f"{name}/.benchmark"
        connection.run(f"rm -rf {remote} && mkdir -p {remote}", hide=True)
        connection.put(str(config), remote=f"{remote}/config.json")

    _parallel(records, upload)


def _run_remote_once(records, settings, parameters, run):
    parameters = dict(parameters, run_id=_run_id("remote", parameters, run))
    name = settings["repo"]["name"]

    def start(replica_id, record):
        connection = _connection(record, settings)
        arguments = _command(parameters, [replica_id], binary="../themis")
        command = " ".join(shlex.quote(value) for value in arguments)
        remote_command = (
            "tmux kill-session -t themis 2>/dev/null || true; "
            f"rm -f {name}/.benchmark/node.log; "
            f"tmux new-session -d -s themis "
            f"'cd {name}/.benchmark && {command} > node.log 2>&1'"
        )
        connection.run(remote_command, hide=True)

    _parallel(records, start)
    leader = _connection(records[0], settings)
    deadline = time.monotonic() + parameters["duration"] + 60
    finished = False
    while time.monotonic() < deadline:
        result = leader.run(
            f"grep -q -- '--- END FINAL RESULTS ---' {name}/.benchmark/node.log",
            warn=True,
            hide=True,
        )
        if result.ok:
            finished = True
            break
        time.sleep(1)

    exited = False
    while finished and time.monotonic() < deadline:
        running = False
        for record in records:
            result = _connection(record, settings).run(
                "tmux has-session -t themis", warn=True, hide=True
            )
            if result.ok:
                running = True
        if not running:
            exited = True
            break
        time.sleep(1)

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    def download(replica_id, record):
        local = LOG_DIR / f"{parameters['run_id']}-node{replica_id}.log"
        _connection(record, settings).get(
            f"{name}/.benchmark/node.log", local=str(local)
        )

    _parallel(records, download)
    if not finished or not exited:
        def cleanup(_, record):
            _connection(record, settings).run(
                "tmux kill-session -t themis 2>/dev/null || true",
                warn=True,
                hide=True,
            )

        _parallel(records, cleanup)
        raise RuntimeError("remote Themis did not exit before timeout; logs were downloaded")

    leader_log = LOG_DIR / f"{parameters['run_id']}-node0.log"
    metrics = _parse_log(leader_log)
    aggregate_keys = (
        "locally_failed_local_order_send_attempts",
        "locally_failed_candidate_send_attempts",
        "locally_failed_benchmark_commit_send_attempts",
        "proposal_verification_failures",
        "order_extraction_failures",
        "follower_candidate_rejections",
        "hosting_commit_rejections",
    )
    for key in aggregate_keys:
        metrics[key] = 0
    for replica_id in range(parameters["nodes"]):
        path = LOG_DIR / f"{parameters['run_id']}-node{replica_id}.log"
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(marker in text for marker in ("BENCHMARK INVALID", "panic:")):
            raise RuntimeError(f"{path} reports a failed benchmark")
        if replica_id != 0:
            metrics["log_paths"].append(str(path.resolve()))
            metrics["build_metadata"].extend(loads(value) for value in re.findall(r"^THEMIS BUILD (\{[^\n]+\})$", text, re.MULTILINE))
        metrics["replica_states"].update({
            replica: (seq, state, digest)
            for replica, seq, state, digest in re.findall(
                r"BENCHMARK STATE replica=(\d+) seq=(\d+) state=([0-9a-f]{64}) fragment=([0-9a-f]{64})", text
            )
        })
        metrics["locally_failed_local_order_send_attempts"] += text.count("BENCHMARK LOCAL SEND FAILURE: LocalOrder")
        metrics["locally_failed_candidate_send_attempts"] += text.count("BENCHMARK CANDIDATE SEND FAILURE")
        metrics["locally_failed_benchmark_commit_send_attempts"] += text.count("BENCHMARK COMMIT SEND FAILURE")
        metrics["proposal_verification_failures"] += text.count("THEMIS PROPOSAL VERIFICATION FAILED")
        metrics["order_extraction_failures"] += text.count("THEMIS ORDER EXTRACTION FAILED")
        metrics["follower_candidate_rejections"] += text.count("BENCHMARK FOLLOWER REJECTED CANDIDATE")
        metrics["hosting_commit_rejections"] += len(re.findall(r"BENCHMARK HOSTING .*COMMIT REJECTED", text))
    _write_result("remote", parameters, run, metrics)


@task
def local(ctx):
    """Build and run the local Themis ordering-layer benchmark."""
    settings = _settings()
    raw = settings["benchmark"]["local"]
    parameters = _local_parameters(settings)
    _validate_parameters(parameters)
    _build_local()
    addresses = [f"127.0.0.1:{settings['port'] + i}" for i in range(parameters["nodes"])]
    _prepare_runtime(parameters["nodes"], addresses)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    runs = int(raw.get("runs", 1))
    if runs <= 0:
        raise RuntimeError("local runs must be positive")
    for run in range(1, runs + 1):
        parameters = dict(parameters, run_id=_run_id("local", parameters, run))
        log = LOG_DIR / f"{parameters['run_id']}.log"
        with log.open("x", encoding="utf-8") as output:
            completed = subprocess.run(
                _command(parameters, range(parameters["nodes"])),
                cwd=RUNTIME_DIR,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=parameters["duration"] + 45,
                check=False,
            )
        if completed.returncode != 0:
            raise RuntimeError(f"local Themis exited with status {completed.returncode}; see {log}")
        _write_result("local", parameters, run, _parse_log(log))


@task
def remote(ctx):
    """Run the configured Themis benchmark matrix on existing AWS instances."""
    settings = _settings()
    matrix = settings["benchmark"]["remote"]
    nodes_values = [int(value) for value in matrix["nodes"]]
    rate_values = [int(value) for value in matrix["rate"]]
    runs = int(matrix.get("runs", 1))
    if not nodes_values or not rate_values or runs <= 0:
        raise RuntimeError("remote nodes/rate must be non-empty and runs must be positive")
    _require_repo(settings)
    available = _spread(_aws_records(settings), settings["instances"]["regions"])
    required = max(nodes_values)
    if len(available) < required:
        raise RuntimeError(f"need {required} running AWS instances, found {len(available)}")
    selected = available[:required]
    _update_remote(selected, settings, install_packages=False)
    for nodes in nodes_values:
        records = selected[:nodes]
        addresses = [f"{record['public']}:{settings['port']}" for record in records]
        _prepare_runtime(nodes, addresses)
        _upload_remote(records, settings)
        for rate in rate_values:
            parameters = _remote_parameters(matrix, nodes, rate)
            _validate_parameters(parameters)
            for run in range(1, runs + 1):
                _run_remote_once(records, settings, parameters, run)


@task
def install(ctx):
    """Install Go/tooling and clone/build Themis on running instances."""
    settings = _settings()
    records = _aws_records(settings)
    if not records:
        raise RuntimeError("no running Themis instances")
    _update_remote(records, settings, install_packages=True)


@task
def kill(ctx):
    """Stop Themis benchmark tmux sessions."""
    settings = _settings()
    records = _aws_records(settings)

    def stop_session(_, record):
        _connection(record, settings).run(
            "tmux kill-session -t themis 2>/dev/null || true", hide=True
        )

    _parallel(records, stop_session)


@task
def logs(ctx):
    """Parse locally available Themis benchmark logs."""
    for path in sorted(LOG_DIR.glob("*.log")):
        try:
            print(path.name)
            print(dumps(_parse_log(path), indent=2))
        except RuntimeError as error:
            print(f"  skipped: {error}")


def _security_group(client, settings):
    vpcs = client.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"]
    if not vpcs:
        raise RuntimeError("AWS region has no default VPC")
    vpc = vpcs[0]["VpcId"]
    name = _testbed(settings)
    groups = client.describe_security_groups(
        Filters=[
            {"Name": "group-name", "Values": [name]},
            {"Name": "vpc-id", "Values": [vpc]},
        ]
    )["SecurityGroups"]
    if groups:
        group = groups[0]
    else:
        group = client.create_security_group(
            GroupName=name, Description="Themis benchmark", VpcId=vpc
        )
    permissions = [
        {
            "IpProtocol": "tcp",
            "FromPort": port,
            "ToPort": port,
            "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
        }
        for port in (22, settings["port"])
    ]
    for permission in permissions:
        try:
            client.authorize_security_group_ingress(
                GroupId=group["GroupId"], IpPermissions=[permission]
            )
        except ClientError as error:
            if error.response["Error"]["Code"] != "InvalidPermission.Duplicate":
                raise
    return group["GroupId"]


def _ubuntu_ami(client):
    images = client.describe_images(
        Owners=["099720109477"],
        Filters=[
            {
                "Name": "name",
                "Values": ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"],
            },
            {"Name": "architecture", "Values": ["x86_64"]},
            {"Name": "state", "Values": ["available"]},
        ],
    )["Images"]
    if not images:
        raise RuntimeError("no Ubuntu 22.04 AMI found")
    return max(images, key=lambda image: image["CreationDate"])["ImageId"]


@task
def create(ctx, nodes=1):
    """Create `nodes` instances in each configured AWS region."""
    settings = _settings()
    nodes = int(nodes)
    if nodes <= 0:
        raise RuntimeError("nodes must be positive")
    for region in settings["instances"]["regions"]:
        client = boto3.client("ec2", region_name=region)
        group = _security_group(client, settings)
        client.run_instances(
            ImageId=_ubuntu_ami(client),
            InstanceType=settings["instances"]["type"],
            KeyName=settings["key"]["name"],
            MinCount=nodes,
            MaxCount=nodes,
            SecurityGroupIds=[group],
            TagSpecifications=[
                {
                    "ResourceType": "instance",
                    "Tags": [{"Key": "Name", "Value": _testbed(settings)}],
                }
            ],
        )
        print(f"requested {nodes} instance(s) in {region}")


@task
def info(ctx):
    """Print AWS instance and SSH information."""
    settings = _settings()
    for record in _aws_records(settings, states=("pending", "running", "stopped")):
        print(
            f"{record['region']} {record['id']} public={record['public']} "
            f"private={record['private']}"
        )


@task
def stop(ctx):
    """Stop all running Themis benchmark instances."""
    settings = _settings()
    records = _aws_records(settings)
    for region in settings["instances"]["regions"]:
        ids = [record["id"] for record in records if record["region"] == region]
        if ids:
            boto3.client("ec2", region_name=region).stop_instances(InstanceIds=ids)


@task
def start(ctx):
    """Start all stopped Themis benchmark instances."""
    settings = _settings()
    records = _aws_records(settings, states=("stopped",))
    for region in settings["instances"]["regions"]:
        ids = [record["id"] for record in records if record["region"] == region]
        if ids:
            boto3.client("ec2", region_name=region).start_instances(InstanceIds=ids)


@task
def destroy(ctx):
    """Terminate all Themis benchmark instances."""
    settings = _settings()
    records = _aws_records(
        settings, states=("pending", "running", "stopping", "stopped")
    )
    for region in settings["instances"]["regions"]:
        ids = [record["id"] for record in records if record["region"] == region]
        if ids:
            boto3.client("ec2", region_name=region).terminate_instances(InstanceIds=ids)
