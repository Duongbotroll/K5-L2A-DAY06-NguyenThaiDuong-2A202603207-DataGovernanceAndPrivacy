# Metric contract — T08 Retention & Delete Request Simulator

> Chốt trước khi viết code và trước khi chạy eval. Không đổi policy/thứ tự ưu tiên sau khi thấy kết quả.

| Mục | Khai báo |
|---|---|
| Track | T08 · Retention & Delete Request Simulator |
| Primary metric | Deletion Completeness |
| Tăng tốt hay giảm tốt? | higher |
| Đơn vị đánh giá | cặp (request_id, artefact_id) |
| Công thức | #cặp expected=delete mà pred=delete / #cặp expected=delete |
| Cách ghép pred ↔ GT | khớp chính xác theo (request_id, artefact_id); cặp thiếu trong pred = không xoá |
| Candidate pool cố định | 212 artefact trong `data_graph.json` (mock-graph-1) × 10 request trong `requests.json` |
| Review budget B / K | không giới hạn: mọi dòng `escalate` và `retain_legal_hold` đều vào review queue |
| Seed | 42 |
| Threshold policy | không có threshold học từ dữ liệu; policy là luật cố định (bên dưới), chốt trước khi code |
| Eval split | toàn bộ 10 request (không có split dev/eval; không tune theo kết quả) |
| Chỉ số lỗi xấu | **False-delete count (mục tiêu 0)** = xoá nhầm artefact ngoại lệ + xoá ngoài phạm vi request |
| Metric phụ | Exception handling accuracy; Audit trace completeness (mọi action có dòng log, item_id = artefact_id); runtime |
| Slices sẽ báo cáo | theo `expected_action` (delete / retain_legal_hold / escalate); theo `type` artefact (raw, backup, frame, face_crop, embedding, annotation, training_export) |
| Độ bất định khi N nhỏ | Wilson 95% CI cho Deletion Completeness và Exception accuracy |
| Idempotency | chạy 2 lần cùng seed → `actions.csv` giống hệt từng byte (có test) |
| Ngày giờ chốt + người chốt | 2026-11-14 · Nguyễn Thái Dương |

## Policy (thứ tự ưu tiên, luật đầu tiên khớp sẽ quyết định)

**Phạm vi của 1 request (subject S):** mọi artefact có S trong `subject_ids`. Lineage (BFS qua `parent_ids`) dùng để
(a) kiểm tra legal hold kế thừa, (b) làm evidence. Artefact không chứa S thì **không** ghi vào output (tránh xoá ngoài phạm vi).

| # | Điều kiện | action | reason_code |
|---|---|---|---|
| R0 | request chưa xác minh danh tính (`identity_verified=false`) | escalate | IDENTITY_NOT_VERIFIED |
| R1 | artefact hoặc **bất kỳ tổ tiên nào** có `legal_hold` | retain_legal_hold | LEGAL_HOLD / LEGAL_HOLD_INHERITED |
| R2 | `acl` không chứa `data-platform` (hệ thống không có quyền xoá) | escalate | NO_PERMISSION |
| R3 | `origin_known = false` | escalate | UNKNOWN_ORIGIN |
| R4 | `subject_ids` có > 1 người | escalate | MULTI_SUBJECT |
| R5 | còn lại | delete | SUBJECT_REQUEST |

- Legal hold lan xuống mọi hậu duệ (backup là bản sao bằng chứng; derived trích từ bằng chứng). Dòng retain ghi mã hold và hẹn xoá lại khi hold hết hạn.
- Escalate ≠ từ chối: chuyển người duyệt (DPO mock) quyết; mọi quyết định ghi vào `audit_log.jsonl`.
- Giả định cần DPO/legal xác nhận: căn cứ ngoại lệ quyền xoá (Luật 91/2025, GDPR Art. 17(3)); hold có áp cho derived không; xử lý artefact nhiều subject (xoá phần của S hay giữ). Không tuyên bố tuân thủ luật từ luật tự động này.

## Baseline (để so sánh)

Xoá raw_video có `filename` chứa subject_id; không duyệt derived/backup/embedding; không kiểm hold/quyền.
Cùng pool, cùng seed 42.
