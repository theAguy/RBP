"""Standard-library-only Task 004A-3 discovery parsing and validation.

This module deliberately lives outside :mod:`rbpbench.rescnn`: Newton discovery
runs before a PyTorch environment exists.  Keep this module importable by the
system Python without importing NumPy, PyTorch, or the ResCNN package.
"""

import argparse
import json
from pathlib import Path
import re


class ResCNN004A3RuntimeError(RuntimeError):
    """Fail-closed Task 004A-3 discovery/runtime contract violation."""


DISCOVERY_COMMAND_FIELDS = (
    "slurm_partition_detail", "sinfo_gpu_inventory", "os_release",
    "uname_kernel", "glibc_version", "conda_command", "conda_version",
    "conda_info", "module_avail", "python3_version", "quota_s",
    "lfs_quota", "df_home",
)

UNBOUNDED_SLURM_LIMITS = ("UNLIMITED", "INFINITE")


def parse_slurm_max_time(raw_value):
    """Return ``(seconds, error)`` for a Slurm ``MaxTime`` value.

    Discovery must preserve evidence even when a partition has no finite time
    limit.  Consequently this parser never raises for malformed site output.
    """

    if not isinstance(raw_value, str) or not raw_value.strip():
        return None, "partition MaxTime is missing"
    value = raw_value.strip()
    if value.upper() in UNBOUNDED_SLURM_LIMITS:
        return None, "partition MaxTime is not a finite reviewed limit: " + value
    try:
        days = 0
        if "-" in value:
            day_text, value = value.split("-", 1)
            days = int(day_text)
        fields = [int(part) for part in value.split(":")]
        if len(fields) == 3:
            hours, minutes, seconds = fields
        elif len(fields) == 2:
            hours, minutes, seconds = 0, fields[0], fields[1]
        else:
            return None, "unsupported Slurm MaxTime: " + raw_value
        if days < 0 or hours < 0 or minutes < 0 or seconds < 0:
            return None, "negative Slurm MaxTime component: " + raw_value
        if minutes >= 60 or seconds >= 60:
            return None, "invalid Slurm MaxTime component: " + raw_value
        total = days * 86400 + hours * 3600 + minutes * 60 + seconds
        if total <= 0:
            return None, "partition MaxTime is not positive: " + raw_value
        return total, None
    except (TypeError, ValueError):
        return None, "unparsable Slurm MaxTime: " + raw_value


def _require_command_evidence(payload, key):
    evidence = payload.get(key)
    if not isinstance(evidence, dict):
        raise ResCNN004A3RuntimeError("discovery lacks command evidence: " + key)
    if set(evidence) != {"available", "returncode", "stdout", "stderr"}:
        raise ResCNN004A3RuntimeError("discovery command evidence is malformed: " + key)
    if not isinstance(evidence["available"], bool):
        raise ResCNN004A3RuntimeError("discovery availability is malformed: " + key)
    if evidence["returncode"] is not None and not isinstance(evidence["returncode"], int):
        raise ResCNN004A3RuntimeError("discovery return code is malformed: " + key)
    if not isinstance(evidence["stdout"], str) or not isinstance(evidence["stderr"], str):
        raise ResCNN004A3RuntimeError("discovery output is malformed: " + key)


def require_discovery_install_policy(payload):
    reachable = payload.get("compute_node_required_channels_reachable")
    location = payload.get("site_approved_install_location")
    if reachable not in (True, False):
        raise ResCNN004A3RuntimeError("discovery lacks compute-node channel reachability")
    if location not in ("login_node", "cpu_job"):
        raise ResCNN004A3RuntimeError("discovery lacks an approved install location")
    return str(location)


def require_partition_preempt_mode(payload):
    """Return the scheduler's raw preemption policy from bound evidence."""

    evidence = payload.get("slurm_partition_detail")
    if not isinstance(evidence, dict) or not isinstance(evidence.get("stdout"), str):
        raise ResCNN004A3RuntimeError("discovery lacks partition preemption evidence")
    matches = re.findall(r"(?:^|\s)PreemptMode=([^\s]+)", evidence["stdout"])
    if len(matches) != 1 or not matches[0].strip():
        raise ResCNN004A3RuntimeError("partition PreemptMode is missing or ambiguous")
    return matches[0].strip()


def require_partition_time_evidence(payload):
    """Validate and return the raw finite-or-unbounded partition time evidence.

    An unbounded scheduler partition is valid discovery evidence.  It is not a
    usable experiment limit: the later bundle must bind a separate positive,
    project-owned limit.
    """

    seconds = payload.get("slurm_limit_seconds")
    error = payload.get("slurm_limit_error")
    partition = payload.get("slurm_partition_detail")
    stdout = partition.get("stdout", "") if isinstance(partition, dict) else ""
    raw_matches = re.findall(r"(?:^|\s)MaxTime=([^\s]+)", stdout)
    if len(raw_matches) != 1:
        raise ResCNN004A3RuntimeError("partition MaxTime is missing or ambiguous")
    raw_limit = raw_matches[0]
    if isinstance(seconds, int) and not isinstance(seconds, bool) and seconds > 0:
        if error is not None:
            raise ResCNN004A3RuntimeError(
                "finite partition limit must not carry a limit error"
            )
        parsed_seconds, parsed_error = parse_slurm_max_time(raw_limit)
        if parsed_error is not None or parsed_seconds != seconds:
            raise ResCNN004A3RuntimeError(
                "finite partition limit disagrees with raw MaxTime evidence"
            )
        return {"kind": "finite", "seconds": seconds, "raw_value": raw_limit}
    if seconds is not None:
        raise ResCNN004A3RuntimeError(
            "partition Slurm limit must be positive or explicitly unbounded"
        )
    for raw_value in UNBOUNDED_SLURM_LIMITS:
        expected = "partition MaxTime is not a finite reviewed limit: " + raw_value
        if error == expected and raw_limit == raw_value:
            return {"kind": "unbounded", "seconds": None, "raw_value": raw_value}
    raise ResCNN004A3RuntimeError(
        "unbounded partition limit is not bound to raw MaxTime evidence"
    )


def require_discovery_payload(payload):
    """Validate the complete data-free evidence needed by 004A-3C."""

    required = {
        "schema_version", "host", "system", "machine", "allocated_cpus",
        "slurm_job_id", "slurm_partition", "requested_slurm_partition",
        "slurm_account", "requested_slurm_account", "installed_ram_bytes",
        "available_ram_bytes", "free_disk_bytes", "quota_available_bytes",
        "operator_quota_available_bytes", "slurm_limit_seconds",
        "slurm_limit_error", "compute_node_required_channels_reachable",
        "site_approved_install_location", "gpu_csv", "nvidia_smi",
        "requires_owner_review_before_lock",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ResCNN004A3RuntimeError("discovery payload is incomplete: {!r}".format(missing))
    if payload["schema_version"] != "task004a3_discovery_v2":
        raise ResCNN004A3RuntimeError("discovery schema mismatch")
    for key in (
        "host", "system", "machine", "slurm_job_id", "slurm_partition",
        "requested_slurm_partition",
    ):
        if not isinstance(payload[key], str) or not payload[key].strip():
            raise ResCNN004A3RuntimeError("discovery identity is empty: " + key)
    if payload["requested_slurm_partition"] != payload["slurm_partition"]:
        raise ResCNN004A3RuntimeError("requested and allocated Slurm partitions disagree")
    for key in ("slurm_account", "requested_slurm_account"):
        if payload[key] is not None and (
            not isinstance(payload[key], str) or not payload[key].strip()
        ):
            raise ResCNN004A3RuntimeError("discovery account is malformed: " + key)
    if (
        payload["requested_slurm_account"] is not None
        and payload["requested_slurm_account"] != payload["slurm_account"]
    ):
        raise ResCNN004A3RuntimeError("requested and allocated Slurm accounts disagree")
    if payload["requires_owner_review_before_lock"] is not True:
        raise ResCNN004A3RuntimeError("discovery does not require owner review before lock")
    for key in DISCOVERY_COMMAND_FIELDS:
        _require_command_evidence(payload, key)
    for key in (
        "slurm_partition_detail", "sinfo_gpu_inventory", "os_release",
        "uname_kernel", "glibc_version", "python3_version", "df_home",
    ):
        evidence = payload[key]
        if (
            evidence["available"] is not True
            or evidence["returncode"] != 0
            or not (evidence["stdout"] or evidence["stderr"]).strip()
        ):
            raise ResCNN004A3RuntimeError(
                "required discovery command did not complete cleanly: " + key
            )
    for key in (
        "allocated_cpus", "installed_ram_bytes", "available_ram_bytes",
        "free_disk_bytes", "quota_available_bytes",
        "operator_quota_available_bytes",
    ):
        if not isinstance(payload[key], int) or isinstance(payload[key], bool) or payload[key] <= 0:
            raise ResCNN004A3RuntimeError("discovery value must be positive: " + key)
    require_partition_time_evidence(payload)
    require_partition_preempt_mode(payload)
    if payload["quota_available_bytes"] != payload["operator_quota_available_bytes"]:
        raise ResCNN004A3RuntimeError("discovery quota fields disagree")
    if not isinstance(payload["gpu_csv"], str) or not payload["gpu_csv"].strip():
        raise ResCNN004A3RuntimeError("discovery GPU evidence is empty")
    if not isinstance(payload["nvidia_smi"], str) or not payload["nvidia_smi"].strip():
        raise ResCNN004A3RuntimeError("discovery nvidia-smi evidence is empty")
    require_discovery_install_policy(payload)
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", type=Path, required=True)
    args = parser.parse_args(argv)
    require_discovery_payload(json.loads(args.validate.read_text()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
