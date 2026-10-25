"""Shared synthetic fixtures for the Task 002C-R3–R5 tests.

Nothing here opens real data.  The fixture is a tiny generated "bundle"
with decoded-style FASTAs at 500/251/101 nt, a labels CSV, exact/RC edge
JSON, and a historical v1 component membership/report, plus a fake
``mmseqs`` that implements the frozen predicate exactly for equal-length
sequences (Hamming identity >= 0.90 on either strand; full coverage) and
supports fault injection through environment variables.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import random
import stat
import sys
import time
from pathlib import Path

from rbpbench.splits import output as splits_output
from rbpbench.splits.components import UnionFind, component_id
from rbpbench.splits.r3r5.contract import InputSpec, fixture_contract
from rbpbench.splits.resource_probe_r2 import ResourceMonitors

ROWS = 90
PROTEINS = 3

FAKE_MMSEQS = r'''#!{python}
"""Fake MMseqs2 18.8cc5c for synthetic R3-R5 tests (frozen predicate on equal-length sequences)."""
import os, sys, time
args = sys.argv[1:]
env = os.environ

def read_fasta(path):
    recs, cur, chunks = {}, None, []
    for line in open(path):
        line = line.rstrip("\n")
        if line.startswith(">"):
            if cur is not None:
                recs[cur] = "".join(chunks)
            cur, chunks = line[1:], []
        else:
            chunks.append(line)
    if cur is not None:
        recs[cur] = "".join(chunks)
    return recs

def write_db(prefix, recs):
    with open(prefix, "w") as h:
        for k, v in recs.items():
            h.write(">" + k + "\n" + v + "\n")
    with open(prefix + ".lookup", "w") as h:
        for i, k in enumerate(recs):
            h.write(f"{i}\t{k}\t0\n")
    open(prefix + ".dbtype", "wb").write(b"\x01\x00\x00\x00")
    open(prefix + ".index", "w").write("".join(f"{i}\t0\t0\n" for i in range(len(recs))))

def rc(s):
    return s[::-1].translate(str.maketrans("ACGT", "TGCA"))

def best_segment(a, b):
    # ungapped local alignment: match +1, mismatch -3 (Kadane)
    best = (0, 0, 0)  # score, length, matches
    score = length = hits = 0
    for x, y in zip(a, b):
        if score <= 0:
            score = length = hits = 0
        score += 1 if x == y else -3
        length += 1
        hits += x == y
        if score > best[0]:
            best = (score, length, hits)
    return best

def qualifies(a, b, coverage):
    if len(a) != len(b):
        return False
    for other in (b, rc(b)):
        _score, length, hits = best_segment(a, other)
        if length and hits / length >= 0.90 and length / len(a) >= coverage and length / len(other) >= coverage:
            return True
    return False

def coverage_flag():
    return float(args[args.index("-c") + 1]) if "-c" in args else 0.8

def matches(pattern_var, *paths):
    pattern = env.get(pattern_var)
    return bool(pattern) and any(pattern in p for p in paths)

def pairs_from(var):
    out = set()
    for item in filter(None, env.get(var, "").split(";")):
        a, b = item.split(",")
        out.add((a, b)); out.add((b, a))
    return out

delay = float(env.get("FAKE_DELAY", "0"))
if delay:
    time.sleep(delay)
cmd = args[0] if args else ""
if cmd == "version":
    print("18.8cc5c")
elif cmd == "createdb":
    recs = read_fasta(args[1])
    if matches("FAKE_EMPTY_DB_MATCH", args[2]):
        recs = {}
    if matches("FAKE_WRONG_DB_MATCH", args[2]) and recs:
        first = next(iter(recs))
        recs = {("row_999999" if k == first else k): v for k, v in recs.items()}
    write_db(args[2], recs)
elif cmd == "convert2fasta":
    recs = read_fasta(args[1])
    if matches("FAKE_CORRUPT_CONVERT_MATCH", args[1]) and recs:
        first = next(iter(recs))
        s = recs[first]
        recs[first] = ("C" if s[0] != "C" else "G") + s[1:]
    with open(args[2], "w") as h:
        for k, v in recs.items():
            h.write(">" + k + "\n" + v + "\n")
elif cmd == "search":
    qdb, tdb, res, tmp = args[1:5]
    os.makedirs(tmp, exist_ok=True)
    if env.get("FAKE_SEARCH_FAIL_MATCH") and matches("FAKE_SEARCH_FAIL_MATCH", res):
        sys.stderr.write("Error: Prefilter died\n"); sys.exit(1)
    if env.get("FAKE_FATAL_DIAG_MATCH") and matches("FAKE_FATAL_DIAG_MATCH", res):
        sys.stderr.write("Process prefiltering step 1 of 2\n")
    if env.get("FAKE_HANG_MATCH") and matches("FAKE_HANG_MATCH", res):
        if env.get("FAKE_HANG_MARKER"):
            open(env["FAKE_HANG_MARKER"], "w").write(str(os.getpid()))
        time.sleep(3600)
    if env.get("FAKE_GROW_MATCH") and matches("FAKE_GROW_MATCH", res):
        with open(os.path.join(tmp, "grow.bin"), "wb") as h:
            h.write(b"0" * int(env.get("FAKE_GROW_BYTES", "1000000")))
        time.sleep(float(env.get("FAKE_GROW_SLEEP", "2")))
    q, t = read_fasta(qdb), read_fasta(tdb)
    full = qdb == tdb and "full_db" in qdb
    audit = "_audit_" in qdb and "control" not in qdb
    suppress = set()
    if full:
        suppress |= pairs_from("FAKE_SUPPRESS_FULL")
    if audit and "cycle1_" in qdb:
        suppress |= pairs_from("FAKE_SUPPRESS_AUDIT_CYCLE1")
    rows = []
    cov = coverage_flag()
    for qi, qs in q.items():
        group = []
        for ti, ts in t.items():
            if (qi, ti) in suppress:
                continue
            if qi == ti and full and qi in env.get("FAKE_DROP_SELF", "").split(","):
                continue
            if "control" in qdb and qi == ti and qi in env.get("FAKE_DROP_CONTROL_SELF", "").split(","):
                continue
            if qualifies(qs, ts, cov):
                group.append(ti)
        for ti in group:
            rows.append(f"{qi}\t{ti}\t182\t1.000\t1.0E-90\t0\t{len(qs)-1}\t{len(qs)}\t0\t{len(qs)-1}\t{len(qs)}\t{len(qs)}M\t0\t0\t0")
    if (not full and "control" not in qdb and "smoke" not in qdb and env.get("FAKE_EXTRA_HIT_MATCH")
            and matches("FAKE_EXTRA_HIT_MATCH", qdb) and q and t):
        # simulate MMseqs2 reporting a qualifying pair that construction did not contain
        rows.append(f"{next(iter(q))}\t{next(iter(t))}" + "\t0" * 13)
    if full and env.get("FAKE_UNGROUP") and len(rows) > 2:
        rows.append(rows[0])
    if full and env.get("FAKE_FOREIGN"):
        rows.append("row_0\trow_999999" + "\t0" * 13)
    with open(res, "w") as h:
        h.write("\n".join(rows) + ("\n" if rows else ""))
elif cmd == "createtsv":
    data = open(args[3]).read()
    with open(args[4], "w") as h:
        h.write(data)
else:
    sys.stderr.write("Error: unsupported fake command " + cmd + "\n")
    sys.exit(2)
'''


def write_fake_mmseqs(directory: Path) -> Path:
    path = Path(directory) / "mmseqs"
    path.write_text(FAKE_MMSEQS.replace("{python}", sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _rc(s: str) -> str:
    return s[::-1].translate(str.maketrans("ACGT", "TGCA"))


def _mutate(rng: random.Random, seq: str, positions) -> str:
    chars = list(seq)
    for i in positions:
        chars[i] = "ACGT"[("ACGT".index(chars[i]) + 1 + rng.randrange(3)) % 4]
    return "".join(chars)


def _center(seq: str, width: int) -> str:
    start = (len(seq) - width) // 2
    return seq[start:start + width]


def design(rows: int = ROWS, seed: int = 11) -> dict:
    """Returns 500-nt sequences plus the designed relations."""
    rng = random.Random(seed)
    base = [None] * rows
    for i in range(rows):
        base[i] = "".join(rng.choice("ACGT") for _ in range(500))
    # similar at every width: 4% scattered substitutions
    for a, b in ((1, 2), (2, 3), (10, 11), (20, 21), (40, 41), (60, 61), (70, 72)):
        base[b] = _mutate(rng, base[a], range(7, 500, 25))
    # similar only at 101 nt: heavy changes outside the central 101 nt
    outside = [i for i in range(500) if not (199 <= i < 300)]
    base[31] = _mutate(rng, base[30], outside[::3])
    # exact duplicate and reverse-complement duplicate at every width
    base[50] = base[49]
    base[53] = _rc(base[52])
    return {"sequences": base}


def write_fixture(root: Path, *, rows: int = ROWS, seed: int = 11, extra_v1_join=(80, 81)) -> dict:
    root = Path(root)
    seqs = design(rows, seed)["sequences"]
    paths = {}
    decode = root / "inputs" / "decode"
    decode.mkdir(parents=True, exist_ok=True)
    by_width = {}
    for width in (500, 251, 101):
        records = {f"row_{i}": (s if width == 500 else _center(s, width)) for i, s in enumerate(seqs)}
        by_width[width] = records
        path = decode / f"sequence_partitions_width_{width}.fasta"
        with path.open("w") as handle:
            for sid, seq in records.items():
                handle.write(f">{sid}\n{seq}\n")
        paths[f"fasta_{width}"] = path
        groups: dict[str, list[str]] = {}
        for sid, seq in records.items():
            key = min(seq, _rc(seq))
            groups.setdefault(key, []).append(sid)
        edges = []
        for members in groups.values():
            members = sorted(members)
            edges.extend([members[i], members[i + 1]] for i in range(len(members) - 1))
        ep = decode / f"duplicate_edges_{width}.json"
        ep.write_text(json.dumps(edges))
        paths[f"exact_rc_{width}"] = ep
    # labels: proteins 1..3, deterministic signs; unknown for some
    rng = random.Random(seed + 1)
    csv = root / "inputs" / "dataset" / "dataset_K562_multilabel_with_NEGs.csv"
    csv.parent.mkdir(parents=True, exist_ok=True)
    lines = ["sequence,labels"]
    for i in range(rows):
        tokens = []
        for pid in range(1, PROTEINS + 1):
            roll = rng.random()
            if roll < 0.4:
                tokens.append(str(pid))
            elif roll < 0.8:
                tokens.append(f"-{pid}")
        lines.append(f"0101,{';'.join(tokens)}")
    csv.write_text("\n".join(lines) + "\n")
    paths["dataset_csv"] = csv
    # v1 membership: a subset of true relations + one protected join without any similarity
    uf = UnionFind([f"row_{i}" for i in range(rows)])
    for a, b in ((1, 2), (10, 11), (49, 50), extra_v1_join):
        uf.union(f"row_{a}", f"row_{b}")
    membership = {}
    for members in uf.groups().values():
        cid = component_id(members)
        for m in members:
            membership[m] = cid
    v1 = root / "inputs" / "v1"
    v1.mkdir(parents=True, exist_ok=True)
    splits_output.write_deterministic_component_membership_gzip(membership.items(), v1 / "component_membership.tsv.gz")
    sizes: dict[str, int] = {}
    for cid in membership.values():
        sizes[cid] = sizes.get(cid, 0) + 1
    report = {"total_rows": rows, "component_count": len(sizes), "component_sizes": sizes,
              "giant_component_gate": {"single_component_gate_tripped": False, "top20_gate_tripped": False}}
    (v1 / "component_report.json").write_text(json.dumps(report))
    paths["v1_component_membership"] = v1 / "component_membership.tsv.gz"
    paths["v1_component_report"] = v1 / "component_report.json"
    for role, rel, content in (
        ("dataset_audit", "manifests/dataset_audit.json", '{"fixture": true}\n'),
        ("proteins_tsv", "configs/proteins.tsv", "protein_id\tprotein_name\n1\tA\n2\tB\n3\tC\n"),
        ("decode_manifest", "manifests/sequence_decode_002b2.json", '{"fixture": "decode"}\n'),
        ("r2_return_manifest", "manifests/sequence_r2_darwin_convergence_return.json", '{"fixture": "r2"}\n'),
    ):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        paths[role] = path
    specs = tuple(InputSpec(role, str(path.relative_to(root)), _sha(path), path.stat().st_size) for role, path in sorted(paths.items()))
    contract = fixture_contract(
        row_count=rows, inputs=specs, v1_expected_component_count=len(sizes),
        giant_single_fraction=0.10, giant_top20_fraction=0.60,
        assignment={"protein_id_max": PROTEINS, "evaluation_floor": 1},
        resources={"poll_interval_seconds": 0.05},
    )
    return {"contract": contract, "paths": paths, "records": by_width, "v1_membership": membership}


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start
        self.real = time.monotonic()

    def __call__(self) -> float:
        return self.now + (time.monotonic() - self.real)

    def advance(self, seconds: float) -> None:
        self.now += seconds


def fake_monitors(**overrides) -> ResourceMonitors:
    from rbpbench.splits.guarded_exec import directory_size_bytes

    values = dict(
        installed_ram_gib=lambda: 128.0,
        available_ram_gib=lambda: 100.0,
        process_tree_rss_kib=lambda pid: 1024,
        free_disk_gib=lambda path: 1000.0,
        dir_size_bytes=directory_size_bytes,
        swap_used_bytes=lambda: ("SwapTotal: 0 kB", 0),
        memory_pressure=lambda: ("fake", "normal"),
        clock=time.monotonic,
        children_peak_rss_kib=lambda: 1024,
    )
    values.update(overrides)
    return ResourceMonitors(**values)


def membership_from_gz(path: Path) -> list[tuple[str, ...]]:
    with gzip.open(path, "rt") as handle:
        return [tuple(line.rstrip("\n").split("\t")) for line in handle]


def clear_fake_env() -> None:
    for key in list(os.environ):
        if key.startswith("FAKE_"):
            del os.environ[key]


# ------------------------------------------------------------ launcher harness
REPO = Path(__file__).resolve().parents[1]


class Harness:
    """A fixture bundle built by the real builder, plus an injectable host."""

    def __init__(self, tmp: Path, *, rows: int = ROWS):
        from rbpbench.splits.r3r5 import bundle

        self.tmp = Path(tmp)
        self.src = self.tmp / "inputs_src"
        self.fixture = write_fixture(self.src, rows=rows)
        self.contract = self.fixture["contract"]
        self.fake = write_fake_mmseqs(self.tmp)
        sources = {spec.role: self.src / spec.path for spec in self.contract.inputs}
        self.bundle = self.tmp / "bundle"
        bundle.build_bundle(REPO, self.bundle, sources, contract=self.contract, require_clean=False)
        self.env = {"SLURM_JOB_ID": "777", "SLURM_CPUS_PER_TASK": "4", "SLURM_MEM_PER_NODE": "98304",
                    "RBP_JOB_TIME_LIMIT_SECONDS": str(48 * 3600)}
        self.monitors = fake_monitors()
        self.quota = {"machine_readable": True, "result": {"kind": "none"}}
        self.alive = False

    def host(self):
        from rbpbench.splits.r3r5 import darwin

        return darwin.Host(env=dict(self.env), monitors=self.monitors, system=lambda: ("Linux", "x86_64"),
                           running_mmseqs=lambda: "", running_rbp_jobs=lambda own: [],
                           job_alive=lambda job: self.alive, quota_probe=lambda path: self.quota)

    def verify_runtime(self, contract, receipt, require_python=True):
        return {"receipt_sha256": "fixture", "mmseqs_executable": str(self.fake),
                "binary": {"exe_name": "mmseqs", "resolved_path": str(self.fake), "sha256": "fake-sha", "version": "18.8cc5c"}}

    def launch(self, mode: str = "execute", **kwargs):
        import io

        from rbpbench.splits.r3r5 import darwin

        stream = io.StringIO()
        code, archive, state = darwin.run(mode, self.bundle, self.tmp / "receipt.json", host=self.host(),
                                          contract=self.contract, verify_runtime_fn=self.verify_runtime,
                                          log_stream=stream, **kwargs)
        self.last_log = stream.getvalue()
        return code, archive, state

    @property
    def work(self) -> Path:
        return self.bundle / "r3r5_work"

    def selected(self) -> list[str]:
        return sorted(p.stem for p in (self.work / "selected").glob("*.json"))

    def status(self, archive: Path) -> dict:
        from rbpbench.splits.r3r5 import returns

        return json.loads(returns.read_return_member(archive, "STATUS.json"))
