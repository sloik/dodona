"""Recover owned planted-defect workspaces after both processes are gone.

    python tools/recover_plant_batches.py [--root SCRATCH]

Operate beneath the runner's current user's scratch directory. Both runners
write the same batch ownership record before admitting a worker. Older runners
left no ownership record, so their workspaces are kept for separate review.
The command reports its own removals and errors. It awards no mutation credit.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import stat
import tempfile
import time

from run_provider_cases import Unobserved, observe, read_private, valid_pid

MARKER = "batch-owner.json"
WORK = "work"
BATCH_NAME = re.compile(r"dodona-(?:plant-batch-[A-Za-z0-9]{6}|rust-plant-batch-[a-z0-9_]{8})")
MARKER_LIMIT = 512


def record_owner(batch: pathlib.Path, supervisor: int, worker: int | None = None) -> None:
    """Publish an entire ownership record before the worker may write."""
    marker = batch / MARKER
    pending = marker.with_suffix(".next")
    descriptor = os.open(pending, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump({"schema": 1, "batch": batch.name, "supervisor": supervisor, "worker": worker}, output)
    pending.replace(marker)


def own_path(info: os.stat_result) -> bool:
    if getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        return False
    current_uid = getattr(os, "geteuid", None)
    return current_uid is None or (info.st_uid == current_uid() and not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH))


def distinct_record(pairs):
    record = dict(pairs)
    if len(record) != len(pairs):
        raise ValueError("duplicate ownership field")
    return record


def read_owner(batch: pathlib.Path) -> tuple[bytes, os.stat_result, int, int | None]:
    marker = batch / MARKER
    info = marker.lstat()
    if not own_path(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("ownership file is not private")
    raw = read_private(marker, MARKER_LIMIT)
    if raw is None or not os.path.samestat(info, marker.lstat()):
        raise ValueError("ownership file changed while it was read")
    record = json.loads(raw, object_pairs_hook=distinct_record)
    if type(record) is not dict or record.keys() != {"schema", "batch", "supervisor", "worker"}:
        raise ValueError("unexpected ownership fields")
    if type(record["schema"]) is not int or record["schema"] != 1 or record["batch"] != batch.name:
        raise ValueError("ownership record is for a different directory or version")
    supervisor, worker = record["supervisor"], record["worker"]
    if type(supervisor) is not int or valid_pid(str(supervisor)) != supervisor:
        raise ValueError("invalid supervisor ID")
    if worker is not None and (type(worker) is not int or worker == supervisor or valid_pid(str(worker)) != worker):
        raise ValueError("invalid worker ID")
    return raw, info, supervisor, worker


def recover(root: pathlib.Path, *, look=observe, remove=shutil.rmtree) -> dict:
    report = {"schema": 1, "removed": [], "kept": {}, "failed": {}}
    try:
        info = root.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("scratch root is not an ordinary directory")
        batches = sorted(path for path in root.iterdir() if BATCH_NAME.fullmatch(path.name))
    except (OSError, ValueError) as error:
        report["failed"]["scratch-root"] = str(error)
        return report

    for batch in batches:
        try:
            reason = recover_batch(batch, look, remove)
        except OSError as error:
            report["failed"][batch.name] = str(error)
            continue
        if reason is None:
            report["removed"].append(batch.name)
        else:
            report["kept"][batch.name] = reason
    return report


def recover_batch(batch: pathlib.Path, look, remove) -> str | None:
    try:
        info = batch.lstat()
        if not own_path(info) or not stat.S_ISDIR(info.st_mode):
            return "unrecognized-layout"
        owner, owner_info, supervisor, worker = read_owner(batch)
    except (OSError, Unobserved, ValueError):
        return "invalid-ownership"

    names = {path.name for path in batch.iterdir()}
    if names not in ({MARKER}, {MARKER, WORK}) or worker is None and WORK in names:
        return "unrecognized-layout"
    work = batch / WORK
    work_info = work.lstat() if WORK in names else None
    if work_info is not None and (not stat.S_ISDIR(work_info.st_mode) or not own_path(work_info)
                                  or work_info.st_dev != info.st_dev):
        return "unrecognized-layout"

    deadline = time.monotonic() + 2
    if look(supervisor, deadline) != "gone" or worker is not None and look(worker, deadline) != "gone":
        return "live-or-unknown"

    # A different directory or modified ownership record never inherits the decision.
    after = batch.lstat()
    if not stat.S_ISDIR(after.st_mode) or not own_path(after) or not os.path.samestat(info, after):
        return "unrecognized-layout"
    try:
        verified_owner, verified_info, _, _ = read_owner(batch)
        if verified_owner != owner or not os.path.samestat(owner_info, verified_info):
            return "invalid-ownership"
    except (OSError, Unobserved, ValueError):
        return "invalid-ownership"

    if {path.name for path in batch.iterdir()} != names:
        return "unrecognized-layout"
    if work_info is not None:
        child = work.lstat()
        if not stat.S_ISDIR(child.st_mode) or not own_path(child) or not os.path.samestat(work_info, child):
            return "unrecognized-layout"
        remove(work)
        if {path.name for path in batch.iterdir()} != {MARKER}:
            raise OSError("scratch contents remain after removal")

    (batch / MARKER).unlink()
    batch.rmdir()
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path(tempfile.gettempdir()))
    report = recover(parser.parse_args().root)
    print(json.dumps(report))
    return 2 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
