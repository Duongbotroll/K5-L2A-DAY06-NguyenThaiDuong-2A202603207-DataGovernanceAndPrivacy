"""T08 · policy precedence (chốt trong reports/metric_contract.md trước khi code).

Luật đầu tiên khớp sẽ quyết định:
  R0 identity chưa xác minh      -> escalate           IDENTITY_NOT_VERIFIED
  R1 legal hold (trực tiếp/kế thừa) -> retain_legal_hold LEGAL_HOLD / LEGAL_HOLD_INHERITED
  R2 acl không có executor        -> escalate           NO_PERMISSION
  R3 origin_known = false         -> escalate           UNKNOWN_ORIGIN
  R4 > 1 subject                  -> escalate           MULTI_SUBJECT
  R5 còn lại                      -> delete             SUBJECT_REQUEST
"""
from __future__ import annotations

ACTIONS = ("delete", "retain_legal_hold", "escalate")
EXECUTOR = "data-platform"   # hệ thống xoá chỉ có quyền trên artefact mà acl chứa role này


def decide(artefact: dict, request: dict, held: dict[str, str], executor: str = EXECUTOR) -> tuple[str, str, str]:
    """Trả (action, reason_code, rule_id) cho một cặp (request, artefact)."""
    aid = artefact["artefact_id"]
    if not request.get("identity_verified", True):
        return "escalate", "IDENTITY_NOT_VERIFIED", "R0"
    if aid in held:
        code = "LEGAL_HOLD" if artefact.get("legal_hold") else "LEGAL_HOLD_INHERITED"
        return "retain_legal_hold", code, "R1"
    if executor not in (artefact.get("acl") or []):
        return "escalate", "NO_PERMISSION", "R2"
    if not artefact.get("origin_known", True):
        return "escalate", "UNKNOWN_ORIGIN", "R3"
    if len(artefact.get("subject_ids") or []) > 1:
        return "escalate", "MULTI_SUBJECT", "R4"
    return "delete", "SUBJECT_REQUEST", "R5"
