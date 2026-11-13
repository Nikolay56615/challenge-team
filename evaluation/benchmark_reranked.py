"""Измерить HTTP p95, долю резерва и пик VRAM локального сервиса."""

import argparse
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import quantiles
from time import perf_counter
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("queries", type=Path)
    parser.add_argument("--count", type=int, default=80)
    args = parser.parse_args()
    queries = json.loads(args.queries.read_text(encoding="utf-8-sig"))[:args.count]
    if len(queries) < 2:
        parser.error("Нужно не менее двух запросов")

    def health():
        with urlopen(args.url + "/api/health", timeout=5) as response:
            return json.load(response)["catalog"]["coverage"]["relevance"]

    def request(case):
        started = perf_counter()
        body = json.dumps({"task": case["task"]}).encode()
        req = Request(args.url + "/api/recommend", body, {"Content-Type": "application/json"})
        with urlopen(req, timeout=5) as response:
            response.read()
            elapsed = (perf_counter() - started) * 1000
        return elapsed

    for case in queries[:5]:
        request(case)
    monitor = subprocess.Popen(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits", "-lms", "100"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    samples = []
    with ThreadPoolExecutor(max_workers=1) as sampler:
        def consume():
            for line in monitor.stdout:
                value = line.strip()
                if value.isdigit():
                    samples.append(int(value))

        sampling = sampler.submit(consume)
        try:
            report = {}
            for concurrency in (1, 2):
                before = health().get("requests", {})
                with ThreadPoolExecutor(max_workers=concurrency) as workers:
                    times = list(workers.map(request, queries))
                after = health().get("requests", {})
                report[concurrency] = {
                    "requests": len(times), "p95_ms": round(quantiles(times, n=100, method="inclusive")[94], 2),
                    **{key: value - before.get(key, 0) for key, value in after.items()},
                }
        finally:
            monitor.terminate()
            monitor.wait(timeout=5)
            sampling.result(timeout=5)
    report["peak_device_mib"] = max(samples, default=None)
    report["relevance"] = health()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
