"""Công cụ review T08 trong terminal (human-in-the-loop).

Đọc out/poc/review_queue.csv (+ actions.csv để hiện ngữ cảnh), hỏi người duyệt từng dòng,
ghi out/poc/review_queue_reviewed.csv. Sau đó chạy lại `make run TRACK=t08` để áp quyết định + audit log.

    python -m tools.review_t08                 # mặc định out/poc
    python -m tools.review_t08 --out out/poc

Phím: Enter/y = approve · e = edit (đổi action) · x = escalate · s = skip
      a = approve TẤT CẢ dòng còn lại có cùng reason_code · q = lưu và thoát
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ACTIONS = {"d": "delete", "r": "retain_legal_hold", "x": "escalate"}
HINT = {
    "LEGAL_HOLD": "Artefact đang bị legal hold trực tiếp → thường approve (giữ, hẹn xoá khi hết hold).",
    "LEGAL_HOLD_INHERITED": "Thừa hưởng hold từ tổ tiên → approve nếu đồng ý hold lan xuống derived.",
    "MULTI_SUBJECT": "Chứa dữ liệu của người khác → giữ escalate (cần gỡ riêng phần của subject) hoặc edit.",
    "UNKNOWN_ORIGIN": "Không rõ nguồn gốc → giữ escalate, cần xác minh trước khi xoá.",
    "NO_PERMISSION": "Hệ thống không có quyền (ACL vendor) → giữ escalate, gửi yêu cầu xoá tới bên giữ dữ liệu.",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/poc")
    a = ap.parse_args(argv)
    out = Path(a.out)
    qp, rp = out / "review_queue.csv", out / "review_queue_reviewed.csv"
    if not qp.exists():
        print(f"Không thấy {qp}. Chạy `make run TRACK=t08` trước.")
        return 2
    q = pd.read_csv(rp if rp.exists() else qp, dtype=str).fillna("")
    acts = pd.read_csv(out / "actions.csv", dtype=str).fillna("")
    ctx = {f"{r.request_id}:{r.artefact_id}": r for r in acts.itertuples()}

    reviewer = input("Tên người duyệt (vd: Nguyễn Thái Dương - DPO mock): ").strip()
    if not reviewer:
        print("Bắt buộc có tên người duyệt.")
        return 2
    todo = [i for i in q.index if q.at[i, "reviewer_decision"] == ""]
    print(f"\n{len(q)} dòng trong queue, {len(todo)} dòng chưa duyệt.\n")

    def set_row(i, decision, override="", note=""):
        q.loc[i, ["reviewer", "reviewer_decision", "override_value", "review_note", "reviewed_at"]] = \
            [reviewer, decision, override, note, now()]

    for n, i in enumerate(todo, 1):
        if q.at[i, "reviewer_decision"]:      # đã duyệt hàng loạt bằng phím a
            continue
        row, c = q.loc[i], ctx.get(q.at[i, "item_id"])
        print("-" * 72)
        print(f"[{n}/{len(todo)}] {row.item_id}   type={row.slice}   đề xuất: {row.suggested_action}   ({row.reason})")
        if c is not None:
            print(f"   subjects={c.subject_ids}   legal_hold={c.legal_hold or '-'}   rule={c.rule}   uri={c.uri}")
        print(f"   gợi ý: {HINT.get(row.reason, '')}")
        while True:
            k = input("   [Enter]approve  e=edit  x=escalate  s=skip  a=approve-cùng-reason  q=lưu&thoát > ").strip().lower()
            if k in ("", "y"):
                set_row(i, "approve")
            elif k == "e":
                v = input("   đổi thành d=delete / r=retain_legal_hold / x=escalate > ").strip().lower()
                if v not in ACTIONS:
                    print("   giá trị không hợp lệ"); continue
                set_row(i, "edit", ACTIONS[v], input("   lý do (bắt buộc): ").strip() or "edit by reviewer")
            elif k == "x":
                set_row(i, "escalate", note=input("   ghi chú: ").strip())
            elif k == "s":
                pass
            elif k == "a":
                same = [j for j in q.index if q.at[j, "reason"] == row.reason and q.at[j, "reviewer_decision"] == ""]
                note = input(f"   ghi chú chung cho {len(same)} dòng {row.reason}: ").strip()
                for j in same:
                    set_row(j, "approve", note=note)
                print(f"   đã approve {len(same)} dòng {row.reason}")
            elif k == "q":
                break
            else:
                print("   phím không hợp lệ"); continue
            break
        if k == "q":
            break

    q.to_csv(rp, index=False)
    done = int((q.reviewer_decision != "").sum())
    print(f"\nĐã lưu {rp} ({done}/{len(q)} dòng có quyết định).")
    print("Bước tiếp: make run TRACK=t08   (áp quyết định + ghi audit_log.jsonl)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
