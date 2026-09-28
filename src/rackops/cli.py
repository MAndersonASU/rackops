"""Trusted operator commands, separate from the future runtime-agent gateway."""

import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from rackops.checker import probe


def local_url(value: str) -> str:
    url = urlsplit(value)
    if (
        url.scheme != "http"
        or url.hostname not in {"127.0.0.1", "localhost", "::1"}
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in {"", "/"}
    ):
        raise argparse.ArgumentTypeError("Use an HTTP loopback address, e.g. http://127.0.0.1:8000")
    return value.rstrip("/")


def doctor() -> dict:
    checks = {}
    for tool, args in {
        "git": ["--version"],
        "docker": ["info", "--format", "{{.OSType}}"],
        "kind": ["version"],
        "kubectl": ["version", "--client", "-o", "json"],
    }.items():
        if shutil.which(tool) is None:
            checks[tool] = {"ready": False, "status": "not_on_path"}
            continue
        try:
            completed = subprocess.run([tool, *args], capture_output=True, timeout=15, text=True)
            ready = completed.returncode == 0
            if tool == "docker":
                ready = ready and completed.stdout.strip() == "linux"
            # Do not persist environment-specific errors or private paths.
            checks[tool] = {
                "ready": ready,
                "status": "ready" if ready else "unavailable_or_wrong_mode",
            }
        except (OSError, subprocess.TimeoutExpired):
            checks[tool] = {"ready": False, "status": "unavailable_or_timed_out"}
    return {
        "python": platform.python_version(),
        "free_disk_gib": round(shutil.disk_usage(Path.cwd()).free / 2**30, 2),
        "tools": checks,
        "cluster_prerequisites_ready": all(
            checks[t]["ready"] for t in ("docker", "kind", "kubectl")
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Read-only tool checks; never prints authentication data")
    sub.add_parser("demo-fixture", help="Simulated Redis fault and recovery; not a benchmark")
    for command in ("smoke", "verify"):
        child = sub.add_parser(command)
        child.add_argument("--url", type=local_url, default="http://127.0.0.1:8000")
    lab = sub.add_parser("lab", help="Trusted operator/test-runner commands only")
    lab.add_argument("action", choices=["up", "reset", "inject", "recover", "baseline", "down"])
    lab.add_argument(
        "--scenario",
        choices=["bad_redis_host", "bad_service_port", "bad_image", "redis_outage", "healthy"],
        default="bad_redis_host",
        help="Scenario for lab inject; ignored by other lab actions",
    )
    lab.add_argument(
        "--expect",
        choices=["verified_repair", "healthy_no_action", "escalated"],
        help="Expected decision status for lab baseline (trusted runner check)",
    )
    lab.add_argument(
        "--expect-cause",
        choices=[
            "bad_dependency_configuration",
            "bad_service_target_port",
            "broken_image",
            "healthy",
            "unsupported_dependency_outage",
        ],
        help="Expected root-cause category for lab baseline (trusted runner check)",
    )
    lab.add_argument(
        "--expect-repairs",
        type=int,
        choices=[0, 1, 2],
        help="Expected number of executed repairs for lab baseline",
    )
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            result = doctor()
        elif args.command == "demo-fixture":
            from rackops.fixture_demo import run_demo

            result = run_demo()
        elif args.command == "lab":
            from rackops.lab import run

            result = run(
                args.action,
                scenario=args.scenario,
                expected=args.expect,
                expected_cause=args.expect_cause,
                expected_repairs=args.expect_repairs,
            )
        else:
            with httpx.Client(
                base_url=args.url, timeout=2, follow_redirects=False, trust_env=False
            ) as client:
                result = probe(client, duration=2 if args.command == "smoke" else 60)
                result["execution_mode"] = "live_http"
                result["benchmark_eligible"] = (
                    False  # Calibration and scenario scoring are pending.
                )
        print(json.dumps(result, indent=2))
        sys.exit(0 if result.get("passed", True) else 1)
    except (RuntimeError, ValueError, OSError) as exc:
        parser.exit(2, f"RackOps: {exc}\n")


if __name__ == "__main__":
    main()
