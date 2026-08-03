#!/usr/bin/env python3

from math import exp
from operator import itemgetter
import random
from pathlib import Path

from upload_perfdata import insert_data, open_local_database


def generate_testdata(
    hi: int, lo: int, step: int, model: dict, noise: float, scale: float
):
    """
    Generate synthetic test data for performance benchmarking.

    Args:
        hi: High end of matrix size range
        lo: Low end of matrix size range
        step: Step size for incrementing matrix sizes
        model: Model dictionary with scaling functions and parameters
        noise: Noise level in GFLOP/s per core
        scale: Overall scaling factor

    Returns:
        List of operation dictionaries with performance data
    """

    operation_names = [
        "gemm_nn_rrr",
        "gemmt_nn_rrr",
        "syrk_nn_rrr",
        "syr2k_nn_rrr",
        "trmm_rnn_rrr",
        "trmm3_rnn_rrr",
        "trsm_rnn_rrr",
    ]
    data_types = ["s", "d", "c", "z"]  # single, double, complex single, complex double
    dt_scaling = {"s": 2.0, "d": 1.0, "c": 2.0, "z": 1.0}

    # Get model parameters
    rpeak_per_core = model["rpeak_per_core"]
    mnk_scaling = model["mnk_scaling"]
    k_scaling = model["k_scaling"]
    trmm_ratio = model["trmm_ratio"]
    trsm_ratio = model["trsm_ratio"]

    operations = []

    # Generate "square" data: m = n = k ranging from lo to hi in steps of step
    for mnk in range(lo, hi + 1, step):
        for dt in data_types:
            for op in operation_names:
                # Choose base ratio based on operation
                if "trsm" in op:
                    base_ratio = trsm_ratio
                elif not op.startswith("gemm_"):
                    base_ratio = trmm_ratio
                else:  # gemm
                    base_ratio = 1.0

                # Calculate GFLOPS using model
                base_gflops = (
                    rpeak_per_core
                    * base_ratio
                    * mnk_scaling(mnk)
                    * dt_scaling[dt]
                    * scale
                )

                # Add random noise
                gflops = base_gflops + random.gauss(0, noise)
                gflops = max(0.1, gflops)  # Ensure positive value

                operations.append(
                    {"op": op, "dt": dt, "m": mnk, "n": mnk, "k": mnk, "gflops": gflops}
                )

                # Calculate GFLOPS using model
                # For rankk operations, use k_scaling instead of mnk_scaling
                base_gflops = (
                    rpeak_per_core
                    * base_ratio
                    * k_scaling(mnk)
                    * dt_scaling[dt]
                    * scale
                )

                # Add random noise
                gflops = base_gflops + random.gauss(0, noise)
                gflops = max(0.1, gflops)  # Ensure positive value

                operations.append(
                    {"op": op, "dt": dt, "m": hi, "n": hi, "k": mnk, "gflops": gflops}
                )

    return operations


def main():
    # Default paths
    db_file = "perf.sqlite"

    noise = 5.0  # GFLOP/s per core normally distributed noise

    machines = [
        {
            "machine": "Xeon v3 (1s 18c)",
            "threads": [1, 4, 8, 18],
            "hi": [3000, 4000, 4000, 6000],
            "lo": [120, 120, 120, 120],
            "step": [120, 120, 120, 120],
            "config": "haswell",
            "model": {
                "rpeak_per_core": 30.0,
                "trmm_ratio": 0.9,
                "trsm_ratio": 0.7,
                "thread_scaling": lambda t: 1.0 if t < 8 else 0.8 + 0.2 * (4 / t),
                "mnk_scaling": lambda m: 1.0 - 0.8 * exp(-m / 500.0),
                "k_scaling": lambda k: 1.0 - 0.6 * exp(-k / 300.0),
            },
        },
        {
            "machine": "AMD EPYC 7763 (1s 64c)",
            "threads": [1, 4, 16, 32, 64],
            "hi": [3000, 4000, 6000, 8000, 10000],
            "lo": [120, 120, 120, 120, 120],
            "step": [120, 120, 120, 120, 120],
            "config": "zen3",
            "model": {
                "rpeak_per_core": 40.0,
                "trmm_ratio": 0.9,
                "trsm_ratio": 0.7,
                "thread_scaling": lambda t: (
                    1.0 if t < 16 else 0.9 - 0.4 * ((t - 16) / 112)
                ),
                "mnk_scaling": lambda m: 1.0 - 0.8 * exp(-m / 500.0),
                "k_scaling": lambda k: 1.0 - 0.6 * exp(-k / 300.0),
            },
        },
        {
            "machine": "AMD EPYC 7763 (2s 128c)",
            "threads": [128],
            "hi": [10000],
            "lo": [120],
            "step": [120],
            "config": "zen3",
            "model": {
                "rpeak_per_core": 40.0,
                "trmm_ratio": 0.9,
                "trsm_ratio": 0.7,
                "thread_scaling": lambda t: (
                    1.0 if t < 16 else 0.9 - 0.4 * ((t - 16) / 112)
                ),
                "mnk_scaling": lambda m: 1.0 - 0.8 * exp(-m / 500.0),
                "k_scaling": lambda k: 1.0 - 0.6 * exp(-k / 300.0),
            },
        },
    ]

    commits = [
        {
            "commit": "abc123",
            "tag": "v1.2",
            "scaling": 1.0,
            "timestamp": "2024-06-01T00:00:00Z",
        },
        {
            "commit": "def456",
            "tag": "v2.1",
            "scaling": 1.1,
            "timestamp": "2025-06-01T00:00:00Z",
        },
        {
            "commit": "24988de",
            "tag": "master",
            "scaling": 1.2,
            "timestamp": "2026-07-01T00:00:00Z",
        },
        {
            "commit": "23ddeeac9",
            "tag": "master",
            "scaling": 0.6,
            "timestamp": "2026-03-01T00:00:00Z",
        },
        {
            "commit": "98ef9ba",
            "tag": "master",
            "scaling": 1.02,
            "timestamp": "2025-08-01T00:00:00Z",
        },
        {
            "commit": "4877711da",
            "tag": "master",
            "scaling": 0.95,
            "timestamp": "2024-09-01T00:00:00Z",
        },
    ]

    print(f"\nCreating database {db_file}...")
    db_file = Path(db_file)
    if db_file.exists():
        print(f"Warning: Database {db_file} already exists. It will be overwritten.")
        db_file.unlink()
    conn = open_local_database(db_file)

    for machine in machines:
        for t, hi, lo, step in zip(*itemgetter("threads", "hi", "lo", "step")(machine)):
            for commit in commits:
                git_commit = commit["commit"]
                git_tag = commit["tag"]
                commit_scaling = commit["scaling"]
                print(
                    f"\nGenerating data for {machine['machine']} with {t} threads @ {git_commit}..."
                )
                data = {
                    "operations": generate_testdata(
                        hi=hi,
                        lo=lo,
                        step=step,
                        model=machine["model"],
                        noise=noise,
                        scale=machine["model"]["thread_scaling"](t) * commit_scaling,
                    ),
                    "machine": machine["machine"],
                    "threads": t,
                    "config": machine["config"],
                    "timestamp": commit["timestamp"],
                }

                total_time = 0.0
                for op_dict in data["operations"]:
                    op = op_dict["op"]
                    m = op_dict["m"]
                    n = op_dict["n"]
                    k = op_dict["k"]
                    dt = op_dict["dt"]
                    t = data["threads"]
                    gflops = op_dict["gflops"] * t
                    time = (2.0 * m * n * k) / (gflops * 1e9)  # Time in seconds
                    if any(x in op for x in ["gemmt", "syrk", "trmm", "trmm3", "trsm"]):
                        time *= 0.5  # Adjust for triangular operations
                    if dt == "c" or dt == "z":
                        time *= 4.0  # Adjust for complex data types
                    total_time += time
                print(
                    f"Estimated total time for {len(data['operations'])} operations: {total_time / 3600:.2f} hours"
                )

                data["commit"] = git_commit
                data["tag"] = git_tag
                data["machine"] = machine["machine"]
                data["timestamp"] = commit["timestamp"]

                print(f"Saving data to {db_file}...")
                insert_data(conn, data)

    conn.close()
    print("Done!")


if __name__ == "__main__":
    main()
