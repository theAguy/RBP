"""Single-process GPU runner and pre-data probe for Task 004A-3."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

import numpy as np
import torch
import torch.nn.functional as F

from rbpbench.rescnn.adam_004a3 import build_gpu_adam, run_three_step_oracle
from rbpbench.rescnn.cache_004a3 import open_cache, PRODUCTION_PARTITION_SIZE
from rbpbench.rescnn.checkpoint import (
    atomic_save_resource_smoke_checkpoint,
    load_resource_smoke_model_checkpoint,
)
from rbpbench.rescnn.config import load_config
from rbpbench.rescnn.factories_004a2 import build_scheduler, configured_loss, gradient_sha256
from rbpbench.rescnn.fidelity import canonical_state_hash
from rbpbench.rescnn.metrics import evaluate_known_outputs
from rbpbench.rescnn.model import CNNMultiLabelResidual, EXPECTED_LEARNABLE_PARAMETERS, count_learnable_parameters
from rbpbench.rescnn.output import atomic_write, canonical_json
from rbpbench.rescnn.portable_004a3 import compare_process_records
from rbpbench.rescnn.projection_004a3 import (
    StorageInputs, TimeInputs, project_storage_bytes, project_wall_seconds,
    require_projection_limits,
)
from rbpbench.rescnn.environment_004a3 import sha256_file
from rbpbench.rescnn.reproducibility import configure_strict_float32, epoch_order, initialize_paired_model
from rbpbench.rescnn.runtime_004a3 import LiveResourceMonitor, linux_peak_rss_bytes
from rbpbench.rescnn.timing_004a3 import benchmark_full_validation_metrics, measure_batches


class ResCNN004A3RunnerError(RuntimeError):
    pass


THREAD_ENV = {
    "OMP_NUM_THREADS": "4", "MKL_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4",
    "VECLIB_MAXIMUM_THREADS": "4", "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
}


def require_pre_python_environment() -> None:
    drift = {key: os.environ.get(key) for key, expected in THREAD_ENV.items() if os.environ.get(key) != expected}
    if drift:
        raise ResCNN004A3RunnerError(f"required pre-Python environment drift: {drift!r}")


def _tensor_digest(tensor: torch.Tensor) -> str:
    value = tensor.detach().cpu().contiguous()
    digest = hashlib.sha256()
    digest.update(str(value.dtype).encode())
    digest.update(str(tuple(value.shape)).encode())
    digest.update(value.numpy().tobytes())
    return digest.hexdigest()


def _runtime_identity(runtime_manifest_sha256: str) -> dict[str, str]:
    if not torch.cuda.is_available():
        raise ResCNN004A3RunnerError("Task 004A-3 requires real CUDA")
    index = torch.cuda.current_device()
    properties = torch.cuda.get_device_properties(index)
    uuid = getattr(properties, "uuid", None)
    if uuid is None:
        # nvidia-smi UUID must be injected by the reviewed launcher on versions
        # where PyTorch does not expose it.
        uuid = os.environ.get("RBP_ALLOCATED_GPU_UUID")
    if not uuid:
        raise ResCNN004A3RunnerError("GPU UUID is unavailable")
    return {
        "gpu_name": torch.cuda.get_device_name(index), "gpu_uuid": str(uuid),
        "runtime_manifest_sha256": runtime_manifest_sha256,
    }


def synthetic_cuda_probe(config_path: Path) -> dict[str, object]:
    """Data-free real-CNN/loss/Adam probe, repeated from fresh models."""

    require_pre_python_environment()
    configure_strict_float32(require_cuda=True)
    config = load_config(config_path)
    oracle = run_three_step_oracle(config, device="cuda")
    signatures = []
    for _repeat in range(2):
        by_config = {}
        for loss_config in config.loss_configs:
            start = initialize_paired_model(config.seeds[0], lambda: CNNMultiLabelResidual(config.output_count))
            model = start.model.cuda()
            if count_learnable_parameters(model) != EXPECTED_LEARNABLE_PARAMETERS:
                raise ResCNN004A3RunnerError("real CNN parameter count drift")
            generator = torch.Generator(device="cuda")
            generator.manual_seed(7821)
            codes = torch.randint(0, 4, (256, 500), generator=generator, device="cuda")
            sequences = F.one_hot(codes, num_classes=4).float()
            targets = torch.randint(0, 2, (256, 122), generator=generator, device="cuda").float()
            masks = torch.randint(0, 2, (256, 122), generator=generator, device="cuda").float()
            masks[0, 0] = 1
            masks[0, 1] = 0
            optimizer = build_gpu_adam(model, config)
            logits = model(sequences)
            breakdown = configured_loss(logits, targets, masks, config=config, loss_config=loss_config)
            optimizer.zero_grad(set_to_none=True)
            breakdown.total.backward()
            gradient = gradient_sha256(model)
            optimizer.step()
            by_config[loss_config.config_id] = {
                "initial": start.initial_state_sha256,
                "loss": _tensor_digest(breakdown.total), "gradient": gradient,
                "updated": canonical_state_hash(model.state_dict()),
            }
        signatures.append(by_config)
    if signatures[0] != signatures[1]:
        raise ResCNN004A3RunnerError("twice-repeated CUDA probe is not bitwise reproducible")
    return {"oracle": oracle.__dict__, "signature": signatures[0], "repeats_equal": True}


def _batch_from_cache(cache, indices: tuple[int, ...], device: torch.device):
    index = np.asarray(indices, dtype=np.int64)
    codes = torch.from_numpy(np.asarray(cache.base_codes[index])).to(device, non_blocking=False)
    targets = torch.from_numpy(np.asarray(cache.targets[index])).to(device, dtype=torch.float32)
    masks = torch.from_numpy(np.asarray(cache.masks[index])).to(device, dtype=torch.float32)
    sequences = F.one_hot(codes.long(), num_classes=4).to(torch.float32)
    return sequences, targets, masks


def run_process(
    *,
    role: str,
    config_path: Path,
    cache_path: Path,
    output_path: Path,
    runtime_manifest_sha256: str,
    source_sha256: str,
    requested_ram_bytes: int,
    physical_gpu_bytes: int,
    minimum_free_disk_bytes: int,
    deadline_monotonic: float,
) -> dict[str, object]:
    process_started = time.perf_counter()
    if role not in ("primary", "repeat"):
        raise ResCNN004A3RunnerError("runner role must be primary or repeat")
    if output_path.exists():
        raise ResCNN004A3RunnerError("process output already exists")
    require_pre_python_environment()
    configure_strict_float32(require_cuda=True)
    config = load_config(config_path)
    config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
    if len(source_sha256) != 64 or set(source_sha256) - set("0123456789abcdef"):
        raise ResCNN004A3RunnerError("source SHA-256 is malformed")
    identity = _runtime_identity(runtime_manifest_sha256)
    cache = open_cache(cache_path)
    monitor = LiveResourceMonitor(
        physical_gpu_bytes=physical_gpu_bytes,
        requested_ram_bytes=requested_ram_bytes,
        output_path=output_path.parent,
        minimum_free_disk_bytes=minimum_free_disk_bytes,
        deadline_monotonic=deadline_monotonic,
        gpu_reserved_reader=torch.cuda.max_memory_reserved,
        rss_reader=linux_peak_rss_bytes,
    )
    for partition in ("train", "validation"):
        if len(cache.indices(partition)) != PRODUCTION_PARTITION_SIZE:
            raise ResCNN004A3RunnerError("resource smoke cache size drift")
    train_indices = tuple(int(i) for i in cache.indices("train"))
    validation_indices = tuple(int(i) for i in cache.indices("validation"))
    config_records = {}
    startup_seconds = time.perf_counter() - process_started
    shared_initial = shared_order = shared_dropped = None
    device = torch.device("cuda")
    for loss_config in config.loss_configs:
        start = initialize_paired_model(config.seeds[0], lambda: CNNMultiLabelResidual(config.output_count))
        model = start.model.to(device)
        order = epoch_order(
            len(train_indices), batch_size=config.batch_size,
            loader_seed=start.streams.loader, epoch=0, drop_last=True,
        )
        optimizer = build_gpu_adam(model, config)
        scheduler = build_scheduler(optimizer, config)
        loss_digest = hashlib.sha256()
        gradient_digest = hashlib.sha256()

        def train_step(local_indices):
            global_indices = tuple(train_indices[i] for i in local_indices)
            sequences, targets, masks = _batch_from_cache(cache, global_indices, device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(sequences)
            breakdown = configured_loss(logits, targets, masks, config=config, loss_config=loss_config)
            breakdown.total.backward()
            optimizer.step()
            return breakdown.total

        def evidence(_batch, total):
            # Deliberately outside the synchronized interval.
            loss_digest.update(total.detach().cpu().numpy().tobytes())
            gradient_digest.update(bytes.fromhex(gradient_sha256(model)))
            monitor.observe()

        model.train()
        timing = measure_batches(
            order.batches, step=train_step, synchronize=torch.cuda.synchronize,
            outside_timed_region=evidence,
        )
        predictions = hashlib.sha256()
        validation_targets = []
        validation_masks = []
        validation_scores = []
        model.eval()
        validation_batches = tuple(
            validation_indices[start:start + config.batch_size]
            for start in range(0, len(validation_indices), config.batch_size)
        )

        def validation_step(batch):
            with torch.no_grad():
                sequences, _targets, _masks = _batch_from_cache(cache, batch, device)
                logits = model(sequences)
                scores = torch.sigmoid(logits).cpu()
                return scores, _targets.cpu(), _masks.cpu()

        def validation_evidence(_batch, result):
            scores, targets, masks = result
            predictions.update(scores.numpy().tobytes())
            validation_scores.append(scores.numpy())
            validation_targets.append(targets.numpy())
            validation_masks.append(masks.numpy())
            monitor.observe()

        validation_timing = measure_batches(
            validation_batches, step=validation_step, synchronize=torch.cuda.synchronize,
            outside_timed_region=validation_evidence,
        )
        scores_array = np.concatenate(validation_scores)
        targets_array = np.concatenate(validation_targets)
        masks_array = np.concatenate(validation_masks)
        metric_started = time.perf_counter()
        metric_rows, metric_summary = evaluate_known_outputs(
            targets_array, scores_array, masks_array,
            expected_output_count=config.output_count,
        )
        metric_seconds = time.perf_counter() - metric_started
        if len(metric_rows) != config.output_count or metric_summary["eligible_output_count"] != config.output_count:
            raise ResCNN004A3RunnerError("resource-smoke validation lost output eligibility")
        scheduler_started = time.perf_counter()
        scheduler.step(float(metric_summary["macro_auroc"]))
        scheduler_seconds = time.perf_counter() - scheduler_started
        checkpoint_path = output_path.with_name(f"{output_path.stem}.{loss_config.config_id}.pt")
        checkpoint_identity = {
            "source_sha256": source_sha256, "config_sha256": config_sha256,
            "environment_sha256": runtime_manifest_sha256,
            "seed": config.seeds[0], "config_id": loss_config.config_id,
        }
        torch.cuda.synchronize()
        checkpoint_started = time.perf_counter()
        checkpoint = atomic_save_resource_smoke_checkpoint(
            checkpoint_path, model=model, optimizer=optimizer,
            scheduler=scheduler, identity=checkpoint_identity,
            training_steps=len(order.batches),
        )
        fresh = CNNMultiLabelResidual(config.output_count).to(device)
        loaded = load_resource_smoke_model_checkpoint(
            checkpoint_path, model=fresh, expected_sha256=str(checkpoint["sha256"]),
            expected_identity=checkpoint_identity,
        )
        torch.cuda.synchronize()
        checkpoint_seconds = time.perf_counter() - checkpoint_started
        config_records[loss_config.config_id] = {
            "checkpoint_sha256": checkpoint["sha256"],
            "checkpoint_model_state_sha256": canonical_state_hash(model.state_dict()),
            "reloaded_model_state_sha256": loaded["model_state_sha256"],
            "checkpoint_bytes": checkpoint_path.stat().st_size,
            "checkpoint_seconds": checkpoint_seconds,
            "prediction_sha256": predictions.hexdigest(),
            "loss_steps_sha256": loss_digest.hexdigest(),
            "gradient_steps_sha256": gradient_digest.hexdigest(),
            "train_timing": timing.__dict__, "validation_timing": validation_timing.__dict__,
            "validation_batch_sizes": [len(batch) for batch in validation_batches],
            "subset_metric_seconds": metric_seconds,
            "scheduler_seconds": scheduler_seconds,
        }
        shared_initial = shared_initial or start.initial_state_sha256
        shared_order = shared_order or order.order_sha256
        shared_dropped = shared_dropped or order.dropped_sha256
        if (shared_initial, shared_order, shared_dropped) != (
            start.initial_state_sha256, order.order_sha256, order.dropped_sha256,
        ):
            raise ResCNN004A3RunnerError("paired config start/order/drop drift")
    record = {
        **identity, "role": role, "initial_state_sha256": shared_initial,
        "order_sha256": shared_order, "dropped_sha256": shared_dropped,
        "config_records": config_records,
        "resources": monitor.observe(),
        "startup_seconds": startup_seconds,
    }
    atomic_write(output_path, canonical_json(record))
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    probe = sub.add_parser("predata-probe")
    probe.add_argument("--config", type=Path, required=True)
    probe.add_argument("--output", type=Path, required=True)
    metric = sub.add_parser("metric-benchmark")
    metric.add_argument("--bundle-config", type=Path, required=True)
    metric.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--role", choices=("primary", "repeat"), required=True)
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--cache", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--runtime-manifest-sha256", required=True)
    run.add_argument("--source-sha256", required=True)
    run.add_argument("--requested-ram-bytes", type=int, required=True)
    run.add_argument("--physical-gpu-bytes", type=int, required=True)
    run.add_argument("--minimum-free-disk-bytes", type=int, required=True)
    run.add_argument("--deadline-monotonic", type=float, required=True)
    compare = sub.add_parser("compare")
    compare.add_argument("--primary", type=Path, required=True)
    compare.add_argument("--repeat", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    project = sub.add_parser("project")
    project.add_argument("--bundle-root", type=Path, required=True)
    project.add_argument("--bundle-config", type=Path, required=True)
    project.add_argument("--primary", type=Path, required=True)
    project.add_argument("--repeat", type=Path, required=True)
    project.add_argument("--metric-benchmark", type=Path, required=True)
    project.add_argument("--comparison", type=Path, required=True)
    project.add_argument("--slurm-limit-seconds", type=int, required=True)
    project.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "predata-probe":
        atomic_write(args.output, canonical_json(synthetic_cuda_probe(args.config)))
    elif args.command == "metric-benchmark":
        bundle = json.loads(args.bundle_config.read_text())
        summary = benchmark_full_validation_metrics(bundle["validation_known_counts"])
        atomic_write(args.output, canonical_json(summary.__dict__))
    elif args.command == "run":
        run_process(
            role=args.role, config_path=args.config, cache_path=args.cache,
            output_path=args.output,
            runtime_manifest_sha256=args.runtime_manifest_sha256,
            source_sha256=args.source_sha256,
            requested_ram_bytes=args.requested_ram_bytes,
            physical_gpu_bytes=args.physical_gpu_bytes,
            minimum_free_disk_bytes=args.minimum_free_disk_bytes,
            deadline_monotonic=args.deadline_monotonic,
        )
    elif args.command == "compare":
        payload = compare_process_records(
            json.loads(args.primary.read_text()), json.loads(args.repeat.read_text()),
        )
        atomic_write(args.output, canonical_json(payload))
    else:
        primary = json.loads(args.primary.read_text())
        repeat = json.loads(args.repeat.read_text())
        metric = json.loads(args.metric_benchmark.read_text())
        bundle = json.loads(args.bundle_config.read_text())
        records = [primary, repeat]
        configs = [record for process in records for record in process["config_records"].values()]
        checkpoint_paths = sorted(args.primary.parent.glob("*.pt"))
        if len(checkpoint_paths) != 6:
            raise ResCNN004A3RunnerError("projection requires six resource-smoke checkpoints")
        hash_started = time.perf_counter()
        hashed_bytes = 0
        for path in checkpoint_paths:
            sha256_file(path); hashed_bytes += path.stat().st_size
        hash_seconds = time.perf_counter() - hash_started
        if hashed_bytes <= 0 or hash_seconds <= 0:
            raise ResCNN004A3RunnerError("inventory hashing measurement is invalid")
        checkpoint_bytes = max(int(record["checkpoint_bytes"]) for record in configs)
        noncheckpoint = max(args.primary.stat().st_size, args.repeat.stat().st_size)
        bundle_bytes = sum(
            path.stat().st_size for path in args.bundle_root.rglob("*")
            if path.is_file() and "run" not in path.relative_to(args.bundle_root).parts
            and "return" not in path.relative_to(args.bundle_root).parts
        )
        projected_inventory = 90 * (checkpoint_bytes + noncheckpoint)
        time_inputs = TimeInputs(
            train_batch_p95_seconds=max(float(record["train_timing"]["p95_seconds"]) for record in configs),
            validation_batch_p95_seconds=max(float(record["validation_timing"]["p95_seconds"]) for record in configs),
            full_metrics_p95_seconds=float(metric["p95_seconds"]),
            scheduler_p95_seconds=max(float(record["scheduler_seconds"]) for record in configs),
            checkpoint_p95_seconds=max(float(record["checkpoint_seconds"]) for record in configs),
            startup_seconds_per_process=max(float(process["startup_seconds"]) for process in records),
            inventory_hash_seconds_per_byte=hash_seconds / hashed_bytes,
            projected_inventory_bytes=projected_inventory,
        )
        storage_inputs = StorageInputs(
            checkpoint_bytes=checkpoint_bytes,
            noncheckpoint_bytes_per_epoch=noncheckpoint,
            largest_atomic_temporary_bytes=checkpoint_bytes,
            environment_bytes=int(bundle["environment_bytes"]),
            bundle_bytes=bundle_bytes,
            return_bytes=args.comparison.stat().st_size,
        )
        wall = project_wall_seconds(time_inputs)
        storage = project_storage_bytes(storage_inputs)
        free = shutil.disk_usage(args.bundle_root).free
        require_projection_limits(
            projected_wall_seconds=float(wall["projected_seconds"]),
            slurm_limit_seconds=args.slurm_limit_seconds,
            projected_storage_bytes=int(storage["projected_bytes"]), free_bytes=free,
            quota_available_bytes=int(bundle["quota_available_bytes"]),
        )
        comparison = json.loads(args.comparison.read_text())
        atomic_write(args.output, canonical_json({
            "schema_version": "task004a3_final_report_v1", "status": "COMPLETED",
            "comparison": comparison, "wall_projection": wall,
            "storage_projection": storage, "free_disk_bytes": free,
            "quota_available_bytes": int(bundle["quota_available_bytes"]),
        }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
