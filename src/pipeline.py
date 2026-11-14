"""PoC PIPELINE · T08 Retention & Delete Request Simulator (làm cá nhân: Nguyễn Thái Dương).

5 bước của lab:
    01 load      requests.json + data_graph.json + kiểm manifest sha256
    02 process   phạm vi theo subject + lineage BFS -> policy precedence (src/t08/policy.py)
    03 rank      mọi dòng ngoại lệ (escalate / retain_legal_hold) vào review queue
    04 review    đọc out/.../review_queue_reviewed.csv nếu có -> áp quyết định người duyệt + audit
    05 decide    dry-run diff -> mock delete + evidence -> GO / HOLD có reason_code + owner

Không đọc fixtures/*/gt/, không gọi network, không xoá dữ liệu thật (chỉ ghi file mock).
Chạy:  make run TRACK=t08
"""
from __future__ import annotations

import pandas as pd

from .common.context import RunContext
from .common.decision import Decision, write_decision
from .common.manifest import verify_manifest
from .common.review import load_review_decisions, make_review_queue, write_review_queue
from .metrics.tracks import get_track
from .t08.lineage import held_by, load_graph, load_requests, scope_for_subject
from .t08.policy import ACTIONS, decide as policy_decide

ACTION_PRIORITY = {"escalate": 2.0, "retain_legal_hold": 1.0, "delete": 0.0}   # cao = review trước
OUT_COLUMNS = ["request_id", "artefact_id", "action", "reason_code", "rule", "type", "subject_ids",
               "n_subjects", "legal_hold", "uri", "deadline", "score", "reviewed_by"]


# ---------------------------------------------------------------- 01 load
def load(ctx: RunContext) -> dict:
    manifest = ctx.input_dir / "manifest.csv"
    problems = verify_manifest(manifest) if manifest.exists() else [{"problem": "no_manifest"}]
    if problems:
        ctx.audit.log(actor="pipeline", action="provenance_problems", item_id=str(manifest), after=problems[:20])
        if ctx.config.get("strict_provenance", True):
            raise ValueError(f"provenance check failed ({len(problems)} problems), first: {problems[:3]}")
    arts = load_graph(ctx.input_dir / "data_graph.json")
    reqs = load_requests(ctx.input_dir / "requests.json")
    return {"artefacts": arts, "requests": reqs, "by_id": {a["artefact_id"]: a for a in arts}}


# ---------------------------------------------------------------- 02 process
def process(ctx: RunContext, data: dict) -> pd.DataFrame:
    arts, by_id = data["artefacts"], data["by_id"]
    held = held_by(arts)
    rows = []
    for r in sorted(data["requests"], key=lambda x: x["request_id"]):
        for aid in scope_for_subject(r["subject_id"], arts):
            a = by_id[aid]
            action, code, rule = policy_decide(a, r, held)
            rows.append({
                "request_id": r["request_id"], "artefact_id": aid, "action": action, "reason_code": code,
                "rule": rule, "type": a["type"], "subject_ids": ";".join(a["subject_ids"]),
                "n_subjects": len(a["subject_ids"]), "legal_hold": held.get(aid, ""), "uri": a.get("uri", ""),
                "deadline": r.get("deadline", ""), "score": ACTION_PRIORITY[action], "reviewed_by": "",
            })
    df = pd.DataFrame(rows, columns=OUT_COLUMNS)
    return df.sort_values(["request_id", "artefact_id"], kind="mergesort").reset_index(drop=True)


# ---------------------------------------------------------------- 03 rank
def rank(ctx: RunContext, scored: pd.DataFrame) -> pd.DataFrame:
    """Không cắt budget: mọi ngoại lệ phải có người duyệt (đã chốt trong metric_contract.md)."""
    exc = scored[scored.action != "delete"].copy()
    exc["item_id"] = exc.request_id + ":" + exc.artefact_id
    exc["slice"] = exc["type"]
    q = make_review_queue(exc, id_col="item_id", score_col="score", budget=len(exc),
                          reason_col="reason_code", action_col="action", slice_col="slice", evidence_col="uri")
    write_review_queue(q, ctx.out("review_queue.csv"))
    return q


# ---------------------------------------------------------------- 04 review
def review(ctx: RunContext, scored: pd.DataFrame, queue: pd.DataFrame) -> pd.DataFrame:
    """Áp quyết định người duyệt từ review_queue_reviewed.csv (nếu có).

    approve  : giữ nguyên action pipeline đề xuất
    edit     : đổi action thành override_value (delete / retain_legal_hold / escalate)
    reject   : như edit nếu có override_value, nếu không thì chuyển escalate
    escalate : giữ escalate (chuyển cấp cao hơn)
    skip     : chưa quyết, giữ nguyên
    """
    final = scored.copy()
    path = ctx.output_dir / "review_queue_reviewed.csv"
    if not path.exists():
        ctx.stats["n_reviewed"] = 0
        return final
    reviewed = load_review_decisions(path)
    ctx.stats["n_reviewed"] = len(reviewed)
    key = final.request_id + ":" + final.artefact_id
    for r in reviewed.itertuples(index=False):
        mask = key == r.item_id
        if not mask.any():
            raise ValueError(f"review: item_id {r.item_id} không có trong output pipeline")
        before = final.loc[mask, "action"].iloc[0]
        after = before
        ov = str(r.override_value).strip().lower()
        if r.reviewer_decision in {"edit", "reject"}:
            if ov and ov not in ACTIONS:
                raise ValueError(f"review: override_value '{ov}' không hợp lệ, phải thuộc {ACTIONS}")
            after = ov or "escalate"
        elif r.reviewer_decision == "escalate":
            after = "escalate"
        final.loc[mask, "action"] = after
        final.loc[mask, "reviewed_by"] = r.reviewer
        if after != before:
            final.loc[mask, "reason_code"] = f"HUMAN_{r.reviewer_decision.upper()}"
        ctx.audit.log(actor=r.reviewer, action=f"review:{r.reviewer_decision}", item_id=r.item_id.split(":", 1)[1],
                      before=before, after=after, reason=r.review_note, request_id=r.item_id.split(":", 1)[0])
    return final


# ---------------------------------------------------------------- 05 decide (+ dry-run, mock delete, evidence)
def execute(ctx: RunContext, final: pd.DataFrame) -> None:
    dry_run = bool(ctx.param("dry_run", True))
    plan = final[["request_id", "artefact_id", "type", "uri", "action", "reason_code", "legal_hold"]].copy()
    plan["state_before"] = "present"
    plan["state_after"] = plan.action.map({"delete": "deleted", "retain_legal_hold": "retained_until_hold_release",
                                           "escalate": "pending_human"})
    plan.to_csv(ctx.out("dry_run_plan.csv"), index=False)
    for r in final.itertuples(index=False):
        ctx.audit.log(actor="pipeline", action=("dry_run:" if dry_run else "") + r.action, item_id=r.artefact_id,
                      reason=r.reason_code, request_id=r.request_id, rule=r.rule, legal_hold=r.legal_hold)
    if not dry_run:
        dels = final[final.action == "delete"][["request_id", "artefact_id", "type", "uri"]].copy()
        dels["tombstone"] = "mock://tombstone/" + dels.artefact_id
        dels["note"] = "MOCK delete — không xoá dữ liệu thật"
        dels.to_csv(ctx.out("deletion_evidence.csv"), index=False)
    summary = (final.pivot_table(index="request_id", columns="action", values="artefact_id", aggfunc="count", fill_value=0)
               .reindex(columns=list(ACTIONS), fill_value=0).reset_index())
    summary = summary.merge(final.groupby("request_id").deadline.first().reset_index(), on="request_id")
    summary["status"] = summary.apply(lambda s: "DONE" if s.escalate == 0 and s.retain_legal_hold == 0
                                      else ("PENDING_REVIEW" if s.escalate else "PARTIAL_HOLD"), axis=1)
    summary.to_csv(ctx.out("request_summary.csv"), index=False)
    ctx.stats.update({"dry_run": dry_run, **{f"n_{a}": int((final.action == a).sum()) for a in ACTIONS}})


def decide(ctx: RunContext, final: pd.DataFrame) -> Decision:
    n_esc = int((final.action == "escalate").sum())
    n_hold = int((final.action == "retain_legal_hold").sum())
    n_del = int((final.action == "delete").sum())
    owner = ctx.config.get("owner", "TODO-owner")
    metrics = {"n_delete": n_del, "n_retain_legal_hold": n_hold, "n_escalate": n_esc, "n_pairs": len(final)}
    evidence = [str(ctx.out(f)) for f in ("actions.csv", "dry_run_plan.csv", "audit_log.jsonl", "request_summary.csv")]
    exc = final[final.action != "delete"]
    n_unreviewed = int((exc.reviewed_by.fillna("") == "").sum())
    metrics["n_exceptions_unreviewed"] = n_unreviewed
    if n_unreviewed:
        return Decision(status="HOLD", reason_code="EXCEPTIONS_PENDING_REVIEW",
                        reason=f"{n_unreviewed}/{len(exc)} ngoại lệ chưa có người duyệt; chạy tools.review_t08 rồi chạy lại",
                        owner=owner, scope="t08:all_requests", evidence=evidence, metrics=metrics)
    if n_esc:
        return Decision(status="HOLD", reason_code="ESCALATED_AWAITING_RESOLUTION",
                        reason=f"Đã duyệt hết ngoại lệ; xoá {n_del}, giữ {n_hold} theo legal hold, "
                               f"{n_esc} cặp đã chuyển cấp (quyền/nguồn gốc/nhiều subject) chờ xử lý trước khi đóng request",
                        owner=owner, scope="t08:all_requests", evidence=evidence, metrics=metrics)
    return Decision(status="GO", reason_code="ALL_RESOLVED",
                    reason=f"Xoá {n_del} artefact; {n_hold} giữ theo legal hold và hẹn xoá khi hết hold",
                    owner=owner, scope="t08:all_requests", evidence=evidence, metrics=metrics)


def run(ctx: RunContext) -> None:
    spec = get_track(ctx.track)
    if spec.track != "t08":
        raise NotImplementedError(f"pipeline này chỉ cài cho t08, không phải {spec.track}")
    data = load(ctx)
    scored = process(ctx, data)
    ctx.stats["n_items"] = len(scored)
    queue = rank(ctx, scored)
    final = review(ctx, scored, queue)
    final.to_csv(ctx.out(spec.pred_file), index=False)
    execute(ctx, final)
    write_decision(decide(ctx, final), ctx.out("decision.json"), ctx.out("decision_log.csv"))
