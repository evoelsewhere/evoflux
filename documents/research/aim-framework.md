# Framework AIM (AI Innovation Modernization) — Nghiên cứu & Thiết kế trên EvoFlux

| | |
|---|---|
| **Trạng thái** | PROPOSED (v1.1 — research + architecture + roadmap) |
| **Ngày** | 2026-07-16 (v1.1: AIM là **mode thứ 3** riêng biệt; v1: cùng ngày, gắn vào Coding mode) |
| **Phạm vi** | Mode chuyên biệt cho dòng dự án legacy migration/modernization, tái sử dụng core harness EvoFlux |
| **Tài liệu liên quan** | [`documents/plans/workflows-feature-plan.md`](../plans/workflows-feature-plan.md) (v5 — prerequisite cho AIM-4), [`documents/analysis/claude-code-vs-evoflux.md`](../analysis/claude-code-vs-evoflux.md) |

---

## Tóm tắt điều hành

**AIM (AI Innovation Modernization)** là **mode thứ ba của EvoFlux** — đứng cạnh Forge và Coding — chịu trách nhiệm riêng cho dòng dự án migration legacy: *hiểu source cũ → convert sang source mới → chứng minh tương đương chức năng (test compare)*. AIM không đụng vào hai mode hiện có; nó tái sử dụng toàn bộ core harness (lead-and-mailbox, code graph, skills, permissions, streaming UI) với workspace model, roster và tool tier riêng.

**Input model của một AIM project** phản ánh đúng thực tế delivery: (1) **base source** — repo(s) legacy cần migrate, mount **read-only**; (2) **target source** — repo đích **đã được dựng base sẵn** (skeleton framework, conventions, CI do solution architect chuẩn bị) mà factory sẽ convert code vào; (3) **KB repo** — knowledge base sinh trong quá trình làm, đồng thời là deliverable giao khách hàng **và là mặt phẳng cộng tác của cả team**: nhiều member, mỗi người một EvoFlux instance ("IDE + agent runner"), tri thức và trạng thái dự án hợp nhất qua git (§3.5-3.6).

Kết quả nghiên cứu ngành (AWS Transform, IBM watsonx Code Assistant for Z, Google Dual Run, GitHub Copilot App Modernization, Thoughtworks CodeConcise, các nghiên cứu học thuật 2024-2026) hội tụ về một kiến trúc chung: **knowledge-first** (parse deterministic + code graph trước, LLM enrich sau), **hybrid deterministic + LLM**, **factory theo migration unit**, và **verification-first** với test-based repair loop. Đáng chú ý: **test compare là khoảng trống lớn nhất** — ngay cả reference implementation mã nguồn mở của Microsoft cũng không có cơ chế verification; đây chính là chỗ AIM tạo khác biệt.

Thiết kế đề xuất: **AIM ≈ content (rulebook packs) + spine mỏng + mode shell mỏng**. Content là các **rulebook pack** cắm theo từng cặp stack nguồn→đích (COBOL→Java, VB6→.NET, Java 8→21…). Spine chỉ có 3 surface backend: state migration (`aim_units`/`aim_runs`/`aim_links`), compare engine deterministic `aim_compare` + golden-master store, structural fallback parser. Mode shell là lớp mỏng: giá trị mode `aim`, tool tier `aim`, roster riêng có lead riêng, route `/aim`, wizard tạo project (base + target + KB + rulebook). **UI của mode là flow-first**: màn hình chính là AIM Board (flow migration của factory + approval inbox + run monitor) — **chat chỉ là drawer tuỳ chọn** để bổ sung ngữ cảnh/trigger/debug, không phải surface chính như Forge/Coding. Đi kèm là **bộ quy tắc UI/UX design-first (§3.13)**: design system/pattern chốt và duyệt trước, cấm convert màn hình hay build surface khi thiết kế chưa duyệt — chống nạn UI conflict khi làm song song. Pipeline AIM biểu diễn bằng workflow YAML theo spec Workflows v5 (cần một mở rộng 1-dòng: scope `aim`), nhưng **AIM-0/1/2/3 không phụ thuộc Workflows** — làm trước được, không chờ.

---

## Phần 1 — Bối cảnh & bài toán

### 1.1 Dòng dự án migration trong công ty phần mềm

Migration/modernization là một trong những dòng dự án ổn định và lớn nhất của các công ty dịch vụ phần mềm: ước tính còn **200-220 tỷ dòng COBOL** đang chạy, chi phí rewrite thủ công 32-50 cent/dòng — bài toán ~100 tỷ USD chỉ riêng mainframe ([XMainframe paper, FPT Software AI Center](https://arxiv.org/abs/2408.04660)). Ngoài mainframe còn các dòng phổ biến không kém: VB6/.NET Framework → .NET hiện đại, Java 6/8/Struts → Java 17+/Spring Boot, PowerBuilder/Delphi/Oracle Forms → web, cùng database migration đi kèm.

Đặc điểm chung của dòng dự án này, khác với dự án phát triển mới:

- **Tri thức nằm trong code, không nằm trong tài liệu.** Tài liệu gốc thất lạc hoặc lỗi thời; SME nghỉ hưu dần; business rules chôn trong hàng nghìn module.
- **Chuẩn thành công là "giống hệt hệ cũ"**, không phải "đúng spec" — vì spec chính là hành vi hệ cũ, kể cả những hành vi kỳ quặc (rounding, padding, xử lý ngày tháng lỗi...).
- **Khối lượng lặp đi lặp lại cao** — hàng trăm/nghìn program, screen, batch job có cấu trúc tương tự → phù hợp mô hình factory + tự động hoá.
- **Khách hàng enterprise yêu cầu audit trail** — mọi thay đổi phải truy vết được từ business rule đến code đến test đến kết quả.
- **Quy trình delivery chuẩn hoá**: solution architect dựng **target base** (skeleton, framework, conventions, CI) trước; đội factory convert từng đơn vị vào base đó — framework phải khớp quy trình này, không phải sinh target từ con số 0.

### 1.2 Ba pain point xuyên suốt SDLC

1. **Hiểu source cũ (reverse engineering).** Đọc hiểu COBOL/VB6/PL-I tốn SME đắt đỏ; ước lượng sai ở giai đoạn này phá vỡ toàn bộ estimation của dự án.
2. **Convert/implement sang source mới (forward engineering).** Transpiler máy móc cho ra code "Java viết kiểu COBOL" không bảo trì được; viết tay thì chậm và lỗi.
3. **Test compare (pain point số 1).** Chứng minh tương đương chức năng chiếm **hơn một nửa timeline và resource** của dự án modernization ([AWS](https://aws.amazon.com/blogs/migration-and-modernization/accelerating-mainframe-modernization-testing-with-aws-transform/)). Khó vì: không có test suite gốc, môi trường legacy khó truy cập, output khác nhau vì lý do "vô hại" (encoding, format ngày, sort order) trộn lẫn với defect thật, và khối lượng so sánh khổng lồ (hàng triệu record).

### 1.3 Tại sao agentic AI, tại sao bây giờ

Giai đoạn 2024-2026 chứng kiến cả 3 hyperscaler + GitHub đưa agentic AI vào modernization như sản phẩm chính thức (AWS Transform GA 5/2025, GitHub Copilot App Modernization GA 9/2025). Điểm chung: không dùng LLM "dịch code" một phát, mà dùng **hệ nhiều agent chuyên biệt + tool deterministic + human gate** phủ từng giai đoạn SDLC. Kết quả đo được đã đủ thuyết phục: Thoughtworks giảm reverse engineering từ 6 tuần/10k LOC xuống ~2 tuần ([Fowler/CodeConcise](https://martinfowler.com/articles/legacy-modernization-gen-ai.html)); AWS/IBM claim rút timeline từ năm xuống tháng.

### 1.4 Tại sao xây trên EvoFlux

EvoFlux đã có sẵn đúng những nền tảng mà các sản phẩm trên phải xây từ đầu:

| Nhu cầu của migration framework | EvoFlux đã có |
|---|---|
| Code comprehension deterministic | Code knowledge graph tree-sitter ~20-25 ngôn ngữ, FTS5, cross-repo resolution (`app/services/code_graph/`) |
| Multi-agent chuyên biệt theo giai đoạn | Teams lead + members qua mailbox, blueprint markdown (`app/agent/mode/team/`, `seed/agents/`) |
| Living documentation SME sửa được | Wiki markdown + Dream engine (`app/services/dream*.py`) |
| Đóng gói tri thức theo stack | Skills / slash commands / snippets resolve theo project `.evoflux/` |
| Chạy pipeline có human gate | Workflows engine (plan v5, node kinds agent/tool/gate/switch/…) |
| Batch định kỳ | Cron scheduler bắn prompt vào chat pipeline (`app/scheduler/`) |
| BYOM | 12 providers — cắm được cả model chuyên dụng như XMainframe của FPT |
| Metrics vận hành | OpenTelemetry + Prometheus + DuckDB + `/telemetry` UI |
| **Khái niệm mode đã là kiến trúc lõi** | Forge/Coding chia sẻ cùng core lead-and-mailbox, streaming UI, permission model — thêm mode thứ 3 là mở rộng theo đúng thớ thiết kế (thậm chí đã có tiền lệ đổi mode: `normalize_mode` từng map `normal`→`forge`, `app/models/chat.py:12-20`) |

Ngoài ra EvoFlux **self-hosted** — quan trọng với dự án outsourcing có ràng buộc bảo mật source code khách hàng (không đẩy code lên SaaS bên thứ ba).

---

## Phần 2 — Nghiên cứu ngành

### 2.1 Bảng landscape tổng quan

| Sản phẩm / công trình | Loại | Phủ giai đoạn | Điểm mạnh nhất | Điểm yếu / khoảng trống |
|---|---|---|---|---|
| [AWS Transform](https://aws.amazon.com/transform/mainframe/) | Hyperscaler SaaS | Assess → Understand → Convert → **Test** → Deploy | Testing agents + Compare tool hoàn chỉnh nhất | Khoá vào AWS, mainframe-centric |
| [IBM watsonx Code Assistant for Z](https://www.ibm.com/products/watsonx-code-assistant-z) | Hyperscaler | Understand → Refactor → Transform → **Validate** | Auto unit-test gen cho semantic equivalence | Khoá vào IBM Z, COBOL→Java |
| [Google Dual Run](https://docs.cloud.google.com/mainframe-dual-run/docs/dual-run-overview) | Hyperscaler | **Test compare / cutover** | Parallel run production — chuẩn vàng equivalence | Chỉ là mảnh test, cần GCP |
| [GitHub Copilot App Modernization](https://github.blog/changelog/2025-09-22-github-copilot-app-modernization-is-now-generally-available-for-java-and-net/) | Dev tool | Assess → Plan → Execute (upgrade) | Plan file + task routing + build-fix loop; rulebook policy | Java/.NET upgrade, không phủ test compare cross-system |
| [Thoughtworks CodeConcise](https://martinfowler.com/articles/legacy-modernization-gen-ai.html) | SI accelerator | **Understand** (reverse engineering) | Knowledge graph từ AST + comprehension pipeline bottom-up | Forward engineering + testing còn speculative |
| [Azure-Samples Legacy-Modernization-Agents](https://github.com/Azure-Samples/Legacy-Modernization-Agents) | OSS reference | Analyze → Map → Convert | Pipeline agent rõ ràng, chunking + complexity scoring | **Không có verification/testing** (tự ghi nhận) |
| [FPT XMainframe](https://arxiv.org/abs/2408.04660) | Model chuyên dụng | (nền tảng model) | LLM 7B/10.5B chuyên COBOL/mainframe + MainframeBench | Là model, không phải framework |
| [Anthropic Code Modernization Playbook](https://resources.anthropic.com/hubfs/Code%20Modernization%20Playbook.pdf) | Playbook | Cả 5 pha | Khung agent 3 loại (understand/convert/test) | Ở mức playbook, không có tooling |

### 2.2 Nhóm hyperscaler — học gì

**AWS Transform** ([reimagine](https://aws.amazon.com/blogs/migration-and-modernization/reimagine-your-mainframe-applications-with-agentic-ai-and-aws-transform/), [refactor](https://aws.amazon.com/blogs/migration-and-modernization/accelerate-mainframe-modernization-with-aws-transform-a-comprehensive-refactor-approach/)) chia 2 con đường: **Refactor** (COBOL→Java, JCL→Groovy, ưu tiên tương đương chức năng, có bước "reforge" dùng LLM nâng readability) và **Reimagine** (reverse-engineer toàn estate → business rules có cấu trúc + data lineage + data dictionary → decompose theo business domain → generate microservices). Điểm kiến trúc đáng học: **specialized agents gọi deterministic purpose-built tools** — LLM không tự làm việc mà điều phối tool xác định. Đặc biệt, mảng testing ([blog riêng](https://aws.amazon.com/blogs/migration-and-modernization/accelerating-mainframe-modernization-testing-with-aws-transform/)) có đủ 5 agent: planning (sinh test case ngôn ngữ tự nhiên **theo business function**, ưu tiên theo complexity/dependency), script generation (sinh JCL thu thập test data từ mainframe — hỗ trợ PS/GDG/PDS/VSAM/DB2, có chỗ cắm sanitization), data collection orchestration, automation execution, và **comparison agent so sánh bit-by-bit** (flat file, PDF, text, binary; DB: Db2/MySQL/Oracle/PostgreSQL/SQL Server). AWS cũng đã công bố pattern kết hợp [AWS Transform + Claude Code](https://aws.amazon.com/blogs/migration-and-modernization/reimagining-mainframe-applications-with-aws-transform-and-claude-code/) — xác nhận hướng "harness tổng quát + tool modernization chuyên dụng" mà AIM/EvoFlux theo đuổi.

**IBM watsonx Code Assistant for Z** ([overview](https://www.ibm.com/products/watsonx-code-assistant-z), [announcement](https://www.ibm.com/new/announcements/ibm-watsonx-code-assistant-for-z-accelerate-the-application-lifecycle-with-generative-ai-and-automation)): chuỗi Understand → Refactor (tách business service từ COBOL bằng slicing theo dependency) → Transform (Granite model) → **Validate**. Bài học lớn nhất là **Validation Assistant: tự sinh unit test để so sánh semantic equivalence** giữa Java mới và COBOL gốc — biến "test compare" thành sản phẩm chứ không phải việc tay.

**Google Dual Run** ([docs](https://docs.cloud.google.com/mainframe-dual-run/docs/dual-run-overview), [blog](https://cloud.google.com/blog/products/infrastructure-modernization/dual-run-by-google-cloud-helps-mitigate-mainframe-migration-risks)): chạy **song song production** hệ cũ và hệ mới với cùng input thật (replay live events), so sánh output — batch (report, DB snapshot) trước, online transaction sau. Nguyên lý gốc: *"If the input of both systems is the same, so must be the output"*. Đây là chuẩn vàng để **cutover không rủi ro**, và là hình mẫu cho tầng cao nhất của test-compare harness trong AIM.

### 2.3 Nhóm dev-tool — GitHub Copilot App Modernization

([GA changelog](https://github.blog/changelog/2025-09-22-github-copilot-app-modernization-is-now-generally-available-for-java-and-net/), [repo](https://github.com/microsoft/github-copilot-modernization), [blog](https://github.blog/ai-and-ml/github-copilot/how-github-copilot-and-ai-agents-are-saving-legacy-systems/)) — orchestrator 3 pha: **Assessment** (phân tích app, nhận diện cơ hội) → **Planning** (sinh `plan.md` + `tasks.json` theo enterprise policy) → **Execution** (route task đến executor agent chuyên biệt: Java upgrade, javax→jakarta, Spring Boot, Azure migration, CVE fix; tự fix build error, validate, tăng test coverage). Hai pattern đáng học: (1) **plan file + task routing** — trạng thái pipeline là file có cấu trúc, agent làm việc trên đó; (2) **rulebook** — doanh nghiệp nhúng chuẩn kiến trúc đích/policy của mình vào workflow. AIM lấy đúng từ "rulebook" cho khái niệm content pack.

### 2.4 Nhóm SI & OSS

**Thoughtworks CodeConcise** ([Fowler article](https://martinfowler.com/articles/legacy-modernization-gen-ai.html)) — quan trọng nhất về phương pháp luận "hiểu code cũ":

- **Code as data**: parse deterministic ra AST, lưu vào graph DB (Neo4j), edges là control flow / calls / inherits. LLM **không** được dùng để hiểu syntax — đó là việc của parser.
- **Comprehension pipeline bottom-up**: enrich node bằng LLM theo tầng trừu tượng tăng dần (method → class → package → capability), node cấp cao dùng kết quả node cấp thấp làm context. Graph-RAG: vector/lexical search tìm node liên quan rồi **traverse tiếp neighbors** để lấy context — thay vì nhét cả file vào prompt.
- **Kết quả đo được**: reverse engineering 10.000 LOC COBOL/IDMS từ 6 tuần → ~2 tuần; ngoại suy tiết kiệm ~240 FTE-year cho cả chương trình.
- **Bài học phản diện**: naive RAG (embed cả file) thất bại với legacy — file không cohesive làm nhiễu context; GenAI không thay được stakeholder alignment (vẫn cần Event Storming, ubiquitous language); human phải giữ quyền kiểm soát output.
- Về forward engineering, bài viết thừa nhận conversion máy móc cho ra code kém idiomatic, và **"lengthy testing and verification cycles" vẫn là gap chưa có lời giải GenAI cụ thể** — khoảng trống mà AIM nhắm vào. Thí nghiệm nội bộ mới hơn của Thoughtworks với Claude Code + CodeConcise ([blog](https://www.thoughtworks.com/en-de/insights/blog/generative-ai/claude-code-codeconcise-experiment)) cho thấy harness tổng quát + knowledge graph là hướng đúng nhưng cần guardrails.

**Microsoft Legacy-Modernization-Agents** ([Azure-Samples](https://github.com/Azure-Samples/Legacy-Modernization-Agents), [devblog](https://devblogs.microsoft.com/all-things-azure/how-we-use-ai-agents-for-cobol-migration-and-mainframe-modernization/)) — reference OSS gần nhất với những gì AIM sẽ build: `CobolAnalyzerAgent` → `BusinessLogicExtractorAgent` → `DependencyMapperAgent` (Neo4j, edges CALL/COPY/PERFORM/EXEC/READ/WRITE) → `JavaConverterAgent`/`CSharpConverterAgent`; chunking theo division/section/paragraph khi file >3.000 dòng; **complexity scoring 3 mức điều khiển reasoning effort** (low 1.5× / medium 2.5× / high 3.5× output tokens); portal realtime + dependency graph + Q&A. Nhưng chính README của nó không có cơ chế verification/testing nào — **xác nhận độc lập rằng test compare là khoảng trống thị trường**, kể cả trong hệ sinh thái Microsoft.

**FPT XMainframe** ([paper](https://arxiv.org/abs/2408.04660), [GitHub](https://github.com/FSoft-AI4Code/XMainframe), [HuggingFace](https://huggingface.co/Fsoft-AIC/XMAiNframe-instruct-7b)) — LLM 7B/10.5B (nền DeepSeek-Coder) fine-tune cho mainframe/COBOL + benchmark MainframeBench (MCQ, QA, COBOL summarization); vượt trội các model tổng quát cùng cỡ trên miền này. Ý nghĩa với AIM: EvoFlux là BYOM (12 providers, kể cả Ollama local) nên **rulebook COBOL có thể chỉ định model chuyên dụng nội bộ như XMainframe cho các agent understand/summarize**, trong khi agent convert dùng model reasoning mạnh — đúng triết lý "model là component thay được".

### 2.5 Nghiên cứu học thuật về LLM code translation (2024-2026)

Hướng nghiên cứu repository-level translation hội tụ về cùng kết luận với industry:

- **Dịch một phát không đủ tin cậy** — cần **test-based repair loop**: dịch → chạy test/so output → đưa failure/diff vào context → sửa → lặp. Các hệ như UniTrans, ExeCoder, TransAgent, BabelCoder đều theo mẫu này ([survey](https://arxiv.org/pdf/2604.25960)).
- **Repo-level cần decompose neuro-symbolic**: AlphaTrans dùng static analysis chia nhỏ + dịch theo thứ tự dependency; [MatchFixAgent](https://arxiv.org/pdf/2509.16187) kết hợp program analysis + LLM agents để **tự sinh targeted tests phục vụ validation + repair** — đúng mô hình `aim-test-engineer` + `aim-converter` của AIM.
- **Cẩn thận "false failures"**: một phần đáng kể test fail khi so sánh bản dịch không phải do dịch sai mà do khác biệt môi trường/format ([nghiên cứu](https://arxiv.org/html/2605.02195v3)) — củng cố yêu cầu **canonicalization trước khi diff** và bước **diff triage** trong thiết kế AIM.

### 2.6 Bảy bài học kiến trúc hội tụ

1. **Knowledge-first.** Xây knowledge base truy vấn được (code graph + docs sinh tự động + business rules catalog) TRƯỚC khi convert. Parse deterministic là nền; LLM enrich phía trên; naive RAG thất bại.
2. **Hybrid deterministic + LLM.** Việc máy móc hoá được (parse, dependency, diff, transform theo rule) dùng tool xác định; LLM cho việc cần phán đoán (naming, idiom, tách service, triage).
3. **Migration unit + dependency ordering.** Chia estate thành đơn vị (program/job/screen/module/table), sắp thứ tự leaves-first theo dependency graph, chạy như **factory** có WIP tracking theo wave.
4. **Verification-first.** Build-fix loop, test oracle, compare harness là công dân hạng nhất — không phải bước cuối. Repair loop lấy diff làm context sửa code đã được chứng minh cả trong industry lẫn học thuật.
5. **Human-in-the-loop tại gate xác định.** SME duyệt business rules; architect duyệt mapping; analyst duyệt phán quyết "acceptable difference". AI đề xuất — người quyết ở các điểm chốt, và các gate này được thiết kế sẵn trong pipeline chứ không tuỳ hứng.
6. **Traceability xuyên suốt.** rule ↔ code cũ ↔ code mới ↔ test ↔ kết quả compare — yêu cầu audit của khách hàng enterprise, đồng thời là dữ liệu điều hành dự án.
7. **Metrics vận hành.** Automation rate, first-pass compile rate, equivalence pass rate, SME-hours saved — nuôi estimation model và câu chuyện bán hàng của dòng dự án.

### 2.7 Deep-dive: Test Compare — giải phẫu pain point

#### 2.7.1 Vì sao đau

- **Không có oracle sẵn**: hệ cũ thường không có test suite; "spec" là hành vi runtime.
- **Môi trường legacy khó truy cập**: mainframe của khách, môi trường chỉ chạy giờ hành chính, data nhạy cảm cần sanitize.
- **Diff nhiễu**: encoding (EBCDIC vs UTF-8), format ngày/số, padding fixed-width, sort order không ổn định, timestamp/run-id — khác biệt "vô hại" trộn lẫn defect thật khiến so sánh thô gần như vô dụng.
- **Khối lượng**: batch hàng triệu record; so tay không khả thi.

#### 2.7.2 Năm tầng kỹ thuật (rẻ → đắt, dùng kết hợp)

| Tầng | Kỹ thuật | Nguồn tham chiếu | Khi nào dùng |
|---|---|---|---|
| 1 | **Golden master / characterization**: chụp input+output hệ cũ thành bộ case chuẩn | AWS test-data collection scripts | Mặc định cho mọi unit; nền của regression về sau |
| 2 | **Auto unit-test generation cho semantic equivalence**: sinh test từ code/rule cũ, chạy trên code mới | IBM WCA4Z Validation Assistant, MatchFixAgent | Unit thuần logic, tách được khỏi I/O |
| 3 | **Batch dual run**: chạy cả 2 hệ cùng input, so file/report/DB snapshot | Google Dual Run (batch), AWS Compare tool | Batch job — dễ nhất, ROI cao nhất |
| 4 | **Online replay/shadow**: capture transaction thật, replay vào hệ mới, so response + state | Google Dual Run (online, preview) | Giai đoạn cutover của hệ transaction |
| 5 | **Parallel run production**: 2 hệ chạy song song production một thời gian trước khi cắt | Google Dual Run, thực hành parallel running kinh điển | Hypercare — mức bảo hiểm cao nhất |

#### 2.7.3 Nguyên tắc thiết kế harness (rút cho AIM)

1. **Canonicalize trước, diff sau** — mọi so sánh đi qua pipeline chuẩn hoá cấu hình được (encoding, mask volatile fields, sort, tolerance số học); diff bit-exact chỉ thực hiện trên dạng canonical.
2. **Compare là tool deterministic, không phải LLM** — kết quả lặp lại được, audit được; LLM chỉ dùng ở tầng **triage** (phân loại cluster diff: defect / acceptable / golden nghi ngờ).
3. **Mọi phán quyết "acceptable difference" phải có vết**: cite rule/ADR, human gate duyệt, và vật chất hoá thành thay đổi cấu hình canonicalizer được commit (audit trail) — không bao giờ là lời nói suông của model.
4. **Repair loop khép kín**: diff report là context đầu vào cho converter agent sửa code, lặp đến pass hoặc hết budget — đây là điểm nghiên cứu học thuật chứng minh tăng chất lượng mạnh nhất.
5. **Provenance của golden master là first-class**: captured từ env thật / replay từ log / synthesized có SME ký — vì chất lượng equivalence không thể vượt quá chất lượng oracle.

---

## Phần 3 — Thiết kế: AIM là mode thứ 3 của EvoFlux

### 3.1 Triết lý thiết kế

> **AIM là một mode riêng biệt (Forge / Coding / AIM), chịu trách nhiệm riêng cho dòng dự án legacy — nhưng là mode shell mỏng trên core harness dùng chung.** Mọi thứ đặc thù theo stack là *content* (rulebook pack); backend chỉ thêm *spine* không thể là content (state có index, compare engine, parser legacy); mode shell chỉ thêm workspace model + roster + tool tier + UI surface — **không fork** agent loop, mailbox, streaming, permissions.

Lý do tách mode thay vì gắn vào Coding (như v1 của tài liệu này):

1. **Trách nhiệm và vòng đời khác nhau**: Coding phục vụ "làm việc lâu dài trong codebase của mình"; AIM phục vụ một **dự án có bắt đầu-kết thúc, có phase, có wave, có certify**. Trộn hai mental model làm rối cả hai.
2. **Workspace model khác nhau về bản chất**: AIM project luôn có cấu trúc **base source (read-only) + target source (đã dựng base) + KB** — không phải "một nhóm repo ngang hàng" như CodingProject.
3. **An toàn**: mode riêng cho phép enforce bất biến quan trọng nhất của dòng dự án migration ngay ở tầng hạ tầng: **không bao giờ sửa source legacy** (xem 3.3).
4. **Sản phẩm hoá**: màn hình chính của mode là **flow board của factory** (tiến độ unit/wave/equivalence, hàng đợi duyệt) — không phải chat, và không phải một panel phụ trong Coding. Persona vận hành AIM là delivery lead/operator tư duy theo dây chuyền, tương tác theo sự kiện (gate cần duyệt, run fail, unit certified) chứ không theo hội thoại; chat trở thành kênh phụ tuỳ chọn (xem 3.12).
5. **Đúng thớ kiến trúc hiện có**: Forge/Coding vốn đã "chia sẻ cùng lead-and-mailbox core, cùng streaming UI, cùng permission model" (README); mode là chiều mở rộng được thiết kế sẵn — `ChatSession.mode` là string có helper `normalize_mode` (từng rename `normal`→`forge`, `app/models/chat.py:12-20`), tool registry có sẵn `tiers` (`app/agent/tools/registry.py:144-167`), router có sẵn pattern `/coding/$focusId/$sessionId` để nhân bản (`web/src/router.ts:29-45`).

### 3.2 Ba mode của EvoFlux sau khi có AIM

| | **Forge** | **Coding** | **AIM** (mới) |
|---|---|---|---|
| Workspace | Sandbox dùng một lần per session | Repo/multi-repo project của bạn | **AIM project = base source (read-only) + target source (đã dựng base) + KB repo** |
| Dùng cho | Task một lần: research, viết lách, prototype | Làm việc lâu dài trong codebase | **Dự án migration legacy trọn vòng đời: assess → understand → convert → test compare → cutover** |
| Team mặc định | lead + consultant + executor + explorer + debate | lead + architect + coder + explorer + debate | **aim-lead + appraiser + archaeologist + target-architect + converter + test-engineer + triage-analyst** (+ explorer/debate dùng chung) |
| Tooling thêm | — | Git, code graph, file tree | **Code graph trên cả legacy (structural parser) + `aim_units`/`aim_compare` + golden store + rulebook + dashboard factory** |
| Vòng đời session | Ephemeral | Persistent theo workspace | **Persistent theo AIM project; trạng thái pipeline sống trong `aim_units` (ngoài session)** |
| Màn hình chính | Chat | Chat + workspace panel | **AIM Board — flow migration (phase/wave/equivalence) + approval inbox + run monitor; chat là drawer tuỳ chọn** |

### 3.3 Concept model & input của AIM mode

**Input của một AIM project** (theo đúng quy trình delivery):

1. **Base source** — repo(s) legacy. **Nhiều module / nhiều repository là trường hợp mặc định, không phải ngoại lệ**: `roles.source` là danh sách; cross-repo code graph (3-tier resolution có sẵn) resolve CALL/COPY/import xuyên repo; unit đặt tên namespace `<module>/<unit>`. Mount **read-only**: đây là bất biến của mode, enforce ở tầng sandbox/permission (xem dưới), không phụ thuộc prompt.
2. **Target source** — repo đích **đã được dựng base**: solution architect đã chọn framework, dựng skeleton/layering, conventions, build/CI. AIM **không sinh target từ con số 0** — nó convert từng migration unit *vào* base này. Hệ quả thiết kế: phase Understand phải hiểu **cả hai phía** (legacy sâu + target-base conventions), và phase Design bị ràng buộc bởi base (mapping phải conform).
3. **KB repo** — tạo mới (từ template) hoặc chỉ định; là bộ nhớ dự án + deliverable.
4. **Rulebook** — chọn pack theo cặp stack (3.7).

**Mapping vào hạ tầng (quyết định thiết kế):**

- **`ChatSession.mode = "aim"`** — giá trị thứ 3 của field string hiện có (`app/models/chat.py:106`); các điểm validate mode thêm 1 nhánh.
- **Project substrate: tái sử dụng `CodingProject` + cột discriminator `kind` (`"coding"` mặc định | `"aim"`)** thay vì bảng project mới. Lý do: cross-repo code graph, project routes (reindex/resolve/search), file tree, git surface đều key theo `CodingProject` — dùng lại là được "miễn phí" toàn bộ; bảng mới đồng nghĩa nhân đôi các đường ống đó. Vai trò repo (source/target/kb) khai báo trong **`aim.yaml` ở gốc KB repo** (nhận diện repo bằng identity dùng chung — remote URL/tên logic — để chia sẻ được giữa các member); `settings["aim"]` cục bộ chỉ giữ mapping workspace_id local ↔ role (schema ở 3.5). Coding mode filter `kind="coding"`, AIM mode filter `kind="aim"` — hai mode không thấy project của nhau.
- **Read-only base source** — năng lực spine mới, nhỏ nhưng giá trị an toàn lớn: `SandboxConfig` (`app/agent/sandbox.py`) thêm khái niệm **write-deny roots** theo vai trò workspace (source repos vào danh sách này khi session mode=aim); các tool ghi (`write/edit/patch/rm`) và shell command scan từ chối đường dẫn thuộc write-deny roots. Đọc/index/grep vẫn bình thường.
- **Tool tier `"aim"`**: `aim_units`/`aim_compare` đăng ký `tiers=("aim",)`; các tool nền (fs/shell/python/git/code graph/web) thêm `"aim"` vào tiers hiện có. Registry đã hỗ trợ sẵn cơ chế này.
- **Roster riêng có lead riêng**: `seed/agents/aim/` gồm `aim-lead` (`role: lead` — hiểu state machine `aim_units`, điều phối phase, biết khi nào gọi workflow nào) + 6 member (3.10). Cơ chế load theo thư mục đã có (`app/agent/loader.py` `load_team_from_dir`).
- **Route `/aim/$focusId[/$sessionId]`** — nhân bản pattern `/coding/...` trong `web/src/router.ts`; layout tái dùng `TeamChatView` với `forcedMode='aim'`; focus = AIM project.

### 3.4 Pipeline SDLC 6 giai đoạn

| # | Giai đoạn | Mục tiêu | Agent chính | Artifact chuẩn | Human gate |
|---|---|---|---|---|---|
| 0 | **Assess** | Inventory đơn vị migration, complexity, wave plan, estimation | `aim-appraiser` | `aim_units` + `inventory/units.md` | Duyệt wave plan |
| 1 | **Understand** | (a) Legacy: module docs + business rules + data dictionary (bottom-up theo dependency); (b) **Target base: trích conventions/layering/pattern vào KB** | `aim-archaeologist` | `modules/*.md`, `business-rules/BR-*.md`, `data-dictionary/`, **`target-conventions.md`** | SME xác nhận rules theo batch |
| 2 | **Design target** | Mapping per-unit theo rulebook, **conform target base** (không thiết kế lại kiến trúc — base đã chốt); **chốt design system UI + pattern mapping màn hình + UX ADR một lần cho cả project** (§3.13A) | `aim-target-architect` | `mapping/<unit>.md`, `ui-conventions.md`, ADR | Architect duyệt mapping; BA/SME duyệt UI conventions |
| 3 | **Convert** | Forward engineering per unit trong worktree của target repo, build-fix loop, smoke compare | `aim-converter` | Code target + unit tests + PR | Code review |
| 4 | **Test & Compare** | Chứng minh tương đương: golden run → compare → triage → repair → certify | `aim-test-engineer`, `aim-triage-analyst`, `aim-converter` | `report.json/md`, `aim_runs`, canonicalizer diffs | Duyệt equivalence + acceptable diffs |
| 5 | **Cutover / Hypercare** | Checklist parity, parallel-run kế hoạch, theo dõi sau go-live | roster tổng hợp | Cutover checklist, run history | Go/no-go |

Mỗi giai đoạn = 1-2 workflow YAML + skills phương pháp + artifact có schema. Trạng thái tiến độ per-unit nằm trong `aim_units.phase` (`inventory → understood → designed → converted → equivalent → cutover`) — **pipeline dừng/chạy lại bất kỳ lúc nào vì state nằm ngoài workflow run** (tôn trọng "không durable runs" của Workflows v5).

### 3.5 Migration state — KB repo là system of record, bảng `aim_*` là index cục bộ

Thiết kế state phải trả lời câu hỏi thực tế của dự án nhiều người: **mỗi member chạy một EvoFlux instance riêng trên máy mình** (EvoFlux là single-user, local-first — vai trò như "IDE của factory"), vậy trạng thái chung của cả dự án sống ở đâu? Trả lời: **trong chính KB repo (git)** — đúng nguyên tắc EvoFlux đã dùng cho code graph: *nguồn sự thật nằm trong file git-tracked, index cục bộ derive từ đó, ai clone cũng rebuild được*.

**1) Manifest project — `aim.yaml` ở gốc KB repo** (config chia sẻ cho cả team, không chôn trong DB cục bộ của một máy):

```yaml
# <project>-aim-kb/aim.yaml
rulebook: {id: cobol-java, version: "0.3"}
roles:                    # repo nhận diện bằng identity dùng chung (remote URL / tên logic),
  source: [core-batch, core-online, common-copybooks]   # KHÔNG phải workspace_id cục bộ
  target: [payroll-java]
golden_dir: golden
compare_default_profile: batch-text-v1
```

`CodingProject.settings["aim"]` (field JSON có sẵn, `app/models/chat.py:310-317`) chỉ còn giữ **mapping cục bộ**: workspace_id local ↔ role trong `aim.yaml`. Member mới join = clone KB + các repo, wizard đọc `aim.yaml` và chỉ hỏi mapping — không phải "xin cấu hình" của người setup đầu.

**2) Unit state — frontmatter trong file per-unit** (`modules/<module>/<unit>.md`): `phase`, `wave`, `assignee`, `kind`, `source_paths`, `target_paths`, `depends_on`, `complexity`, links. File-per-unit nên merge git gần như không bao giờ conflict — hai người sửa cùng một unit là lỗi phân công, không phải lỗi công cụ.

**3) Run history — commit vào KB**: `runs/<unit>/<run-id>/report.{json,md}` + `meta.yaml` (verdict, kind, session ref). Append-only theo thư mục → không conflict.

**4) Bảng `aim_*` = index cục bộ derive từ KB** (rebuild được bất kỳ lúc nào, không phải nguồn sự thật) — để board/API query nhanh trên estate 10²-10⁴ unit. Một Alembic migration (sau `00000020` của workflows) + cột `kind="aim"` trên `coding_projects` (xem 3.3):

| Bảng | Index từ | Vai trò |
|---|---|---|
| `aim_units` | frontmatter `modules/**` | Inventory + WIP cho board; query `(project_id, phase)` |
| `aim_runs` | `runs/**` | Lịch sử run + verdict cho dashboard |
| `aim_links` | frontmatter units/rules | Traceability matrix (yêu cầu audit) |

Watcher file (pattern có sẵn — code graph đã có watcher per-workspace) reindex khi KB đổi: **`git pull` xong là board cập nhật**.

**Tool `aim_units`** (pattern `@tool` tại `app/agent/tools/registry.py`, đăng ký trong `_default_tool_registry` ở `app/agent/loader.py`) vẫn là **write-path duy nhất** cho agents (`get/list/set_phase/record_run/add_link`), nhưng nó **ghi file frontmatter + cập nhật index**, không ghi DB "chay" — mọi thay đổi state đi qua git như code: có lịch sử, có blame, có revert, có review.

**Đồng bộ nhiều người**: mặc định qua git — pull/push theo nhịp run (per-run session commit KB giống commit code ở target repo). Board mỗi máy "tươi" đến lần pull gần nhất; với nhịp factory (một unit tính bằng giờ) độ trễ này chấp nhận được. Team muốn board realtime chung: trỏ mọi instance vào **shared Postgres** (`DATABASE_URL` đã hỗ trợ sẵn) — đây là nâng cấp vận hành, không đổi thiết kế.

### 3.6 Knowledge Base — repo git riêng

**Quyết định: KB là một repo git riêng** (`<project>-aim-kb`), add vào project như một `CodingWorkspace` bình thường — **không** dùng wiki toàn cục (wiki bị khoá cấu trúc 2 cấp và pin subdirs tại `app/services/wiki.py:158-201`; hợp đồng của Dream là session→wiki, không phải codebase comprehension). Lợi ích: git-trackable (KB chính là **deliverable giao khách hàng**), agent ghi bằng fs tools thường, FTS/code-graph index được, cross-repo link với source/target.

```
<project>-aim-kb/
  aim.yaml                        # manifest project: rulebook + roles các repo (identity chung) — §3.5
  INDEX.md
  inventory/units.md              # bảng tổng hợp sinh từ frontmatter modules/** (bản đọc nhanh cho người)
  modules/<module>/<unit>.md      # kiểu CodeConcise + frontmatter STATE (phase, wave, assignee…) — §3.5;
                                  #   namespace theo module khi source nhiều repo
  business-rules/BR-<MOD>-####.md # 1 rule / file; ID prefix theo module (chống trùng khi nhiều người tạo);
                                  #   frontmatter: id, status(candidate|confirmed), source refs
  data-dictionary/<record>.md     # copybook/record layout/table → từ điển field chuẩn
  interfaces/{screens,jobs,apis}/
  target-conventions.md           # trích từ target base: layering, naming, pattern, build/CI (phase 1b)
  ui-conventions.md               # design system đích + pattern mapping màn hình + UX ADR refs (§3.13A)
  mapping/<unit>.md               # quyết định thiết kế target per unit (conform target-conventions)
  decisions/ADR-###.md            # gồm cả các "accepted difference" từ triage
  golden/                         # golden-master store (xem 3.8)
  runs/<unit>/<run-id>/report.md  # report nhỏ vào git; actuals thô gitignored
```

**Comprehension pipeline** (kiểu CodeConcise, bottom-up): xếp unit leaves-first theo `code_edges` (calls/imports/contains) → mỗi unit một turn agent đọc source + graph neighborhood + **docs của các callee đã viết trước đó** → ghi `modules/<module>/<unit>.md` + trích candidate `business-rules/` → human gate xác nhận rule theo batch. Phía target: một pass nhẹ hơn trích `target-conventions.md` từ target base (đọc skeleton + build files + sample code). Trước khi có Workflows engine, pipeline chạy bằng slash command `/aim-understand-unit`.

**Nhiều source repo & nhiều người cùng xây KB** (mô hình vận hành):

- **Estate nhiều module/repo là mặc định**: `roles.source` trong `aim.yaml` là danh sách; cross-repo code graph resolve CALL/COPY xuyên repo; wave thường trùng ranh giới module; `interfaces/` ghi **hợp đồng giữa các module** — thứ quan trọng nhất khi hai nhóm convert hai module có nói chuyện với nhau.
- **KHÔNG có "một người scan cả estate"**: phần scan/index là *deterministic và cục bộ* — máy của ai clone repo nào thì tự index repo đó (graph là dữ liệu derive, không cần chia sẻ). Phần comprehension (LLM viết docs) **chia theo module/wave cho từng member** — mỗi người chạy agent trên máy mình, output đổ về KB qua git. Wave 0 = các lá dùng chung (copybooks/common) do một nhóm nhỏ làm trước để mọi người đứng trên cùng nền docs.
- **Convention chống dẫm chân**: claim unit bằng `assignee` trong frontmatter (một commit — thấy ngay trên board của mọi người sau pull); BR ID prefix theo module (`BR-<MOD>-####`); ADR đánh số theo PR.
- **SME confirm = PR review trên KB repo** — git-native: reviewer duyệt `business-rules/*.md`, `mapping/*.md` như duyệt code, audit trail có sẵn từ git history; Approval Inbox (3.12) là lối tắt cho gate *trong lúc chạy* trên máy mỗi người, còn quyết định tri thức dài hạn (rule confirmed, UI conventions, ADR) đi qua PR để cả team thấy.
- Hệ quả đẹp: **KB đồng thời là mặt phẳng cộng tác** — EvoFlux mỗi máy chỉ là "IDE + agent runner"; git server của team (GitLab/GitHub nội bộ) mới là chỗ dự án hội tụ, đúng như mô hình code hiện nay.

**Chiến lược ngôn ngữ legacy 3 tầng** (chọn per rulebook qua `parser_strategy`):

- **Tier 1 — tree-sitter thật** khi grammar đủ tốt: subclass `TreeSitterParser` và đăng ký (pattern có sẵn `app/services/code_graph/parsers/base.py`). Java/C#/Pascal-Delphi đã có sẵn → rulebook Java 8→21 **không cần việc parser nào**.
- **Tier 2 — structural fallback parser (mặc định cho COBOL/JCL/PL-I/RPG/VB6)**: xem 3.9.
- **Tier 3 — LLM enrichment vào KB** cho phần extractor không thấy: chunk theo đơn vị structural của Tier 2, viết prose vào `modules/`. Retrieval giữ lexical FTS + graph + KB markdown — **không vector RAG naive** (backend vector tuỳ chọn `memory_vector.py` bật sau được mà không đổi thiết kế).

### 3.7 Rulebook content pack — đóng gói tri thức theo cặp stack

Rulebook là một **thư mục content pack**, sống tại `{EVOFLUX_CONFIG_DIR}/aim/rulebooks/<id>/` (bundled mẫu: `app/agent/builtin_aim/rulebooks/`; override per-project: `<kb-repo>/.evoflux/aim/rulebooks/`):

```
rulebook.yaml            # manifest: id, version, source/target stacks, unit kinds,
                         #   map đuôi file, parser_strategy (tree_sitter|structural|none),
                         #   compare profiles mặc định, entrypoint runner scripts
agents/*.md              # overlay roster lõi (vd: thêm skills: [cobol-idioms] cho converter)
skills/<name>/SKILL.md   # tri thức stack: idiom mapping, gotchas, pattern EXEC CICS/SQL
commands/*.md            # slash shortcuts cho thời kỳ pre-workflows
workflows/*.yaml         # pipeline templates theo schema v5 (scope: aim)
mappings/*.md            # bảng mapping construct (PERFORM→method, VSAM→JPA, copybook→DTO…)
canonicalizers/*.yaml    # profile chuẩn hoá compare (xem 3.8)
extractors/*.yaml        # pattern config cho structural parser (xem 3.9)
runners/*.sh|*.py        # script môi trường: chạy job legacy, chạy target, export DB→CSV
target-base/             # (tuỳ chọn) template/checklist dựng target base cho cặp stack này —
                         #   hỗ trợ solution architect chuẩn hoá bước "dựng base"; gồm cả UI kit
                         #   (component library + layout templates) nếu stack có UI (§3.13A R1)
ui-patterns/*.md         # bảng mapping pattern màn hình legacy → template đích (search-list,
                         #   detail-edit, wizard…) — bắt buộc với stack screen-heavy (VB6, Oracle Forms)
```

**Ngữ nghĩa install**: service nhỏ `aim_rulebook_service` copy `agents/` → `{CONFIG_DIR}/agents/aim-<stack>-*.md` (đúng tiền lệ seed install tại `app/core/workspace_init.py`), copy `skills/commands/workflows` → `.evoflux/{skills,commands,workflows}/` của KB workspace — **mọi cơ chế discovery hiện có tự nhận, zero thay đổi loader**. `mappings/canonicalizers/extractors/runners` tham chiếu tại chỗ. `aim.yaml` của KB ghi rulebook id+version (chia sẻ cho cả team — ai install cũng ra cùng phiên bản); upgrade = re-install (first-source-wins giữ override của project).

Đây chính là "product hoá tri thức dự án": sau mỗi dự án, những gì team học được (mapping mới, canonicalizer case mới, gotcha mới) **commit ngược vào rulebook pack** — tài sản tái sử dụng của cả dòng dự án, thứ các công ty dịch vụ đang thiếu công cụ để tích luỹ.

### 3.8 Test-compare harness (trọng tâm đầu tư)

**(a) Golden-master store — trên đĩa, trong KB repo** (version được, review được, giao được):

```
golden/units/<unit>/cases/<case-id>/
  input/          # files, stdin, DB seed exports (CSV), job params
  expected/       # output legacy: files, report PDF→text, DB snapshot CSV
  meta.yaml       # provenance: captured|prod_log_replay|synthesized; lệnh capture;
                  # canonicalizer profile; codepage (EBCDIC cpXXX); env fingerprint;
                  # SME sign-off ref
```

Actuals thô của từng run vào `.aim-actuals/<run-id>/` (gitignored); report nhỏ (`report.json/md`) vào `runs/` trong git. File lớn: git-lfs hoặc exclude.

**(b) Tool `aim_compare` — compare engine deterministic** (builtin tool mới `app/agent/tools/builtin/aim_compare.py`, pattern `@tool` chuẩn, `tiers=("aim",)`):

- Args: `unit`, `case_set` *hoặc* cặp `left`/`right` path tường minh, `profile`, `report_dir` tuỳ chọn.
- **Canonicalizer pipeline** theo profile YAML từ rulebook, chạy per file-class: chuyển encoding (EBCDIC codepage→UTF-8), mask trường volatile (timestamp/run-id/counter), chuẩn hoá whitespace + number format, sort-before-diff cho output không thứ tự, so sánh field-level theo schema fixed-width/CSV có tolerance, PDF→text. DB compare = so CSV snapshot do `runners/` export (phạm vi files-first; driver DB live để sau).
- Diff **bit-exact trên dạng canonical** → `report.json` (per file: match|diff|missing|extra; per record/field khi có schema) + `report.md` cho người đọc.
- **Contract trả về JSON compact**: `{"verdict": "pass|fail", "diff_count": N, "clusters": [...], "report_path": "..."}` — để tool-node của workflow parse được và templating `{{nodes.compare.output.verdict}}` hoạt động theo v5 §4.3.

**(c) Diff-triage agent loop**: `aim-triage-analyst` đọc `report.json` theo cluster, phân loại từng cluster: `defect` | `acceptable_difference` (bắt buộc cite rule/ADR) | `golden_suspect`. Acceptable difference vật chất hoá thành **YAML diff đề xuất cho canonicalizer profile** → human gate duyệt → commit vào KB (audit trail). Mọi disposition ghi qua `aim_units` vào `aim_runs`/`aim_links` — khép kín traceability rule↔code↔test↔run.

**(d) Repair loop**: v5 Phase 1 cấm cycle trong DAG (validate tại save), nên vòng lặp sửa nằm **trong turn của converter agent**: node `repair` là agent node có `aim_compare` trong tool của blueprint, tự lặp fix→compare trong turn (kỷ luật test-driven-development) đến khi pass hoặc hết budget; node compare **cuối** của workflow là verdict chính thức. Trung thực với ngữ nghĩa v5, không cần sửa engine.

**(e) Dashboard data**: `aim_units` + `aim_runs` phía sau `GET /api/team/projects/{id}/aim/summary` (+ `/units`, `/runs/{id}`), đặt cạnh các route code-graph per-project hiện có trong `app/api/routes/team/projects.py`.

### 3.9 Structural fallback parser — đưa legacy vào code graph

Điểm mấu chốt đã xác minh: `LanguageParser` Protocol chỉ yêu cầu `name`, `extensions`, `parse(file_path, source) -> ParseResult` — **không bắt buộc tree-sitter**, và header của `app/services/code_graph/parsers/registry.py:1-6` tuyên bố rõ đây là extension point ("Nothing else in the pipeline needs to change").

- **`parsers/structural.py` (mới)**: extractor regex/line-structural tổng quát, cấu hình bằng `extractors/*.yaml` của rulebook. Ví dụ COBOL: divisions/sections/paragraphs = nodes; `PERFORM`/`CALL`/`COPY` = edges calls/imports; target của `EXEC SQL/CICS` = references. JCL: steps = nodes, `PGM=`/`DD DSN=` = edges. (Đúng cách Azure-Samples đã chứng minh hiệu quả bằng regex.)
- **Thay đổi engine duy nhất**: `build_registry()` thêm tham số `extra_parsers` (hiện chỉ khởi tạo builtins tại `registry.py:92-99`), luồn từ config workspace/rulebook qua `code_graph_service.py`; indexer giữ nguyên (resolve qua `registry.for_path`).
- **Kết quả**: code legacy vào thẳng `code_nodes`/`code_edges`/FTS5 → mọi code-graph tool hiện có (`code_search`, `code_graph`, overview, path) **hoạt động với COBOL/JCL** — nền "deterministic parsing + graph TRƯỚC, LLM SAU" thành hiện thực cho legacy.

### 3.10 Roster AIM — team riêng của mode

Roster lõi stack-generic tại `seed/agents/aim/` (blueprint markdown nhẹ như roster hiện có — xem `seed/agents/coding/architect.md`); rulebook overlay skills stack qua `agents/*.md` của pack. Load theo cơ chế thư mục sẵn có (`load_team_from_dir`, một `role: lead` per dir).

| Blueprint | Role | Giai đoạn | Tools/skills chính |
|---|---|---|---|
| `aim-lead` | **lead** | Điều phối toàn pipeline | Hiểu state machine `aim_units`; quyết định phase/wave tiếp theo; gọi đúng workflow; tổng hợp báo cáo. Tool: `aim_units`, code graph, delegate |
| `aim-appraiser` | member | 0 — Assess | code graph tools, `aim_units`; wave planning, complexity scoring |
| `aim-archaeologist` | member | 1 — Understand | code_search/code_path, fs write vào KB; skill `aim-legacy-comprehension` |
| `aim-target-architect` | member | 1b+2 — Target conventions & Design | spec-driven-development, api-and-interface-design + `mappings/` của rulebook + `target-conventions.md` |
| `aim-converter` | member | 3+4 — Convert/Repair | worktree_start/finish, edit/patch, shell, `aim_compare`; test-driven-development, deprecation-and-migration (đều đã builtin) |
| `aim-test-engineer` | member | 4 — Test | shell/python, `aim_compare`, `aim_units`; sinh test plan theo business function + golden case synthesis (pattern AWS) |
| `aim-triage-analyst` | member | 4 — Triage | `aim_compare` (đọc), `aim_units`; skill `aim-diff-triage` |

(`explorer`/`debate` của roster chung có thể thêm vào team khi cần khảo sát tự do hoặc second opinion.)

### 3.11 Thư viện workflow AIM (conform schema v5 + mở rộng scope `aim`)

**Phụ thuộc nhỏ vào Workflows plan**: schema v5 hiện định nghĩa `scope: forge | coding` và validate "coding definitions require a coding session" (v5 §4.2, §9.1). AIM cần **mở rộng enum scope thêm `aim`** (workflow scope `aim` chạy trong session mode `aim`, project của session là target) — thay đổi ~vài dòng ở models/validation, đề xuất đưa vào Workflows M1 hoặc một patch nhỏ sau M6. Các ràng buộc còn lại được tôn trọng nguyên vẹn: sequential-topological, không cycle, gate = `ask_user` choices, `foreach` body đúng 1 node inline, inputs scalar (enum có `options`), filter chỉ `json`/`truncate`, chỉ `gate`/`switch` có edge `when:` (không match → kết thúc graceful), node ready khi mọi edge vào resolved và ≥1 fired (§6.3).

**`aim-assess.yaml`** — inventory + wave plan có gate duyệt:

```yaml
schema_version: 1
name: aim-assess
scope: aim
inputs:
  - {name: wave_size, type: number, required: false}
nodes:
  - id: overview
    kind: tool
    tool: code_overview
    args: {}
  - id: inventory
    kind: agent
    subagents: [aim-appraiser]
    prompt: |
      Xây/refresh inventory đơn vị migration cho project này.
      Dùng code_search/code_graph cho dependencies; ghi units, complexity và
      wave plan (wave size mục tiêu {{inputs.wave_size}}) qua tool aim_units,
      và viết inventory/units.md trong KB repo.
      Tổng quan graph: {{nodes.overview.output.text | truncate:4000}}
  - id: wave_gate
    kind: gate
    title: "Duyệt wave plan migration"
    body: "{{nodes.inventory.output.text | truncate:2000}}"
    choices: [approve, rework]
  - id: mark
    kind: tool
    tool: aim_units
    args: {action: set_project_phase, phase: assessed}
  - id: ping
    kind: notify
    message: "Assessment xong — wave plan đã được duyệt."
edges:
  - {from: overview, to: inventory}
  - {from: inventory, to: wave_gate}
  - {from: wave_gate, to: mark, when: approve}   # "rework" → kết thúc graceful (v5 §6.3)
  - {from: mark, to: ping}
```

**`aim-convert-unit.yaml`** — per-unit là hình thức chính (ngắn, restartable, idempotent nhờ phase state trong `aim_units`); bulk wave là wrapper `aim-convert-wave` với `foreach` body = 1 agent node trên `{{item}}` (gate không được phép trong body — đã duyệt per-wave ở upstream):

```yaml
schema_version: 1
name: aim-convert-unit
scope: aim
inputs:
  - {name: unit, type: string, required: true}
nodes:
  - id: ctx
    kind: tool
    tool: aim_units
    args: {action: get, unit: "{{inputs.unit}}"}   # → JSON: paths, rules, mapping refs
  - id: design
    kind: agent
    subagents: [aim-target-architect]
    prompt: |
      Tạo/refresh mapping/{{inputs.unit}}.md trong KB. Cite các business rule
      đã confirmed, bảng mapping của rulebook, và tuân thủ target-conventions.md
      (mapping phải conform target base — không tự chế kiến trúc mới).
      Context unit: {{nodes.ctx.output | json | truncate:3000}}
  - id: design_gate
    kind: gate
    title: "Duyệt target mapping cho {{inputs.unit}}"
    body: "{{nodes.design.output.text | truncate:2000}}"
    choices: [approve, rework]
  - id: convert
    kind: agent
    subagents: [aim-converter]
    prompt: |
      Implement {{inputs.unit}} vào target repo theo mapping đã duyệt.
      Làm trong worktree (worktree_start/finish); viết unit tests; chạy
      aim_compare với golden smoke cases và sửa đến khi pass hoặc hết 3 vòng.
      Nhắc: source legacy là read-only — mọi thay đổi chỉ ở target repo.
  - id: smoke
    kind: tool
    tool: shell
    args: {command: "cd <target-repo> && ./gradlew test --tests '*{{inputs.unit}}*'"}
  - id: mark
    kind: tool
    tool: aim_units
    args: {action: set_phase, unit: "{{inputs.unit}}", phase: converted}
  - id: ping
    kind: notify
    message: "{{inputs.unit}} đã convert — sẵn sàng test-compare."
edges:
  - {from: ctx, to: design}
  - {from: design, to: design_gate}
  - {from: design_gate, to: convert, when: approve}
  - {from: convert, to: smoke}
  - {from: smoke, to: mark}
  - {from: mark, to: ping}
```

**`aim-test-compare.yaml`** — golden master + run target + compare + triage + repair + gate certify (repair lặp bên trong turn của converter — không cycle):

```yaml
schema_version: 1
name: aim-test-compare
scope: aim
inputs:
  - {name: unit, type: string, required: true}
  - {name: case_set, type: enum, required: true, options: [smoke, full]}
nodes:
  - id: run_target
    kind: tool
    tool: shell                    # runner deterministic từ rulebook
    args: {command: "./.evoflux/aim/runners/run_target.sh {{inputs.unit}} {{inputs.case_set}}"}
  - id: compare
    kind: tool
    tool: aim_compare
    args: {unit: "{{inputs.unit}}", case_set: "{{inputs.case_set}}"}
  - id: verdict
    kind: switch
    value: "{{nodes.compare.output.verdict}}"
  - id: triage
    kind: agent
    subagents: [aim-triage-analyst]
    prompt: |
      Triage report compare tại {{nodes.compare.output.report_path}}.
      Phân loại từng diff cluster: defect | acceptable_difference (cite rule/ADR)
      | golden_suspect. Ghi disposition qua aim_units; đề xuất thay đổi
      canonicalizer profile dưới dạng YAML diff nếu khác biệt chấp nhận được.
  - id: repair
    kind: agent
    subagents: [aim-converter]
    prompt: |
      Sửa các defect từ kết quả triage dưới đây trong target repo. Chạy lại
      aim_compare cho {{inputs.unit}}/{{inputs.case_set}} sau mỗi lần sửa,
      đến khi pass hoặc hết 3 vòng.
      Triage: {{nodes.triage.output.text | truncate:3000}}
  - id: final_compare
    kind: tool
    tool: aim_compare
    args: {unit: "{{inputs.unit}}", case_set: "{{inputs.case_set}}"}
  - id: equiv_gate
    kind: gate
    title: "Chấp nhận functional equivalence cho {{inputs.unit}} ({{inputs.case_set}})?"
    body: "Verdict cuối: {{nodes.final_compare.output.verdict}} — report: {{nodes.final_compare.output.report_path}}"
    choices: [accept, reject]
  - id: mark
    kind: tool
    tool: aim_units
    args: {action: set_phase, unit: "{{inputs.unit}}", phase: equivalent}
  - id: ping
    kind: notify
    message: "{{inputs.unit}} được chứng nhận equivalent trên bộ case {{inputs.case_set}}."
edges:
  - {from: run_target, to: compare}
  - {from: compare, to: verdict}
  - {from: verdict, to: mark,   when: pass}       # pass thẳng
  - {from: verdict, to: triage, when: fail}
  - {from: triage, to: repair}
  - {from: repair, to: final_compare}
  - {from: final_compare, to: equiv_gate}
  - {from: equiv_gate, to: mark, when: accept}    # reject → kết thúc graceful; run giữ trạng thái fail trong aim_runs
  - {from: mark, to: ping}
```

(Node `mark` có 2 edge vào từ switch/gate — hợp lệ theo §6.3: node ready khi mọi edge vào *resolved* và ≥1 *fired*; nhánh không đi qua bị đánh dấu dead nên không deadlock.)

Thư viện đầy đủ về sau: `aim-understand` (comprehension bottom-up 2 phía), `aim-convert-wave` (foreach), `aim-cutover-check`.

### 3.12 UI của AIM mode — flow-first, chat là kênh phụ tuỳ chọn

**Nguyên tắc: màn hình chính của AIM là dòng chảy migration, không phải chat.** Persona vận hành AIM (delivery lead / PM / factory operator) đặt câu hỏi dashboard — "cái gì đang ở đâu, cái gì blocked, cái gì chờ tôi duyệt, equivalence bao nhiêu %" — và tương tác theo **sự kiện** (gate cần duyệt, run fail, unit được certify), không theo hội thoại. Forge/Coding là chat-first vì công việc là exploratory; AIM là factory nên **flow-first**. Chat vẫn tồn tại nhưng là **drawer tuỳ chọn**: bổ sung ngữ cảnh cho agent, hỏi đáp ad-hoc ("vì sao unit này fail hoài?"), trigger thủ công, debug. EvoFlux đã có tiền lệ surface không-phải-chat làm màn hình chính (`/telemetry`, `/scheduler`, Monitor view) — AIM đi cùng thớ đó.

**Ràng buộc kiến trúc quan trọng — flow UI là renderer khác của CÙNG execution substrate, không phải engine mới.** Mọi thứ vẫn chạy qua session + turn + SSE stream; workflows vẫn inline-in-session đúng v5 (không durable runs). Cụ thể:

- **Session model: một session ngầm PER-RUN** (đã chốt — không dùng một "session vận hành" chung per project). Mỗi run từ board = FE tạo một session AIM mới (đặt tên theo `<unit>/<workflow>/<n>`, `project_id` trỏ về AIM project) rồi gọi đúng API mà composer sẽ gọi (`POST /api/workflows/{name}/run {session_id, inputs}` — v5 §9.1); thời pre-workflows thì bắn prompt/slash-command vào session đó qua chat pipeline như scheduler vẫn làm. Lý do per-run: (1) chạy **song song nhiều unit** tự nhiên — ràng buộc v5 "một execution active per session" thành per-run thay vì nghẽn cổ chai cả project; (2) khớp mô hình per-unit idempotent + worktree per-unit; (3) transcript mỗi run là **artifact audit khép kín** (chat drawer của run mở đúng session đó); (4) run hỏng thì bỏ session, chạy lại unit — không rác lịch sử chung. Session per-run được auto-archive sau khi run kết thúc; Run Monitor là nơi tổng hợp thay cho việc lục danh sách session.
- Human gate vẫn là `ask_user` — chỉ đổi **chỗ render**: Approval Inbox thay vì bubble trong chat; câu trả lời route về đúng question của session bên dưới (API questions có sẵn: `app/api/routes/team/questions.py`).
- Tiến độ run render từ `workflow_progress` SSE (v5 M5 đã định nghĩa event + FE reducer — AIM tái dùng, nâng từ "pill trong chat" thành panel).
- **Không có execution path thứ hai** — board/inbox/monitor chỉ là projection; mở chat drawer của một run là thấy đúng transcript của session đó.

**Các surface:**

1. **AIM Board (màn hình chính)** — flow visualization của factory: cột theo phase (`inventory → understood → designed → converted → equivalent → cutover`), unit là card (kind, complexity, wave, verdict gần nhất), nhóm/filter theo wave; live update qua SSE. Có **chế độ trình bày** ("showoff" cho steering meeting/presale): wave burn-up, % equivalence theo wave, animation unit chảy qua các phase.
2. **Approval Inbox** — hàng đợi mọi human gate của project (duyệt wave plan, duyệt mapping, certify equivalence, duyệt acceptable-difference/canonicalizer diff): card có preview ngữ cảnh + approve/reject. Đây là hình thức UI của nguyên tắc human-in-the-loop (2.6 #5) — gate không trôi trong transcript mà nằm trong work queue.
3. **Run Monitor** — các run đang chạy (unit, workflow, node hiện tại, thời lượng); click = timeline node + report links + nút "mở transcript" (chat drawer của session run đó).
4. **Unit detail** — hồ sơ per-unit: traceability từ `aim_links` (rules ↔ code ↔ tests ↔ runs), lịch sử `aim_runs`, golden cases, nút hành động (`Run convert`, `Run test-compare smoke/full`).
5. **Chat drawer (tuỳ chọn, mặc định đóng)** — slide-over gắn với project hoặc với session của một run; tái dùng `TeamChatView` nguyên vẹn (Split/Monitor vẫn dùng được khi mở full).
6. **Route & wizard**: `/aim/$focusId` mở thẳng AIM Board (nhân bản pattern route `/coding` trong `web/src/router.ts`, nhưng component gốc là Board chứ không phải chat view). **`AimSetupWizard`** 4 bước: (1) tên project + chọn rulebook, (2) add base source repo(s) (đánh dấu read-only), (3) add target repo **đã dựng base** (+ checklist từ `target-base/` của rulebook nếu có), (4) KB repo (tạo từ template / chỉ định). Ghi `CodingProject(kind="aim")` + `settings["aim"]` (mapping cục bộ) + sinh `aim.yaml` vào KB. Chế độ **Join existing**: chọn/clone KB repo có sẵn → wizard đọc `aim.yaml` và chỉ hỏi mapping repo local (§3.5).
7. **Không cần gì AIM-specific trên workflow canvas** — pipeline AIM là YAML v5 thường; `aim_compare`/`aim_units` xuất hiện như tool node bình thường (tuỳ chọn thêm Tier-A tool preset).

**Trade-off thừa nhận**: flow-first làm FE scope của AIM lớn hơn "một panel" (board + inbox + monitor + drawer). Giảm rủi ro bằng cách ship theo lớp: AIM-2 chỉ cần board dạng kanban/bảng đơn giản đọc `aim_units` + chat drawer làm đường trigger; inbox/monitor/animation dồn về AIM-5 khi workflows đã có SSE progress để tái dùng.

### 3.13 Quy tắc thiết kế UI/UX — design-first, cấm "chạy luôn"

Bài học từ thực tế dòng dự án: **UI/UX làm theo kiểu "chạy luôn" — mỗi agent/mỗi unit/mỗi màn tự quyết giao diện — luôn thất bại vì các mảnh conflict lẫn nhau**: N màn hình ra N kiểu, component trùng lặp, luồng thao tác mỗi nơi một phách, không nghiệm thu được. Nguyên nhân gốc không phải code kém mà là *quyết định thiết kế bị đưa ra rải rác*. Nguyên tắc xuyên suốt: **design-first** (thiết kế được duyệt trước khi code), **pattern-based** (lắp từ khuôn, không vẽ tự do), **một nguồn sự thật**. Áp dụng ở hai tầng:

**(A) Cho app đích của dự án migration** — rules của framework, sống trong rulebook + KB:

| # | Rule | Enforce bằng |
|---|---|---|
| R1 | **Chưa có design system đích thì chưa convert màn hình nào.** UI kit (component library, layout templates, conventions cho validation/error/empty-state/i18n) thuộc target base, dựng & duyệt ở phase Design | Gate phase 2; checklist + starter kit trong `target-base/` của rulebook |
| R2 | **Convert theo pattern, không theo cảm hứng.** Screen inventory (phase Understand) phân loại màn theo pattern (search-list, detail-edit, master-detail, wizard, report…); `ui-conventions.md` quy định pattern legacy → template đích nào; convert một màn = instantiate template + map field/validation. N màn cùng pattern → cùng một khuôn | `ui-patterns/` trong rulebook; `mapping/<unit>.md` phải cite pattern |
| R3 | **Converter chỉ lắp từ UI kit** — cấm tự chế component/style per màn | Code review + lint (style ngoài design token → fail CI) |
| R4 | **Modernize có chủ đích, quyết một lần.** Thay đổi UX so với hệ cũ (menu→navigation, multi-window→tab, gộp bước màn 3270…) là ADR cấp project chốt ở phase Design; per màn không quyết lại; deviation phải cite ADR | `decisions/ADR-*.md`; review/triage đối chiếu |
| R5 | **Test compare cho UI đo task parity, không đo pixel.** Scenario script (browser automation built-in của EvoFlux) chạy nghiệp vụ trên app đích + `aim_compare` so DB state/output sau thao tác + checklist field-level (mọi field/validation màn cũ được ánh xạ hoặc có ADR loại bỏ); screenshot chỉ phục vụ human review | `aim-test-engineer` sinh scenario từ business rules; golden của màn hình = state/output, không phải ảnh |
| R6 | **Gate UI theo wave màn hình** — BA/SME duyệt trên staging; không auto-certify màn hình chỉ bằng script | Approval Inbox |

**(B) Cho chính UI của AIM mode** — kỷ luật khi build EvoFlux:

| # | Rule | Enforce bằng |
|---|---|---|
| R7 | **UX spec trước code**: mỗi surface (Board/Inbox/Monitor/Unit detail/Drawer) có user journey theo persona (operator, SME, architect) + wireframe + interaction contract (SSE event nào cập nhật vùng nào), duyệt xong mới implement | Điều kiện vào của AIM-2 và AIM-5 (§4.1) |
| R8 | **Không sáng chế design system riêng** — dùng đúng token/component hiện có (Tailwind v4 + shadcn/base-ui, pattern panel/`SettingsModal`); AIM phải nhìn như một phần EvoFlux | Review; không thêm dependency UI mới ngoài `@xyflow/react` đã plan |
| R9 | **Một việc — một nơi**: trigger ở Board/Unit detail, duyệt ở Inbox, theo dõi ở Monitor, hội thoại ở Drawer — không rải nút trùng chức năng khắp các surface | Action map là một phần của UX spec (R7) |
| R10 | **Một nguồn sự thật cho state hiển thị**: mọi surface render từ `aim_units`/`aim_runs` + SSE; cấm state suy diễn cục bộ (Board nói `converted` trong khi Drawer nói đang chạy = bug thiết kế, không phải bug code) | Query/reducer dùng chung (TanStack Query + SSE reducer) |
| R11 | **Rule cho agent, không chỉ cho người**: vì EvoFlux tự build bằng agent, R7-R10 đóng gói thành skill `aim-ui-conventions` gắn vào agent làm FE | Skill + review checklist |

Điểm chung của hai tầng: ép mọi quyết định UI lên **trước**, vào **một chỗ có duyệt** — phần sau chỉ còn lắp ráp; song song hoá bao nhiêu cũng không conflict vì không còn gì để "tự quyết" giữa chừng.

---

## Phần 4 — Roadmap & Rủi ro

### 4.1 Roadmap

Prerequisite cho AIM-4: **Workflows M1-M6** theo [plan v5](../plans/workflows-feature-plan.md) (+ mở rộng scope `aim` ~vài dòng). **AIM-0/1/2/3 không phụ thuộc Workflows** — chạy song song được; AIM-2 và AIM-3 cũng song song nhau được.

| Phase | Nội dung | Định nghĩa "xong" |
|---|---|---|
| **AIM-0 — Content pack** ✅ **ĐÃ IMPLEMENT** (2026-07-16, zero backend change; làm mới hoàn toàn cho AIM mode — không pilot trong Coding, theo quyết định của user) | Roster 7 blueprint tại `seed/agents/aim/` (gồm `aim-lead` — full prompt body vì role mới không có builtin instructions, đã xác minh qua `app/agent/loader.py`); 6 method skills tại `app/agent/builtin_skills/aim-*` (đã pass `scripts/validate_skills.py`, **live ngay hôm nay** vì đây là discovery root có sẵn); 4 slash command tại `seed/commands/` (staging — chưa auto-discover, có README hướng dẫn copy thủ công); KB template tại `seed/aim-kb-template/`; 2 rulebook pack tại `app/agent/builtin_aim/rulebooks/{java8-java21,vb6-dotnet}/` (đủ rulebook.yaml, agents/ overlay, skills/, mappings/, canonicalizers/, runners/, target-base/checklist; vb6-dotnet có thêm `extractors/vb6-structural.yaml` + `ui-patterns/`); 3 workflow YAML generic tại `app/agent/builtin_aim/workflows/` | Content pack hoàn chỉnh — đối chiếu chéo bằng script (frontmatter/YAML parse, tên skill khớp thư mục thật, node/edge trong workflow YAML hợp lệ theo v5 §6.3, tool name `code_overview`/`shell` xác minh khớp registry thật) + `pytest` (119+ test liên quan agent loader/skills/workspace-init đều pass, không regress); README cập nhật 44→50 skill. **Milestone chạy được đầu tiên vẫn = AIM-0 + AIM-2 gặp nhau** (chưa tới — cần mode shell) |
| **AIM-1 — State + compare spine** (mode-agnostic) | State layer §3.5: `aim.yaml` + frontmatter per-unit trong KB (**system of record**) + 3 bảng `aim_*` **index cục bộ** (+ cột `kind` trên `coding_projects`) + watcher reindex KB sau pull; tool `aim_units` (ghi frontmatter + index) + `aim_compare`; golden store layout + canonicalizer engine (profile YAML: masks, sort, encoding, fixed-width schemas); API `/aim/summary\|units\|runs` | Golden case capture từ mẫu legacy so sánh deterministic được; agent tự hoàn thành vòng fix→compare chỉ bằng tools; **hai máy clone cùng KB thấy cùng board sau `git pull`** |
| **AIM-2 — Mode shell** | **UX spec + wireframe các surface duyệt trước khi code (§3.13B R7)**; `mode="aim"` + validation; tool tier `aim`; roster seed `seed/agents/aim/` với `aim-lead`; **read-only base source** (write-deny roots trong `SandboxConfig` theo vai trò workspace); route `/aim/$focusId` mở **AIM Board skeleton** (kanban/bảng đơn giản đọc `aim_units` qua API summary, live SSE) + **chat drawer** (đường trigger thời pre-workflows); `AimSetupWizard` (tạo mới hoặc **join project có sẵn**: clone KB → đọc `aim.yaml` → chỉ hỏi mapping repo local) | Tạo được AIM project qua wizard; **member thứ hai join bằng clone KB không cần xin cấu hình**; mở `/aim/<project>` thấy Board (không phải chat); session mode aim chạy với roster AIM; mọi tool ghi bị chặn trên base source (test chứng minh); Coding/Forge không thấy AIM project và ngược lại |
| **AIM-3 — Legacy graph** (song song AIM-2) | `parsers/structural.py` + hook `build_registry(extra_parsers=...)`; extractor configs COBOL/JCL; validate code_search/FTS trên estate mẫu; hoàn thiện thứ tự bottom-up trong skill comprehension | Estate COBOL index vào code_nodes/edges; `aim-archaeologist` viết module docs leaves-first |
| **AIM-4 — Pipelines** (sau Workflows M6 + scope `aim`) | Thư viện workflow YAML (3.11 + `aim-understand`, `aim-convert-wave`, `aim-cutover-check`); `aim_rulebook_service` install pack vào discovery roots; approval-manifest v5 tự phủ các node `aim_compare`/`aim_units`/shell | `/workflow aim-test-compare <unit> smoke` chạy end-to-end có gates trong session AIM |
| **AIM-5 — Mission control hoàn thiện + scale** | **UX spec vòng 2 (Inbox/Monitor/Unit detail) duyệt trước khi code (R7)**; AIM Board đầy đủ + **Approval Inbox** (gates render ngoài chat, trả lời route về `ask_user`/questions API) + **Run Monitor** (từ `workflow_progress` SSE, tái dùng reducer M5) + Unit detail traceability + chế độ trình bày (wave burn-up, % equivalence — dùng cho steering meeting); pattern batch qua scheduler ("xử lý N unit tiếp theo"); đề xuất scheduler-trigger cho v5 Phase 2 nếu pilot cần chạy đêm không người | Vận hành trọn một wave **hoàn toàn từ board** (trigger, duyệt gate, xem report) không cần mở chat; báo cáo equivalence xuất cho khách hàng |

### 4.2 Rủi ro & giải pháp

| # | Rủi ro | Giải pháp |
|---|---|---|
| 1 | **Parser legacy yếu** (tree-sitter COBOL kém; PL-I/RPG tệ hơn) | Chiến lược 3 tầng, structural parser là mặc định (Azure-Samples đã chứng minh regex đủ tốt để seed graph); đo extraction recall trên pilot estate trước khi commit Tier 1; Tier 3 LLM phủ phần còn lại |
| 2 | **Không capture được golden từ env legacy** (rất phổ biến ở outsourcing) | `meta.yaml` ghi provenance bắt buộc: `captured` (ưu tiên — runner script kiểu AWS để khách tự chạy) / `prod_log_replay` / `synthesized` (bắt buộc SME sign-off gate); triage có disposition `golden_suspect` để master yếu không âm thầm certify equivalence |
| 3 | **Workflow không durable + `/workflow` là FE-intercepted** (scheduler không trigger được workflow ở Phase 1 — v5 F17/§9.1) | Decompose per-unit idempotent (state trong `aim_units`/disk, crash = chạy lại unit); batch đêm = scheduled prompt thường cho `aim-lead` ("xử lý N unit chưa xử lý theo skill aim-understand") — scheduler hỗ trợ sẵn; đề xuất scheduler-trigger ở v5 Phase 2 |
| 4 | **LLM triage tự phán "acceptable"** | Triage không bao giờ final: `acceptable_difference` bắt buộc cite rule/ADR + human gate; nới canonicalizer = YAML diff được duyệt và commit vào KB; mọi disposition trace được trong `aim_runs`/`aim_links` |
| 5 | **Single-node scale** (SQLite + 1 máy) | Indexing đã job hoá per-repo; compare stream per unit; wave giới hạn batch size; giới hạn trung thực: 1 máy / project line — scale factory = N máy × N project, không phải 1 cluster; Postgres qua `DATABASE_URL` khi cần |
| 6 | **`foreach` sequential chậm với wave lớn** (Phase 1) | Chạy per-unit song song bằng nhiều session/worktree (đã isolate); `foreach.concurrency` của v5 Phase 2 giải quyết sau mà không đổi YAML |
| 7 | **Rulebook drift vs bản copy đã install** | Rulebook id+version pin trong `aim.yaml` của KB (cả team cùng thấy); lệnh re-install; first-source-wins giữ override của project — đánh đổi chấp nhận được cho zero thay đổi loader |
| 8 | **Chất lượng convert phụ thuộc model** | BYOM per-agent: model reasoning mạnh cho architect/converter, model rẻ cho việc máy móc, model chuyên dụng (vd XMainframe) cho understand COBOL; complexity scoring của unit (học từ Azure-Samples) điều khiển thinking_level |
| 9 | **Chi phí duy trì mode thứ 3** (3 mode cùng sống) | Mode = shell mỏng: không fork agent loop/mailbox/streaming/permission; chỉ own workspace model + roster + tier + route + wizard + board. Kỷ luật: mọi thứ dùng chung được thì để ở core; test ranh giới mode (project filter theo `kind`, tier gating) trong CI |
| 10 | **Flow-first UI có nguy cơ tách đôi execution path** (board tự chế cách chạy riêng, trôi khỏi mô hình inline của v5) | Board/Inbox/Monitor chỉ là **renderer** trên cùng session + SSE stream: run từ board dùng đúng `POST /api/workflows/{name}/run` với session ngầm; gate dùng đúng `ask_user`/questions API; tiến độ từ `workflow_progress` (M5). Cấm mọi đường chạy riêng trong review. FE scope tăng → ship theo lớp (kanban đơn giản ở AIM-2, inbox/monitor/animation ở AIM-5) |
| 11 | **UI app đích hổ lốn khi convert màn hình song song** ("chạy luôn" không có design system — N màn ra N kiểu, không nghiệm thu được) | §3.13A: cấm convert màn khi chưa có UI kit trong target base (R1); pattern mapping bắt buộc — convert = instantiate template (R2); lint chặn style ngoài kit (R3); UX ADR quyết một lần cấp project (R4); test UI = task parity thay pixel-diff (R5); gate BA/SME theo wave màn hình (R6) |
| 12 | **Cộng tác nhiều người qua git**: board stale (quên pull/push), trùng BR ID, hai người cùng làm một unit | State là frontmatter trong KB + index derive (§3.5) nên mọi máy **hội tụ sau pull** — không có state cục bộ nào bị mất; auto-pull + watcher reindex; BR ID prefix theo module; claim unit bằng `assignee` (một commit, thấy trên board mọi người); SME confirm qua PR review; conflict git trên file per-unit = tín hiệu lỗi phân công, không phải lỗi công cụ; cần realtime → shared Postgres (`DATABASE_URL` có sẵn) |

### 4.3 Câu hỏi mở

1. **DB-compare scope**: bắt đầu bằng export-to-CSV snapshot (đơn giản, deterministic); khi nào driver DB live (so trực tiếp Db2/Oracle/Postgres) đáng đầu tư?
2. **Ma trận EBCDIC codepage per khách hàng** — canonicalizer phải cấu hình được per case, không chỉ per project.
3. **Business rules confirmed có nên chảy ngược vào wiki toàn cục** (qua Dream) để tái sử dụng cross-project? Tạm hoãn — wiki bị ràng buộc cấu trúc (`app/services/wiki.py:158-201`).
4. **Online/transaction replay** (tầng 4 của test compare): cần capture-replay infra riêng — để sau khi batch compare chứng minh giá trị.
5. **Estimation model**: dữ liệu `aim_units.complexity` + thời gian thực tế per phase tích luỹ qua các dự án → nuôi model estimation cho presale; cần chuẩn hoá metrics từ AIM-1.
6. **Target base do ai chuẩn hoá đến đâu**: `target-base/` trong rulebook là template hay chỉ checklist? Mức tự động hoá bước dựng base (scaffold generator?) — để mở, quyết sau 1-2 pilot khi thấy pattern lặp lại.
7. **Forge/Coding có được mở AIM project không**: mặc định không (filter theo `kind`), nhưng có nên cho Coding mode "attach read-only" vào target repo của AIM project khi cần sửa ngoài luồng? Cần quy tắc rõ để không phá traceability.
8. **Khi nào cần "server mode"**: v1 chủ trương mỗi member một instance + git làm mặt phẳng hội tụ (đúng local-first, không cần user model — EvoFlux hiện không có multi-tenant). Nếu pilot cho thấy nhu cầu board realtime chung/phân quyền theo role là thật, cân nhắc shared Postgres trước, rồi mới đến một instance server chung — đó là ngã rẽ sản phẩm lớn, quyết sau khi có dữ liệu pilot.

### 4.4 Metrics thành công (đo qua telemetry hiện có + `aim_runs`)

- **Automation rate**: % unit đi hết phase 3-4 không cần sửa tay ngoài repair loop.
- **First-pass compile rate** và **first-pass equivalence rate** per rulebook (đo chất lượng mapping/prompt của pack).
- **Equivalence pass rate** theo wave/case_set — con số báo cáo khách hàng.
- **SME-hours saved** ở phase Understand (baseline: ~6 tuần/10k LOC theo số Thoughtworks).
- **Diff triage precision**: % phán quyết `acceptable_difference` bị human gate đảo — đo độ tin của triage agent.
- **UI consistency**: % màn hình convert pass lint UI-kit và dùng đúng template pattern (R2/R3) — đo trực tiếp nạn "mỗi màn một kiểu".

---

## Phụ lục A — Nguồn tham khảo

**Hyperscalers**
- AWS: [Reimagine mainframe với agentic AI](https://aws.amazon.com/blogs/migration-and-modernization/reimagine-your-mainframe-applications-with-agentic-ai-and-aws-transform/) · [Comprehensive refactor approach](https://aws.amazon.com/blogs/migration-and-modernization/accelerate-mainframe-modernization-with-aws-transform-a-comprehensive-refactor-approach/) · [Accelerating modernization testing](https://aws.amazon.com/blogs/migration-and-modernization/accelerating-mainframe-modernization-testing-with-aws-transform/) · [AWS Transform + Claude Code](https://aws.amazon.com/blogs/migration-and-modernization/reimagining-mainframe-applications-with-aws-transform-and-claude-code/) · [Tackling large portfolio](https://aws.amazon.com/blogs/migration-and-modernization/tackling-large-mainframe-portfolio-with-agentic-ai-and-aws-transform/) · [Product page](https://aws.amazon.com/transform/mainframe/)
- IBM: [watsonx Code Assistant for Z](https://www.ibm.com/products/watsonx-code-assistant-z) · [Announcement: accelerate application lifecycle](https://www.ibm.com/new/announcements/ibm-watsonx-code-assistant-for-z-accelerate-the-application-lifecycle-with-generative-ai-and-automation) · [IBM Research: COBOL→Java](https://research.ibm.com/blog/cobol-java-ibm-z)
- Google: [Dual Run overview](https://docs.cloud.google.com/mainframe-dual-run/docs/dual-run-overview) · [Dual Run blog](https://cloud.google.com/blog/products/infrastructure-modernization/dual-run-by-google-cloud-helps-mitigate-mainframe-migration-risks) · [Mainframe Assessment Tool](https://docs.cloud.google.com/mainframe-assessment-tool/docs/mainframe-modernization-overview)

**Dev tools & OSS**
- GitHub: [Copilot App Modernization GA](https://github.blog/changelog/2025-09-22-github-copilot-app-modernization-is-now-generally-available-for-java-and-net/) · [microsoft/github-copilot-modernization](https://github.com/microsoft/github-copilot-modernization) · [How Copilot and AI agents are saving legacy systems](https://github.blog/ai-and-ml/github-copilot/how-github-copilot-and-ai-agents-are-saving-legacy-systems/) · [Docs: upgrade projects](https://docs.github.com/en/copilot/tutorials/upgrade-projects)
- Microsoft: [Azure-Samples/Legacy-Modernization-Agents](https://github.com/Azure-Samples/Legacy-Modernization-Agents) · [devblog: How we use AI agents for COBOL migration](https://devblogs.microsoft.com/all-things-azure/how-we-use-ai-agents-for-cobol-migration-and-mainframe-modernization/)

**SI & consulting**
- Thoughtworks: [Legacy Modernization meets GenAI (Martin Fowler site)](https://martinfowler.com/articles/legacy-modernization-gen-ai.html) · [Claude Code + CodeConcise experiment](https://www.thoughtworks.com/en-de/insights/blog/generative-ai/claude-code-codeconcise-experiment) · [Mainframe modernization with AI](https://www.thoughtworks.com/en-us/clients/mainframe-modernization-ai)

**Model & benchmark**
- FPT Software AI Center: [XMainframe paper (arXiv 2408.04660)](https://arxiv.org/abs/2408.04660) · [FSoft-AI4Code/XMainframe](https://github.com/FSoft-AI4Code/XMainframe) · [XMAiNframe-instruct-7b](https://huggingface.co/Fsoft-AIC/XMAiNframe-instruct-7b)

**Playbook & học thuật**
- Anthropic: [Code Modernization Playbook (PDF)](https://resources.anthropic.com/hubfs/Code%20Modernization%20Playbook.pdf)
- [MatchFixAgent: repository-level translation validation & repair (arXiv 2509.16187)](https://arxiv.org/pdf/2509.16187) · [LLMs for Multilingual Code Intelligence: A Survey (arXiv 2604.25960)](https://arxiv.org/pdf/2604.25960) · [Beyond Translation Accuracy: False Failures (arXiv 2605.02195)](https://arxiv.org/html/2605.02195v3) · [In-Isolation Validation in Repo-Level Translation (arXiv 2511.21878)](https://arxiv.org/pdf/2511.21878)

## Phụ lục B — Điểm neo hạ tầng EvoFlux (đã xác minh trong codebase)

| Thành phần | Đường dẫn |
|---|---|
| Workflows plan v5 (node kinds §4.2/§4.5, templating §4.3, edge/ready semantics §6.3, M1-M6 §11; scope enum cần +`aim`) | `documents/plans/workflows-feature-plan.md` |
| `ChatSession.mode` (string) + tiền lệ đổi mode `normalize_mode` | `app/models/chat.py:106`, `:12-20` |
| `CodingProject.settings` (JSON trống — chỗ neo config AIM; thêm cột `kind`) + join đa-repo | `app/models/chat.py:310-317`, `:333-370` |
| Tool `tiers` (cơ chế gate tool theo mode, sẵn cho tier `aim`) | `app/agent/tools/registry.py:144-167` |
| Sandbox (nơi thêm write-deny roots cho base source read-only) | `app/agent/sandbox.py` |
| Parser extension point (Protocol không cần tree-sitter) | `app/services/code_graph/parsers/registry.py:1-6`, `:42-68`, `:92-99`; `parsers/base.py:42-49` |
| Tool pattern cho `aim_compare`/`aim_units` | `app/agent/tools/registry.py` (`@tool`), đăng ký tại `app/agent/loader.py` (`_default_tool_registry`) |
| API per-project (chỗ thêm `/aim/*`) | `app/api/routes/team/projects.py` |
| Wiki bị khoá cấu trúc (lý do KB là repo riêng) | `app/services/wiki.py:74`, `:158-201` |
| Seed/install agent blueprints + load team theo thư mục (roster `seed/agents/aim/`) | `app/core/workspace_init.py:31-39`, `app/agent/loader.py` (`load_team_from_dir`), `seed/agents/coding/*.md` |
| Skill/command discovery 3 tầng (cơ chế rulebook tận dụng) | `app/api/routes/skills.py:61-67`, `app/services/commands.py:79` |
| Scheduler (batch đêm bằng prompt) | `app/scheduler/scheduler.py` |
| Gate answer path cho Approval Inbox (ask_user/questions) | `app/api/routes/team/questions.py`, `AskUserService` (v5 F10/M4) |
| Frontend: route mode + wizard + pattern panel cho dashboard | `web/src/router.ts:29-45`, `web/src/components/ProjectSetupModal.tsx`, `web/src/components/ProjectCodeGraphPanel.tsx` |
