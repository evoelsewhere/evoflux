# AIM Mode Shell — UX Spec (AIM-2)

| | |
|---|---|
| **Trạng thái** | PROPOSED — chờ duyệt (theo §3.13 R7 của [`aim-framework.md`](../research/aim-framework.md): không code UI khi spec chưa duyệt) |
| **Ngày** | 2026-07-16 |
| **Phạm vi** | Chỉ 3 surface AIM-2 cần: **AIM Board (skeleton)**, **chat drawer**, **AimSetupWizard**. Approval Inbox / Run Monitor / Unit detail đầy đủ là AIM-5 — không nằm trong spec này |
| **Người duyệt** | _(điền tên khi duyệt — SME/lead UX nội bộ hoặc chính user)_ |

---

## 1. Vì sao có tài liệu này

`aim-framework.md` §3.13B (R7) đặt luật: **"mỗi surface UI mới có user journey theo persona + wireframe + interaction contract, duyệt xong mới implement."** AIM-2 là lần đầu tiên AIM mode có UI thật — route `/aim`, wizard, board. Tài liệu này là spec đó cho đúng 3 surface AIM-2 cần build, để không lặp lại đúng lỗi mà §3.13A đang cấm ở phía app đích: "chạy luôn" mà không thống nhất thiết kế trước.

## 2. Persona

- **Delivery lead / operator** (chính) — mở board mỗi sáng, hỏi "cái gì blocked, cái gì cần tôi", trigger việc tiếp theo. Không cần biết chi tiết kỹ thuật của agent.
- **Solution architect** — chạy wizard một lần khi khởi tạo project, hiếm khi quay lại.
- **Contributor kỹ thuật** (archaeologist/converter/test-engineer role, nhưng vận hành bởi người) — chủ yếu dùng chat drawer để trực tiếp trò chuyện với agent khi cần debug hoặc bổ sung ngữ cảnh.

## 3. Journey

### J1 — Tạo project mới (Solution architect)
1. Vào `/aim` (chưa có project nào) → thấy empty state, nút "Create migration project".
2. Wizard 4 bước (xem wireframe §4.2):
   - **Bước 1**: Tên project + chọn rulebook (dropdown liệt kê rulebook đã cài, vd `java8-java21`, `vb6-dotnet`).
   - **Bước 2**: Add base source repo(s) — mỗi repo thêm vào hiển thị badge **"read-only"** ngay lập tức (không chờ tạo xong project mới biết) — đây là tín hiệu UX quan trọng nhất của bước này: người dùng phải thấy rõ ràng những repo này sẽ không bao giờ bị agent ghi vào.
   - **Bước 3**: Add target repo (đã dựng base) — nếu rulebook có `target-base/checklist.md`, hiển thị checklist đó dưới dạng danh sách tick-off tham khảo (không block Continue nếu chưa tick hết — đây là gợi ý, không phải validation cứng).
   - **Bước 4**: KB repo — "Create new from template" (mặc định) hoặc "Use existing path". Review toàn bộ lựa chọn trước khi "Create project".
3. Sau khi tạo: điều hướng thẳng vào AIM Board của project vừa tạo (rỗng, đang ở phase "assess").

### J2 — Tham gia project có sẵn (Contributor khác máy)
1. Chọn "Join existing" ngay từ bước 1 của wizard thay vì "Create new".
2. Chọn/clone KB repo có sẵn → wizard đọc `aim.yaml` → chỉ hỏi mapping repo local (source/target nằm ở đâu trên máy này) — **không hỏi lại** rulebook/tên project vì đã có trong `aim.yaml`.
3. Vào thẳng Board — thấy đúng state mà người tạo project đã thấy (đọc từ cùng KB).

### J3 — Xem tiến độ hằng ngày (Delivery lead)
1. Mở `/aim/<project>` → Board hiện ngay (không phải chat) — xem wireframe §4.1.
2. Đọc nhanh 4 metric card đầu (tổng số unit, % equivalent, wave đang chạy, lần chạy gần nhất) rồi lướt 6 cột theo phase.
3. Unit card màu vàng (nhạt) = run gần nhất fail; xanh (nhạt) = pass — không cần mở gì thêm để biết "cái gì đang cháy".
4. Muốn hiểu sâu một unit / hỏi vì sao fail → mở chat drawer (xem J4).

### J4 — Hỏi/trigger qua chat drawer
1. Bấm nút "Chat" ở header Board → drawer trượt ra bên phải, Board co lại (xem wireframe §4.3) — **không rời khỏi route `/aim/<project>`**.
2. Drawer hiển thị đúng transcript của session gắn với unit/run đang xem (nếu mở từ context một unit) hoặc một session project-level mới (nếu mở từ header chung).
3. Gõ câu hỏi hoặc lệnh (`/aim-convert-unit core-batch/EODCLOSE`) — hành xử y hệt `TeamChatView` bình thường, không có gì "đặc biệt cho AIM" ở tầng chat.
4. Đóng drawer — Board trở lại full width, không mất state.

## 4. Wireframe

*(3 mockup HTML đã render trong chat — mô tả lại bằng ASCII/prose dưới đây để lưu trong git, vì ảnh render không tồn tại ngoài phiên chat.)*

### 4.1 AIM Board — main view

```
┌───────────────────────────────────────────────────────────────────┐
│ core-batch migration [java8-java21]      [Wave: all ▾] [💬 Chat]   │
├───────────────────────────────────────────────────────────────────┤
│ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐                   │
│ │Total 42 │ │Equiv 62%│ │Wave  2  │ │Run  4m  │  ← metric cards   │
│ └─────────┘ └─────────┘ └─────────┘ └─────────┘                   │
├───────────────────────────────────────────────────────────────────┤
│ Inventory  Understood  Designed  Converted  Equivalent  Cutover    │
│   ·8          ·6          ·5        ·4          ·18        ·1     │
│ [card]      [card]      [card]   [card‼fail] [card✓pass] [card]   │
│ [card]                                                             │
└───────────────────────────────────────────────────────────────────┘
```
- Mỗi unit card: `<module>/<name>` + kind + wave; nếu có run gần nhất → nền vàng nhạt (fail) hoặc xanh nhạt (pass), không cần biểu tượng phụ.
- Cột không cuộn dọc bên trong card list ở bản skeleton — nếu một cột vượt quá ~6 card, hiện "+N khác" (đủ dùng cho pilot; virtualized list là cải tiến AIM-5).
- Không có drag-and-drop giữa cột ở AIM-2 (đổi phase là việc của agent qua `aim_units`, không phải người kéo-thả card).

### 4.2 AimSetupWizard — bước 2/4 (mẫu đại diện)

```
┌──────────────────────────────────┐
│ ▓▓▓▓ ▓▓▓▓ ░░░░ ░░░░   Step 2 of 4│
│ Add base source repos             │
│ Mounted read-only for this project│
│ ┌──────────────────────────────┐ │
│ │ 📁 ~/repos/core-batch  [read-only]│
│ ├──────────────────────────────┤ │
│ │ 📁 ~/repos/common-copybooks [read-only]│
│ └──────────────────────────────┘ │
│ [+ Add another repo]              │
│                    [Back] [Continue]│
└──────────────────────────────────┘
```
- Progress bar 4 đoạn ở trên cùng, luôn hiển thị dù đang ở bước nào.
- Badge "read-only" xuất hiện NGAY khi thêm repo — không chờ submit, để người dùng tin tưởng ngay từ lúc nhập.
- Bước 3 (target repo) và bước 4 (KB) dùng cùng khung layout, chỉ đổi nội dung form giữa progress bar và nút Back/Continue.

### 4.3 Board + chat drawer

```
┌───────────────────────────┬───────────────┐
│ core-batch migration   [x]│ Session:      │
│ Designed·5 Converted·4 ...│ EODCLOSE/...  │
│ [card]     [card‼fail]    │ ┌───────────┐ │
│                            │ │agent msg  │ │
│                            │ └───────────┘ │
│                            │        ┌────┐ │
│                            │        │you │ │
│                            │        └────┘ │
│                            │ [Message...]  │
└───────────────────────────┴───────────────┘
```
- Drawer chiếm ~220-320px bên phải (tuỳ viewport), Board co lại bằng CSS grid (không overlay che Board — cả hai cùng nhìn thấy, đúng tinh thần "một việc, một nơi" của R9: trigger/xem ở Board, hội thoại ở drawer, cả hai đồng thời).
- Nút đóng `[x]` ở góc trái header Board (không phải trên drawer) — nhất quán vị trí toggle.

## 5. Interaction contract

| Sự kiện | Vùng cập nhật | Nguồn dữ liệu |
|---|---|---|
| Board mount / đổi wave filter | 4 metric card + 6 cột unit | `GET /team/projects/{id}/aim/summary`, `GET /team/projects/{id}/aim/units?wave=` |
| Unit card có run mới (fail/pass) | Màu nền card đó | Poll lại `aim/units` theo interval ngắn (AIM-2: polling đơn giản, ví dụ 10s — **chưa dùng SSE**; nâng cấp SSE là AIM-5 khi có `workflow_progress`) |
| Bấm "Chat" ở header | Mở drawer, giữ nguyên route `/aim/{focusId}` | Tạo/tái dùng session theo model **per-run đã chốt** (mục 3.12 của aim-framework.md) nếu mở từ context một run đang chạy; session project-level mặc định nếu mở từ header chung |
| Gõ trong drawer | Transcript trong drawer | Pipeline chat/SSE y hệt `TeamChatView` hiện có — **không có cơ chế riêng cho AIM** |
| Đóng drawer | Board full width | Chỉ CSS/layout state, không mất session — session vẫn chạy nền, mở lại drawer là thấy tiếp |
| Wizard "Continue" mỗi bước | Validate tối thiểu (path tồn tại, tên không rỗng) rồi sang bước kế | Không gọi API tạo project cho đến bước cuối "Create project" — bước 1-3 chỉ giữ state client-side |
| Wizard "Create project" | Điều hướng `/aim/<project_id>` | `POST` tạo `CodingProject(kind="aim")` + workspace mapping + sinh `aim.yaml` (theo §3.5); AIM-2 chỉ cần route đích tồn tại, backend tạo project đã có sẵn service pattern từ `svc.create_project` — cần mở rộng nhỏ để set `kind` + `settings["aim"]` |

## 6. Tái sử dụng component (đúng R8 — không sáng chế design system riêng)

- Panel/card pattern: theo đúng `ProjectCodeGraphPanel.tsx` (đã có data-fetch + panel skeleton pattern) — `AimBoardPanel` clone cấu trúc này, không viết CSS mới.
- Wizard: theo đúng bố cục nhiều bước của `ProjectSetupModal.tsx` (đã có 3-bước tương tự) — mở rộng thành 4 bước, tái dùng modal shell/progress-indicator nếu có sẵn.
- Chat drawer: `TeamChatView` nguyên vẹn, chỉ đặt trong một container slide-over (Zustand store thêm 1 boolean `aimDrawerOpen`, không có state mới nào khác).
- Metric card, badge, button: dùng đúng token Tailwind v4 + component shadcn/base-ui hiện có trong `web/src/components/` — không thêm thư viện UI mới ngoài `@xyflow/react` đã plan riêng cho workflow canvas (không liên quan AIM-2).

## 7. Quy ước copy (ngắn, áp dụng chung)

- Sentence case cho mọi label/nút/tiêu đề — không Title Case, không ALL CAPS.
- Nút hành động bắt đầu bằng động từ: "Create project", "Add another repo", "Continue" — không "Submit"/"OK".
- Badge trạng thái ngắn gọn, không câu: "read-only", "fail", "pass" — không "This repo is read-only.".
- Rỗng (chưa có project) là lời mời, không phải xin lỗi: tiêu đề đặt tên không gian ("Start a migration project"), một dòng mô tả, nút hành động là động từ.

## 8. Câu hỏi mở (cần quyết trước khi code)

1. Polling interval cho Board (đề xuất 10s) có chấp nhận được không, hay cần WebSocket/SSE ngay từ AIM-2? (Đề xuất: polling đủ dùng cho pilot quy mô nhỏ, tránh xây SSE integration sớm khi chưa có `workflow_progress` thật.)
2. Cột phase khi >~6 unit: "+N khác" (link mở view riêng) có đủ cho AIM-2, hay cần scroll/virtualize ngay? (Đề xuất: đủ, hoãn virtualize sang AIM-5.)
3. Route Join existing nằm ở đâu trong UI — nút riêng trên trang chọn project, hay một toggle trong bước 1 của wizard? (Đề xuất trong wireframe: toggle trong bước 1, xem J2.)

## 9. Duyệt

- [ ] Người duyệt xác nhận 3 wireframe + interaction contract khớp kỳ vọng.
- [ ] 3 câu hỏi mở ở mục 8 đã có quyết định.
- [ ] Sau khi tick xong, AIM-2 mới được phép bắt đầu code theo đúng §3.13 R7.
