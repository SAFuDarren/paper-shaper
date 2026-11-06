"""Optional, model-free microbenchmark. Uses synthetic data in temporary directories."""
import argparse
import gc
import importlib.util
import json
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time
try:
    import tracemalloc
except ImportError:
    tracemalloc = None
from types import SimpleNamespace


def measure(operation, repeats):
    times, peaks = [], []
    for _ in range(repeats):
        gc.collect()
        if tracemalloc is not None:
            tracemalloc.start()
        started = time.perf_counter()
        operation()
        times.append((time.perf_counter() - started) * 1000)
        if tracemalloc is not None:
            peaks.append(tracemalloc.get_traced_memory()[1])
            tracemalloc.stop()
    return {"median_ms": round(statistics.median(times), 3),
            "peak_python_mib": round(max(peaks) / (1024 * 1024), 3) if peaks else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--mib", type=int, default=32)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.mib < 1 or args.repeats < 1:
        parser.error("mib and repeats must be positive")
    skill = args.skill.resolve()
    sys.path.insert(0, str(skill / "scripts"))
    spec = importlib.util.spec_from_file_location("framework_benchmark", skill / "scripts/framework.py")
    framework = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(framework)
    with tempfile.TemporaryDirectory(prefix="paper-shaper-bench-") as directory:
        root = Path(directory)
        source = root / "synthetic.txt"
        line = "x" * 1023 + "\n"
        with source.open("w", encoding="utf-8", newline="\n") as stream:
            for _ in range(args.mib * 1024):
                stream.write(line)
        work = root / "paper"
        framework.init(work, root)
        state = framework.load(work / "workflow-state.json")
        framework.mutate(state, work, SimpleNamespace(command="attach", path=str(source), material_id="source",
                         start=2, end=3, optional=False, note="synthetic benchmark"))
        results = {"python": platform.python_version(), "implementation": platform.python_implementation(),
                   "platform": platform.platform(), "source_mib": args.mib, "repeats": args.repeats,
                   "scope": "Warm-filesystem microbenchmark; Python allocations, not RSS or model quality/tokens",
                   "hash": measure(lambda: framework.core.digest(source), args.repeats),
                   "small_excerpt_packet": measure(lambda: framework.packet(state, work), args.repeats)}
        packet = framework.packet(state, work)
        results["packet_chars"] = packet["chars"]
        results["skill_entry_chars"] = len((skill / "SKILL.md").read_text(encoding="utf-8"))
        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
