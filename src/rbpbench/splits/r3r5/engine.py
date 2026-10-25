"""E0–E8 orchestration for the accepted R3–R5 workflow.

Each stage writes one fresh candidate generation, verifies it completely,
promotes one selection record atomically, and only then lets the next stage
start.  Accepted, current records are reused on resume; a present but
stale or damaged record is an integrity stop.  The audit runs at most two
cycles: one complete 18-search audit, then — only when it found qualifying
pairs absent from every protected relation — one pre-authorized rebuild
(E4–E7) whose audit must report zero.  There is no other loop.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

from rbpbench.data.audit import sha256_file
from rbpbench.splits import commands as cmd
from rbpbench.splits import ingestion
from rbpbench.splits import output as splits_output
from rbpbench.splits.direct_edges import read_normalized_edges
from rbpbench.splits.r3r5 import assign as r3assign
from rbpbench.splits.r3r5 import audit as r3audit
from rbpbench.splits.r3r5 import components as r3comp
from rbpbench.splits.r3r5 import exact_rc_audit, fullsearch, smoke
from rbpbench.splits.r3r5.contract import ORDERED_DIRECTIONS, PARTITIONS, Contract
from rbpbench.splits.r3r5.state import Workspace, atomic_write_json, digest, utc_now
from rbpbench.splits.r3r5.stops import (
    ExternalResourceStop,
    IntegrityStop,
    ResourceLimitStop,
    SchedulerTimeStop,
    ScientificStop,
    ToolFailureStop,
)
from rbpbench.splits.r3r5.supervise import (
    DEADLINE_BUDGET,
    DEADLINE_RESERVE,
    DEADLINE_STAGE,
    Deadline,
    run_child,
)
from rbpbench.splits.resource_probe_r2 import ResourceMonitors, read_fasta_strict

ENGINE_SCHEMA = 1
MIN_SECONDS_BEFORE_RESERVE = 60.0


def _gzip_lines(path: Path, header: str | None, rows) -> None:
    with open(path, "wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz:
            if header is not None:
                gz.write((header + "\n").encode("utf-8"))
            for row in rows:
                gz.write(("\t".join(row) + "\n").encode("utf-8"))


def _write_pairs(path: Path, pairs) -> None:
    Path(path).write_text("".join(f"{a}\t{b}\n" for a, b in pairs))


def _read_pairs(path: Path) -> list[tuple[str, str]]:
    out = []
    for raw in Path(path).read_text().splitlines():
        a, b = raw.split("\t")
        out.append((a, b))
    return out


@dataclass
class Runtime:
    contract: Contract
    bundle_root: Path
    workspace: Workspace
    mmseqs_bin: str
    binary: dict
    monitors: ResourceMonitors
    allocation_deadline: float
    quota_check: Callable[[Path, int | None], dict]
    log: Callable[[str], None] = lambda message: None
    poll_interval: float | None = None
    events: list = field(default_factory=list)


class Workflow:
    def __init__(self, runtime: Runtime):
        self.rt = runtime
        self.c = runtime.contract
        self.ws = runtime.workspace
        self.universe_list = self.c.universe()
        self.universe = frozenset(self.universe_list)

    # ----------------------------------------------------------- helpers
    def input_path(self, role: str) -> Path:
        return self.rt.bundle_root / self.c.input(role).path

    def verify_input(self, role: str) -> str:
        spec = self.c.input(role)
        path = self.input_path(role)
        if not path.is_file():
            raise IntegrityStop(f"frozen input {role} is missing at {spec.path}")
        if spec.byte_size is not None and path.stat().st_size != spec.byte_size:
            raise IntegrityStop(f"frozen input {role} has {path.stat().st_size} bytes, expected {spec.byte_size}")
        actual = sha256_file(path)
        if actual != spec.sha256:
            raise IntegrityStop(f"frozen input {role} hashes to {actual}, expected {spec.sha256}")
        return actual

    def fingerprint(self, stage: str, upstream: Mapping[str, str], **extra) -> str:
        return digest({"engine_schema": ENGINE_SCHEMA, "contract": self.c.content_hash, "stage": stage,
                       "binary_sha256": self.rt.binary.get("sha256"), "upstream": dict(sorted(upstream.items())),
                       "extra": extra})

    def reserve_at(self) -> float:
        return self.rt.allocation_deadline - self.c.resources.packaging_reserve_hours * 3600.0

    def seconds_before_reserve(self) -> float:
        return self.reserve_at() - self.rt.monitors.clock()

    def require_time(self, label: str, needed: float = MIN_SECONDS_BEFORE_RESERVE) -> None:
        remaining = self.seconds_before_reserve()
        if remaining < needed:
            raise SchedulerTimeStop(
                f"{label}: {max(remaining, 0):.0f}s remain before the packaging reserve; {needed:.0f}s are required"
            )

    def aux_deadline(self, label: str) -> Deadline:
        self.require_time(label)
        now = self.rt.monitors.clock()
        stage_at = now + self.c.resources.auxiliary_child_timeout_hours * 3600.0
        return Deadline(stage_at, DEADLINE_STAGE) if stage_at <= self.reserve_at() else Deadline(self.reserve_at(), DEADLINE_RESERVE)

    def width_launch_gate(self, width: int, path: Path, label: str) -> dict:
        free = self.rt.monitors.free_disk_gib(path)
        needed = self.c.resources.launch_free_gib(width)
        if free < needed:
            raise ExternalResourceStop(
                f"{label}: {free:.2f} GiB free; C1 requires the 80-GiB floor plus the {self.c.resources.ceiling_gib(width)}-GiB "
                f"width-{width} ceiling = {needed} GiB before launch"
            )
        quota = self.rt.quota_check(path, width)
        return {"free_gib": free, "required_free_gib": needed, "quota": quota}

    def run(self, command, *, generation: Path, owned_dir: Path, width: int, deadline: Deadline) -> dict:
        self.rt.log(f"launch {command.tool}: {' '.join(command.argv[:2])} (width {width}, {deadline.kind})")
        evidence = run_child(command, contract=self.c, monitors=self.rt.monitors, log_dir=generation / "logs",
                             owned_dir=owned_dir, width=width, deadline=deadline, binary=self.rt.binary,
                             poll_interval=self.rt.poll_interval)
        return evidence

    def logs(self, generation: Path) -> list[Path]:
        log_dir = generation / "logs"
        return sorted(log_dir.glob("*.log")) if log_dir.is_dir() else []

    def write_json(self, path: Path, value) -> Path:
        atomic_write_json(path, value)
        return path

    # -------------------------------------------------------------- E0
    def stage_smoke(self) -> dict:
        key = "e0_smoke"
        fp = self.fingerprint(key, {}, seed=self.c.seed, widths=list(self.c.widths))
        record = self.ws.current(key, fingerprint=fp)
        if record is not None:
            return record
        gen = self.ws.new_generation("e0_smoke", key)
        results, steps = {}, {}
        for width in self.c.widths:
            fasta = gen / f"smoke_{width}.fasta"
            smoke.write_smoke_fasta(self.c.seed, width, fasta)
            db, res, tsv, tmp = gen / f"smoke_db_{width}", gen / f"smoke_res_{width}", gen / f"smoke_{width}.tsv", gen / f"tmp_{width}"
            steps[f"createdb_{width}"] = self.run(cmd.createdb_command(fasta, db, mmseqs_bin=self.rt.mmseqs_bin),
                                                  generation=gen, owned_dir=gen, width=width, deadline=self.aux_deadline("smoke createdb"))
            search = cmd.with_threads(cmd.components_v2_direct_search_command(db, db, res, tmp, width=width, mmseqs_bin=self.rt.mmseqs_bin),
                                      self.c.mmseqs_threads)
            steps[f"search_{width}"] = self.run(search, generation=gen, owned_dir=gen, width=width, deadline=self.aux_deadline("smoke search"))
            steps[f"createtsv_{width}"] = self.run(cmd.createtsv_search_command(db, db, res, tsv, mmseqs_bin=self.rt.mmseqs_bin),
                                                   generation=gen, owned_dir=gen, width=width, deadline=self.aux_deadline("smoke createtsv"))
            with tsv.open() as handle:
                results[str(width)] = smoke.check_smoke_hits(handle, width)
        report = self.write_json(gen / "smoke_report.json", {"results": results, "steps": steps})
        passed = all(r["passed"] for r in results.values())
        reconstructable = [p for p in gen.iterdir() if p.name.startswith(("smoke_db_", "smoke_res_", "tmp_"))]
        record = self.ws.promote(key, group="e0_smoke", generation=gen, fingerprint=fp, upstream={},
                                 retained=[report, *self.logs(gen)], reconstructable=reconstructable,
                                 payload={"passed": passed, "results": results})
        self.ws.cleanup_reconstructable(record, reason="E0 smoke databases are reconstructable from the generated fixture")
        if not passed:
            raise ToolFailureStop("E0 real-binary smoke test did not reproduce the frozen RC/identity/coverage semantics",
                                  details={"results": results})
        return record

    # ------------------------------------------------------------ E1–E3
    def stage_edges(self, width: int, smoke_digest: str) -> dict:
        key = f"edges_{width}"
        role = f"fasta_{width}"
        fp = self.fingerprint(key, {"e0_smoke": smoke_digest}, fasta_sha256=self.c.input(role).sha256)
        record = self.ws.current(key, fingerprint=fp)
        if record is not None:
            return record
        group = f"edges_{width}"
        owned = self.ws.group_dir(group)
        gate = self.width_launch_gate(width, self.ws.root, key)
        timeout = self.c.resources.construction_timeout_seconds(width)
        self.require_time(key, needed=timeout)
        deadline = Deadline(self.rt.monitors.clock() + timeout, DEADLINE_STAGE)
        self.verify_input(role)
        fasta = self.input_path(role)
        read_fasta_strict(fasta, width=width, universe=self.universe)
        gen = self.ws.new_generation(group, key)
        db, res, tmp = gen / "full_db", gen / "full_result", gen / "tmp"
        raw_tsv, normalized = gen / f"raw_full_search_{width}.tsv", gen / f"normalized_edges_{width}.tsv"
        steps = {"createdb": self.run(cmd.createdb_command(fasta, db, mmseqs_bin=self.rt.mmseqs_bin),
                                      generation=gen, owned_dir=owned, width=width, deadline=deadline)}
        lookup_ids = r3audit.read_lookup_ids(db, label=f"edges {width} database")
        if len(lookup_ids) != len(self.universe) or set(lookup_ids) != self.universe:
            raise IntegrityStop(f"width {width}: full database .lookup does not list exactly the canonical universe")
        steps["search"] = self.run(
            cmd.with_threads(cmd.components_v2_direct_search_command(db, db, res, tmp, width=width, mmseqs_bin=self.rt.mmseqs_bin),
                             self.c.mmseqs_threads),
            generation=gen, owned_dir=owned, width=width, deadline=deadline)
        steps["createtsv"] = self.run(cmd.createtsv_search_command(db, db, res, raw_tsv, mmseqs_bin=self.rt.mmseqs_bin),
                                      generation=gen, owned_dir=owned, width=width, deadline=deadline)
        edge_set, metrics = fullsearch.reconcile_full_search_file(raw_tsv, width=width, universe=self.universe)
        normalized_info = fullsearch.write_and_reread_normalized(edge_set, normalized, universe=self.universe)
        report = {
            "width": width, "metrics": metrics, "normalized": normalized_info,
            "raw_tsv": {"name": raw_tsv.name, "byte_size": raw_tsv.stat().st_size, "sha256": sha256_file(raw_tsv)},
            "same_database_query_and_target": True, "launch_gate": gate, "steps": steps,
        }
        report_path = self.write_json(gen / f"edges_report_{width}.json", report)
        reconstructable = [p for p in gen.iterdir() if p.name.startswith(("full_db", "full_result", "tmp"))]
        record = self.ws.promote(key, group=group, generation=gen, fingerprint=fp, upstream={"e0_smoke": smoke_digest},
                                 retained=[raw_tsv, normalized, report_path, *self.logs(gen)], reconstructable=reconstructable,
                                 payload={"width": width, "normalized_sha256": edge_set.sha256, "edge_count": len(edge_set.edges),
                                          "raw_rows": metrics["raw_rows"]})
        self.ws.cleanup_reconstructable(record, reason="MMseqs2 database/result/temp files are reconstructable from the bound FASTA, binary and frozen command")
        return record

    # ----------------------------------------------------------------- E4
    def load_v1(self) -> dict[str, str]:
        self.verify_input("v1_component_report")
        self.verify_input("v1_component_membership")
        report = ingestion.load_component_report(self.input_path("v1_component_report"), expected_row_count=self.c.row_count,
                                                 expected_component_count=self.c.v1_expected_component_count)
        universe = ingestion.load_component_membership(
            self.input_path("v1_component_membership"), expected_sample_count=self.c.row_count,
            expected_component_count=self.c.v1_expected_component_count, expected_component_sizes=report.component_sizes)
        return dict(universe.sample_to_component)

    def load_exact_rc(self) -> dict[int, list[tuple[str, str]]]:
        out = {}
        for width in self.c.widths:
            self.verify_input(f"exact_rc_{width}")
            data = json.loads(self.input_path(f"exact_rc_{width}").read_text())
            if not isinstance(data, list):
                raise IntegrityStop(f"exact/RC evidence for width {width} is not a JSON list")
            out[width] = r3comp.normalize_pairs(data, self.universe, label=f"exact/RC {width}")
        return out

    def relation_inputs(self, edge_records: Mapping[int, dict], discovered: list[tuple[str, str]]) -> r3comp.RelationInputs:
        direct = {}
        for width in self.c.widths:
            path = self.ws.retained_path(edge_records[width], f"normalized_edges_{width}.tsv")
            direct[width] = read_normalized_edges(path, width=width, universe=self.universe)
        return r3comp.RelationInputs(universe=tuple(self.universe_list), direct=direct, exact_rc=self.load_exact_rc(),
                                     v1_membership=self.load_v1(), discovered=tuple(discovered))

    def stage_components(self, cycle: int, edge_records: Mapping[int, dict], discovered_source: dict | None) -> dict:
        key = f"cycle{cycle}_components"
        upstream = {f"edges_{w}": self.ws.record_digest(f"edges_{w}") for w in self.c.widths}
        discovered: list[tuple[str, str]] = []
        if discovered_source is not None:
            upstream[discovered_source["stage"]] = self.ws.record_digest(discovered_source["stage"])
            discovered = _read_pairs(self.ws.retained_path(discovered_source, "audit_discovered_edges.tsv"))
        fp = self.fingerprint(key, upstream, exact=[self.c.input(f"exact_rc_{w}").sha256 for w in self.c.widths],
                              v1=self.c.input("v1_component_membership").sha256)
        record = self.ws.current(key, fingerprint=fp)
        if record is None:
            self.require_time(key)
            gen = self.ws.new_generation(key, key)
            forward = r3comp.build_components(self.relation_inputs(edge_records, discovered), self.c)
            repeat = r3comp.build_components(self.relation_inputs(edge_records, discovered), self.c, reverse_order=True)
            if not r3comp.same_result(forward, repeat):
                raise IntegrityStop(f"{key}: reordered reconstruction from freshly reread inputs differs")
            membership_path = gen / "components_v2.tsv.gz"
            splits_output.write_deterministic_component_membership_gzip(forward.membership.items(), membership_path)
            report_path = self.write_json(gen / "components_report.json", {
                "cycle": cycle, "summary": forward.summary, "metadata": forward.metadata,
                "reordered_repeat_identical": True, "membership_sha256": sha256_file(membership_path),
                "audit_discovered_edge_count": len(discovered),
            })
            gate = forward.summary["giant_component_gate"]
            record = self.ws.promote(key, group=key, generation=gen, fingerprint=fp, upstream=upstream,
                                     retained=[membership_path, report_path],
                                     payload={"component_count": forward.summary["component_count"],
                                              "v1_split": forward.summary["v1_comparison"]["v1_components_split_by_v2"],
                                              "giant_gate_tripped": gate["single_component_gate_tripped"] or gate["top20_gate_tripped"]})
        report = json.loads(self.ws.retained_path(record, "components_report.json").read_text())
        r3comp.enforce_gates(r3comp.ComponentsResult(membership={}, summary=report["summary"], metadata={}))
        return record

    def read_components(self, record: dict) -> dict[str, str]:
        rows = splits_output.read_component_membership_gzip(self.ws.retained_path(record, "components_v2.tsv.gz"))
        membership = dict(rows)
        if len(membership) != len(rows) or set(membership) != self.universe:
            raise IntegrityStop("components-v2 membership does not cover the universe exactly once")
        return membership

    # ----------------------------------------------------------------- E5
    def _assignment_generation(self, key: str, fp: str, upstream: dict, membership, components, *, repeat: bool) -> dict:
        record = self.ws.current(key, fingerprint=fp)
        if record is not None:
            return record
        self.require_time(key)
        gen = self.ws.new_generation(key, key)
        ordered = r3assign.reordered(components) if repeat else list(components)
        assignment = r3assign.run_assignment(ordered, self.c)
        summary = r3assign.scientific_summary(membership, assignment, self.c)
        membership_path = gen / "membership.tsv.gz"
        splits_output.write_deterministic_membership_gzip(r3assign.membership_rows(membership, assignment), membership_path)
        summary_path = self.write_json(gen / "assignment_summary.json", summary)
        return self.ws.promote(key, group=key, generation=gen, fingerprint=fp, upstream=upstream,
                               retained=[membership_path, summary_path],
                               payload={"input_order": "reordered" if repeat else "canonical",
                                        "partition_row_counts": summary["partition_row_counts"]})

    def stage_assignment(self, cycle: int, components_record: dict) -> dict:
        key = f"cycle{cycle}_assignment"
        upstream = {components_record["stage"]: self.ws.record_digest(components_record["stage"])}
        label_inputs = {r: self.c.input(r).sha256 for r in ("dataset_csv", "dataset_audit", "proteins_tsv")}
        fp_repeat = self.fingerprint(f"{key}_repeat", upstream, **label_inputs)
        repeat_current = self.ws.current(f"{key}_repeat", fingerprint=fp_repeat)
        primary_upstream = dict(upstream)
        membership = self.read_components(components_record)
        if repeat_current is None or self.ws.load_record(key) is None:
            for role in label_inputs:
                self.verify_input(role)
            components = r3assign.aggregate_component_labels(self.input_path("dataset_csv"), membership, self.c)
        else:
            components = []
        repeat = self._assignment_generation(f"{key}_repeat", fp_repeat, upstream, membership, components, repeat=True)
        primary_upstream[f"{key}_repeat"] = self.ws.record_digest(f"{key}_repeat")
        fp = self.fingerprint(key, primary_upstream, **label_inputs)
        record = self._assignment_generation(key, fp, primary_upstream, membership, components, repeat=False)
        a_rows = splits_output.read_membership_gzip(self.ws.retained_path(record, "membership.tsv.gz"))
        b_rows = splits_output.read_membership_gzip(self.ws.retained_path(repeat, "membership.tsv.gz"))
        a_summary = json.loads(self.ws.retained_path(record, "assignment_summary.json").read_text())
        b_summary = json.loads(self.ws.retained_path(repeat, "assignment_summary.json").read_text())
        if a_rows != b_rows or a_summary != b_summary:
            raise IntegrityStop(f"{key}: independent reordered assignment differs from the canonical assignment")
        sample_to_partition = {sid: part for sid, _cid, part in a_rows}
        self.check_whole_components(membership, sample_to_partition)
        self._enforce_assignment(membership, a_rows, a_summary)
        return record

    def check_whole_components(self, membership: Mapping[str, str], sample_to_partition: Mapping[str, str]) -> None:
        seen: dict[str, str] = {}
        for sample_id, cid in membership.items():
            partition = sample_to_partition[sample_id]
            if seen.setdefault(cid, partition) != partition:
                raise IntegrityStop(f"component {cid} is split across partitions")
        if set(sample_to_partition) != self.universe or not set(sample_to_partition.values()) <= set(PARTITIONS):
            raise IntegrityStop("assignment does not map the universe to train/validation/test only")

    def _enforce_assignment(self, membership, rows, summary) -> None:
        for p, deviation in summary["row_fraction_deviation_pp"].items():
            if deviation > self.c.assignment.row_fraction_acceptance_pct:
                raise ScientificStop(f"{p} row fraction deviates {deviation:.3f} pp")
        if not summary["minimum_count_report"]["passed"]:
            raise ScientificStop("evaluation floors are not met", details={"violations": summary["minimum_count_report"]["violations"]})
        components_in_rows = {cid for _sid, cid, _p in rows}
        if components_in_rows != set(membership.values()):
            raise IntegrityStop("assignment membership names different components from components v2")

    @staticmethod
    def partition_map(rows) -> dict[str, str]:
        return {sid: part for sid, _cid, part in rows}

    # ----------------------------------------------------------------- E6
    def stage_exact_audit(self, cycle: int, assignment_record: dict) -> dict:
        key = f"cycle{cycle}_exact_audit"
        upstream = {assignment_record["stage"]: self.ws.record_digest(assignment_record["stage"])}
        fp = self.fingerprint(key, upstream, fastas=[self.c.input(f"fasta_{w}").sha256 for w in self.c.widths])
        record = self.ws.current(key, fingerprint=fp)
        if record is None:
            self.require_time(key)
            gen = self.ws.new_generation(key, key)
            sample_to_partition = self.partition_map(
                splits_output.read_membership_gzip(self.ws.retained_path(assignment_record, "membership.tsv.gz")))
            exact = self.load_exact_rc()
            results = {}
            for width in self.c.widths:
                self.verify_input(f"fasta_{width}")
                records = exact_rc_audit.read_fasta_records(self.input_path(f"fasta_{width}"), width=width, expected_ids=self.universe)
                results[str(width)] = exact_rc_audit.audit_width(records, sample_to_partition, exact[width], width=width)
            report = self.write_json(gen / "exact_rc_audit.json", {"cycle": cycle, "widths": results,
                                                                   "implementation": "rbpbench.splits.r3r5.exact_rc_audit (independent)"})
            record = self.ws.promote(key, group=key, generation=gen, fingerprint=fp, upstream=upstream, retained=[report],
                                     payload={"passed": all(r["passed"] for r in results.values())})
        if not record["payload"]["passed"]:
            raise IntegrityStop(f"{key}: exact/RC audit found cross-partition groups or disagrees with accepted evidence")
        return record

    # ----------------------------------------------------------------- E7
    def stage_audit_prep(self, cycle: int, width: int, assignment_record: dict, edges_record: dict, exact_record: dict) -> dict:
        key = f"cycle{cycle}_auditprep_{width}"
        upstream = {r["stage"]: self.ws.record_digest(r["stage"]) for r in (assignment_record, edges_record, exact_record)}
        fp = self.fingerprint(key, upstream, fasta=self.c.input(f"fasta_{width}").sha256)
        record = self.ws.current(key, fingerprint=fp)
        if record is not None:
            return record
        group = f"cycle{cycle}_audit_{width}"
        owned = self.ws.group_dir(group)
        gate = self.width_launch_gate(width, self.ws.root, key)
        gen = self.ws.new_generation(group, key)
        rows = splits_output.read_membership_gzip(self.ws.retained_path(assignment_record, "membership.tsv.gz"))
        partition_of = self.partition_map(rows)
        self.verify_input(f"fasta_{width}")
        full = read_fasta_strict(self.input_path(f"fasta_{width}"), width=width, universe=self.universe)
        reference = {sid: r3audit.sequence_digest(seq) for sid, seq in full.items()}
        partitions, steps, databases = {}, {}, {}
        for partition in PARTITIONS:
            ids = frozenset(s for s, p in partition_of.items() if p == partition)
            fasta = gen / f"partition_{partition}.fasta"
            db = gen / f"db_{partition}"
            roundtrip = gen / f"roundtrip_{partition}.fasta"
            r3audit.write_partition_fasta(full, ids, fasta)
            steps[f"createdb_{partition}"] = self.run(cmd.createdb_command(fasta, db, mmseqs_bin=self.rt.mmseqs_bin), generation=gen,
                                                      owned_dir=owned, width=width, deadline=self.aux_deadline(f"{key} createdb"))
            steps[f"convert2fasta_{partition}"] = self.run(r3audit.convert2fasta_command(db, roundtrip, mmseqs_bin=self.rt.mmseqs_bin),
                                                           generation=gen, owned_dir=owned, width=width,
                                                           deadline=self.aux_deadline(f"{key} convert2fasta"))
            partitions[partition] = r3audit.reconcile_partition_database(
                fasta_path=fasta, db_prefix=db, roundtrip_fasta=roundtrip, partition_ids=ids, reference_inventory=reference,
                width=width, label=f"cycle {cycle} width {width} {partition}")
            databases[partition] = self.ws.inventory(gen, sorted(p for p in gen.iterdir() if p.is_file() and p.name.startswith(f"db_{partition}")))
        edges = read_normalized_edges(self.ws.retained_path(edges_record, f"normalized_edges_{width}.tsv"), width=width, universe=self.universe)
        selection = r3audit.select_positive_control(seed=self.c.seed, width=width, cycle=cycle, partition_of=partition_of,
                                                    construction_edges=list(edges.edges),
                                                    self_hits=self.c.positive_control_self_hits,
                                                    max_edges=self.c.positive_control_max_edges)
        control_fasta = gen / "positive_control.fasta"
        with control_fasta.open("w") as handle:
            for sid in selection["members"]:
                handle.write(f">{sid}\n{full[sid]}\n")
        cdb, cres, ctsv, ctmp = gen / "control_db", gen / "control_result", gen / "positive_control.tsv", gen / "control_tmp"
        steps["control_createdb"] = self.run(cmd.createdb_command(control_fasta, cdb, mmseqs_bin=self.rt.mmseqs_bin), generation=gen,
                                             owned_dir=owned, width=width, deadline=self.aux_deadline(f"{key} control createdb"))
        steps["control_search"] = self.run(
            cmd.with_threads(cmd.audit_search_command(cdb, cdb, cres, ctmp, width=width, mmseqs_bin=self.rt.mmseqs_bin), self.c.mmseqs_threads),
            generation=gen, owned_dir=owned, width=width, deadline=self.aux_deadline(f"{key} control search"))
        steps["control_createtsv"] = self.run(cmd.createtsv_search_command(cdb, cdb, cres, ctsv, mmseqs_bin=self.rt.mmseqs_bin),
                                              generation=gen, owned_dir=owned, width=width, deadline=self.aux_deadline(f"{key} control createtsv"))
        with ctsv.open() as handle:
            control = r3audit.check_positive_control(handle, selection, width=width)
        report = self.write_json(gen / f"audit_prep_{width}.json", {
            "cycle": cycle, "width": width, "partitions": partitions, "positive_control": {"selection": selection, "result": control},
            "launch_gate": gate, "steps": steps})
        reconstructable = [p for p in gen.iterdir() if p.name.startswith(("partition_", "db_", "roundtrip_", "positive_control.fasta",
                                                                             "control_db", "control_result", "control_tmp"))]
        return self.ws.promote(key, group=group, generation=gen, fingerprint=fp, upstream=upstream,
                               retained=[report, ctsv, *self.logs(gen)], reconstructable=reconstructable,
                               payload={"databases": databases, "partitions": {p: v["records"] for p, v in partitions.items()},
                                        "positive_control_passed": True})

    def verify_prep_databases(self, prep: dict) -> None:
        for partition, entries in prep["payload"]["databases"].items():
            for entry in entries:
                path = self.ws.abs(entry["path"])
                if not path.is_file() or path.stat().st_size != entry["byte_size"] or sha256_file(path) != entry["sha256"]:
                    raise IntegrityStop(f"{prep['stage']}: audit database file {entry['path']} changed or was substituted")

    def stage_direction(self, cycle: int, width: int, query: str, target: str, prep: dict, assignment_record: dict) -> dict:
        key = f"cycle{cycle}_audit_{width}_{query}_to_{target}"
        upstream = {prep["stage"]: self.ws.record_digest(prep["stage"])}
        fp = self.fingerprint(key, upstream, width=width, query=query, target=target)
        record = self.ws.current(key, fingerprint=fp)
        if record is not None:
            return record
        group = f"cycle{cycle}_audit_{width}"
        owned = self.ws.group_dir(group)
        used = self.ws.budget_used(cycle, width)
        remaining = self.c.resources.audit_budget_seconds(width) - used
        if remaining <= 0:
            raise ResourceLimitStop(f"{key}: the {self.c.resources.audit_budget_seconds(width) / 3600:.0f}-h width-{width} audit budget is exhausted")
        self.require_time(key)
        now = self.rt.monitors.clock()
        deadline = Deadline(now + remaining, DEADLINE_BUDGET) if now + remaining <= self.reserve_at() else Deadline(self.reserve_at(), DEADLINE_RESERVE)
        self.verify_prep_databases(prep)
        prep_gen = self.ws.abs(prep["generation"])
        rows = splits_output.read_membership_gzip(self.ws.retained_path(assignment_record, "membership.tsv.gz"))
        partition_of = self.partition_map(rows)
        query_ids = frozenset(s for s, p in partition_of.items() if p == query)
        target_ids = frozenset(s for s, p in partition_of.items() if p == target)
        for name, ids in ((query, query_ids), (target, target_ids)):
            lookup = r3audit.read_lookup_ids(prep_gen / f"db_{name}", label=f"{key} {name} database")
            if set(lookup) != ids or len(lookup) != len(ids):
                raise IntegrityStop(f"{key}: the {name} database does not list exactly that partition")
        gen = self.ws.new_generation(group, key)
        res, tsv, tmp = gen / "result", gen / f"audit_{width}_{query}_to_{target}.tsv", gen / "tmp"
        steps = {}
        started = self.rt.monitors.clock()
        outcome = "interrupted"
        try:
            steps["search"] = self.run(
                cmd.with_threads(cmd.audit_search_command(prep_gen / f"db_{query}", prep_gen / f"db_{target}", res, tmp, width=width,
                                                          mmseqs_bin=self.rt.mmseqs_bin), self.c.mmseqs_threads),
                generation=gen, owned_dir=owned, width=width, deadline=deadline)
            steps["createtsv"] = self.run(cmd.createtsv_search_command(prep_gen / f"db_{query}", prep_gen / f"db_{target}", res, tsv,
                                                                       mmseqs_bin=self.rt.mmseqs_bin),
                                          generation=gen, owned_dir=owned, width=width, deadline=deadline)
            outcome = "completed"
        finally:
            self.ws.charge_budget(cycle, width, label=key, elapsed=self.rt.monitors.clock() - started, outcome=outcome)
        violations = r3audit.directed_violations(tsv, width=width, query_partition=query, target_partition=target,
                                                 query_ids=query_ids, target_ids=target_ids)
        violations_path = gen / f"violations_{width}_{query}_to_{target}.tsv"
        _write_pairs(violations_path, violations)
        report = self.write_json(gen / f"audit_{width}_{query}_to_{target}.json", {
            "cycle": cycle, "width": width, "query_partition": query, "target_partition": target,
            "query_records": len(query_ids), "target_records": len(target_ids), "violation_count": len(violations),
            "steps": steps})
        record = self.ws.promote(key, group=group, generation=gen, fingerprint=fp, upstream=upstream,
                                 retained=[tsv, violations_path, report, *self.logs(gen)],
                                 reconstructable=[p for p in gen.iterdir() if p.name.startswith(("result", "tmp"))],
                                 payload={"cycle": cycle, "width": width, "query": query, "target": target,
                                          "violation_count": len(violations)})
        return record

    def stage_audit_summary(self, cycle: int, direction_records: list[dict], exact_record: dict, v1_membership: Mapping[str, str],
                            edge_records: Mapping[int, dict], prior_discovered: list[tuple[str, str]]) -> dict:
        key = f"cycle{cycle}_audit_summary"
        upstream = {r["stage"]: self.ws.record_digest(r["stage"]) for r in direction_records}
        upstream[exact_record["stage"]] = self.ws.record_digest(exact_record["stage"])
        fp = self.fingerprint(key, upstream)
        record = self.ws.current(key, fingerprint=fp)
        if record is None:
            self.require_time(key)
            expected = {(w, q, t) for w in self.c.widths for q, t in ORDERED_DIRECTIONS}
            seen = set()
            rows = []
            for r in direction_records:
                p = r["payload"]
                identity = (p["width"], p["query"], p["target"])
                if r["stage"] != f"cycle{cycle}_audit_{p['width']}_{p['query']}_to_{p['target']}" or p["cycle"] != cycle or identity in seen:
                    raise IntegrityStop(f"{key}: directed audit record {r['stage']} does not match its declared identity")
                seen.add(identity)
                for a, b in _read_pairs(self.ws.retained_path(r, f"violations_{p['width']}_{p['query']}_to_{p['target']}.tsv")):
                    rows.append((str(p["width"]), f"{p['query']}_to_{p['target']}", a, b))
            if seen != expected:
                raise IntegrityStop(f"{key}: expected all {len(expected)} directed audits, found {len(seen)}")
            gen = self.ws.new_generation(key, key)
            violation_pairs = sorted({(a, b) for _w, _d, a, b in rows})
            protected = set()
            for w in self.c.widths:
                protected |= set(read_normalized_edges(self.ws.retained_path(edge_records[w], f"normalized_edges_{w}.tsv"),
                                                       width=w, universe=self.universe).edges)
            for pairs in self.load_exact_rc().values():
                protected |= set(pairs)
            protected |= set(prior_discovered)
            classified = r3audit.classify_cycle_violations(violation_pairs, protected_pairs=protected, v1_membership=v1_membership)
            violations_file = gen / f"violations_cycle{cycle}.tsv.gz"
            _gzip_lines(violations_file, "width\tdirection\tsample_a\tsample_b", sorted(rows))
            discovered_file = gen / "audit_discovered_edges.tsv"
            _write_pairs(discovered_file, classified["audit_discovered"])
            summary = {"cycle": cycle, "directed_audits": len(seen), "violation_rows": len(rows),
                       "distinct_violation_pairs": len(violation_pairs),
                       "protected_but_split_pairs": [list(p) for p in classified["protected_but_split"]],
                       "audit_discovered_pair_count": len(classified["audit_discovered"])}
            summary_path = self.write_json(gen / f"audit_summary_cycle{cycle}.json", summary)
            record = self.ws.promote(key, group=key, generation=gen, fingerprint=fp, upstream=upstream,
                                     retained=[violations_file, discovered_file, summary_path],
                                     payload={"violation_pairs": len(violation_pairs),
                                              "protected_but_split": len(classified["protected_but_split"]),
                                              "audit_discovered": len(classified["audit_discovered"])})
        return record

    # ----------------------------------------------------------------- E8
    def stage_final(self, cycle: int, chain: list[dict], components_record: dict, assignment_record: dict,
                    edge_records: Mapping[int, dict], discovered: list[tuple[str, str]]) -> dict:
        key = "final"
        upstream = {r["stage"]: self.ws.record_digest(r["stage"]) for r in chain}
        fp = self.fingerprint(key, upstream, cycle=cycle)
        record = self.ws.current(key, fingerprint=fp)
        if record is not None:
            return record
        self.require_time(key)
        for r in chain:  # independent rehash of every retained artifact
            self.ws.verify_retained(r)
        inputs = self.relation_inputs(edge_records, discovered)
        relations = [list(inputs.direct[w].edges) for w in self.c.widths] + [list(v) for v in inputs.exact_rc.values()]
        v1_groups: dict[str, list[str]] = {}
        for sid, cid in inputs.v1_membership.items():
            v1_groups.setdefault(cid, []).append(sid)
        relations.append([(min(m), x) for m in v1_groups.values() for x in m if x != min(m)])
        relations.append(list(inputs.discovered))
        membership = self.read_components(components_record)
        bfs = r3comp.verify_membership_by_bfs(membership, self.universe_list, relations)
        rows = splits_output.read_membership_gzip(self.ws.retained_path(assignment_record, "membership.tsv.gz"))
        partition_of = self.partition_map(rows)
        if any(membership[sid] != cid for sid, cid, _p in rows):
            raise IntegrityStop("final: assignment membership component IDs differ from components v2")
        self.check_whole_components(membership, partition_of)
        recomputed = self._recompute_partition_summary(partition_of)
        summary = json.loads(self.ws.retained_path(assignment_record, "assignment_summary.json").read_text())
        if recomputed["partition_row_counts"] != summary["partition_row_counts"] or \
                recomputed["partition_label_counts"] != summary["partition_label_counts"]:
            raise IntegrityStop("final: independently recomputed partition/label counts differ from the assignment summary")
        self._enforce_assignment(membership, rows, summary)
        for r in chain:
            if "_audit_" in r["stage"] and "_to_" in r["stage"] and r["payload"]["violation_count"] != 0:
                raise IntegrityStop(f"final: {r['stage']} reports violations")
            if "_auditprep_" in r["stage"] and not r["payload"]["positive_control_passed"]:
                raise IntegrityStop(f"final: {r['stage']} positive control did not pass")
            if r["stage"].endswith("_exact_audit") and not r["payload"]["passed"]:
                raise IntegrityStop("final: exact/RC audit did not pass")
            if r["stage"].endswith("_audit_summary") and r["stage"] == f"cycle{cycle}_audit_summary" and r["payload"]["violation_pairs"]:
                raise IntegrityStop("final: the accepted audit cycle reports violations")
        gen = self.ws.new_generation("final", key)
        final_membership = gen / "membership.tsv.gz"
        splits_output.write_deterministic_membership_gzip(rows, final_membership)
        if splits_output.read_membership_gzip(final_membership) != rows:
            raise IntegrityStop("final membership does not reproduce the accepted assignment")
        manifest = {
            "checkpoint": self.c.checkpoint, "contract_sha256": self.c.content_hash, "accepted_cycle": cycle,
            "remediation_cycle_used": cycle == 2, "audit_discovered_edge_count": len(discovered),
            "binary": self.rt.binary, "universe_size": len(self.universe),
            "partition_row_counts": recomputed["partition_row_counts"], "component_count": len(set(membership.values())),
            "bfs_verification": bfs, "final_membership_sha256": sha256_file(final_membership),
            "selected_records": {r["stage"]: self.ws.record_digest(r["stage"]) for r in chain},
            "retained_artifacts": {r["stage"]: r["retained"] for r in chain},
            "frozen_inputs": {spec.role: {"path": spec.path, "sha256": spec.sha256, "byte_size": spec.byte_size} for spec in self.c.inputs},
            "finalized_at_utc": utc_now(),
        }
        manifest_path = self.write_json(gen / "final_manifest.json", manifest)
        return self.ws.promote(key, group="final", generation=gen, fingerprint=fp, upstream=upstream,
                               retained=[final_membership, manifest_path], payload={"cycle": cycle})

    def _recompute_partition_summary(self, partition_of: Mapping[str, str]) -> dict:
        self.verify_input("dataset_csv")
        a = self.c.assignment
        rows = {p: 0 for p in PARTITIONS}
        labels: dict[str, dict[int, list[int]]] = {p: {pid: [0, 0] for pid in range(a.protein_id_min, a.protein_id_max + 1)} for p in PARTITIONS}
        seen = 0
        for _index, sample_id, signed in ingestion.iter_csv_component_label_rows(
                self.input_path("dataset_csv"), protein_id_min=a.protein_id_min, protein_id_max=a.protein_id_max):
            partition = partition_of[sample_id]
            rows[partition] += 1
            seen += 1
            for pid, sign in signed.items():
                labels[partition][pid][0 if sign > 0 else 1] += 1
        if seen != len(self.universe):
            raise IntegrityStop("final: CSV row count differs from the universe")
        return {"partition_row_counts": rows,
                "partition_label_counts": {p: {str(pid): v for pid, v in sorted(per.items())} for p, per in labels.items()}}

def run_workflow(runtime: Runtime) -> dict:
    """Runs (or resumes) E0–E8.  Returns the success summary or raises a
    typed :mod:`stops` exception."""
    wf = Workflow(runtime)
    c = runtime.contract
    smoke_record = wf.stage_smoke()
    smoke_digest = runtime.workspace.record_digest(smoke_record["stage"])
    edge_records = {}
    for width in c.widths:
        edge_records[width] = wf.stage_edges(width, smoke_digest)
    v1_membership = wf.load_v1()
    discovered_source = None
    discovered: list[tuple[str, str]] = []
    for cycle in range(1, c.max_audit_cycles + 1):
        components_record = wf.stage_components(cycle, edge_records, discovered_source)
        assignment_record = wf.stage_assignment(cycle, components_record)
        exact_record = wf.stage_exact_audit(cycle, assignment_record)
        chain = [smoke_record, *edge_records.values(), components_record,
                 runtime.workspace.load_record(f"cycle{cycle}_assignment_repeat"), assignment_record, exact_record]
        if discovered_source is not None:
            chain.append(discovered_source)
        directions = []
        for width in c.widths:
            prep = wf.stage_audit_prep(cycle, width, assignment_record, edge_records[width], exact_record)
            chain.append(prep)
            width_records = []
            for query, target in ORDERED_DIRECTIONS:
                width_records.append(wf.stage_direction(cycle, width, query, target, prep, assignment_record))
            directions.extend(width_records)
            chain.extend(width_records)
            for record in [prep, *width_records]:
                runtime.workspace.cleanup_reconstructable(
                    record, reason=f"width-{width} audit databases/results reconstructable after all six directions were accepted")
        summary = wf.stage_audit_summary(cycle, directions, exact_record, v1_membership, edge_records, discovered)
        chain.append(summary)
        payload = summary["payload"]
        if payload["violation_pairs"] == 0:
            final = wf.stage_final(cycle, chain, components_record, assignment_record, edge_records, discovered)
            return {"status": "SUCCESS", "accepted_cycle": cycle, "final_record": final["stage"]}
        if payload["protected_but_split"]:
            raise IntegrityStop(f"cycle {cycle}: {payload['protected_but_split']} audit violation(s) are already-protected pairs "
                                "split across partitions")
        if cycle >= c.max_audit_cycles:
            raise ScientificStop(f"cycle {cycle} (the single remediation cycle) still reports {payload['violation_pairs']} "
                                 "qualifying cross-partition pair(s); the split is rejected")
        discovered_source = summary
        discovered = _read_pairs(runtime.workspace.retained_path(summary, "audit_discovered_edges.tsv"))
        runtime.log(f"cycle {cycle}: {len(discovered)} audit-discovered direct edge(s); starting the single remediation cycle")
    raise IntegrityStop("audit cycle loop ended without a terminal decision")


__all__ = ["Runtime", "Workflow", "run_workflow", "ENGINE_SCHEMA"]
