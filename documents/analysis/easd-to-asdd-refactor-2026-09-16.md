# EASD → ASDD: what changed and why — 2026-09-16

Successor to [easd-folder-structure-audit-2026-09-15.md](easd-folder-structure-audit-2026-09-15.md).
Sections 5 and 6 of that audit are superseded: they proposed reshaping the EASD
catalogue around `module/capability` while keeping the database model. This
change removes the database model instead.

## Vấn đề

EASD giữ cùng một sự thật ở hai nơi — năm bảng `trace_*` và cây tài liệu
tracked — rồi bảo vệ cặp đó bằng hai ràng buộc:

1. **Hash binding.** Mỗi thao tác phải truyền lại đúng sha256 của trạng thái
   hiện tại: `expected_hash` khi accept, `trace_spec_hash`/`trace_plan_hash` khi
   delegate, `spec_hash` khi ghi evidence. ~12 chỗ ném `TraceConflict`.
2. **Session binding.** `trace_runs.session_id` là FK tới `chat_sessions` kèm
   unique index `uq_trace_runs_active_session`. Một chat ôm được đúng một Run;
   đổi chat phải `rebind_run_to_session(force=True)`. ~15 chỗ ném "belongs to
   another Coding session".

Cả hai tồn tại để quản lý sự bất đồng giữa hai bản sao. Người dùng gặp chúng như
lỗi không hành động được, và tài liệu mô tả không khớp code.

## Quyết định

Bỏ bản sao trong database. Một change là một thư mục Markdown trong repository:

- pha là trường `status` trong `proposal.md`;
- hợp đồng là delta ở `specs/<capability>/spec.md`;
- danh tính là tên thư mục.

Mô hình file theo [OpenSpec](https://github.com/Fission-AI/OpenSpec); vòng lặp
sáu pha và kỷ luật execution-log theo
[Agent-Driven Development](https://github.com/Pyro-IV/Agent-Driven-Development).
Rail điều hướng và các cổng duyệt của người dùng là phần EvoFlux giữ nguyên.

Tên phương pháp: **ASDD — Agent Specification-Driven Development**. Bỏ chữ
"Evo"; product surface là **Agent Spec-Driven**.

## Đã bỏ

| Thứ bị bỏ | Vì sao |
|---|---|
| `trace_runs`, `trace_spec_revisions`, `trace_plan_revisions`, `trace_evidence`, `trace_deviations` | bản sao thứ hai của thứ đã có trong repository |
| `content_hash`, `spec_hash`, `plan_hash`, `expected_hash` | ràng buộc tồn tại chỉ để đồng bộ bản sao đó |
| `TraceRun.session_id` + `uq_trace_runs_active_session` | trói một change vào một chat |
| `rebind_run_to_session`, `active_run_for_session` | chỉ cần thiết vì có ràng buộc trên |
| `easd_submit_specification`, `easd_submit_plan`, `easd_submit_review` | agent ghi Markdown bằng công cụ file thường |
| `/api/easd/*`, alias `/api/trace` | thay bằng `/api/asdd/*` định danh theo slug |
| `_outside_impact_targets` trong verification | impact trong ASDD là văn xuôi, không phải hợp đồng máy đọc |

`artifact_hash` trong `app/agent/verification.py` giữ lại: đó là khoá cache
content-addressed của kết quả verify, không ai phải truyền nó vào đâu.

## Đã mất — ghi nhận thẳng

1. **Không còn optimistic concurrency.** Hai agent ghi cùng một file đè nhau.
   Giảm thiểu bằng khoá theo repository (`asdd_runtime.py`) và bằng việc
   `git diff` luôn nhìn thấy được. Đây là cái giá của thiết kế, không phải sót.
2. **Không còn gate "thay đổi ngoài impact targets".** EASD chặn được vì spec có
   `impact_targets` typed. ASDD mô tả impact bằng văn xuôi trong `proposal.md`,
   nên không tái lập được mà không đưa lại contract typed.
3. **Run EASD cũ không migrate.** Trạng thái của chúng không có tương đương
   trong catalogue file-based. Migration `00000065` drop bảng; không backfill.

## Bốn migration bị rút

`00000055`, `00000060`, `00000061`, `00000062` chỉ tồn tại để dựng `trace_*` và
cột `delegation_tasks.trace_run_id`, nên bị xoá; chuỗi nối lại `00000054 →
00000063`.

Điều này **làm chết app** với database đang dừng đúng ở một trong bốn id đó:
Alembic không resolve được stamp không có file và startup hỏng — kiểm chứng
bằng `Can't locate revision identified by '00000062'`. Preflight còn báo sai
hướng ("newer than this build... install a newer version").

`schema_version.RETIRED_REVISIONS` ánh xạ bốn id đó về `00000054`, và
`repair_retired_revision()` dập stamp. Nó được gọi từ `app/migrations/env.py`
chứ không phải từ `app/api/app.py`: mọi đường migrate đều chui qua `env.py` —
auto-upgrade lúc server khởi động, `make migrate`, và `alembic upgrade head`
trần. Đặt ở chỗ khác thì còn ít nhất một đường vẫn chết, đã kiểm chứng đúng
trường hợp CLI.

An toàn vì `00000065` drop đúng những gì bốn revision đó tạo ra: phát lại từ
`00000054` cho ra cùng một schema. Test parametrize cả bốn id và **không** gọi
repair bằng tay, để bắt buộc đường tự động phải hoạt động.

## Cấu trúc đích

```text
<data_directory>/                     # .evoflux/asdd/config.json chỉ định, mặc định documents/asdd
├── project.md
├── specs/<capability>/spec.md
└── changes/
    ├── <change-id>/{proposal,design,tasks}.md
    │   ├── specs/<capability>/spec.md
    │   └── evidence/<id>.md
    └── archive/YYYY-MM-DD-<change-id>/
```

Vòng đời: `drafting → proposed → specifying → specified → [designing → designed]
→ tasking → tasked → implementing → verifying → ready → archived`.

Ánh xạ ADD sáu pha: SCOPE=proposal, FRAME=delta specs, CONSTRAIN=design+tasks,
EXECUTE=implementing, VERIFY=verifying, CONSOLIDATE=archive.

## Còn lại

- `documents/` của chính repo này vẫn có `analysis/`, `plans/`, `releases/`,
  `research/` ở gốc. Chúng là tài liệu người viết, không thuộc catalogue ASDD, và
  ở nguyên chỗ cũ theo đúng rule 14.
- `CHANGELOG.md` và `documents/releases/v2.0.1.md` vẫn nhắc EASD. Đó là mô tả
  các bản đã phát hành; sửa chúng là nói sai lịch sử.
