#!/usr/bin/env python3

"""
Collect performance data from a BLIS build and save to database.

Usage:
    python3 collect_perfdata.py <config.yaml> <git_ref> [<git_ref> ...] [-j N]

The script reads a YAML configuration file that specifies machine details,
thread configurations, and optional metadata. It then clones, builds, and
prepares the test environment for one or more git references, creating a
runjob.sh batch script for each commit.
"""

import argparse
import json
import subprocess
import sys
import re
import yaml
from pathlib import Path

substitution_vars = {
    "dt": "sdcz",
    "mstorage": "r",
    "vstorage": "r",
    "repeat": 3,
    "1m": 1,
    "native": 1,
    "level2": 0,
    "level3": 1,
}


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Collect BLIS performance data from one or more git commits/tags/branches"
    )
    parser.add_argument(
        "config_file", help="YAML configuration file with machine specs and metadata"
    )
    parser.add_argument(
        "git_refs",
        nargs="+",
        help="One or more git commit hashes, tags, or branch names to collect data for",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=1,
        help="Number of concurrent jobs to pass to make (default: 1)",
    )
    parser.add_argument(
        "-s",
        "--status",
        help="YAML file to save the status of each git reference (most recent commit) after processing",
    )
    parser.add_argument(
        "-a",
        "--sbatch-args",
        help="Additional arguments to pass to sbatch in the generated runjob.sh script",
    )

    return parser.parse_args()


def read_config_file(config_path: str | Path) -> dict:
    """
    Read and parse the YAML configuration file.

    Expected structure:
    machine: <machine_name>
    threads: [<thread_counts>]
    hi: [<high_matrix_sizes>]
    lo: [<low_matrix_sizes>]
    step: [<step_sizes>]
    config: <config_name>
    <other_user_defined_keys>: <values>

    Returns:
        dict: Configuration data with required and optional keys
    """
    config_path = Path(config_path)
    if not config_path.exists():
        print(f"Error: Configuration file '{config_path}' not found")
        sys.exit(1)

    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"Error parsing YAML file: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading configuration file: {e}")
        sys.exit(1)

    # Validate required fields
    required_fields = ["machine", "threads", "hi", "lo", "step", "config"]
    missing_fields = [field for field in required_fields if field not in config]

    if missing_fields:
        print(f"Error: Missing required config fields: {', '.join(missing_fields)}")
        sys.exit(1)

    # Validate threads, hi, lo, and step arrays
    array_fields = ["threads", "hi", "lo", "step"]

    # Check that all array fields are lists
    for field in array_fields:
        if not isinstance(config[field], (list, tuple)):
            print(
                f"Error: '{field}' must be a list/array, got {type(config[field]).__name__}"
            )
            sys.exit(1)

    # Check that all arrays are non-empty
    for field in array_fields:
        if len(config[field]) == 0:
            print(f"Error: '{field}' array must not be empty")
            sys.exit(1)

    # Check that all arrays have the same length
    lengths = {field: len(config[field]) for field in array_fields}
    if len(set(lengths.values())) > 1:
        print("Error: 'threads', 'hi', 'lo', and 'step' must all have the same length")
        print(f"  threads: {lengths['threads']}")
        print(f"  hi: {lengths['hi']}")
        print(f"  lo: {lengths['lo']}")
        print(f"  step: {lengths['step']}")
        sys.exit(1)

    # Check that all elements in each array are positive integers
    for field in array_fields:
        for i, value in enumerate(config[field]):
            if not isinstance(value, int) or value <= 0:
                print(
                    f"Error: '{field}[{i}]' must be a positive integer, got {value} ({type(value).__name__})"
                )
                sys.exit(1)

    for var, default in substitution_vars.items():
        if var not in config:
            config[var] = default

    return config


def extract_user_defined_keys(config: dict) -> str:
    """
    Extract user-defined keys (non-standard fields) from config.

    Standard fields are: machine, threads, hi, lo, step, config
    All other keys are collected into a JSON-formatted comment.

    Args:
        config (dict): Configuration dictionary

    Returns:
        str: JSON-formatted string of user-defined keys, or empty string
    """
    standard_fields = {
        "machine",
        "threads",
        "hi",
        "lo",
        "step",
        "config",
        "dt",
        "mstorage",
        "vstorage",
        "repeat",
        "1m",
        "native",
        "level2",
        "level3",
    }
    user_keys = {k: v for k, v in config.items() if k not in standard_fields}

    if user_keys:
        return json.dumps(user_keys)
    return ""


def validate_git_ref(repo_dir: Path, git_ref: str) -> str | None:
    """
    Validate that the git reference exists in the repository.

    Args:
        repo_dir (Path): Directory of the git repository
        git_ref (str): Git commit hash, tag, or branch name

    Returns:
        str: Short commit hash if valid, None otherwise
    """
    try:
        # Try to resolve the reference to a short commit hash
        result = subprocess.run(
            ["git", "rev-parse", "--short", git_ref],
            capture_output=True,
            cwd=repo_dir,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        result = subprocess.run(
            ["git", "rev-parse", "--short", f"origin/{git_ref}"],
            capture_output=True,
            cwd=repo_dir,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            print(f"Error: Git reference '{git_ref}' not found")
            return None
    except FileNotFoundError:
        print("Error: git command not found")
        return None


def get_git_tag_for_commit(repo_dir: Path, commit_hash: str) -> str | None:
    """
    Get the tag or branch name for a given commit hash.

    Args:
        repo_dir (Path): Directory of the git repository
        commit_hash (str): Full commit hash

    Returns:
        str | None: Tag name if commit is tagged, otherwise None
    """
    try:
        # Try to get tag for this commit
        result = subprocess.run(
            ["git", "describe", "--tags", "--exact-match", commit_hash],
            capture_output=True,
            cwd=repo_dir,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass

    return None


def clone_blis_repository(repo_dir: Path) -> bool:
    """
    Clone the BLIS repository into the specified directory.

    Args:
        repo_dir (Path): Directory where BLIS will be cloned

    Returns:
        bool: True if successful, False otherwise
    """
    # Remove directory if it already exists
    if repo_dir.exists():
        print(f"Removing existing BLIS directory: {repo_dir}")
        subprocess.run(["rm", "-rf", str(repo_dir)], check=True)

    print(f"Cloning BLIS repository to {repo_dir}...")
    try:
        result = subprocess.run(
            ["git", "clone", "https://github.com/flame/blis", str(repo_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(f"Error cloning repository: {result.stderr}")
            return False
        result = subprocess.run(
            ["git", "fetch", "--all", "--tags"],
            capture_output=True,
            cwd=repo_dir,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(f"Error fetching branches and tags: {result.stderr}")
            return False
        print("Repository cloned successfully")
        return True
    except Exception as e:
        print(f"Error during clone: {e}")
        return False


def checkout_git_ref(repo_dir: Path, build_dir: Path, git_ref: str) -> bool:
    """
    Checkout the specified git reference (commit/tag/branch).

    Args:
        repo_dir (Path): Repository directory
        build_dir (Path): Build directory
        git_ref (str): Git reference to check out

    Returns:
        bool: True if successful, False otherwise
    """

    print(f"Checking out {git_ref} into {build_dir}...")
    try:
        # Remove directory if it already exists
        if build_dir.exists():
            print(f"Removing existing BLIS build directory: {build_dir}")
            subprocess.run(["rm", "-rf", str(build_dir)], check=True)

        build_dir.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            f"git archive {git_ref} | tar -x -C {build_dir}",
            capture_output=True,
            cwd=repo_dir,
            text=True,
            shell=True,
            check=False,
        )
        if result.returncode != 0:
            print(f"Error cloning repository: {result.stderr}")
            return False
        print("Repository checked out successfully")
        return True
    except Exception as e:
        print(f"Error during checkout: {e}")
        return False


def get_compiler_version(cc: str) -> str | None:
    """
    Get the compiler vendor and version for the specified compiler.
    This function is adapted from BLIS: https://github.com/flame/blis/blob/master/configure
        Copyright (C) 2014, The University of Texas at Austin
        See BSD3 license at https://github.com/flame/blis/blob/master/LICENSE or ../LICENSE

    Args:
        cc (str): Compiler command (e.g., gcc, clang, icc)

    Returns:
        str: Compiler vendor and version string, or None on failure
    """

    # Query the full vendor version string output. This includes the
    # version number along with (potentially) a bunch of other textual
    # clutter.
    # NOTE: This maybe should use merged stdout/stderr rather than only
    # stdout. But it works for now.
    try:
        result = subprocess.run(
            [cc, "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        vendor_string = result.stdout.strip()
    except Exception as e:
        print(f"Error getting compiler version: {e}")
        return None

    # Query the compiler "vendor" (ie: the compiler's simple name) and
    # isolate the version number.
    # The last part ({ read first rest ; echo $first ; }) is a workaround
    # to OS X's egrep only returning the first match.
    for vendor in [
        "icc",
        "gcc",
        "clang",
        "NVIDIA",
        "emcc",
        "pnacl",
        "IBM",
        "oneAPI",
        "crosstool-NG",
        "GCC",
    ]:
        if vendor in vendor_string:
            cc_vendor = vendor
            break
    else:
        cc_vendor = None

    # AOCC version strings contain both "clang" and "AOCC" substrings, and
    # so we have perform a follow-up check to make sure cc_vendor gets set
    # correctly.
    if "AOCC" in vendor_string:
        cc_vendor = "aocc"

    # Detect armclang, which doesn't have a nice, unambiguous, one-word tag
    if "Arm C/C++/Fortran Compiler" in vendor_string:
        cc_vendor = "armclang"

    if not cc_vendor:
        print(
            f"Error: Unable to determine compiler vendor from string: {vendor_string}"
        )
        return None

    # Begin parsing cc_vendor for the version string.

    if cc_vendor == "GCC":
        # Conda gcc sometimes has GCC (all caps) in the version string
        cc_vendor = "gcc"

    if cc_vendor == "crosstool-NG":
        # Treat compilers built by crosstool-NG (for eg: conda) as gcc.
        cc_vendor = "gcc"

    if cc_vendor == "icc" or cc_vendor == "gcc":
        try:
            result = subprocess.run(
                [cc, "-dumpversion"],
                capture_output=True,
                text=True,
                check=False,
            )
            cc_version = result.stdout.strip()
        except Exception as e:
            print(f"Error getting compiler version: {e}")
            return None

    elif cc_vendor == "armclang":
        # Treat armclang as regular clang.
        cc_vendor = "clang"
        result = re.search(r"based on LLVM ([0-9]+\.[0-9]+\.?[0-9]*)", vendor_string)
        if not result:
            print(
                f"Error: Unable to parse armclang version from string: {vendor_string}"
            )
            return None
        cc_version = result.group(1)

    elif cc_vendor == "clang":
        result = re.search(
            r"(clang|LLVM) version ([0-9]+\.[0-9]+\.?[0-9]*)", vendor_string
        )
        if not result:
            print(f"Error: Unable to parse clang version from string: {vendor_string}")
            return None
        cc_version = result.group(2)

    elif cc_vendor == "aocc":
        # Versions 2.0 and 2.1 had different version string formats from
        # 2.2 and later, so we have to handle them separately.
        # Examples:
        # AOCC.LLVM.2.0.0.B191.2019_07_19 clang version 8.0.0 (CLANG: Jenkins AOCC_2_0_0-Build#191) (based on LLVM AOCC.LLVM.2.0.0.B191.2019_07_19)
        # AOCC.LLVM.2.1.0.B1030.2019_11_12 clang version 9.0.0 (CLANG: Build#1030) (based on LLVM AOCC.LLVM.2.1.0.B1030.2019_11_12)
        # AMD clang version 10.0.0 (CLANG: AOCC_2.2.0-Build#93 2020_06_25) (based on LLVM Mirror.Version.10.0.0)
        # AMD clang version 11.0.0 (CLANG: AOCC_2.3.0-Build#85 2020_11_10) (based on LLVM Mirror.Version.11.0.0)
        # AMD clang version 12.0.0 (CLANG: AOCC_3.0.0-Build#2 2020_11_05) (based on LLVM Mirror.Version.12.0.0)

        if "AOCC.LLVM.2" in vendor_string:
            # Grep for the AOCC.LLVM.x.y.z substring first, and then isolate the
            # version number. Also, the string may contain multiple instances of
            # the version number, so only use the first occurrence.
            result = re.search(r"AOCC\.LLVM\.([0-9]+\.[0-9]+\.?[0-9]*)", vendor_string)
            if not result:
                print(
                    f"Error: Unable to parse AOCC.LLVM version from string: {vendor_string}"
                )
                return None
            cc_version = result.group(1)

        else:
            # Grep for the AOCC_x.y.z substring first, and then isolate the
            # version number. As of this writing, these version strings don't
            # include multiple instances of the version, but we nonetheless
            # take only the first occurrence as a future-oriented safety
            # measure.
            result = re.search(r"AOCC_([0-9]+\.[0-9]+\.?[0-9]*)", vendor_string)
            if not result:
                print(
                    f"Error: Unable to parse AOCC version from string: {vendor_string}"
                )
                return None
            cc_version = result.group(1)

    elif cc_vendor == "oneAPI":
        # Treat Intel oneAPI's clang as clang, not icc.
        cc_vendor = "clang"
        result = re.search(r"[0-9]+\.[0-9]+\.[0-9]+\.?[0-9]*", vendor_string)
        if not result:
            print(f"Error: Unable to parse oneAPI version from string: {vendor_string}")
            return None
        cc_version = result.group(0)

    elif cc_vendor == "NVIDIA":
        result = re.search(r"[0-9]+\.[0-9]+-[0-9]+", vendor_string)
        if not result:
            print(f"Error: Unable to parse NVIDIA version from string: {vendor_string}")
            return None
        cc_version = result.group(0).replace("-", ".")

    else:
        result = re.search(r"[0-9]+\.[0-9]+\.?[0-9]*", vendor_string)
        if not result:
            print(f"Error: Unable to parse version from string: {vendor_string}")
            return None
        cc_version = result.group(0)

    return f"{cc_vendor} {cc_version}"


def configure_blis(blis_dir: Path, config_name: str) -> str | None:
    """
    Run BLIS configure script with the specified configuration.

    Args:
        blis_dir (Path): BLIS directory
        config_name (str): Configuration name for -tomp

    Returns:
        str: Compiler name and version if successful, None otherwise
    """
    print(f"Running configure with config: {config_name}...")
    configure_script = blis_dir / "configure"

    if not configure_script.exists():
        print(f"Error: configure script not found at {configure_script}")
        return None

    try:
        result = subprocess.run(
            ["./configure", "-tomp", config_name],
            cwd=blis_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(f"Error running configure: {result.stderr}")
            return None
        print("Configuration successful")
    except Exception as e:
        print(f"Error during configure: {e}")
        return None

    config_mk_path = blis_dir / "config.mk"
    if not config_mk_path.exists():
        print(f"Error: config.mk not found at {config_mk_path}")
        return None

    for line in config_mk_path.read_text().splitlines():
        if line.startswith("CC"):
            parts = line.split("=")
            if len(parts) != 2:
                print(f"Error: Invalid format for CC line: {line}")
                return None
            cc = parts[1].strip()
            return get_compiler_version(cc)

    print("CC variable not found in config.mk")
    return None


def build_blis(blis_dir: Path, jobs: int = 1) -> Path | None:
    """
    Build BLIS and run make check to generate test executable and verify library.

    Args:
        blis_dir (Path): BLIS directory
        jobs (int): Number of concurrent jobs to pass to make

    Returns:
        Path: Path to test executable if successful, None otherwise
    """
    print(f"Running make check with -j {jobs}...")
    try:
        result = subprocess.run(
            ["make", "-j", str(jobs), "check"],
            cwd=blis_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=3600,  # 1 hour timeout for build
        )
        if result.returncode != 0:
            print(f"Error running make check: {result.stderr}")
            return None

        # Verify test executable exists
        test_exec = blis_dir / "test_libblis.x"
        if not test_exec.exists():
            print(f"Error: test executable not found at {test_exec}")
            return None

        print("Build successful, test executable created")
        return test_exec

    except subprocess.TimeoutExpired:
        print("Error: make check timed out (exceeded 1 hour)")
        return None
    except Exception as e:
        print(f"Error during build: {e}")
        return None


def create_job_directory(
    commit_hash: str, config: dict, blis_dir: Path, sbatch_args: str | None
) -> Path | None:
    """
    Create a job directory named after the commit hash and generate runjob.sh.

    Args:
        commit_hash (str): Short git commit hash
        config (dict): Configuration dictionary
        blis_dir (Path): Path to BLIS repository
        sbatch_args (str | None): Additional arguments to pass to sbatch

    Returns:
        Path: Path to job directory if successful, None otherwise
    """
    # Create directory in original working directory
    job_dir = Path.cwd() / commit_hash
    print(f"Creating job directory: {job_dir}")

    try:
        job_dir.mkdir(exist_ok=True)
    except Exception as e:
        print(f"Error creating directory: {e}")
        return None

    # Read runjob.sh.in template
    template_file = Path(__file__).parent / "runjob.sh.in"
    if not template_file.exists():
        print(f"Error: Template file not found: {template_file}")
        return None

    try:
        with open(template_file, "r") as f:
            template_content = f.read()
    except Exception as e:
        print(f"Error reading template: {e}")
        return None

    # Build substitution values
    threads_array = " ".join(str(t) for t in config["threads"])
    lo_array = " ".join(str(l) for l in config["lo"])
    hi_array = " ".join(str(h) for h in config["hi"])
    step_array = " ".join(str(s) for s in config["step"])

    scripts_dir = Path(__file__).parent

    # Perform substitutions
    script_content = (
        template_content.replace("@BLIS_DIR@", str(blis_dir))
        .replace("@THREADS_ARRAY@", threads_array)
        .replace("@LO_ARRAY@", lo_array)
        .replace("@HI_ARRAY@", hi_array)
        .replace("@STEP_ARRAY@", step_array)
        .replace("@MACHINE@", config["machine"])
        .replace("@CONFIG@", config["config"])
        .replace("@COMMIT_DIR@", str(Path.cwd() / commit_hash))
        .replace("@GIT_COMMIT@", commit_hash)
        .replace("@SCRIPTS_DIR@", str(scripts_dir))
        .replace("@NUM_THREAD_BLOCKS@", str(len(config["threads"])))
        .replace("@SBATCH_ARGS@", "#SBATCH " + sbatch_args if sbatch_args else "")
    )

    # Substitute optional variables
    for var in substitution_vars.keys():
        script_content = script_content.replace(f"@{var.upper()}@", str(config[var]))

    # Write runjob.sh
    runjob_file = job_dir / "runjob.sh"
    try:
        with open(runjob_file, "w") as f:
            f.write(script_content)
        # Make executable
        runjob_file.chmod(0o755)
        print(f"✓ Generated batch script: {runjob_file}")
        return job_dir
    except Exception as e:
        print(f"Error writing batch script: {e}")
        return None


def get_commit_timestamp(repo_dir: Path, commit_hash: str) -> str | None:
    """
    Get the commit timestamp for a given commit hash.

    Args:
        repo_dir (Path): Directory of the git repository
        commit_hash (str): Full commit hash

    Returns:
        str | None: Commit timestamp in ISO format if successful, None otherwise
    """
    try:
        result = subprocess.run(
            ["git", "show", "-s", "--format=%cI", commit_hash],
            capture_output=True,
            cwd=repo_dir,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            print(f"Error getting commit timestamp: {result.stderr}")
            return None
    except Exception as e:
        print(f"Error during git show: {e}")
        return None


def process_git_ref(
    git_ref: str,
    commit_hash: str,
    config: dict,
    args: argparse.Namespace,
    repo_dir: Path,
    build_dir: Path,
    user_comment: str,
) -> bool:
    """
    Process a single git reference: clone, build, and generate batch script.

    Args:
        git_ref (str): Git reference to process
        commit_hash (str): Resolved commit hash for the git reference
        config (dict): Configuration dictionary
        args (argparse.Namespace): Command line arguments
        repo_dir (Path): Directory of BLIS git repository
        build_dir (Path): Top-level build directory to use
        user_comment (str): User-defined metadata comment

    Returns:
        bool: True if successful, False otherwise
    """
    print(f"\n{'=' * 60}")
    print(f"Processing: {git_ref}{f' ({commit_hash})' if commit_hash else ''}")
    print(f"{'=' * 60}\n")

    git_tag = get_git_tag_for_commit(repo_dir, commit_hash) or git_ref
    print(f"Commit hash: {commit_hash}")
    print(f"Tag/Branch: {git_tag}")

    print(f"\n{'=' * 60}")
    print("Building BLIS and preparing test environment")
    print(f"{'=' * 60}\n")

    # Clone BLIS repository into commit-specific build directory
    commit_build_dir = build_dir / commit_hash

    print(f"Build directory: {commit_build_dir}")

    # Checkout requested git reference
    print()
    if not checkout_git_ref(repo_dir, commit_build_dir, commit_hash):
        print("Error: Failed to checkout git reference")
        return False

    # Configure BLIS
    print()
    compiler_info = configure_blis(commit_build_dir, config["config"])
    if not compiler_info:
        print("Error: Failed to configure BLIS")
        return False

    job_config = json.loads(user_comment) if user_comment else {}
    job_config["compiler"] = compiler_info
    job_config["machine"] = config["machine"]
    job_config["tag"] = git_tag
    job_config["timestamp"] = get_commit_timestamp(repo_dir, commit_hash)
    if user_comment:
        job_config["comment"] = user_comment

    # Build BLIS and generate test executable
    print()
    test_exec = build_blis(commit_build_dir, jobs=args.jobs)
    if not test_exec:
        print("Error: BLIS build failed or test executable not created")
        return False

    # Create job directory and generate batch script
    print()
    job_dir = create_job_directory(
        commit_hash, config, commit_build_dir, args.sbatch_args
    )
    if not job_dir:
        print("Error: Failed to create job directory or generate batch script")
        return False

    job_config_path = job_dir / "config.yaml"
    try:
        with open(job_config_path, "w") as f:
            yaml.safe_dump(job_config, f)
    except Exception as e:
        print(f"Error writing configuration metadata to '{job_config_path}': {e}")
    else:
        print(f"✓ Saved configuration metadata to: {job_config_path}")

    print("\nConfiguration Summary")
    print(f"{'=' * 40}")
    print(f"  Git reference: {git_tag}")
    print(f"  Resolved commit: {commit_hash}")
    print(f"  Machine: {config['machine']}")
    print(f"  Config name: {config['config']}")
    print(f"  Compiler info: {compiler_info}")
    if user_comment:
        print(f"  User metadata: {user_comment}")

    print("\nNext Steps")
    print(f"{'=' * 40}")
    print(f"  Batch script created: {job_dir}/runjob.sh")
    print()
    print("  To run the performance collection:")
    print(f"    cd {job_dir}")
    print("    ./runjob.sh")
    print()
    print("  Or submit to SLURM:")
    print(f"    sbatch {job_dir}/runjob.sh\n")

    return True


def main():
    """Main entry point."""
    args = parse_arguments()

    print(f"{'=' * 60}")
    print("BLIS Performance Data Collector")
    print(f"{'=' * 60}\n")

    # Read and parse configuration
    print("Reading configuration...")
    config = read_config_file(args.config_file)
    print(f"  Machine: {config['machine']}")
    print(f"  Config: {config['config']}")
    print(f"  Thread counts: {config['threads']}")
    print(
        f"  Matrix size range (lo-hi-step): {config['lo']}-{config['hi']}-{config['step']}"
    )

    # Extract user-defined keys
    user_comment = extract_user_defined_keys(config)
    if user_comment:
        print(f"  User-defined metadata: {user_comment}")

    print(f"\n{'=' * 60}")
    print("Clone BLIS repository and preparing build environment")
    print(f"{'=' * 60}\n")
    build_dir = Path.cwd() / "blis_build"
    repo_dir = build_dir / "blis"
    if not clone_blis_repository(repo_dir):
        print("Error: Failed to clone BLIS repository")
        sys.exit(1)

    # Process each git reference
    print(f"\n{'=' * 60}")
    print(f"Processing {len(args.git_refs)} git reference(s)")
    print(f"{'=' * 60}\n")

    failed_refs = []
    successful_refs = []

    status_data = {}
    if args.status:
        status_file = Path(args.status)
        if status_file.exists():
            try:
                with open(status_file, "r") as f:
                    status_data = yaml.safe_load(f) or {}
            except Exception as e:
                print(f"Error reading status file '{status_file}': {e}")
                sys.exit(1)

    for git_ref in args.git_refs:
        print(f"Validating git reference: {git_ref}")
        if ":" in git_ref:
            git_ref, commit_hash = git_ref.split(":", 1)
            commit_hash = validate_git_ref(repo_dir, commit_hash)
        else:
            commit_hash = validate_git_ref(repo_dir, git_ref)

        if not commit_hash:
            failed_refs.append(git_ref)
            continue

        if git_ref in status_data and status_data[git_ref] == commit_hash:
            print(f"Skipping {git_ref}: already processed with commit {commit_hash}")
            successful_refs.append(git_ref)
            continue

        if process_git_ref(
            git_ref, commit_hash, config, args, repo_dir, build_dir, user_comment
        ):
            successful_refs.append(git_ref)
        else:
            failed_refs.append(git_ref)

    # Print summary
    print(f"\n{'=' * 60}")
    print("Summary")
    print(f"{'=' * 60}\n")
    print(f"Successful: {len(successful_refs)}")
    for ref in successful_refs:
        print(f"  ✓ {ref}")
    if failed_refs:
        print(f"Failed: {len(failed_refs)}")
        for ref in failed_refs:
            print(f"  ✗ {ref}")
        sys.exit(1)


if __name__ == "__main__":
    main()
