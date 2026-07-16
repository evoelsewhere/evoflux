# UX Spec — AIM Mode Shell (v2)

| | |
|---|---|
| **Phiên bản** | v2 — 2026-07-16 (supersede v1 Board-first). Đổi theo chỉ đạo user sau khi backend core AIM-0→3 hoàn tất: AIM là mode riêng điều hướng **sidebar → project → tính năng con → main content**, không phải một Board đơn lẻ |
| **Trạng thái** | CHỜ DUYỆT (§3.13B R7: spec + wireframe duyệt xong mới code) |
| **Phạm vi** | Toàn bộ shell FE của AIM mode, chia lớp FE-1→FE-4 bên dưới. Approval Inbox / Run Monitor SSE vẫn là AIM-5 (sau Workflows) |
| **Backend đã sẵn** | `GET /team/projects?kind=aim` · `POST /team/projects/aim` + `/aim/preview` + `/aim/join` · `GET /team/projects/{id}/aim/{summary,units,runs/{id}}` · session `mode="aim"` + roster + read-only base source (e13f4ef) · legacy graph structural parser (7a7c476) |

## 1. Định vị mode

AIM hướng tới **vận hành một dây chuyền migration**: setup rulebook, chạy pipeline phân tích source base → KB, rồi chạy pipeline convert/test-compare vào target source. Người dùng sống trong **một project tại một thời điểm**, nhảy giữa các tính năng con của project đó — giống cách một IDE mở một solution rồi chuyển giữa các panel, KHÔNG giống chat-first của Forge/Coding.

Hệ quả IA (chỉ đạo user 2026-07-16):

```
Switch mode [Forge | Coding | AIM]
  └─ Sidebar: danh sách AIM project (+ New/Join)
       └─ Click project → expand các tính năng con (dropdown trong sidebar)
            └─ Click tính năng → main content đổi surface, làm việc tại đó
```

## 2. Personas (giữ từ v1)

- **Operator/lead kỹ thuật** — theo dõi tiến độ wave, trigger pipeline, triage fail.
- **Contributor** (archaeologist/converter/test-engineer vai người) — làm việc trên KB, chạy convert/compare từng unit, cần chat với agent khi debug.
- **Architect/BA/SME** — đọc KB, business rules, báo cáo equivalence; ít trigger.

## 3. Information Architecture

### 3.1 Cây điều hướng

```
AIM (mode tab thứ 3 trong Sidebar switch — icon ArrowRightLeft)
│
├─ ▾ core-batch migration          ← project (kind=aim)
│    ├─ Overview                   ← Board kanban theo phase + 4 metric (mặc định khi mở project)
│    ├─ Knowledge Base             ← file-tree + markdown viewer của KB repo
│    ├─ Rulebook                   ← manifest pack + mappings/canonicalizers/extractors (read-only)
│    ├─ Pipelines                  ← trigger assess/understand/convert/compare (per-run session) + danh sách session
│    └─ Runs & Reports             ← aim_runs + report.json/md viewer
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
| `/aim/$projectId/$feature/$sessionId` | Feature + chat drawer đang mở session cụ thể (per-run) |

Giống `/coding/$focusId/$sessionId` về tinh thần: URL đủ để khôi phục đúng chỗ đang làm việc sau reload/share link.

### 3.3 Chat — vẫn là drawer, không phải surface chính (giữ quyết định v1)

- Nút Chat ở header main content mở **drawer trượt phải** (~300-360px, CSS grid co main content — không overlay).
- Session model **per-run** (đã chốt): trigger từ Pipelines tạo session ngầm tên `<unit>/<pipeline>/<n>`; mở từ header dùng session project-level mặc định.
- **Ràng buộc kỹ thuật giữ nguyên**: `TeamChatView` là singleton toàn cục (useTeamStore, h-dvh, global shortcuts) — drawer đặt đúng MỘT instance trong grid column, ẩn/hiện bằng CSS, KHÔNG mount instance thứ hai.

## 4. Journeys

**J1 — Tạo project mới (operator)**: switch AIM → sidebar trống → `+ New / Join` → wizard 4 bước (tên+rulebook → source repos *(badge read-only ngay khi thêm)* → target repo *(đã dựng base)* → KB path + review) → điều hướng `/aim/<id>/overview`.

**J2 — Join project có sẵn (contributor thứ 2)**: clone KB repo bằng git → wizard tab Join → nhập KB path → wizard đọc `aim.yaml` hiện rulebook + danh sách identity → chỉ map identity → local path → xong, không hỏi lại config nào khác.

**J3 — Vòng làm việc hằng ngày**: mở `/aim/<project>` → Overview thấy kanban phase/wave + metric → click card unit fail → chuyển Runs & Reports xem diff report → mở drawer chat hỏi `aim-triage-analyst` / trigger `/aim-compare-unit` → đóng drawer, Overview cập nhật (poll 10s).

**J4 — Phân tích source ra KB**: Pipelines → chọn `assess` hoặc `understand-unit` → chạy trong per-run session (drawer mở hiện transcript) → kết quả ghi vào KB repo → xem lại ở Knowledge Base (tree + markdown), unit chuyển phase trên Overview.

**J5 — Soi rulebook (architect)**: Rulebook → xem manifest (id/version/parser_strategy/unit_kinds), mappings, canonicalizer profiles, extractor configs — trả lời "dây chuyền này convert theo luật nào?" không cần đọc repo EvoFlux.

## 5. Wireframes

### 5.1 Shell: sidebar + Overview (mặc định)

```
┌──────────┬────────────────────────────────────────────┬─────────┐
│ F|C|AIM  │ core-batch migration   [java8-java21] [Chat]│         │
│──────────│─────────────────────────────────────────────│ (drawer │
│ ▾ core-  │ Total 128 │ Equiv 62% │ Waves 4 │ Run 09:12 │  đóng)  │
│   batch  │─────────────────────────────────────────────│         │
│  ·Overvw │ Inventory Understood Designed Conv Equiv Cut│         │
│  ·KB     │ ┌──────┐  ┌──────┐   ┌──────┐ ┌────┐ ┌────┐│         │
│  ·Rulebk │ │ EOD1 │  │ PAY2 │   │ RPT3 │ │BAT4│ │GL5 ││         │
│  ·Pipeln │ └──────┘  └──────┘   └──────┘ └────┘ └────┘│         │
│  ·Runs   │ ┌──────┐  ...                              │         │
│ ▸ billing│ │ EOD2 │                                    │         │
│          │ └──────┘                                    │         │
│ + New/Jn │  [Wave: all ▾]                              │         │
└──────────┴────────────────────────────────────────────┴─────────┘
```

### 5.2 Sidebar expand + Knowledge Base

```
┌──────────┬────────────────────────────────────────────┐
│ ▾ core-  │ Knowledge Base — core-batch-kb              │
│   batch  │──────────────┬──────────────────────────────│
│  ·Overvw │ modules/     │ # EODCLOSE                   │
│  ·KB   ◀ │  core-batch/ │ Phase: understood · Wave 1   │
│  ·Rulebk │   EODCLOSE.md│ ## Purpose                   │
│  ·Pipeln │   PAYROLL.md │ Đóng ngày giao dịch, ghi sổ  │
│  ·Runs   │ business-    │ ## Calls                     │
│          │  rules/      │ - PAYROLL01 (BR-CORE-0007)   │
│          │ runs/        │ ...                          │
└──────────┴──────────────┴──────────────────────────────┘
```

### 5.3 Pipelines + drawer per-run

```
┌──────────┬───────────────────────────┬────────────────┐
│  ·Pipeln◀│ Pipelines                 │ EODCLOSE/      │
│          │ [Assess] [Understand unit]│ compare/3      │
│          │ [Convert unit] [Compare]  │ ┌────────────┐ │
│          │───────────────────────────│ │aim-test-eng│ │
│          │ Sessions gần đây          │ │ running... │ │
│          │ · EODCLOSE/compare/3  ● │ └────────────┘ │
│          │ · PAYROLL/convert/1   ✓ │ [Message...]   │
└──────────┴───────────────────────────┴────────────────┘
```

(Wizard 4 bước giữ nguyên wireframe v1 — không vẽ lại.)

## 6. Interaction contract

| Sự kiện | Vùng cập nhật | Nguồn dữ liệu | Ghi chú |
|---|---|---|---|
| Switch mode AIM | Sidebar list project | `GET /team/projects?kind=aim` | Forge/Coding không thấy project aim (đã enforce backend) |
| Click project | Expand feature items + điều hướng `/aim/$id/overview` | — (client state `expandedProjects`, giống CodingSidebar) | Nhớ project mở lần cuối (localStorage, giống `oa-last-coding-focus`) |
| Overview mount / đổi wave | Metric row + 6 cột kanban | `GET .../aim/summary`, `GET .../aim/units?wave=` | **Poll 10s** (giữ v1) — SSE là AIM-5 |
| Click item KB | Tree + markdown viewer | Workspace-files API trên KB repo path (roles.kb) | Tái dùng `CodingWorkspacePanel`/`CodingFileViewerPanel` |
| Mở Rulebook | Manifest + file configs read-only | **GAP: cần endpoint nhỏ** `GET /team/projects/{id}/aim/rulebook` trả rulebook.yaml + danh sách file pack | Backend ~1 route đọc từ `app/agent/builtin_aim/rulebooks/` |
| Bấm pipeline button | Mở drawer với session per-run mới, prefill slash command (vd `/aim-compare-unit core-batch/EODCLOSE`) | `POST /team/sessions/resolve` (mode=aim, project_id, create=true) + pipeline chat | Pre-Workflows: pipeline = per-run session + command; nút chỉ là "trigger có ngữ cảnh". AIM-4 nâng thành `POST /api/workflows/{name}/run` — **không tạo execution path riêng** |
| Danh sách session per project | Sessions gần đây trong Pipelines | `GET /team/sessions?project_id=` (đã có) | |
| Mở run trong Runs & Reports | Bảng aim_runs + viewer report | `GET .../aim/runs/{id}` + đọc file report từ KB repo | report_path đã lưu trong AimRun |
| Đóng/mở drawer | Grid column 0px ↔ ~320px | Zustand `useAimUIStore.drawerOpen` (1 boolean) | Session không mất — chỉ CSS |

## 7. Tái sử dụng component (R8 — không sáng chế design system riêng)

| Cần | Dùng lại | Bằng chứng |
|---|---|---|
| Sidebar project + expand feature | Pattern `CodingSidebar` (expandedProjects Set, section collapse, resizable width, collapsed icon strip) | `web/src/components/CodingSidebar.tsx:318-360,1042-1067` |
| Mode switch 3 tab | `Sidebar.tsx` mode switch hiện có, thêm tab AIM (ArrowRightLeft) | đã build thử trước khi discard — pattern OK |
| Kanban/metric panel | Pattern `ProjectCodeGraphPanel` (flex shell + inline useQuery) | v1 đã xác minh |
| KB browser | `CodingWorkspacePanel` (TreeNodeView) + `CodingFileViewerPanel` | có sẵn, nhận workspace path |
| Wizard | Pattern `ProjectSetupModal` (StepIndicator, RepoRow, pickFolder Tauri/web) | v1 đã xác minh |
| Chat drawer | `TeamChatView` nguyên vẹn trong 1 grid column (singleton!) | v1 đã xác minh + test live |
| Query keys | mở rộng `queryKeys.projects.aim*` | đã có sẵn từ đợt FE bị discard (viết lại nhanh) |

## 8. Thứ tự build (mỗi lớp ship được độc lập)

| Lớp | Nội dung | Cần backend thêm? |
|---|---|---|
| **FE-1 Shell** | Tab AIM + sidebar list/expand + routes `/aim/...` + empty state + AimSetupWizard (create/join) + localStorage last-project | Không — API đủ |
| **FE-2 Overview + Chat** | Board kanban + metrics (poll 10s) + chat drawer per-run + `_workspace` plumbing cho mode aim (fix đã biết từ đợt trước: `resetSessionState` + `agentWorkspace` trong TeamChatView) | Không |
| **FE-3 KB + Runs** | KB browser (tree+markdown) + Runs & Reports (bảng + report viewer) + Pipelines (nút trigger prefill command + session list) | Không |
| **FE-4 Rulebook** | Rulebook viewer read-only | **1 endpoint** `GET .../aim/rulebook` |
| **AIM-5** (sau Workflows) | Approval Inbox + Run Monitor SSE + wave burn-up | Workflows M1-M6 |

## 9. Câu hỏi mở (cần chốt khi duyệt)

1. **Pipelines pre-Workflows**: nút trigger = mở drawer với command prefill (đề xuất, đơn giản, không đường chạy riêng) — hay tự động gửi command luôn? Đề xuất: **prefill, user bấm gửi** — giữ human-in-the-loop trước khi có approval-manifest của Workflows.
2. **KB browser edit hay read-only?** Đề xuất: read-only ở FE-3 (sửa KB là việc của agent/git); edit inline để sau.
3. **Vị trí danh sách session AIM trong sidebar**: KHÔNG list session theo ngày như Forge (per-run session rất nhiều, auto-archive) — chỉ hiện trong Pipelines của từng project. Xác nhận?

## 10. Sign-off

- [ ] IA sidebar → project → feature → main content (mục 3)
- [ ] 5 feature: Overview / KB / Rulebook / Pipelines / Runs (mục 3.1)
- [ ] URL scheme (mục 3.2)
- [ ] Chat drawer + per-run giữ nguyên (mục 3.3)
- [ ] Thứ tự build FE-1→FE-4 (mục 8)
- [ ] 3 câu hỏi mở (mục 9)
