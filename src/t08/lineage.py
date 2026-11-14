"""T08 · đọc data graph + request, truy lineage (BFS qua parent_ids).

Không đọc fixtures/*/gt/. Mọi hàm là thuần (pure) để dễ test và idempotent.
"""
from __future__ import annotations

import json
from collections import defaultdict, deque
from pathlib import Path

REQUIRED_ARTEFACT_KEYS = {"artefact_id", "type", "subject_ids", "parent_ids", "acl", "legal_hold", "origin_known"}
REQUIRED_REQUEST_KEYS = {"request_id", "subject_id"}


def load_graph(path: Path) -> list[dict]:
    """Đọc data_graph.json; JSON hỏng / thiếu khoá / parent không tồn tại -> ValueError (exit 2)."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{path}: JSON hỏng ({e})") from e
    arts = doc.get("artefacts") if isinstance(doc, dict) else doc
    if not isinstance(arts, list) or not arts:
        raise ValueError(f"{path}: không có danh sách artefacts")
    ids = set()
    for a in arts:
        missing = REQUIRED_ARTEFACT_KEYS - set(a)
        if missing:
            raise ValueError(f"{path}: artefact {a.get('artefact_id')} thiếu khoá {sorted(missing)}")
        if a["artefact_id"] in ids:
            raise ValueError(f"{path}: artefact_id trùng {a['artefact_id']}")
        ids.add(a["artefact_id"])
    dangling = [(a["artefact_id"], p) for a in arts for p in a["parent_ids"] if p not in ids]
    if dangling:
        raise ValueError(f"{path}: parent_ids trỏ tới artefact không tồn tại: {dangling[:5]}")
    return arts


def load_requests(path: Path) -> list[dict]:
    try:
        reqs = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{path}: JSON hỏng ({e})") from e
    if not isinstance(reqs, list):
        raise ValueError(f"{path}: phải là danh sách request")
    seen = set()
    for r in reqs:
        missing = REQUIRED_REQUEST_KEYS - set(r)
        if missing:
            raise ValueError(f"{path}: request {r.get('request_id')} thiếu khoá {sorted(missing)}")
        if r["request_id"] in seen:
            raise ValueError(f"{path}: request_id trùng {r['request_id']}")
        seen.add(r["request_id"])
    return reqs


def children_index(arts: list[dict]) -> dict[str, list[str]]:
    ch: dict[str, list[str]] = defaultdict(list)
    for a in arts:
        for p in a["parent_ids"]:
            ch[p].append(a["artefact_id"])
    return ch


def descendants(start: list[str], ch: dict[str, list[str]]) -> set[str]:
    """BFS xuống mọi hậu duệ (không gồm chính start)."""
    out: set[str] = set()
    dq = deque(start)
    while dq:
        n = dq.popleft()
        for c in ch.get(n, []):
            if c not in out:
                out.add(c)
                dq.append(c)
    return out


def held_by(arts: list[dict]) -> dict[str, str]:
    """artefact_id -> mã legal hold (trực tiếp hoặc kế thừa từ tổ tiên). Hold lan xuống mọi hậu duệ."""
    ch = children_index(arts)
    held: dict[str, str] = {}
    for a in sorted(arts, key=lambda x: x["artefact_id"]):
        if a["legal_hold"]:
            held.setdefault(a["artefact_id"], a["legal_hold"])
            for d in sorted(descendants([a["artefact_id"]], ch)):
                held.setdefault(d, a["legal_hold"])
    return held


def scope_for_subject(subject_id: str, arts: list[dict]) -> list[str]:
    """Phạm vi request = mọi artefact có subject trong subject_ids.

    Tìm theo subject_ids (không chỉ BFS từ raw) để bắt cả artefact liên kết chéo, ví dụ
    frame nhiều subject có cha là raw của người khác. Hậu duệ không chứa subject thì
    nằm ngoài phạm vi (xoá chúng = false-delete).
    """
    return sorted(a["artefact_id"] for a in arts if subject_id in a["subject_ids"])
