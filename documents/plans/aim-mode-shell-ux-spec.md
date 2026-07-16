# UX Spec — AIM Mode Shell (v2.1)

| | |
|---|---|
| **Phiên bản** | v2.1 — 2026-07-16. v2 = IA sidebar → project → feature → main content. **v2.1 = sửa theo chỉ đạo user: KHÔNG hướng chat trong mode này — pipeline trigger bằng UI thuần; chat chỉ là tuỳ chọn SAU KHI pipeline chạy xong** (supersede mọi mô tả "chat drawer là đường trigger" của v1/v2) |
| **Trạng thái** | CHỜ DUYỆT (§3.13B R7: spec + wireframe duyệt xong mới code) |
| **Phạm vi** | Toàn bộ shell FE của AIM mode, chia lớp FE-1→FE-4 bên dưới. Approval Inbox / Run Monitor SSE vẫn là AIM-5 (sau Workflows) |
| **Backend đã sẵn** | `GET /team/projects?kind=aim` · `POST /team/projects/aim` + `/aim/preview` + `/aim/join` · `GET /team/projects/{id}/aim/{summary,units,runs/{id}}` · session `mode="aim"` + roster + read-only base source (e13f4ef) · legacy graph structural parser (7a7c476) |

## 1. Định vị mode

AIM hướng tới **vận hành một dây chuyền migration**: setup rulebook, chạy pipeline phân tích source base → KB, rồi chạy pipeline convert/test-compare vào target source. Người dùng sống trong **một project tại một thời điểm**, nhảy giữa các tính năng con của project đó — giống một IDE mở một solution rồi chuyển giữa các panel.

**Nguyên tắc số 1 (user chốt 2026-07-16): mode này KHÔNG hướng đến chat.** Mọi thao tác vận hành — tạo project, trigger pipeline, xem tiến độ, đọc KB, đọc report — là UI thuần (button/form/table/viewer). Chat chỉ xuất hiện ở đúng một chỗ: **tuỳ chọn "Discussion" trên một run ĐÃ CHẠY XONG** (đọc transcript, hỏi thêm agent về kết quả). Không có nút Chat ở header, không có composer thường trực, không có "gõ lệnh để chạy pipeline".

Hệ quả IA:

```
Switch mode [Forge | Coding | AIM]
  └─ Sidebar: danh sách AIM project (+ New/Join)
       └─ Click project → expand các tính năng con (dropdown trong sidebar)
            └─ Click tính năng → main content đổi surface, làm việc tại đó
```

## 2. Personas

- **Operator/lead kỹ thuật** — theo dõi tiến độ wave, trigger pipeline bằng nút, triage fail qua report.
- **Contributor** (archaeologist/converter/test-engineer vai người) — làm việc trên KB, chạy convert/compare từng unit; khi cần đào sâu một run fail thì mở Discussion của run đó (hậu-run).
- **Architect/BA/SME** — đọc KB, business rules, báo cáo equivalence; không bao giờ cần đụng chat.

## 3. Information Architecture

### 3.1 Cây điều hướng

```
AIM (mode tab thứ 3 trong Sidebar switch — icon ArrowRightLeft)
│
├─ ▾ core-batch migration          ← project (kind=aim)
│    ├─ Overview                   ← Board kanban theo phase + 4 metric (mặc định khi mở project)
│    ├─ Knowledge Base             ← file-tree + markdown viewer của KB repo
│    ├─ Rulebook                   ← manifest pack + mappings/canonicalizers/extractors (read-only)
│    ├─ Pipelines                  ← form trigger assess/understand/convert/compare + bảng run đang chạy/đã xong
│    └─ Runs & Reports             ← aim_runs + report.json/md viewer + Discussion (hậu-run)
│
├─ ▸ billing-vb6 migration
│
└─ [+ New / Join project]          ← AimSetupWizard 4 bước (giữ nguyên v1)
```

### 3.2 URL scheme

| Route | Nội dung |
|---|---|
| `/aim` | Empty state (chưa có project) hoặc redirect project mở lần cuối |
| `/aim/$projectId` | Redirect `/aim/$projectId/overview` |
| `/aim/$projectId/$feature` | `feature ∈ overview \| kb \| rulebook \| pipelines \| runs` |
| `/aim/$projectId/runs/$runId` | Chi tiết một run: report + (nếu run đã xong) panel Discussion |

URL đủ để khôi phục đúng chỗ đang làm việc sau reload/share link — giống tinh thần `/coding/$focusId`.

### 3.3 Pipeline chạy KHÔNG qua chat; chat chỉ là tuỳ chọn hậu-run

**Trigger**: trong Pipelines, user chọn pipeline (assess / understand-unit / convert-unit / compare-unit) + unit/wave qua form, bấm **Run**. FE tự làm hai việc dưới nắp: resolve một session per-run mới (`mode="aim"`, `project_id`, tên `<unit>/<pipeline>/<n>`) rồi POST command tương ứng vào session đó qua đúng pipeline chat/SSE hiện có. **Không mở composer, không hiện drawer** — human-in-the-loop chính là cú bấm nút (pipeline ghi vào target source có thêm confirm dialog). Đây vẫn là CÙNG execution substrate — không đường chạy riêng; AIM-4 chỉ đổi call thành `POST /api/workflows/{name}/run`.

**Trong lúc chạy**: bảng run trong Pipelines hiện trạng thái (● running / ✓ pass / ✗ fail) qua polling (`GET /team/sessions?project_id=` + `aim/summary`). Không có surface chat trong lúc chạy.

**Sau khi chạy xong** (và CHỈ sau khi xong): run row/run detail hiện nút **Discussion** — mở panel chứa transcript của đúng session per-run đó, cho phép hỏi thêm (vd hỏi `aim-triage-analyst` vì sao fail). Đây là chỗ DUY NHẤT trong mode có chat.

**Ràng buộc kỹ thuật giữ nguyên**: `TeamChatView` là singleton toàn cục (useTeamStore, h-dvh, global shortcuts) — Discussion đặt đúng MỘT instance, ẩn/hiện bằng CSS, KHÔNG mount instance thứ hai.

## 4. Journeys

**J1 — Tạo project mới (operator)**: switch AIM → sidebar trống → `+ New / Join` → wizard 4 bước (tên+rulebook → source repos *(badge read-only ngay khi thêm)* → target repo *(đã dựng base)* → KB path + review) → điều hướng `/aim/<id>/overview`.

**J2 — Join project có sẵn (contributor thứ 2)**: clone KB repo bằng git → wizard tab Join → nhập KB path → wizard đọc `aim.yaml` hiện rulebook + danh sách identity → chỉ map identity → local path → xong, không hỏi lại config nào khác.

**J3 — Vòng làm việc hằng ngày**: mở `/aim/<project>` → Overview thấy kanban phase/wave + metric → thấy unit fail → Runs & Reports xem diff report → đủ hiểu thì thôi; chưa đủ thì (tuỳ chọn) mở **Discussion** của run đó hỏi thêm → quay lại Pipelines bấm Run compare lại → Overview cập nhật (poll 10s).

**J4 — Phân tích source ra KB**: Pipelines → form chọn `assess` (hoặc `understand-unit` + unit) → bấm Run → theo dõi trạng thái trong bảng run → xong thì xem kết quả ở Knowledge Base (tree + markdown), unit chuyển phase trên Overview. Không đụng chat ở bất kỳ bước nào.

**J5 — Soi rulebook (architect)**: Rulebook → xem manifest (id/version/parser_strategy/unit_kinds), mappings, canonicalizer profiles, extractor configs — trả lời "dây chuyền này convert theo luật nào?" không cần đọc repo EvoFlux.

## 5. Wireframes

### 5.1 Shell: sidebar + Overview (mặc định — không có nút chat nào)

```
┌──────────┬──────────────────────────────────────────────┐
│ F|C|AIM  │ core-batch migration          [java8-java21] │
│──────────│──────────────────────────────────────────────│
│ ▾ core-  │ Total 128 │ Equiv 62% │ Waves 4 │ Run 09:12  │
│   batch  │──────────────────────────────────────────────│
│  ·Overvw │ Inventory Understood Designed Conv Equiv Cut │
│  ·KB     │ ┌──────┐  ┌──────┐   ┌──────┐ ┌────┐ ┌────┐ │
│  ·Rulebk │ │ EOD1 │  │ PAY2 │   │ RPT3 │ │BAT4│ │GL5 │ │
│  ·Pipeln │ └──────┘  └──────┘   └──────┘ └────┘ └────┘ │
│  ·Runs   │ ┌──────┐  ...                                │
│ ▸ billing│ │ EOD2 │                        [Wave: all ▾]│
│ + New/Jn │ └──────┘                                     │
└──────────┴──────────────────────────────────────────────┘
```

### 5.2 Pipelines: form trigger + bảng run (không chat)

```
┌──────────┬──────────────────────────────────────────────┐
│  ·Pipeln◀│ Pipelines                                    │
│          │ Pipeline: [compare-unit ▾]  Unit: [EODCLOSE ▾]│
│          │                              [▶ Run]         │
│          │──────────────────────────────────────────────│
│          │ Run                    Status   Started      │
│          │ EODCLOSE/compare/3     ● running 09:41       │
│          │ PAYROLL/convert/1      ✓ pass    09:12       │
│          │ EODCLOSE/compare/2     ✗ fail    08:55       │
└──────────┴──────────────────────────────────────────────┘
```

### 5.3 Runs & Reports: report + Discussion (chỉ hiện khi run đã xong)

```
┌──────────┬───────────────────────────┬──────────────────┐
│  ·Runs ◀ │ EODCLOSE/compare/2  ✗ fail│ Discussion       │
│          │───────────────────────────│ (transcript của  │
│          │ report.md                 │  session run này)│
│          │ - amount: 12.50 ≠ 12.55   │ aim-triage:      │
│          │ - date fmt: OK (masked)   │ "lệch rounding   │
│          │ - 2/48 records differ     │  ở BR-CORE-0007" │
│          │                           │ [hỏi thêm...]    │
│          │ [Mở Discussion] ──────────▶                  │
└──────────┴───────────────────────────┴──────────────────┘
```

(Wizard 4 bước giữ nguyên wireframe v1 — không vẽ lại. Discussion đóng mặc định; run đang chạy KHÔNG có nút này.)

## 6. Interaction contract

| Sự kiện | Vùng cập nhật | Nguồn dữ liệu | Ghi chú |
|---|---|---|---|
| Switch mode AIM | Sidebar list project | `GET /team/projects?kind=aim` | Forge/Coding không thấy project aim (đã enforce backend) |
| Click project | Expand feature items + điều hướng `/aim/$id/overview` | — (client state `expandedProjects`, giống CodingSidebar) | Nhớ project mở lần cuối (localStorage, giống `oa-last-coding-focus`) |
| Overview mount / đổi wave | Metric row + 6 cột kanban | `GET .../aim/summary`, `GET .../aim/units?wave=` | **Poll 10s** — SSE là AIM-5 |
| Bấm **Run** trong Pipelines | Thêm row ● running vào bảng run; KHÔNG mở chat | FE: resolve session per-run (`POST /team/sessions/resolve` mode=aim, project_id, create=true) → POST command vào session (pipeline chat hiện có, fire-and-forget) | **Đã chốt: auto-send, không prefill composer.** Pipeline ghi target (convert) có confirm dialog. Cùng substrate — AIM-4 chỉ đổi call thành workflows run |
| Run đổi trạng thái | Row ● → ✓/✗ ; nút Discussion enable khi xong | Poll `GET /team/sessions?project_id=` (loop/idle status) + `aim/summary` | |
| Mở run trong Runs & Reports | Report viewer (report.json/md) | `GET .../aim/runs/{id}` + đọc file report từ KB repo | report_path đã lưu trong AimRun |
| Bấm **Discussion** (run đã xong) | Panel transcript trượt phải, composer hỏi thêm | Session per-run của run đó — `TeamChatView` singleton, CSS toggle | Chỗ DUY NHẤT có chat trong mode; đóng = layout state, session còn nguyên |
| Click item KB | Tree + markdown viewer | Workspace-files API trên KB repo path (roles.kb) | Tái dùng `CodingWorkspacePanel`/`CodingFileViewerPanel`, read-only |
| Mở Rulebook | Manifest + file configs read-only | **GAP: cần endpoint nhỏ** `GET /team/projects/{id}/aim/rulebook` | Backend ~1 route đọc từ `app/agent/builtin_aim/rulebooks/` |

## 7. Tái sử dụng component (R8 — không sáng chế design system riêng)

| Cần | Dùng lại | Bằng chứng |
|---|---|---|
| Sidebar project + expand feature | Pattern `CodingSidebar` (expandedProjects Set, section collapse, resizable width, collapsed icon strip) | `web/src/components/CodingSidebar.tsx:318-360,1042-1067` |
| Mode switch 3 tab | `Sidebar.tsx` mode switch hiện có, thêm tab AIM (ArrowRightLeft) | đã build thử trước khi discard — pattern OK |
| Kanban/metric panel | Pattern `ProjectCodeGraphPanel` (flex shell + inline useQuery) | v1 đã xác minh |
| KB browser | `CodingWorkspacePanel` (TreeNodeView) + `CodingFileViewerPanel` | có sẵn, nhận workspace path |
| Wizard | Pattern `ProjectSetupModal` (StepIndicator, RepoRow, pickFolder Tauri/web) | v1 đã xác minh |
| Discussion panel | `TeamChatView` nguyên vẹn trong 1 grid column (singleton!), chỉ mount khi user mở từ run đã xong | v1 đã xác minh + test live |
| Trigger run programmatic | Đúng POST /team/chat pipeline mà scheduler đã dùng để bắn prompt vào session | scheduler service pattern có sẵn |
| Query keys | mở rộng `queryKeys.projects.aim*` | pattern đã có từ đợt FE bị discard (viết lại nhanh) |

## 8. Thứ tự build (mỗi lớp ship được độc lập)

| Lớp | Nội dung | Cần backend thêm? |
|---|---|---|
| **FE-1 Shell** | Tab AIM + sidebar list/expand + routes `/aim/...` + empty state + AimSetupWizard (create/join) + localStorage last-project | Không — API đủ |
| **FE-2 Overview + Pipelines** | Board kanban + metrics (poll 10s); Pipelines form trigger (auto-send vào session per-run) + bảng run status | Không |
| **FE-3 KB + Runs + Discussion** | KB browser (tree+markdown, read-only) + Runs & Reports (bảng + report viewer) + Discussion panel hậu-run (kèm `_workspace` plumbing mode aim trong TeamChatView — fix đã biết từ đợt trước) | Không |
| **FE-4 Rulebook** | Rulebook viewer read-only | **1 endpoint** `GET .../aim/rulebook` |
| **AIM-5** (sau Workflows) | Approval Inbox + Run Monitor SSE + wave burn-up | Workflows M1-M6 |

## 9. Quyết định đã chốt + câu hỏi còn lại

Đã chốt (user, 2026-07-16):
- **Không hướng chat trong mode** — trigger pipeline bằng UI thuần (auto-send dưới nắp), chat chỉ là Discussion tuỳ chọn trên run đã xong.

Còn lại (đề xuất kèm — không phản đối thì làm theo):
1. **KB browser read-only** ở FE-3 (sửa KB là việc của agent/git); edit inline để sau.
2. **Không list session AIM theo ngày ở sidebar** (per-run nhiều + auto-archive) — run chỉ hiện trong Pipelines/Runs của từng project.
3. **Confirm dialog** trước pipeline ghi vào target source (convert-unit); assess/understand/compare chạy thẳng.

## 10. Sign-off

- [ ] IA sidebar → project → feature → main content (mục 3)
- [ ] 5 feature: Overview / KB / Rulebook / Pipelines / Runs (mục 3.1)
- [ ] URL scheme (mục 3.2)
- [ ] **Không chat; Discussion chỉ hậu-run** (mục 3.3)
- [ ] Thứ tự build FE-1→FE-4 (mục 8)
- [ ] 3 đề xuất còn lại (mục 9)
