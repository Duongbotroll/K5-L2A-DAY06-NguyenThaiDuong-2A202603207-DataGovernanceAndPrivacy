"""BASELINE T08 (theo đề): xoá raw_video có filename chứa subject_id.

Không duyệt derived / backup / embedding, không kiểm legal hold / quyền / multi-subject.
Chạy:
    python -m src.main --track t08 --pipeline src.baseline_t08 --output out/baseline --run-name baseline --offline --seed 42
"""
from __future__ import annotations

import pandas as pd

from .common.context import RunContext
from .common.decision import Decision, write_decision
from .common.manifest import verify_manifest
from .t08.lineage import load_graph, load_requests


def run(ctx: RunContext) -> None:
    problems = verify_manifest(ctx.input_dir / "manifest.csv")
    if problems:
        raise ValueError(f"provenance check failed: {problems[:3]}")
    arts = load_graph(ctx.input_dir / "data_graph.json")
    reqs = load_requests(ctx.input_dir / "requests.json")
    rows = []
    for r in reqs:
        for a in arts:
            if a["type"] == "raw_video" and r["subject_id"] in str(a.get("filename", "")):
                rows.append({"request_id": r["request_id"], "artefact_id": a["artefact_id"], "action": "delete",
                             "reason_code": "BASELINE_FILENAME_MATCH"})
                ctx.audit.log(actor="baseline", action="delete", item_id=a["artefact_id"],
                              reason="filename match", request_id=r["request_id"])
    out = pd.DataFrame(rows, columns=["request_id", "artefact_id", "action", "reason_code"])
    out = out.sort_values(["request_id", "artefact_id"]).reset_index(drop=True)
    out.to_csv(ctx.out("actions.csv"), index=False)
    ctx.stats["n_items"] = len(out)
    write_decision(Decision(status="HOLD", reason_code="BASELINE_ONLY",
                            reason="Baseline chỉ xoá raw theo filename, không dùng để release",
                            owner=ctx.config.get("owner", "baseline"), scope=ctx.track,
                            evidence=[str(ctx.out("actions.csv"))]),
                   ctx.out("decision.json"), ctx.out("decision_log.csv"))
