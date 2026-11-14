"""Tự kiểm T08 KHÔNG cần ground truth (repo học viên không có gt/).

Chỉ dùng sự thật đọc được từ data_graph.json (không dùng policy của PoC để chấm PoC):
  - in_scope_pairs     : mọi cặp (request, artefact) có subject trong subject_ids  (= mẫu số)
  - scope_coverage     : cặp in-scope có action / in-scope pairs
  - delete_coverage    : cặp in-scope "sạch" (không hold, có quyền, rõ nguồn, 1 subject) được delete / số cặp sạch
  - held_deleted       : delete trên artefact bị legal hold (trực tiếp hoặc tổ tiên)      → mục tiêu 0
  - out_of_scope_del   : delete trên artefact không chứa subject của request              → mục tiêu 0
  - flagged_deleted    : delete trên artefact thiếu quyền / không rõ nguồn / nhiều subject → mục tiêu 0
  - copies_left        : backup + embedding + face_crop sạch của subject KHÔNG bị delete
  - audit_completeness : action có dòng audit (item_id = artefact_id) / action
Chú ý: "sạch" và "held" là định nghĩa của người làm (giả định hold lan xuống derived), ghi rõ trong report.

    python -m tools.self_eval_t08 --runs out/baseline out/poc --out reports/self_eval_t08.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.t08.lineage import held_by, load_graph, load_requests


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (round(c - h, 4), round(c + h, 4))


def evaluate(run_dir: Path, fix: Path) -> dict:
    arts = load_graph(fix / "data_graph.json")
    reqs = load_requests(fix / "requests.json")
    by = {a["artefact_id"]: a for a in arts}
    held = held_by(arts)
    flagged = {a["artefact_id"] for a in arts
               if "data-platform" not in a["acl"] or not a["origin_known"] or len(a["subject_ids"]) > 1}
    scope = {(r["request_id"], a["artefact_id"]) for r in reqs for a in arts if r["subject_id"] in a["subject_ids"]}
    clean = {k for k in scope if k[1] not in held and k[1] not in flagged}
    subj = {r["request_id"]: r["subject_id"] for r in reqs}

    act = pd.read_csv(run_dir / "actions.csv")
    pairs = dict(zip(zip(act.request_id, act.artefact_id), act.action))
    dels = {k for k, v in pairs.items() if v == "delete"}
    copies = {k for k in clean if by[k[1]]["type"] in ("backup", "embedding", "face_crop")}

    audit = run_dir / "audit_log.jsonl"
    logged = {json.loads(l).get("item_id") for l in audit.read_text().splitlines() if l.strip()} if audit.exists() else set()
    info = json.loads((run_dir / "run_info.json").read_text()) if (run_dir / "run_info.json").exists() else {}

    n_cov = len(scope & set(pairs))
    n_del = len(clean & dels)
    return {
        "run": run_dir.name,
        "n_rows": len(act),
        "in_scope_pairs": len(scope),
        "scope_coverage": round(n_cov / len(scope), 4),
        "delete_coverage": round(n_del / len(clean), 4),
        "delete_coverage_ci95": wilson_ci(n_del, len(clean)),
        "delete_coverage_counts": f"{n_del}/{len(clean)}",
        "held_deleted": sum(1 for k in dels if k[1] in held),
        "out_of_scope_del": sum(1 for k in dels if subj[k[0]] not in by[k[1]]["subject_ids"]),
        "flagged_deleted": sum(1 for k in dels if k[1] in flagged),
        "copies_left": f"{len(copies - dels)}/{len(copies)}",
        "audit_completeness": round(sum(1 for a in act.artefact_id if a in logged) / max(len(act), 1), 4),
        "runtime_s": info.get("runtime_seconds", info.get("seconds")),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", default=["out/baseline", "out/poc"])
    ap.add_argument("--fixture", default="fixtures/t08_deletion")
    ap.add_argument("--out", default="reports/self_eval_t08.md")
    a = ap.parse_args(argv)
    res = [evaluate(Path(r), Path(a.fixture)) for r in a.runs]
    keys = [k for k in res[0] if k != "run"]
    lines = ["# Self-eval T08 (không dùng GT, sinh bởi `python -m tools.self_eval_t08`)", "",
             "| Chỉ số | " + " | ".join(r["run"] for r in res) + " |", "|---|" + "---|" * len(res)]
    lines += [f"| {k} | " + " | ".join(str(r[k]) for r in res) + " |" for k in keys]
    Path(a.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    Path(a.out).with_suffix(".json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
