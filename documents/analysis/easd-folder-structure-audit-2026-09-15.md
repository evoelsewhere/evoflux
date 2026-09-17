# EASD folder structure audit — 2026-09-15

Tổng hợp toàn bộ cấu trúc thư mục EASD làm đầu vào cho một đợt refactor lớn.
Audit đọc code ở trạng thái **working tree** (bao gồm thay đổi chưa commit), đối
chiếu với `governance-main/openspec` như prior art trong cùng workspace.

## 1. Bốn lớp lưu trữ

EASD không có "một cây thư mục". Nó có bốn lớp, mỗi lớp một chủ sở hữu và một
vòng đời khác nhau. Refactor nào chạm một lớp mà quên ba lớp kia đều tạo drift.

| Lớp | Vị trí | Ai ghi | Git | Vai trò |
|---|---|---|---|---|
| **L1 — Shapes** | `app/easd_skills/{skeleton,templates,SKILL.md,RULES.md}` | người (source) | tracked | định nghĩa hình dạng chuẩn, đóng gói trong package |
| **L2 — Install surface** | `.evoflux/easd/config.json`, `.evoflux/easd/RULES.md`, `.evoflux/skills/easd-*` | setup service | tracked | hợp đồng mà agent đọc trước mỗi phase |
| **L3 — Tracked KB** | `<data_directory>/` (evoflux: `documents/`) | store khi publish | tracked | tri thức chuẩn tắc + hiện trạng + lịch sử |
| **L4 — Local runtime** | `.evoflux/easd/.local/{runs,templates,locks}` | store khi chạy Run | **ignored** | ledger thi hành, bằng chứng, khoá |

Hằng số đường dẫn: [easd_setup_service.py:44](../../app/services/easd_setup_service.py:44).
`.gitignore` của L4 là đúng một dòng `.local/`
([easd_setup_service.py:65](../../app/services/easd_setup_service.py:65)).

## 2. Cấu trúc hiện tại (sau WIP chưa commit)

```text
# L1 — nguồn hình dạng, đóng trong package
app/easd_skills/
├── RULES.md                      # 52 dòng, copy nguyên văn sang .evoflux/easd/RULES.md
├── __init__.py                   # EASD_TEMPLATE_NAMES (16), EASD_SKELETON_FILES (8)
├── skeleton/                     # → sinh ra L3
│   ├── README.md  index.yaml
│   ├── specs/README.md
│   ├── features/README.md
│   ├── architecture/README.md  architecture/decisions/README.md
│   ├── reference/README.md
│   └── records/README.md
├── templates/                    # → sinh ra L4/templates
│   ├── *.yaml  (intent, specification, plan, mission, review,
│   │            verification, evidence, deviation, event, run, spec-index)
│   └── *.md    (feature, architecture, decision, reference, record)
└── easd-{specify,plan,implement,review,verify}/
    ├── SKILL.md
    └── references/code-context-contract.md

# L2 — hợp đồng cài đặt
.evoflux/
├── easd/config.json              # data_directory, rules_file, templates_directory,
│                                 # runtime_directory, skills_directory, skills[]
├── easd/RULES.md
├── easd/.gitignore               # ".local/"
└── skills/easd-*/                # bản sao skill để agent nạp

# L3 — knowledge base được version-control
documents/
├── README.md                     # mô tả cấu trúc + authority
├── index.yaml                    # sections{} + authority{normative,current_state,execution,historical}
├── specs/                        # NORMATIVE
│   └── <title-slug>[-N]/         # 1 thư mục / 1 Run
│       ├── index.yaml            # id, title, status, current_revision, current_hash,
│       │                         # current_path, owning_run_id, updated_at
│       └── revisions/0001.yaml   # bản accepted bất biến
├── features/                     # CURRENT STATE
├── architecture/ (+ decisions/)  # CURRENT STATE
├── reference/                    # CURRENT STATE
└── records/                      # HISTORICAL — phẳng, YYYY-MM-DD-<slug>.md
    └── <slug>.yaml               # convergence_record (máy) ← trộn ở đây, xem F6

# L4 — runtime cục bộ, bị ignore
.evoflux/easd/.local/
├── locks/runtime.lock
├── templates/                    # 17 file, giải nén từ L1
└── runs/<title-slug>--<run-uuid>/
    ├── run.yaml  intent.yaml  convergence.yaml
    ├── specifications/0001.yaml  plans/0001.yaml
    ├── missions/  reviews/  verifications/  evidence/  deviations/
    └── events/
```

Tám thư mục con của mỗi Run được tạo cứng tại
[easd_repository_store.py:362](../../app/services/easd_repository_store.py:362).

## 3. Delta chưa commit (đã làm trong WIP hiện tại)

1. **Bỏ khỏi skeleton**: `guides/`, `development/`, `images/`,
   `records/{analysis,research,plans,releases}/`, cùng legacy `runs/`,
   `templates/`. `sections` trong `index.yaml` từ 8 → 5.
2. **`records/` phẳng**, đặt tên `YYYY-MM-DD-<slug>.md`; facet khai báo trong
   front matter thay vì thư mục con.
3. **Media đi kèm**: `assets/` nằm cạnh Markdown tham chiếu nó; không còn
   section media dùng chung.
4. **Bỏ run-uuid khỏi tên thư mục tracked**: `spec_catalog_directory()` →
   `spec_catalog_slug()`; identity chuyển vào `index.yaml.owning_run_id`, phân
   giải bằng scan ([easd_repository_store.py:223](../../app/services/easd_repository_store.py:223)).
5. **Convergence record** rời `records/runs/*.yaml` ra `records/*.yaml`, identity
   đọc từ `run_id` bên trong file ([easd_repository_store.py:842](../../app/services/easd_repository_store.py:842)).
6. **`spec_catalog_index` do store tự phân giải từ đĩa**, caller không còn suy ra
   từ title.
7. Bỏ template `guide.md` và toàn bộ `EASD_LEGACY_OPTIONAL_SKELETON_FILES`.

Hướng đi chung của WIP là đúng và nhất quán: **identity sống trong nội dung tài
liệu, không sống trong tên đường dẫn.** Phần còn lại của audit dựa trên nguyên
tắc đó.

## 4. Findings

### F1 — Catalogue định danh theo Run, không theo capability · **cao**

`_claim_spec_directory` cấp thư mục mới cho mỗi Run; slug trùng thì đẻ `-2`,
`-3`, tối đa 100 ([easd_repository_store.py:257](../../app/services/easd_repository_store.py:257)).
Run thứ hai chạm cùng một hành vi **không merge, không supersede** bản cũ.

Hệ quả: sau một năm `specs/` là changelog, không phải catalogue "current truth
per capability" — đúng thứ mà OpenSpec ở `governance-main` tránh bằng cách tách
`changes/` (delta) khỏi `specs/<capability>/spec.md` (trạng thái hợp nhất).

Đây là finding nặng nhất và nó **không phải vấn đề format**.

### F2 — `specs/` là section YAML duy nhất trong một KB toàn Markdown · **cao**

`features/`, `architecture/`, `reference/`, `records/` đều Markdown. Chỉ
`specs/` — section **normative**, thứ được đọc nhiều nhất — là YAML.

Và không có gì trong sản phẩm đọc lại nó: `load_published_spec`
([easd_repository_store.py:606](../../app/services/easd_repository_store.py:606))
chỉ xuất hiện trong tests. Nguồn sự thật cho máy là DB (`TraceSpecRevision`) và
snapshot L4. Độc giả thật của `documents/specs/` chỉ có hai: người đọc diff/PR,
và agent đọc file bằng `Read` (skill `easd-specify` yêu cầu đọc `specs/` như
authority). Cả hai đều đọc Markdown tốt hơn.

### F3 — Không có index sinh tự động · **trung bình**

Muốn biết catalogue có gì phải glob `specs/*/index.yaml` rồi parse từng file.
Không có `specs/README.md` liệt kê capability → path → revision → hash.

### F4 — README của `specs/` đã stale so với WIP · **trung bình, sửa ngay**

Cả `app/easd_skills/skeleton/specs/README.md` lẫn bản tracked ở ba repo
(`evoflux`, `evo-conductor`, `evo-webbridge`) vẫn ghi:

> Each published Run Spec uses `<slug>--<owning-run-uuid>/`

Trong khi code WIP đã bỏ hậu tố uuid. Contract đang nói sai về chính nó.

### F5 — `records/` phẳng trộn hai loại tài liệu khác bản chất · **trung bình**

Sau khi flatten, `records/` chứa đồng thời:

- `YYYY-MM-DD-<slug>.md` — audit/research/plan do người viết, và
- `<slug>.yaml` — `convergence_record` do máy sinh
  ([easd_repository_store.py:866](../../app/services/easd_repository_store.py:866)).

Hai vòng đời, hai tác giả, hai định dạng, một thư mục phẳng, không tiền tố phân
biệt. Đây là vấn đề **mới do WIP tạo ra**, không phải nợ cũ.

### F6 — Mọi phân giải identity giờ là O(n) đọc file · **trung bình**

`_find_spec_directory` đọc *mọi* `specs/*/index.yaml`;
`_find_convergence_record` đọc *mọi* `records/*.yaml` và `records/runs/*.yaml`;
`_run_directory` quét ba gốc (`runs_path`, `checkout_runs_path`,
`legacy_runs_path`). `_published_spec_index` được gọi trong mọi `create_run` và
`update_run`.

Với vài chục spec thì không sao. Đây là ghi nhận để chọn ngưỡng, không phải lệnh
tối ưu sớm — nhưng nếu đã refactor thì một `specs/README.md` sinh tự động (F3)
cũng chính là index tra cứu, giải quyết luôn F6.

### F7 — Không có cơ chế dọn artifact L4 bị bỏ · **thấp**

`_legacy_generated_candidates` chỉ dọn `<data_directory>/templates/*` (vị trí
legacy tracked), không đụng `.local/templates/`. WIP đã bỏ `guide.md` khỏi
`EASD_TEMPLATE_NAMES` nhưng `.evoflux/easd/.local/templates/guide.md` vẫn nằm
trên đĩa. Nếu chuyển spec sang Markdown thì `spec-index.yaml` sẽ thành rác y hệt.

### F8 — Worktree cô lập không có L4 · **thấp, cần xác nhận**

`.local/` bị ignore, và skill nói rõ "An isolated worktree intentionally has no
checkout-local runtime copy". Nghĩa là agent chạy trong worktree không đọc được
`templates_directory` mà `config.json` trỏ tới. Cần khẳng định trong RULES rằng
templates là tiện ích tuỳ chọn, không phải hợp đồng bắt buộc — hoặc đưa chúng
lên L1/L2.

## 5. Cấu trúc đích đề xuất

### 5.1 `specs/` — Markdown + front matter, gom theo module/capability

```text
documents/specs/
├── README.md                     # SINH TỰ ĐỘNG: bảng capability → path, revision, hash, run
└── <module>/
    ├── README.md                 # SINH TỰ ĐỘNG: index con
    └── <capability>/
        ├── spec.md               # bản normative hiện hành (front matter = identity)
        └── revisions/0001.md     # bản bất biến đã accepted
```

`spec.md` front matter — đây là chỗ trả lời cho ý "đưa `content_hash` vào nội
dung thay vì vào tên file": **đúng, và mở rộng cho toàn bộ identity**.

```yaml
---
kind: easd_specification
capability: spec-catalogue-layout
module: easd
status: accepted
revision: 1
content_hash: <sha256 của payload JSON chuẩn hoá>   # KHÔNG phải hash của file md
owning_run_id: <uuid>
accepted_at: <RFC3339 UTC>
generated_by: easd/publish_spec_revision
---
```

Ràng buộc bắt buộc, theo đúng thứ tự quan trọng:

1. **Markdown không bao giờ bị hash.** `content_hash` vẫn tính trên JSON chuẩn
   hoá của `TraceSpecification`
   ([trace_contracts.py:543](../../app/services/trace_contracts.py:543)).
   Front matter chỉ *ghi lại* hash, không định nghĩa nó. Nhờ vậy không cần
   parser ngược từ Markdown về payload.
2. **Render phải deterministic** (thứ tự khoá cố định, không timestamp trôi), để
   gate CI "render lại từ DB/snapshot rồi so byte" phát hiện mọi drift.
3. **`spec.md` là generated.** Header `<!-- generated — do not edit -->` cộng
   gate. Sửa tay được là toàn bộ mô hình acceptance/hash sụp.
4. **Criteria render thành `### <AC-ID>`** kèm bảng evidence policy, giữ nguyên
   pattern `^[A-Z][A-Z0-9_-]+$`
   ([trace_contracts.py:295](../../app/services/trace_contracts.py:295)) để
   `criterion_id` vẫn grep được và vẫn khớp với evidence/handoff/delegate.
5. **Bỏ `index.yaml` mỗi thư mục.** Mọi trường của nó (`status`,
   `current_revision`, `current_hash`, `owning_run_id`, `updated_at`) đã nằm
   trong front matter. `_find_spec_directory` chuyển sang quét front matter của
   `*/*/spec.md` — cùng chi phí, bớt hẳn một file. Template `spec-index.yaml`
   bị khai tử.

### 5.2 Khoá gom nhóm

`module` đã tồn tại trong schema:
[`TraceImpactTarget.module`](../../app/services/trace_contracts.py:313). Nhưng
`capability` thì chưa, và đây là thay đổi ngữ nghĩa quan trọng nhất của cả đợt
refactor:

> thêm `capability` (slug ổn định) + `module` vào `TraceSpecification`, để Run
> sau publish **revision tiếp theo vào cùng thư mục** thay vì đẻ `-2`.

Không có nó thì cây `modules/` vẫn loạn vì mỗi Run tự đặt tên. Trade-off thật
cần chốt: **ai quyết `capability` slug** — agent đề xuất trong draft, hay user
chốt tại thời điểm accept. Khuyến nghị: agent đề xuất, validate chống danh sách
capability đã tồn tại, user thấy và sửa được trong màn accept.

### 5.3 `records/`

Tách theo bản chất, không theo chủ đề:

```text
documents/records/
├── YYYY-MM-DD-<slug>.md      # người viết: analysis, research, plan, release
└── convergence/<slug>.yaml   # máy sinh
```

Giữ được ý "records phẳng" của WIP cho phần người viết, mà không trộn với
artifact máy (F5).

## 6. Thứ tự refactor

Mỗi bước một commit, mỗi bước tự đứng được.

| # | Bước | Chạm | Rủi ro |
|---|---|---|---|
| 0 | Sửa README `specs/` cho khớp WIP (F4) | skeleton + 3 repo tracked | không |
| 1 | Tách `records/convergence/` (F5) | `_claim_convergence_record_path` | thấp |
| 2 | Thêm `capability` + `module` vào `TraceSpecification` (5.2) | contracts, skill `easd-specify`, UI accept | **cao — chốt trước** |
| 3 | Viết renderer `TraceSpecification → spec.md` deterministic | service mới + test byte-compare | trung bình |
| 4 | Đổi layout catalogue sang `<module>/<capability>/`, bỏ `index.yaml` | `publish_spec_revision`, `_find_spec_directory`, `load_published_spec` | trung bình |
| 5 | Sinh `specs/README.md` + `<module>/README.md` (F3, F6) | cùng hook publish | thấp |
| 6 | Gate CI regenerate-and-compare + header "do not edit" | CI | thấp |
| 7 | Dọn template chết & reaper cho `.local/templates` (F7) | setup service | thấp |

**Toàn bộ điểm móc ghi file chỉ có một**:
[`publish_spec_revision`](../../app/services/easd_repository_store.py:521), gọi
từ [easd_repository_sync.py:228](../../app/services/easd_repository_sync.py:228)
và [:247](../../app/services/easd_repository_sync.py:247). Refactor không phải
rải rác.

## 7. Thời điểm

`documents/specs/` ở cả `evoflux`, `evo-conductor`, `evo-webbridge` hiện chỉ
chứa `README.md` — **không có spec nào đã publish**. Chi phí migration bằng 0
ngay lúc này, và tăng đơn điệu theo từng Run được accept sau đó.

## 8. Đã thực thi (2026-09-15)

Toàn bộ bảng ở mục 6 đã làm, với ba quyết định khác so với bản audit ban đầu:

1. **Không giữ back-compat theo thế hệ.** Vì chưa có bên nào cài EASD, mọi cơ
   chế nhận diện "thế hệ cũ" đã bị bỏ: `EASD_LEGACY_SKILL_SHA256`,
   `EASD_SUPERSEDED_SKILL_SHA256`, `_is_legacy_bundled_skill`,
   `_normalize_knowledge_readme` và các fallback quét vị trí cũ trong
   `records/`. Setup ghi cái đang thiếu, giữ nguyên cái đang có; muốn bản mới
   thì repair với `overwrite`.
2. **Đánh số revision theo capability, không theo Run.** Một capability sống lâu
   hơn Run đầu tiên đặc tả nó, nên `revisions/NNNN.md` là thứ tự hành vi thay
   đổi. Bất biến được bảo vệ bằng cặp `(owning_run_id, revision)`: cùng một
   revision của cùng một Run mà khác `content_hash` là xung đột.
3. **Trang tự lành thay cho gate CI regenerate-and-compare.** Repo không chứa
   payload để render lại, nên gate CI chỉ kiểm tra cấu trúc front matter. Bù
   lại, `publish_spec_revision` ghi đè `spec.md` bất cứ khi nào byte khác bản
   render hiện tại — sửa tay bị khôi phục ở lần publish kế tiếp.

Còn lại, chưa làm vì nằm ngoài phạm vi refactor cấu trúc:

- `localize_legacy_runs` / `preview_runtime_migration` / `legacy_runs_path` vẫn
  còn. Chúng cùng loại "back-compat cho một installed base không tồn tại" nhưng
  là API công khai, gỡ đi là quyết định sản phẩm chứ không phải dọn dẹp.
- KB của chính `evoflux` vẫn ở layout cũ: `documents/` có cả `analysis/`,
  `plans/`, `releases/`, `research/` ở gốc lẫn `records/<facet>/`. Di chuyển
  tài liệu thật là việc riêng, không gộp vào đây.
