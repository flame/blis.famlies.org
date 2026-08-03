#!/usr/bin/env python3

"""
Upload performance data to the central database.

This script performs Stage 3 of the data collection process:
1. Downloads the current perf.sqlite database from the FTPS server
2. Merges it with any local perf.sqlite databases found in directories
   named after git commit hashes
3. Uploads the merged database back to the server

Usage:
    python3 upload_perfdata.py

The script assumes:
- A .netrc file is configured for FTPS authentication
- Local perf.sqlite databases exist in subdirectories matching git commit hashes
- Write permissions exist in the current directory
"""

import argparse
import json
import sqlite3
import mysql.connector
import mysql.connector.pooling
import mysql.connector.abstracts
import subprocess
import sys
import yaml
import re
from pathlib import Path


type LocalConnection = sqlite3.Connection

type RemoteConnection = (
    mysql.connector.pooling.PooledMySQLConnection
    | mysql.connector.abstracts.MySQLConnectionAbstract
)


REMOTE_DB_USER = "blis"
REMOTE_DB_PASSWORD = "blis"
REMOTE_DB_NAME = "famlvkgo_blis-perf-ci"


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Upload merged performance data to central database"
    )
    parser.add_argument(
        "--keep-local",
        action="store_true",
        help="Keep local database after uploading",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Skip upload step, only merge local database",
    )
    parser.add_argument(
        "-s",
        "--status",
        help="YAML file to save the status of each git reference (most recent commit) after processing",
    )
    parser.add_argument(
        "-t",
        "--tunnel",
        help="Open an SSH tunnel to a remote database before uploading ([user@]host[:port[:local_port]])",
    )

    args = parser.parse_args()
    if args.dry_run:
        args.keep_local = True

    return args


def parse_testsuite(filepath: str | Path) -> dict:
    """Parse output.testsuite file and extract relevant data."""
    data = {"config": None, "threads": None, "operations": []}

    with open(filepath, "r") as f:
        lines = f.readlines()

    # Extract config (last word on "% active sub-configuration" line)
    for line in lines:
        if "% active sub-configuration" in line:
            parts = line.split()
            data["config"] = parts[-1].strip()
            break

    # Extract threads (first number in the "% environment" line after "% ways of parallelism")
    for i, line in enumerate(lines):
        if "% ways of parallelism" in line:
            # Look for the "% environment" line - it should be the next non-empty line or within next few lines
            for j in range(i + 1, min(i + 5, len(lines))):
                if "environment" in lines[j]:
                    # This line has the thread values, extract first number
                    numbers = re.findall(r"\d+", lines[j])
                    if numbers:
                        data["threads"] = int(numbers[0])
                    break
            break

    # Parse operation blocks
    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for header lines starting with "% blis_"
        if line.startswith("% blis_<dt><op>"):
            # This is a header line, parse it to determine columns
            header = line.strip()

            # Parse column names from header
            # Format: % blis_<dt><op>_<params>_<stor>            m   gflops   resid      result
            # or:     % blis_<dt><op>_<params>_<stor>            m     n     k   gflops   resid      result

            columns = []
            parts = header.split()
            # Skip the first two parts (% and the template)
            for part in parts[2:]:
                if part in ["m", "n", "k", "gflops", "resid", "result"]:
                    columns.append(part)

            # Read data lines until we hit another header or comment
            i += 1
            while i < len(lines):
                data_line = lines[i]

                # Stop if we hit another header or empty comment section
                if data_line.startswith("%"):
                    break

                # Stop if line is empty
                if not data_line.strip():
                    i += 1
                    break

                # Parse the data line
                parts = data_line.split()
                if len(parts) >= 1 and parts[0].startswith("blis_"):
                    operation_name = parts[0]
                    values = parts[1:]

                    # Extract dt and op from operation_name
                    # Format: blis_s/d/c/z<op>_...
                    if len(operation_name) >= 7:
                        dt = operation_name[5]  # 6th character (0-indexed: 5)
                        op = operation_name[
                            6:
                        ]  # 7th character onwards, remove "blis_" and dt

                        # Create record
                        record = {
                            "op": op,
                            "dt": dt,
                            "m": -1,
                            "n": -1,
                            "k": -1,
                            "gflops": None,
                        }

                        # Map values to columns
                        for col_idx, col_name in enumerate(columns):
                            if col_idx < len(values):
                                try:
                                    if col_name in ["m", "n", "k"]:
                                        record[col_name] = int(values[col_idx])
                                    elif col_name == "gflops":
                                        record["gflops"] = float(values[col_idx])
                                except ValueError:
                                    pass

                        data["operations"].append(record)

                i += 1
        else:
            i += 1

    return data


def open_local_database(path: str | Path) -> LocalConnection:
    """Open SQLite database."""
    conn = sqlite3.connect(path)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE perf (
            `machine` text NOT NULL,
            `config` text NOT NULL,
            `commit` text NOT NULL,
            `tag` text NOT NULL,
            `timestamp` timestamp NOT NULL,
            `comment` text DEFAULT NULL,
            `gflops` double NOT NULL,
            `m` int(11) DEFAULT NULL,
            `n` int(11) DEFAULT NULL,
            `k` int(11) DEFAULT NULL,
            `op` text NOT NULL,
            `dt` char(1) NOT NULL,
            `threads` int(11) NOT NULL,
            `ir_nt` int(11) DEFAULT NULL,
            `jr_nt` int(11) DEFAULT NULL,
            `ic_nt` int(11) DEFAULT NULL,
            `jc_nt` int(11) DEFAULT NULL
        )
    """
    )

    conn.commit()
    return conn


def open_remote_database(url: str | Path, port: int | str = 3306) -> RemoteConnection:
    """Open MySQL database."""
    conn = mysql.connector.connect(
        host=url,
        port=int(port),
        user=REMOTE_DB_USER,
        password=REMOTE_DB_PASSWORD,
        database=REMOTE_DB_NAME,
    )
    return conn


def insert_data(
    conn: LocalConnection,
    data: dict,
):
    """Insert parsed data into database."""
    cursor = conn.cursor()

    for operation in data["operations"]:
        cursor.execute(
            """
            INSERT INTO `perf`
                (`tag`, `commit`, `timestamp`, `machine`, `threads`, `gflops`, `m`, `n`, `k`, `op`, `dt`, `config`, `comment`)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                data["tag"],
                data["commit"],
                data["timestamp"],
                data["machine"],
                data["threads"],
                operation["gflops"],
                operation["m"],
                operation["n"],
                operation["k"],
                operation["op"],
                operation["dt"],
                data["config"],
                data["comment"] if "comment" in data else None,
            ),
        )

    conn.commit()


def import_testsuite(
    testsuite_file: str | Path,
    conn: LocalConnection,
    git_commit: str,
    git_tag: str,
    timestamp: str,
    machine: str,
    comment: str | None = None,
) -> bool:
    """
    Import test suite data into SQLite database.

    Arguments:
        testsuite_file (str or Path): Path to the output.testsuite file
        conn (Connection): SQLite database connection
        git_commit (str): Git commit hash
        git_tag (str): Git tag/branch
        machine (str, optional): Machine name to store in the database
        comment (str, optional): Comment to store in the database
        timestamp (str, optional): Timestamp to store in the database
    Returns:
        bool: True if successful, False otherwise
    """
    # Check if testsuite file exists
    if not Path(testsuite_file).exists():
        print(f"Error: {testsuite_file} not found")
        return False

    print(f"Reading {testsuite_file}...")
    data = parse_testsuite(testsuite_file)
    data["commit"] = git_commit
    data["tag"] = git_tag
    data["machine"] = machine
    data["comment"] = comment if comment else ""
    data["timestamp"] = timestamp

    print(f"Config: {data['config']}")
    print(f"Threads: {data['threads']}")
    print(f"Operations found: {len(data['operations'])}")

    print(f"Git commit: {git_commit}")
    print(f"Git tag/branch: {git_tag}")
    print(f"Commit timestamp: {timestamp}")

    print(f"Inserting {len(data['operations'])} rows...")
    insert_data(conn, data)
    print("Done!")

    return True


def is_git_hash_like(name):
    """
    Check if a string looks like a git commit hash.

    Git short hashes are typically 7-40 hex characters.
    """
    if not isinstance(name, str):
        return False
    # Accept 7-40 hex characters (short or full commit hash)
    if len(name) < 7 or len(name) > 40:
        return False
    try:
        int(name, 16)
        return True
    except ValueError:
        return False


def find_commit_directories():
    """
    Find all subdirectories in the current directory that look like git commit hashes.

    Returns:
        list: List of Path objects for commit directories containing output.testsuite
    """
    commit_dirs = []
    cwd = Path.cwd()

    for item in cwd.iterdir():
        if (
            item.is_dir()
            and is_git_hash_like(item.name)
            and (item / "runjob.sh").exists()
        ):
            commit_dirs.append(item)

    return sorted(commit_dirs)


def download_database(url, output_file):
    """
    Download the database from the FTPS server using curl.

    Args:
        url (str): FTPS URL to download from
        output_file (str): Local file path to save to

    Returns:
        "success": Download successful
        "not_found": File not found on server (404)
        "error": Other error occurred
    """
    print(f"Downloading database from {url}...")
    try:
        result = subprocess.run(
            ["curl", "-n", "--ssl-reqd", "-o", output_file, "-w", "%{http_code}", url],
            capture_output=True,
            text=True,
            check=False,
        )
        # Extract HTTP status code from stdout (last part)
        http_code = result.stdout.strip().split()[-1] if result.stdout.strip() else ""

        if http_code == "200" or result.returncode == 0:
            print(f"  ✓ Database downloaded: {output_file}")
            return "success"
        elif http_code == "404":
            print("  Database not found on server (404)")
            return "not_found"
        else:
            print(f"  Error downloading database (HTTP {http_code}): {result.stderr}")
            return "error"
    except FileNotFoundError:
        print("  Error: curl command not found")
        return "error"
    except Exception as e:
        print(f"  Error during download: {e}")
        return "error"


def import_commit_dir(commit_dir: str | Path, conn: LocalConnection) -> bool:
    """
    Import the output.testsuite file from a commit directory into a new SQLite database.
    If the database already exists, it will not be recreated.

    Arguments:
        commit_dir (str or Path): Path to the commit directory containing output.testsuite
        conn (LocalConnection): SQLite database connection

    Returns:
        bool: True if successful, False otherwise
    """
    commit_dir = Path(commit_dir)
    commit_hash = commit_dir.name
    config_path = commit_dir / "config.yaml"
    if not config_path.exists():
        print(f"Error: config.yaml not found in {commit_dir}")
        return False

    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
    except Exception as e:
        print(f"Error reading config.yaml: {e}")
        return False

    machine = config.pop("machine", None)
    git_tag = config.pop("tag", None)
    timestamp = config.pop("timestamp", None)
    comment = json.dumps(config)

    if not machine:
        print("Error: 'machine' missing in config.yaml")
        return False

    outputs = list(commit_dir.glob("output.testsuite.*"))
    if not outputs:
        print(f"Error: No output.testsuite files found in {commit_dir}")
        return False

    for output_file in outputs:
        print(f"\nImporting {output_file} into local database...")
        if not import_testsuite(
            output_file, conn, commit_hash, git_tag, timestamp, machine, comment
        ):
            print(f"Error: Failed to import {output_file}")
            return False

    return True


def record_status(commit_dir: Path) -> dict:
    """
    Record the status of a git commit hash.

    Args:
        commit_dir (Path): Path to the commit directory

    Returns:
        dict: Status dictionary with commit hash and timestamp
    """
    commit_hash = commit_dir.name
    config_path = commit_dir / "config.yaml"
    if not config_path.exists():
        print(f"Error: config.yaml not found in {commit_dir}")
        return {}

    try:
        with open(config_path, "r") as f:
            tag = yaml.safe_load(f).get("tag", None)
            return {tag: commit_hash} if tag else {}
    except Exception as e:
        print(f"Error reading config.yaml: {e}")
        return {}


def upload_database(
    local_conn: LocalConnection,
    remote_conn: RemoteConnection,
) -> bool:
    """
    Upload the local database to the remote database.

    Args:
        local_conn (LocalConnection): Local SQLite database connection
        remote_conn (RemoteConnection): Remote MySQL database connection

    Returns:
        bool: True if successful, False otherwise
    """

    remote_conn.start_transaction()

    local_cursor = local_conn.cursor()
    remote_cursor = remote_conn.cursor()

    def execute(local_stmt: str, remote_stmt: str) -> bool:
        try:
            local_cursor.execute(local_stmt)
            while True:
                rows = local_cursor.fetchmany(10000)
                if not rows:
                    break
                remote_cursor.executemany(remote_stmt, rows)
        except Exception as e:
            match = re.search("INSERT INTO `([^`]+)`", remote_stmt)
            table = match.group(1) if match else "<unknown>"
            print(f"Error during upload of `{table}`: {e}")
            remote_conn.rollback()
            return False

        return True

    if not execute(
        """
        SELECT DISTINCT `machine`, `config`, `commit`, `tag`, date(`timestamp`) as `timestamp`, `comment`
        FROM `perf`
        """,
        """
        INSERT INTO `runs` (
            `machine`, `config`, `commit`, `tag`, `timestamp`, `comment`
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
    ):
        return False

    if not execute(
        """
        SELECT `gflops`, `m`, `n`, `k`, `op`, `dt`, `threads`, `ir_nt`, `jr_nt`, `ic_nt`, `jc_nt`, `machine`, `config`, `commit`, `tag`
        FROM `perf`
        """,
        """
        INSERT INTO `perf` (
            `run`, `gflops`, `m`, `n`, `k`, `op`, `dt`, `threads`, `ic_nt`, `jc_nt`, `ir_nt`, `jr_nt`
        )
        SELECT `id`, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        FROM `runs`
        WHERE `runs`.`machine` = %s AND `runs`.`config` = %s AND `runs`.`commit` = %s AND `runs`.`tag` = %s
        """,
    ):
        return False

    if not execute(
        """
        SELECT MAX(`gflops`) as `gflops`, `op`, `dt`, `threads`, `machine`, `config`, `commit`, `tag`
        FROM `perf`
        GROUP BY `op`, `dt`, `threads`, `machine`, `config`, `commit`, `tag`
        """,
        """
        INSERT INTO `max_perf` (
            `run`, `gflops`, `op`, `dt`, `threads`
        )
        SELECT `id`, %s, %s, %s, %s
        FROM `runs`
        WHERE `runs`.`machine` = %s AND `runs`.`config` = %s AND `runs`.`commit` = %s AND `runs`.`tag` = %s
        """,
    ):
        return False

    if not execute(
        """
        SELECT MAX(`gflops`) as `gflops`, `op`, `dt`, `machine`, `config`, `commit`, `tag`
        FROM `perf`
        GROUP BY `op`, `dt`, `machine`, `config`, `commit`, `tag`
        """,
        """
        INSERT INTO `max_perf` (
            `run`, `gflops`, `op`, `dt`
        )
        SELECT `id`, %s, %s, %s
        FROM `runs`
        WHERE `runs`.`machine` = %s AND `runs`.`config` = %s AND `runs`.`commit` = %s AND `runs`.`tag` = %s
        """,
    ):
        return False

    remote_conn.commit()

    return True


def main():
    """Main entry point."""

    args = parse_arguments()

    print(f"\n{'=' * 60}")
    print("BLIS Performance Data Upload")
    print(f"{'=' * 60}\n")

    # Find local commit directories with databases
    print("Looking for local databases in commit hash directories...")
    commit_dirs = find_commit_directories()
    if not commit_dirs:
        print("  No local databases found in commit hash directories")
        print("  Nothing to merge and upload")
        return

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

    local_db_path = Path("perf.sqlite")
    if local_db_path.exists():
        print("Existing local database found, removing first")
        local_db_path.unlink()
    local_db = open_local_database(local_db_path)

    for commit_dir in commit_dirs:
        print(f"\nImporting data from {commit_dir}...")
        if not import_commit_dir(commit_dir, local_db):
            print(f"Error: Failed to import data from {commit_dir}")
            sys.exit(1)
        status_data.update(record_status(commit_dir))

    if not args.dry_run:
        print(f"\n{'=' * 60}")
        print("Uploading merged database")
        print(f"{'=' * 60}\n")

        mysql_port = 3306  # Default local port for MySQL
        tunnel = None
        if args.tunnel:
            # Parse the tunnel argument
            parts = args.tunnel.split("@")
            if len(parts) == 2:
                host, ports = (
                    parts[1].split(":", 1) if ":" in parts[1] else (parts[1], None)
                )
                user = parts[0]
            else:
                host, ports = (
                    parts[0].split(":", 1) if ":" in parts[0] else (parts[0], None)
                )
                user = None

            ssh_port = None
            if ports:
                if ":" in ports:
                    ssh_port, mysql_port = ports.split(":", 1)
                else:
                    ssh_port = ports

            ssh_command = ["ssh", "-fN", f"{user}@{host}" if user else host]
            ssh_command.append("-L")
            ssh_command.append(f"{mysql_port}:localhost:3306")
            if ssh_port:
                ssh_command.append("-p")
                ssh_command.append(f"{ssh_port}")

            print(f"Opening SSH tunnel to {host} on local port {mysql_port}...")
            try:
                tunnel = subprocess.Popen(ssh_command)
                print("SSH tunnel established.")
            except subprocess.CalledProcessError as e:
                print(f"Error establishing SSH tunnel: {e}")
                sys.exit(1)

        remote_db = open_remote_database("localhost", mysql_port)
        if not upload_database(local_db, remote_db):
            print("Error: Failed to upload database")
            sys.exit(1)

        if tunnel:
            print("Closing SSH tunnel...")
            tunnel.terminate()
            tunnel.wait()
            print("SSH tunnel closed.")

        if args.status:
            status_file = Path(args.status)
            try:
                with open(status_file, "w") as f:
                    yaml.safe_dump(status_data, f)
            except Exception as e:
                print(f"Error writing status file '{status_file}': {e}")
                sys.exit(1)

    if not args.keep_local:
        try:
            local_db_path.unlink()
            print(f"Removed {local_db_path}")
        except Exception as e:
            print(f"Warning: Error deleting {local_db_path}: {e}")

    print(f"\n{'=' * 60}")
    print("Upload Complete")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
