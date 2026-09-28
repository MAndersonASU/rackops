"""Labeled in-cluster request generator; no Kubernetes API access."""

import argparse
import json
import time
import uuid

import httpx

from rackops.checker import request_pair, summarize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    with httpx.Client(base_url="http://rackops-api:8000", timeout=2, trust_env=False) as client:
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
