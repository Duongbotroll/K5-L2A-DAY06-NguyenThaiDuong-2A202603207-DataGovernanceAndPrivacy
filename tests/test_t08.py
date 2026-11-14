"""Tests T08 (Nguyễn Thái Dương): success, idempotency, exception, scope, failure."""
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from src import main as runner
from src.t08.lineage import held_by, load_graph, scope_for_subject
from src.t08.policy import decide

FIX = Path("fixtures/t08_deletion")


def _run(out: Path, inp: Path = FIX, pipeline: str = "src.pipeline") -> int:
    return runner.main(["--track", "t08", "--input", str(inp), "--pipeline", pipeline,
                        "--output", str(out), "--offline", "--seed", "42"])


@pytest.fixture(scope="module")
def poc(tmp_path_factory):
    out = tmp_path_factory.mktemp("poc")
    assert _run(out) == 0
    return out, pd.read_csv(out / "actions.csv")


def test_success_end_to_end(poc):
    out, df = poc
    for f in ["actions.csv", "review_queue.csv", "audit_log.jsonl", "dry_run_plan.csv",
              "request_summary.csv", "decision.json", "decision_log.csv"]:
        assert (out / f).exists(), f
    assert set(df.action) <= {"delete", "retain_legal_hold", "escalate"}
    assert not df.duplicated(["request_id", "artefact_id"]).any()
    assert df.request_id.nunique() == 10


def test_idempotent_two_runs(tmp_path):
    """Đề bắt buộc: chạy 2 lần phải ra cùng kết quả."""
    assert _run(tmp_path / "r1") == 0
    assert _run(tmp_path / "r2") == 0
    assert (tmp_path / "r1/actions.csv").read_bytes() == (tmp_path / "r2/actions.csv").read_bytes()


def test_legal_hold_never_deleted(poc):
    _, df = poc
    held = held_by(load_graph(FIX / "data_graph.json"))
    rows = df[df.artefact_id.isin(held)]
    assert len(rows) > 0
    assert (rows.action == "retain_legal_hold").all()
    assert set(df[df.artefact_id.isin(["a0043", "a0099"])].action) == {"retain_legal_hold"}


def test_no_delete_outside_request_scope(poc):
    _, df = poc
    arts = {a["artefact_id"]: a for a in load_graph(FIX / "data_graph.json")}
    subj = {r["request_id"]: r["subject_id"] for r in json.loads((FIX / "requests.json").read_text())}
    for r in df.itertuples():
        assert subj[r.request_id] in arts[r.artefact_id]["subject_ids"], (r.request_id, r.artefact_id)


def test_exceptions_escalated(poc):
    _, df = poc
    act = dict(zip(df.request_id + ":" + df.artefact_id, df.action))
    assert act["DR-001:a0011"] == "escalate"      # nhiều subject + liên kết chéo (cha thuộc subj_00)
    assert act["DR-004:a0075"] == "escalate"      # origin không rõ
    assert act["DR-008:a0156"] == "escalate"      # acl vendor-x, không có quyền


def test_cross_linked_artefact_in_scope():
    """a0011 có cha là raw của subj_00 → BFS từ raw subj_01 sẽ bỏ sót; tìm theo subject_ids thì không."""
    assert "a0011" in scope_for_subject("subj_01", load_graph(FIX / "data_graph.json"))


def test_policy_precedence_hold_beats_multi_subject():
    a = {"artefact_id": "x", "legal_hold": None, "acl": ["data-platform"], "origin_known": False,
         "subject_ids": ["s1", "s2"]}
    assert decide(a, {"identity_verified": True}, {"x": "LH-1"})[0] == "retain_legal_hold"
    assert decide(a, {"identity_verified": True}, {})[1] == "UNKNOWN_ORIGIN"
    assert decide(a, {"identity_verified": False}, {})[1] == "IDENTITY_NOT_VERIFIED"


def test_baseline_misses_derived_and_deletes_held(tmp_path):
    assert _run(tmp_path, pipeline="src.baseline_t08") == 0
    df = pd.read_csv(tmp_path / "actions.csv")
    assert (df.action == "delete").all() and len(df) == 10
    assert "a0043" in set(df.artefact_id)            # failure mode: xoá nhầm raw đang legal hold


def test_corrupt_json_fails_clearly(tmp_path):
    bad = tmp_path / "fx"
    shutil.copytree(FIX, bad)
    p = bad / "data_graph.json"
    p.write_text(p.read_text()[: len(p.read_text()) // 2])
    assert _run(tmp_path / "out", inp=bad) == 2      # manifest hash lệch / JSON hỏng → exit 2, không im lặng


def test_review_override_applied_and_audited(tmp_path):
    out = tmp_path / "o"
    assert _run(out) == 0
    q = pd.read_csv(out / "review_queue.csv", dtype=str).fillna("")
    i = q.index[q.item_id == "DR-001:a0011"][0]
    q.loc[i, ["reviewer", "reviewer_decision", "override_value", "review_note"]] = [
        "Nguyễn Thái Dương", "edit", "retain_legal_hold", "test override"]
    q.to_csv(out / "review_queue_reviewed.csv", index=False)
    assert _run(out) == 0
    df = pd.read_csv(out / "actions.csv")
    row = df[(df.request_id == "DR-001") & (df.artefact_id == "a0011")].iloc[0]
    assert row.action == "retain_legal_hold" and row.reviewed_by == "Nguyễn Thái Dương"
    log = [json.loads(l) for l in (out / "audit_log.jsonl").read_text().splitlines()]
    assert any(e["action"] == "review:edit" and e["item_id"] == "a0011" for e in log)
