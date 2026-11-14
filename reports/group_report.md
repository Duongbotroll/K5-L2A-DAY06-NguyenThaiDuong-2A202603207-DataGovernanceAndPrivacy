# Report — Day 06 Data Lab (Field-to-Release PoC) · T08 · làm cá nhân

> Mọi con số lấy từ file do script sinh ra: `reports/self_eval_t08.md|json` (`python -m tools.self_eval_t08`),
> `out/poc/run_info.json`, `out/poc/decision.json`. Repo học viên không có `gt/`, nên metric chính thức
> (`python -m src.evaluate`) chỉ chạy được khi giảng viên cài overlay; xem mục 05.

## 00 · Header

| Mục | Giá trị |
|---|---|
| Group ID | G00-solo-2A202603207 (làm cá nhân) |
| Challenge | T08 · Retention & Delete Request Simulator |
| Thành viên + vai trò | Nguyễn Thái Dương (2A202603207) — toàn bộ: integrator, data/baseline, algorithm, tests, review (DPO mock), report |
| Git URL | https://github.com/Duongbotroll/K5-L2A-DAY06-NguyenThaiDuong-2A202603207-DataGovernanceAndPrivacy |
| Tag `demo-180m` (commit) | `aaf9b29` |
| Tag `final-24h` (commit) | ____ (điền sau `make tag-final`) |
| Deadline (giờ VN) | ____ |

## 01 · Problem statement

- **Ai bị ảnh hưởng:** chủ thể dữ liệu (người lái/người xuất hiện trong video) gửi yêu cầu xoá; công ty chịu rủi ro pháp lý nếu
  (a) xoá thiếu — còn backup/embedding định danh sau khi báo "đã xoá", hoặc (b) xoá nhầm — huỷ dữ liệu đang bị legal hold
  hoặc dữ liệu của người khác.
- **Điểm nghẽn:** dữ liệu một người bị nhân bản qua lineage raw → frame → face_crop → embedding / annotation, cộng backup và
  training_export gộp nhiều người. Xoá theo filename chỉ chạm raw.
- **Đầu vào → đầu ra:** `requests.json` (10 yêu cầu) + `data_graph.json` (212 artefact) → `actions.csv`
  (`request_id, artefact_id, action ∈ {delete, retain_legal_hold, escalate}`) + `audit_log.jsonl` + `deletion_evidence.csv`.
- **Tiêu chí GO / HOLD (chốt trước eval, `src/pipeline.py::decide`):** HOLD nếu còn ngoại lệ chưa duyệt
  (`EXCEPTIONS_PENDING_REVIEW`) hoặc còn cặp đã chuyển cấp chưa giải quyết (`ESCALATED_AWAITING_RESOLUTION`);
  GO khi mọi cặp là delete hoặc retain có mã hold (`ALL_RESOLVED`).
- **Giả định cần DPO/legal xác nhận:** legal hold lan xuống mọi hậu duệ; artefact nhiều subject không tự xoá; ACL của vendor
  nghĩa là hệ thống không có quyền xoá. Không tuyên bố tuân thủ GDPR / Luật 91/2025 từ luật tự động.

## 02 · Data & provenance

| Split | N | Nguồn | License | Synthetic? |
|---|---|---|---|---|
| toàn bộ (không chia dev/eval) | 10 request × 212 artefact → 158 cặp in-scope | `fixtures/t08_deletion` (mock-graph-1) | CC0 (repo khoá học) | Có — mock, không có dữ liệu thật |

- **Schema:** artefact có `type, subject_ids, parent_ids, uri, owner, acl, legal_hold, origin_known`. Phân bố type:
  frame 45, face_crop 45, embedding 45, annotation 45, raw_video 15, backup 15, training_export 2.
- **Case đặc biệt tìm được trong dữ liệu:** 2 raw bị legal hold (`a0043` LH-2026-03, `a0099` LH-2026-07);
  3 embedding không rõ nguồn (`a0075, a0079, a0083`); 1 backup ACL `vendor-x` (`a0156`); 8 frame/annotation 2 subject;
  2 training_export 9–10 subject; liên kết chéo `a0011` (có subj_01 nhưng cha `a0001` thuộc subj_00).
- **Seed:** 42. `manifest.csv` verified (sha256): có — `load()` gọi `verify_manifest`, `make preflight` báo hash khớp.
- Không dùng dữ liệu thật (đề cấm xoá dữ liệu thực trong lab).

## 03 · Research & design

- **Kỹ thuật:** duyệt đồ thị BFS qua `parent_ids` để lan legal hold xuống hậu duệ; phạm vi request xác định theo
  `subject_ids` (không chỉ BFS từ raw) để bắt artefact liên kết chéo; policy precedence cố định
  legal hold > quyền > nguồn gốc > nhiều subject > delete (gợi ý trong đề, mục 8).
- **Tham chiếu:** GDPR Art. 17(3) (ngoại lệ quyền xoá, trong đó có nghĩa vụ pháp lý); Luật 91/2025 về bảo vệ dữ liệu cá nhân
  (ngoại lệ quyền xoá) — chỉ dùng làm căn cứ giả định, cần legal xác nhận số điều; California DROP (một yêu cầu xoá gửi tới
  nhiều bên) — lý do coi backup ở vendor là bên phải nhận yêu cầu riêng. (Ngày xem: ____ — điền khi đối chiếu văn bản gốc.)
- **Data flow:**
  `requests + graph → (01) load + verify manifest → (02) scope theo subject + held_by (BFS) → policy R0–R5 →
  (03) review queue = mọi ngoại lệ → (04) người duyệt (tools.review_t08) → override + audit →
  (05) dry_run_plan → mock delete + deletion_evidence → request_summary → decision GO/HOLD`
- **Thành phần offline:** không có model; chỉ pandas + json. Không gọi network (`--offline`).
- **Trade-off:** chọn bảo thủ (giữ/escalate khi nghi ngờ) vì false-delete không khôi phục được, đổi lại xoá chậm hơn
  và có over-retention (xem failure case 2).

## 04 · Baseline vs PoC

- **Baseline** (`src/baseline_t08.py`, commit `932790e`): xoá raw_video có `filename` chứa subject_id; không duyệt derived,
  không kiểm hold/quyền.
- **PoC** (`src/pipeline.py` + `src/t08/`, commit `2384b6b`, review `713688a`/`aaf9b29`): như mục 03.
- Cùng pool 10 request × 212 artefact, cùng seed 42, cùng lệnh `src.main --offline`.

**Bảng 1 · Baseline vs PoC (self-eval không GT, `reports/self_eval_t08.md`)**

| Metric (unit) | Baseline | PoC | Δ & chú thích |
|---|---|---|---|
| Delete coverage (cặp sạch được xoá / cặp sạch) | 0.0784 (8/102), CI95 [0.040, 0.147] | 1.0 (102/102), CI95 [0.964, 1.0] | +0.92; higher tốt. PoC = 1.0 một phần do cùng định nghĩa "sạch" với policy (xem 05) |
| held_deleted (xoá nhầm artefact legal hold) | **2** | 0 | baseline xoá `a0043`, `a0099` → vi phạm hold |
| copies_left (backup/embedding/face_crop sạch còn sót) | 52/52 | 0/52 | đúng failure mode "chỉ xoá raw, giữ bản sao" |
| out_of_scope_del / flagged_deleted | 0 / 0 | 0 / 0 | lower tốt |
| Scope coverage (cặp in-scope có action) | 0.0633 | 1.0 | |
| Audit completeness | 1.0 | 1.0 | mọi action có dòng log |
| Runtime (158 cặp) | ____ s | ____ s | lấy từ `run_info.json` trên Codespace |

## 05 · Evaluation protocol

- **Metric chính thức:** Deletion Completeness = #cặp `expected=delete` mà pred = delete / #cặp `expected=delete`;
  phụ: False-delete count (ngoại lệ bị xoá + xoá ngoài phạm vi), Exception accuracy, Audit completeness
  (`src/metrics/tracks.py::eval_t08`, khai báo tại `reports/metric_contract.md`).
- **Lệnh:** `python -m src.evaluate --track t08 --pred out/poc/actions.csv --run-name poc --out reports/metrics_poc.json`
  — repo học viên không có `gt/` nên trả exit 2; giảng viên chạy khi chấm.
- **Self-eval thay thế:** `held_deleted`, `out_of_scope_del`, `flagged_deleted`, `copies_left` là sự thật khách quan đọc từ
  graph, không phụ thuộc policy. `delete_coverage` của PoC thì **có tính vòng** (cùng định nghĩa "sạch" với luật R1–R5),
  nên chỉ chứng minh pipeline thực thi đúng policy, không chứng minh policy khớp GT. Rủi ro lớn nhất khi chấm GT là
  giả định hold lan xuống derived: nếu GT coi derived là `delete`, PoC mất 38 cặp completeness nhưng vẫn 0 false-delete.
- **Threshold / budget:** không có threshold học; review budget không giới hạn (mọi ngoại lệ, 56 dòng). Chốt 2026-11-14.
- **Độ bất định:** Wilson 95% CI (bảng 1). N nhỏ (10 request) → không ngoại suy sang dữ liệu thật.

## 06 · Result slices

| Slice (type, PoC) | N | delete | retain | escalate |
|---|---|---|---|---|
| raw_video | 10 | 8 | 2 | 0 |
| backup | 10 | 7 | 2 | 1 |
| frame | 33 | 21 | 6 | 6 |
| face_crop | 30 | 24 | 6 | 0 |
| embedding | 30 | 21 | 7 | 2 |
| annotation | 33 | 21 | 6 | 6 |
| training_export | 12 | 0 | 12 | 0 |

(Sau review: `a0075` đổi escalate → retain, nên embedding retain = 7.)

- **Failure case 1 — baseline để sót bản sao và xoá nhầm legal hold.** DR-001 (subj_01): baseline chỉ xoá raw `a0015`, để
  nguyên backup `a0016`, 3 face_crop `a0018, a0022, a0026` và 3 embedding định danh `a0019, a0023, a0027` — báo "đã xoá"
  nhưng dữ liệu nhận diện vẫn còn. Với DR-002 (subj_03) và DR-005 (subj_07), baseline xoá luôn raw `a0043`, `a0099` đang
  legal hold. Root cause: khớp theo filename, không duyệt lineage, không đọc `legal_hold`. Toàn bộ 10 request: 52/52 bản sao
  sạch còn sót, 2 artefact bị hold bị xoá.
- **Failure case 2 — PoC over-retention qua training_export.** `a0211` (10 subject) là hậu duệ của raw bị hold `a0043`, nên
  R1 đánh dấu `retain_legal_hold` cho cả 7 request khác (DR-003, 004, 005, 007, 008, 009, 010) dù hold LH-2026-03 chỉ liên quan
  subj_03. DR-010 (subj_14) vì vậy không thể đóng (PARTIAL_HOLD). Root cause: hold lan theo artefact, không theo subject;
  export gộp nhiều người kế thừa hold của một người. Hướng sửa: tách export theo subject (xoá dòng của subject khỏi export)
  hoặc giới hạn hold theo phạm vi vụ việc — cần legal xác nhận.
- **Case đã xử lý đúng — liên kết chéo `a0011`:** frame có subj_00 + subj_01 nhưng cha thuộc subj_00. Nếu BFS chỉ từ raw
  của subj_01 thì bỏ sót; PoC tìm theo `subject_ids` nên bắt được và escalate (MULTI_SUBJECT). Có test `test_cross_linked_artefact_in_scope`.
- **Latency:** ____ s / 158 cặp trên GitHub Codespaces (2 vCPU), Python 3.13 (lấy từ `out/poc/run_info.json`).

## 07 · Human & decision

- **Review queue:** `out/poc/review_queue.csv` = mọi cặp không phải delete (56 dòng: 40 retain + 16 escalate), sắp theo
  escalate trước. Công cụ `python -m tools.review_t08` hiện ngữ cảnh (subject, hold, rule, uri) và gợi ý; bản đã duyệt lưu ở
  `reports/review_queue.csv`.
- **Override + audit:** người duyệt "Nguyễn Thái Dương - DPO mock" approve 55 dòng, **edit 1 dòng** (`DR-004:a0075`
  escalate → retain_legal_hold, lý do "chờ xác minh nguồn gốc embedding, chưa xoá"). `review()` áp quyết định, đổi
  `reason_code` thành `HUMAN_EDIT`, ghi `review:<decision>` vào `audit_log.jsonl` (append-only). Ghi chú review bị lệch nhóm ở
  lần đầu đã được sửa (commit `aaf9b29`); log giữ cả bản cũ và bản sửa.
- **Decision:** `HOLD · ESCALATED_AWAITING_RESOLUTION · owner Nguyễn Thái Dương (DPO mock)` — xoá 102, giữ 41 theo legal hold,
  15 cặp đã chuyển cấp chờ xử lý (`reports/decision_log.csv`).
- **Khi nào HOLD thay vì tự động release:** còn ngoại lệ chưa có người duyệt; còn artefact ngoài quyền (vendor) chưa có
  xác nhận xoá; còn artefact nhiều subject chưa tách. Retain do legal hold không chặn GO nhưng phải hẹn xoá khi hết hold.

## 08 · Reproduce & tests

```bash
make setup
python -m src.main --track t08 --pipeline src.baseline_t08 --output out/baseline --run-name baseline --offline --seed 42
make run TRACK=t08                      # PoC; nếu có out/poc/review_queue_reviewed.csv thì áp review
python -m tools.review_t08              # (tuỳ chọn) duyệt ngoại lệ, rồi make run lại
python -m tools.self_eval_t08           # -> reports/self_eval_t08.md|json
pytest -q
```

- `pytest -q`: 0 failed; 10 test của T08 trong `tests/test_t08.py` (success E2E, idempotency 2 lần, legal hold không bị xoá,
  không xoá ngoài phạm vi, escalate đúng 3 loại ngoại lệ, liên kết chéo, precedence, baseline xoá nhầm hold,
  JSON hỏng → exit 2, override của reviewer được áp + audit).
- Máy: GitHub Codespaces, Linux, Python 3.13 · git sha: xem `run_info.json`.

## 09 · Limitations & ethics

- Dữ liệu mock; không xoá dữ liệu thật (`deletion_evidence.csv` chỉ ghi tombstone `mock://`).
- Giả định hold lan xuống derived và cách xử lý multi-subject chưa được legal xác nhận; nếu sai, completeness thay đổi
  (mục 05). Không tuyên bố "đạt GDPR / Luật 91/2025".
- Scale 10×: thuật toán O(request × artefact) cho scope, BFS O(cạnh) — đủ nhanh; nút thắt sẽ là review thủ công
  (56 ngoại lệ / 10 request) → cần ưu tiên theo deadline (SLA) và gom duyệt theo nhóm lý do.
- Cải tiến (mốc +24h): SLA dashboard theo `deadline` trong `request_summary.csv`; resume khi job xoá bị ngắt
  (ghi checkpoint các artefact đã xoá, chạy lại bỏ qua); tách training_export theo subject.

## 10 · Contribution

**Bảng 2 · Individual contribution evidence** (đối chiếu `git shortlog -sne --all` và `reports/team_contributions.csv`)

| Học viên | Git author | Module / vai trò | Commit SHA | Trình bày? |
|---|---|---|---|---|
| Nguyễn Thái Dương | Nguyễn Thái Dương | toàn bộ (làm cá nhân) | `de6930f` contract · `932790e` baseline+lineage/policy · `2384b6b` pipeline+tests · `713688a` review tool + evidence · `aaf9b29` sửa ghi chú review | Có |

- **Sử dụng AI:** có dùng trợ lý AI (Claude) hỗ trợ viết code, test và bản nháp report; tôi chạy, kiểm tra, review ngoại lệ và
  quyết định policy. (Sửa câu này theo quy định của lớp.)

## 11 · References

| URL | Ngày xem | Ý nghĩa |
|---|---|---|
| GDPR Art. 17 — https://gdpr-info.eu/art-17-gdpr/ | ____ | Quyền xoá và ngoại lệ (nghĩa vụ pháp lý, khiếu kiện) → căn cứ retain khi có legal hold |
| Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15 + Nghị định 356/2025 | ____ | Ngoại lệ quyền xoá theo luật VN — cần đối chiếu số điều với văn bản gốc |
| California DROP (CPPA) | ____ | Một yêu cầu xoá phải tới mọi bên giữ dữ liệu → backup ở vendor cần yêu cầu riêng |

---

**Bảng 3 · Checklist chốt khi nộp**

- [x] Link repo và tag trong report; input không chứa PII thật.
- [x] 1 lệnh run, 1 lệnh evaluate, 1 lệnh tests; không download khi chạy.
- [x] Có baseline/PoC metrics (self-eval), 2 failure case, reviewer evidence, decision log.
- [x] License/source provenance, seed, offline; N = 158 cặp.
- [ ] Tag `final-24h` + điền runtime, ngày xem references.
