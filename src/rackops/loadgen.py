"""Labeled in-cluster request generator; no Kubernetes API access."""

import argparse
import json
import time
import uuid

import httpx

from rackops.checker import probe, request_pair, summarize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--duration", type=int, choices=range(1, 121))
    args = parser.parse_args()
    if args.once and args.duration is not None:
        parser.error("Choose either --once or --duration")
    with httpx.Client(base_url="http://rackops-api:8000", timeout=2, trust_env=False) as client:
        if args.duration is not None:
            result = probe(client, duration=args.duration, rate=5)
            print(json.dumps(result), flush=True)
            raise SystemExit(0 if result["passed"] else 1)
        while True:
            samples = []
            for _ in range(2):
                key = "load-" + uuid.uuid4().hex[:16]
                samples.extend(request_pair(client, key, key))
            result = summarize(samples)
            if args.once:
                result["failures"] = [
                    {"method": ("PUT" if index % 2 == 0 else "GET"), "reason": sample.reason}
                    for index, sample in enumerate(samples)
                    if not sample.success
                ]
            print(json.dumps(result), flush=True)
            if args.once:
                raise SystemExit(0 if result["passed"] else 1)
            time.sleep(2)


if __name__ == "__main__":
    main()
