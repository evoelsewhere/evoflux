# Tool search code cho agent - so sánh các harness và đề xuất cho EvoFlux

| | |
|---|---|
| **Trạng thái** | P0-P2 IMPLEMENTED (2026-09-30); P3 (tự thêm context) chưa làm, cần đo |
| **Ngày** | 2026-09-30 |
| **Phạm vi** | Tool `grep` / `glob` mà model gọi để tìm code: schema, output, giới hạn, cách ship ripgrep, hiển thị trên UI |
| **Code liên quan** | [`app/agent/tools/builtin/filesystem/grep.py`](../../app/agent/tools/builtin/filesystem/grep.py), [`glob.py`](../../app/agent/tools/builtin/filesystem/glob.py), [`_ignore.py`](../../app/agent/tools/builtin/filesystem/_ignore.py), [`web/src/components/ToolCall/display.tsx`](../../web/src/components/ToolCall/display.tsx), [`scripts/build_sidecar.py`](../../scripts/build_sidecar.py) |

---

## Tóm tắt điều hành

Tool `grep` của EvoFlux đã dùng ripgrep, có context lines và fallback Python.
Tuy vậy có hai điểm yếu lớn so với các harness khác:

1. **Bản desktop không ship `rg`.** `grep.py` chỉ gọi `shutil.which("rg")`.
   Máy end user thường không cài ripgrep, nên mọi lần search đều chạy fallback
   `os.walk` + `re`. Fallback này chậm, bị timeout 10 giây, và chỉ đọc
   `.gitignore` ở thư mục bắt đầu tìm (`load_gitignore_rules(root)`). Mọi
   harness còn lại đều ship ripgrep theo app: Claude Code bundle sẵn, Gemini
   CLI vendor binary trong repo, Codex đóng gói qua DotSlash, opencode tự tải
   bản pinned, Roo dùng `@vscode/ripgrep`.
2. **Chỉ có một kiểu output là từng dòng nội dung, và cắt kết quả mà không báo.**
   Khi đạt `max_results` (mặc định 100) tool dừng lại mà không nói cho model
   biết còn kết quả. Model không hỏi được "chỉ danh sách file", "đếm bao nhiêu"
   hay "trang tiếp theo".

Thiết kế của Claude Code giải quyết cả hai: `output_mode` với mặc định
`files_with_matches`, phân trang bằng `head_limit` + `offset`, chế độ `count`
có tổng đầy đủ, filter `glob`/`type`, và `multiline`. Đề xuất làm theo thứ tự:
ship `rg` trước, sau đó thêm output mode, phân trang và thông báo cắt kết quả.

## Đã triển khai (2026-09-30)

Những chỗ khác so với đề xuất bên dưới:

- **Ship rg:** `build_sidecar.py` tải ripgrep 15.2.0 theo target triple.
  SHA-256 được pin trong script; Linux dùng bản musl tĩnh. File được đặt vào
  `sidecar-bundle/ripgrep/`. Tauri truyền đường dẫn qua `EVOFLUX_RG_BIN`, và
  `grep` ưu tiên binary này trước `rg` trên `PATH`. Tool `shell` được nối
  thư mục này vào **cuối** `PATH`, nên Skill chạy `rg` qua shell vẫn dùng
  được trên máy chưa cài ripgrep, còn `rg` user tự cài vẫn được ưu tiên.
- **Tên tham số:** giữ `max_results` (tương thích ngược), thêm `offset`,
  `output_mode`, `type`, `fixed_strings`, `multiline`. Không thêm
  `head_limit` hay `max_per_file`, để schema gửi kèm mỗi turn gọn hơn.
- **Output mặc định vẫn là `content`.** Mô tả tool hướng model dùng
  `files_with_matches` trước khi cần tìm vị trí code.
- **Thứ tự ổn định:** `content` và `count` chạy `rg --sort=path` để các trang
  `offset` không lặp hoặc sót dòng giữa hai lần gọi. `files_with_matches`
  để rg chạy đa luồng rồi mới sắp theo mtime.
- **Pattern Rust regex không nhận** (backreference, look-around) được chạy
  lại bằng `rg --pcre2` thay vì rơi xuống fallback Python. Loại file không
  tồn tại thì trả nguyên lỗi của rg cho model.
- **`--no-require-git`:** rg đọc `.gitignore` cả khi thư mục không phải git
  repo, cho khớp với fallback Python.
- **`glob`** sắp mọi kết quả theo mtime rồi mới cắt trang. Trước đây nó cắt
  200 file đầu theo tên rồi mới sắp. Giờ có thêm `offset` và dòng báo cắt
  kết quả.
- **Lưu ý CRLF:** rg đọc byte thô, nên với `multiline` trên file CRLF model
  cần viết `\r?\n`; mô tả tham số đã ghi điều này.

## Hiện trạng EvoFlux (trước khi triển khai)

| Khía cạnh | `grep` hiện tại |
|---|---|
| Tham số | `pattern`, `directory`, `include` (glob tên file), `max_results` (100), `case_insensitive`, `context` (≤ 10) |
| Output | `file:line: content`; dòng context dùng `file-line- content`, các khối cách nhau bằng `--`; mỗi dòng cắt ở 200 ký tự |
| Sắp xếp | Theo thứ tự rg trả về |
| Cắt kết quả | Dừng ở `max_results` **và không có thông báo** |
| Pattern sai | rg lỗi thì fallback sang `re` của Python; `re` cũng lỗi thì trả `Invalid regex` |
| gitignore | rg tự đọc gitignore lồng nhau, sau đó lọc thêm theo `.gitignore` gốc; fallback chỉ đọc `.gitignore` ở thư mục bắt đầu tìm |
| Nguồn `rg` | Chỉ lấy trên PATH hệ thống; sidecar bundle không có |
| UI | Header `Searching <pattern> in <dir> (<include>)`; kết quả hiển thị dạng danh sách file (`FileListResult`) |

`glob` luôn quét bằng Python (`Path.glob` / `os.walk`), sắp theo mtime (mới nhất
trước), mặc định tối đa 200 kết quả, và cũng không báo khi bị cắt.

## Các harness khác làm thế nào

Nguồn là code trên nhánh mặc định ngày 2026-09-30, trừ chỗ có ghi tag.

| | Output mặc định | Giới hạn mặc định | Phân trang | Sắp xếp | Context | gitignore | Khi không có rg | Nguồn rg |
|---|---|---|---|---|---|---|---|---|
| **Claude Code** | `files_with_matches` | `head_limit` 250 | `head_limit` + `offset` | mtime (Glob) | `-A`/`-B`/`-C` | Grep có, Glob không (mặc định) | `USE_BUILTIN_RIPGREP=0` dùng rg hệ thống | bundle theo app |
| **opencode** | dòng, nhóm theo file | 100 cố định | không | thứ tự rg (v1.0 sắp theo mtime) | không | có | không có | rg hệ thống, không có thì tải 15.1.0 |
| **Gemini CLI** | dòng, nhóm theo file | 100 | không | theo file, rồi theo dòng | C/A/B + tự thêm context | có + `.geminiignore` | `git grep` → `grep` → JS | vendor binary trong repo |
| **Codex** | shell `rg` (`grep_files` cũ: chỉ path) | 100 (max 2000) | không | `--sortr=modified` | không | có | prompt: "use alternatives" | DotSlash trong npm package |
| **Roo / Cline cũ** | dòng + 1 dòng context | 300 / 0.25 MB | không | thứ tự rg | 1 dòng cố định | có + `.rooignore` | không có | `@vscode/ripgrep` |
| **Cline SDK** | 1 match/file + 2 dòng context | 100 / 48 KB | không | thứ tự rg | 2 dòng | có | walk bằng JS | rg hệ thống |

### Chi tiết đáng học

- **Claude Code** ([tools reference](https://code.claude.com/docs/en/tools-reference),
  [env vars](https://code.claude.com/docs/en/env-vars)):
  - Có ba output mode: `files_with_matches` (mặc định), `content`, `count`.
  - `count` trả tổng đầy đủ kể cả khi danh sách bị `head_limit`/`offset` cắt.
  - `offset` vượt quá cuối trả `No entries at this offset` thay vì "không có
    kết quả".
  - Pattern sai trả nguyên lỗi của ripgrep; trước v2.1.208 trả "No files found".
  - Glob sắp theo mtime, giới hạn 100 và báo cho model khi bị cắt.
  - Schema quan sát được trong phiên làm việc (không có trong docs): `pattern`,
    `path`, `glob`, `type`, `output_mode`, `-A`/`-B`/`-C`/`context`, `-n`
    (mặc định true), `-i`, `-o`, `multiline`, `head_limit` (mặc định 250,
    `0` = không giới hạn), `offset`.
  - Chưa xác minh từ nguồn nào: Grep `files_with_matches` có sắp theo mtime không.
- **Gemini CLI** ([`ripGrep.ts`](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/tools/ripGrep.ts),
  [`grep-utils.ts`](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/tools/grep-utils.ts)):
  - Khi chỉ có 1-3 kết quả và model không xin context, tool tự thêm ±50 dòng
    (1 kết quả) hoặc ±15 dòng (2-3 kết quả). Comment trong code ghi là giảm
    khoảng 10% số turn trên SWE-bench.
  - Chỉ dùng rg hệ thống khi binary nằm ở đường dẫn hệ thống đáng tin, để
    tránh chạy nhầm một `rg` giả nằm trong repo.
  - Có `fixed_strings`, `max_matches_per_file` và `total_max_matches`.
- **opencode** ([`grep.ts`](https://github.com/sst/opencode/blob/dev/packages/opencode/src/tool/grep.ts),
  [`ripgrep.ts`](https://github.com/sst/opencode/blob/dev/packages/core/src/ripgrep.ts)):
  - Dùng `rg --json`; mỗi dòng cắt ở 2000 ký tự.
  - Khi bị cắt, thông báo kèm luôn cách sửa: `(Results truncated. Consider using
    a more specific path or pattern.)`.
- **Codex**
  ([`grep_files.rs` @ rust-v0.50.0](https://github.com/openai/codex/blob/rust-v0.50.0/codex-rs/core/src/tools/handlers/grep_files.rs)):
  - Từng thử một tool chỉ trả path, sắp theo `--sortr=modified`.
  - Tool này đã bị bỏ; hiện Codex để model gọi `rg` qua shell.
  - Lưu ý: `--sort`/`--sortr` khiến rg chạy đơn luồng.
- **Aider** là hướng ngược lại: không có tool search mà dựng repo map bằng
  tree-sitter rồi xếp hạng bằng PageRank. EvoFlux đã chủ động không làm
  index/graph toàn repo (xem `app/agent/AGENTS.md`), nên hướng này nằm ngoài
  phạm vi.

## Đề xuất cho EvoFlux

### P0 - Ship ripgrep trong sidecar bundle

Đây là thay đổi lợi nhất: không phải đổi schema, mà `grep` trên máy end user
nhanh lên nhiều bậc và đọc đúng gitignore lồng nhau.

- `scripts/build_sidecar.py` tải một bản ripgrep pinned (ví dụ 15.1.0) cho
  từng target triple từ GitHub release của BurntSushi, **kiểm tra SHA-256**,
  rồi đặt vào `sidecar-bundle/bin/rg[.exe]` cùng file license (MIT/Unlicense).
  Smoke test sẽ chạy thử `rg --version` bằng binary đã đóng gói.
- `grep.py` tìm `rg` đã đóng gói trước (đường dẫn truyền vào qua env từ
  Tauri/sidecar, không tự dò trong workspace). Không có thì mới dùng rg hệ
  thống, và chỉ khi nó nằm ngoài workspace, giống cách Gemini kiểm tra.
  Fallback Python giữ nguyên.
- `glob` có thể dùng `rg --files --glob` khi có rg, để hai tool xử lý
  gitignore giống nhau.

### P1 - Output mode, phân trang, thông báo cắt kết quả

Thêm vào `grep` (vẫn tương thích ngược với tham số cũ):

| Tham số | Ý nghĩa |
|---|---|
| `output_mode` | `content` \| `files_with_matches` \| `count` |
| `head_limit` | Số dòng/file trả về; thay thế cho `max_results` (giữ `max_results` làm alias) |
| `offset` | Bỏ qua N mục đầu để lấy trang tiếp theo |

- **Mặc định giữ `content`** trong giai đoạn đầu, vì prompt của các agent seed
  đang giả định output dạng dòng. Chỉ đổi mặc định sang `files_with_matches`
  sau khi đo trên eval nội bộ.
- Mỗi lần bị cắt phải có một dòng cuối cho model, ví dụ `[showing 1-100 of
  340+ matches - pass offset=100 or narrow directory/include]`. `count` luôn
  kèm tổng đầy đủ.
- Pattern sai: trả nguyên lỗi của rg khi fallback `re` cũng không compile
  được, không trả "No matches".

### P2 - Filter và độ chính xác

- `type` (map sang `rg --type`), `fixed_strings`, `multiline` (`rg -U
  --multiline-dotall`). `multiline` thay thế cho lỗi hiện tại "grep is
  line-oriented".
- Tham số `max_per_file` để một file minified không chiếm hết kết quả.
- `files_with_matches` sắp theo mtime (mới nhất trước), giống `glob`.
  Đánh đổi: rg chạy đơn luồng, nên chỉ áp dụng cho mode này.

### P3 - Thử nghiệm, cần đo trước khi bật

- Tự thêm context khi có 1-3 kết quả, như Gemini. Cần A/B trên tác vụ Coding
  vì làm tăng token mỗi lần gọi.

### UI

`display.tsx` đã có header `Searching <pattern> in <dir> (<include>)` và
`ToolCallGroup` đã gom các lời gọi discovery. Khi có P1:

- Header thêm chế độ và kết quả, ví dụ `Searched TODO · 12 files`, và
  `· truncated` khi bị cắt.
- `FileListResult` hiển thị `files_with_matches` thành danh sách file bấm được,
  còn `count` thành bảng `file · số match`.

## Rủi ro và việc cần kiểm tra

- **Supply chain:** binary rg tải về phải pin version + SHA-256 trong repo và
  được ký cùng bundle, giống sidecar Python.
- **Kích thước bundle:** rg khoảng 5-6 MB mỗi platform.
- **Prompt agent:** cần rà các prompt seed và mô tả tool nhắc tới
  `max_results` hoặc output dạng dòng trước khi đổi mặc định.
- **Test:** thêm case cho `offset` vượt quá cuối, `count` có tổng khi bị cắt,
  thông báo cắt kết quả, pattern sai, và thứ tự tìm rg (bundle → hệ thống → Python).
