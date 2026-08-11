# AIM Modernization Limitations & Automation Boundary

| | |
|---|---|
| **Trạng thái** | PROPOSED — research + architecture direction |
| **Ngày** | 2026-08-04 |
| **Phạm vi** | Bổ sung assessment về tương thích legacy ↔ target, giới hạn tự động hóa, human decision và remediation vào AIM mode |
| **Tài liệu liên quan** | [`aim-framework.md`](aim-framework.md), [`../analysis/aim-production-audit-2026-08-01.md`](../analysis/aim-production-audit-2026-08-01.md) (open blocker #5 — waiver/supersession lifecycle), [`../plans/aim-product-production-roadmap-2026-07-28.md`](../plans/aim-product-production-roadmap-2026-07-28.md) |

---

## 1. Tóm tắt điều hành

AIM hiện có nền tảng tốt cho một modernization factory: inventory theo migration unit, knowledge base làm source of truth, dependency-aware workflow, human gate, deterministic verification, golden-master comparison và cutover checklist. Tuy nhiên, product model hiện vẫn ngầm giả định rằng sau khi inventory và thiết kế xong, mọi unit đều có thể đi qua một lifecycle tuyến tính:

```text
inventory → understood → designed → converted → equivalent → cutover
```

Giả định này chưa phản ánh thực tế của legacy modernization. Một unit có thể không thể chuyển trực tiếp sang target vì:

- thư viện hoặc framework không hỗ trợ runtime/ngôn ngữ mới;
- API hoặc platform capability đã bị loại bỏ;
- proprietary component không có source hoặc replacement;
- protocol, middleware, hardware hoặc scheduler không tồn tại trên target;
- data semantics khác nhau về precision, encoding, transaction hoặc consistency;
- thiếu môi trường legacy, test data hoặc golden baseline;
- NFR, security, compliance hoặc licensing không cho phép phương án đề xuất;
- business rule không thể suy ra từ code và cần SME xác nhận;
- chi phí refactor lớn hơn giá trị kinh doanh;
- ứng dụng nên retain, retire, replace hoặc replatform thay vì rewrite/convert.

Do đó AIM không nên đặt mục tiêu **full automation**. Hướng phù hợp là **bounded automation**:

> Tự động hóa tối đa những bước có thể tạo evidence và kiểm chứng; mọi uncertainty, limitation, manual work, architectural decision và accepted risk phải trở thành dữ liệu hạng nhất của dự án.

Đề xuất trung tâm của tài liệu này là thêm một lớp mới vào AIM: **Modernization Feasibility & Automation Boundary**.

Lớp này nằm giữa inventory và wave planning, đồng thời được revalidate trước design, conversion, equivalence và cutover.

---

## 2. Vấn đề cần giải quyết

### 2.1 Complexity không đồng nghĩa với feasibility

Một unit ít dòng code vẫn có thể không thể migrate tự động nếu phụ thuộc vào:

- native driver không hỗ trợ target OS;
- CORBA/RMI-IIOP hoặc COM component;
- vendor library đã EOL;
- stored procedure hoặc database behavior đặc thù;
- batch scheduler, terminal protocol hoặc hardware integration;
- undocumented business decision.

Ngược lại, một unit nhiều dòng nhưng chỉ sử dụng construct chuẩn, có test tốt và dependency được hỗ trợ có thể tự động hóa cao.

Vì vậy không thể dùng `complexity.score` làm đại diện cho compatibility, risk hoặc automation coverage.

### 2.2 “Build thành công” chưa chứng minh target phù hợp

Build/test pass chỉ chứng minh một phạm vi hẹp. Nó không trả lời:

- behavior có tương đương trên dữ liệu thực không;
- performance và batch window có đạt không;
- transaction boundary có còn đúng không;
- observability, rollback và disaster recovery có sẵn không;
- target dependency có được vendor support không;
- security/compliance exception có được phê duyệt không.

### 2.3 Không phải unit nào cũng nên convert

Modernization cần cho phép nhiều chiến lược:

- `retire` — loại bỏ vì không còn giá trị hoặc không còn traffic;
- `retain` — giữ lại do rủi ro, compliance, hardware hoặc dependency;
- `replace` — thay bằng SaaS/COTS/vendor product;
- `rehost` — di chuyển gần như nguyên trạng;
- `replatform` — thay runtime/platform với thay đổi giới hạn;
- `refactor` — thay đổi cấu trúc nhưng giữ capability;
- `rewrite` — xây lại theo target architecture;
- `hybrid` — cô lập hoặc chạy song song theo strangler/side-by-side.

Lifecycle AIM hiện tại phù hợp nhất với `refactor/rewrite`, nhưng chưa biểu diễn các nhánh còn lại.

### 2.4 Ranh giới trách nhiệm của AI chưa được biểu diễn

Human gate hiện đã tồn tại, nhưng chưa có contract mô tả rõ:

- bước nào được chạy tự động;
- bước nào agent chỉ được đề xuất;
- bước nào bắt buộc SME/architect/operator thực hiện;
- blocker nào agent phải dừng;
- evidence nào cần trước khi một quyết định được đóng;
- ai chịu trách nhiệm cho manual action.

---

## 3. Audit hiện trạng AIM

### 3.1 Những nền tảng có thể tái sử dụng

| Nền tảng hiện có | Giá trị cho hướng đề xuất |
|---|---|
| KB repo là source of truth | Lưu assessment, limitation, decision và evidence có version control |
| Unit frontmatter + local index | Có thể bổ sung projection phục vụ filter/dashboard |
| Rulebook project-owned | Nơi phù hợp để khai báo target support contract và scanner adapter |
| Readiness policy | Điểm chặn lifecycle khi còn compatibility blocker |
| Traceability issues | Có thể mở rộng thành limitation/risk projection |
| Workflow gates | Phù hợp cho architecture decision, SME confirmation và accepted risk |
| Golden-master compare | Evidence cho functional equivalence |
| Cutover checklist | Có thể mở rộng sang NFR, operational và residual-risk gates |
| Dependency-aware wave ordering | `readiness._conversion_wave_order` / `_cutover_wave_order` đã deterministic; feasibility có thể tham gia vào thứ tự và điều kiện chọn unit |

Lưu ý một điểm dễ hiểu nhầm: **wave assignment hiện do agent đề xuất**, không phải thuật toán. `aim-assess.yaml` giao việc chia wave cho `aim-appraiser` qua prompt; phần deterministic trong `readiness.py` chỉ sắp xếp thứ tự và chặn dependency *bên trong* một wave đã có. Vì vậy "feasibility-aware wave planning" là một hạng mục công việc riêng (biến wave assignment thành deterministic), không phải một tham số thêm vào thuật toán sẵn có.

### 3.2 Khoảng trống trong model hiện tại

`UnitFrontmatter` và `AimUnit` hiện có các trường lifecycle, paths, dependency và một `complexity` dictionary tự do, nhưng chưa có:

- modernization strategy;
- feasibility status;
- automation level theo stage;
- compatibility findings;
- open human decisions;
- manual work owner;
- risk score có schema;
- target-support evidence;
- assessment revision/freshness.

Không nên tiếp tục nhét toàn bộ dữ liệu mới vào `complexity`, vì:

- không có validation;
- khó query và migrate;
- dễ trộn complexity với feasibility;
- không thể quản lý lifecycle của từng limitation;
- khó audit ai đã đóng blocker dựa trên evidence nào.

### 3.3 Khoảng trống trong `aim-assess`

Assessment hiện tập trung vào:

- code graph;
- unit inventory;
- dependency;
- LOC và technical complexity;
- wave assignment.

Cần bổ sung:

- source/target stack fingerprint;
- dependency manifest và SBOM;
- deprecated/removed API analysis;
- source-target support matrix;
- target compile/build probe;
- data and integration compatibility;
- testability và environment availability;
- NFR/security/compliance/licensing constraints;
- recommended modernization strategy;
- automation boundary và manual backlog;
- evidence-backed human decision gate trước wave approval.

### 3.4 Khoảng trống trong readiness và traceability

Readiness hiện chặn dựa trên lifecycle artifacts như mapping, verification command, golden case và phase của dependency. Nó chưa chặn khi:

- có critical compatibility issue chưa xử lý;
- target replacement chưa được proof-of-concept;
- có decision bắt buộc nhưng chưa có ADR;
- support status còn `unknown`;
- manual work chưa có owner;
- assessment đã stale sau khi đổi target runtime/rulebook;
- residual risk chưa được chấp nhận.

Traceability hiện biểu diễn `blocker | warning | info`, nhưng issue cần thêm lifecycle, category, evidence, owner, resolution và acceptance.

---

## 4. Kết quả nghiên cứu ngành

### 4.1 Thoughtworks: AI là accelerator, không phải autonomous replacement

Thoughtworks mô tả GenAI như một assistant và nhấn mạnh con người phải kiểm soát output, đặc biệt khi generated code có thể ảnh hưởng business continuity. Các hạn chế của automated translation được liệt kê rõ:

- code quality thấp hoặc không idiomatic;
- naming không phù hợp target paradigm;
- không tận dụng tốt open-source/internal libraries;
- mất data precision;
- mất giá trị của source history;
- verification cycle dài khi hệ thống cũ thiếu safety net.

Họ cũng khuyến nghị evolutionary modernization thay cho big-bang và thừa nhận không có giải pháp one-size-fits-all.

Nguồn: [Legacy Modernization meets GenAI — Martin Fowler/Thoughtworks](https://martinfowler.com/articles/legacy-modernization-gen-ai.html).

### 4.2 Microsoft: assessment, decision và guided execution là các stage riêng

GitHub Copilot modernization hiện thực hiện:

1. assessment project structure, dependencies, breaking changes và API compatibility;
2. trình bày strategy decisions để người dùng review;
3. sinh plan gồm dependency paths và risk mitigations;
4. chia thành task có validation criteria;
5. tự sửa lỗi có thể sửa và yêu cầu người dùng trợ giúp khi không thể xử lý.

Automatic mode vẫn dừng ở genuine blocker. Guided mode dừng tại từng stage boundary để người dùng review.

Nguồn: [GitHub Copilot modernization for .NET](https://learn.microsoft.com/en-us/dotnet/core/porting/github-copilot-app-modernization/overview).

.NET Upgrade Assistant cũng thừa nhận migration phức tạp cần manual refactoring và cung cấp side-by-side incremental mode cho ứng dụng không phù hợp với in-place conversion.

Nguồn: [.NET Upgrade Assistant overview](https://learn.microsoft.com/en-us/dotnet/core/porting/upgrade-assistant-overview).

### 4.3 AWS: phải chọn strategy trước khi refactor

AWS Prescriptive Guidance sử dụng 7 migration strategies: Retire, Retain, Rehost, Relocate, Repurchase, Replatform và Refactor/Re-architect.

AWS đánh giá refactor là chiến lược phức tạp và tốn kém nhất; với large migration, không nên mặc định refactor mọi application. Retain có thể là quyết định đúng khi còn high risk, dependency, specialized hardware, compliance hoặc cần assessment chi tiết hơn.

Nguồn: [AWS — About the migration strategies](https://docs.aws.amazon.com/prescriptive-guidance/latest/large-migration-guide/migration-strategies.html).

### 4.4 Testing vẫn là ranh giới lớn của automation

Theo bài blog của AWS, testing thường chiếm hơn một nửa timeline và resource của một dự án mainframe modernization. Đây là con số AWS quan sát được từ các engagement của họ, không phải một tỷ lệ chuẩn ngành — trích như một order of magnitude, không dùng làm hằng số ước lượng. Functional equivalence cần xử lý:

- hàng triệu record;
- data format khác biệt;
- external-system dependencies;
- functional, integration, non-functional và UAT;
- bit-by-bit comparison trong một số loại dự án.

Ngay cả khi AWS tạo test data collection scripts, mainframe expert vẫn review và kiểm soát job submission/data transfer vì security và governance.

Nguồn: [Accelerating mainframe modernization testing with AWS Transform](https://aws.amazon.com/blogs/migration-and-modernization/accelerating-mainframe-modernization-testing-with-aws-transform/).

### 4.5 Ví dụ Java: “ngôn ngữ mới hỗ trợ” không có nghĩa dependency cũ còn chạy

OpenJDK JEP 320 loại Java EE và CORBA modules khỏi JDK 11. Application phụ thuộc vào các module này có thể gặp source và binary incompatibility khi nâng từ JDK 6/7/8.

Một số API như JAXB/JAX-WS có artifact thay thế, nhưng các capability như RMI-IIOP không có replacement độc lập tương đương. Đây là ví dụ cho thấy assessment phải phân biệt:

- dependency có replacement đơn giản;
- dependency cần adapter;
- capability cần redesign;
- capability không thể tiếp tục trên target;
- application nên chạy side-by-side hoặc retain.

Nguồn: [OpenJDK JEP 320 — Remove the Java EE and CORBA Modules](https://openjdk.org/jeps/320).

### 4.6 Kết luận hội tụ

Các nguồn đều hội tụ ở sáu nguyên tắc:

1. Assessment phải đi trước execution.
2. Dependency/API compatibility phải được phân tích có evidence.
3. Không phải workload nào cũng nên refactor hoặc rewrite.
4. Automation phải dừng ở blocker thật.
5. Human review là một phần của operating model, không phải fallback bất thường.
6. Verification và incremental delivery quan trọng hơn tỷ lệ generated code.

---

## 5. Kiến trúc đề xuất

### 5.1 Lớp mới: Modernization Feasibility & Automation Boundary

```text
Legacy inventory
      │
      ▼
Source + target fingerprint
      │
      ▼
Compatibility findings ──────► Limitation / decision registry
      │                                      │
      ▼                                      ▼
Strategy recommendation              Human / architect gate
      │                                      │
      └──────────────────┬───────────────────┘
                         ▼
              Feasibility-aware wave plan
                         │
                         ▼
        ┌───────┬────────┴───────┬─────────┐
        ▼       ▼                ▼         ▼
     Design → Convert  →     Compare  →  Cutover
        ▲       ▲                ▲         ▲
        └───────┴── assessment revalidation ┘
```

Mỗi mũi tên đi lên là một lần revalidate: trước khi vào stage, assessment phải còn fresh theo fingerprint hiện tại của rulebook/target contract/source dependency.

### 5.2 Hai cấp assessment

#### Project/estate level

- target architecture support envelope;
- source and target stack inventory;
- organization-approved dependencies;
- EOL/licensing/vendor-support policy;
- NFR and operational constraints;
- security/compliance/data-residency requirements;
- test environment and cutover capabilities;
- allowed modernization strategies;
- automation policy and required approvers.

#### Migration-unit level

- recommended strategy;
- feasibility status;
- automation mode by lifecycle stage;
- compatibility issues;
- data/integration/NFR risks;
- manual actions;
- decisions required;
- evidence and confidence;
- estimated remediation class;
- assessment revision and freshness.

---

## 6. Target Support Contract

Rulebook cần bổ sung một contract có schema. Contract này **mở rộng khối `target` sẵn có**, không tạo một khối song song: `RulebookManifest` đã có `source`/`target` kiểu `RulebookStack` (`stack`, `language`, `standard`, `edition`, `version`, `file_extensions`), nên `runtime.language`/`runtime.version` nếu khai báo lại sẽ trở thành hai nguồn sự thật.

```yaml
# rulebook/rulebook.yaml
target:
  stack: java
  language: java
  version: "21"

  # Các khối dưới đây là phần bổ sung của tài liệu này.
  contract:
    runtime:
      os: linux

    frameworks:
      required:
        - spring-boot: "3.x"
      prohibited:
        - java-ee-javax

    dependencies:
      policy: approved-list
      allow_unknown: false
      require_vendor_support: true

    data:
      database: postgresql
      decimal_precision_loss: forbidden
      default_encoding: utf-8

    operations:
      containerized: true
      rollback_required: true
      observability_required: true

    compliance:
      external_saas_allowed: false
      data_residency: on-premise
```

Hai ràng buộc triển khai:

- `RulebookManifest` và `RulebookStack` đang đặt `ConfigDict(extra="forbid")`. Không thể thêm key mới vào `rulebook.yaml` mà không thêm field tương ứng vào model — mọi rulebook hiện có sẽ fail validation nếu làm ngược lại. Vì vậy `contract` phải là một Pydantic model mới, optional, default rỗng, để rulebook cũ vẫn parse được.
- Không cần cơ chế fingerprint riêng cho contract. `aim.yaml` đã pin `rulebook.id@version` và `_assert_rulebook_identity` đã fail-closed khi lệch. Quy tắc stale nên gắn vào chính cặp id/version đó: mọi assessment ghi lại `rulebook_version` tại thời điểm chạy; khi rulebook version thay đổi, assessment cũ hơn chuyển sang `stale`. Điều này cũng buộc mọi thay đổi contract phải bump rulebook version — một hành vi mong muốn.

---

## 7. Taxonomy

Tài liệu này dùng **bốn enum độc lập**. Chúng mô tả bốn câu hỏi khác nhau và không được trộn vào cùng một cột trong artifact hay UI:

| Enum | Phạm vi | Trả lời câu hỏi |
|---|---|---|
| `category` (§7.1) | issue | Limitation thuộc loại kỹ thuật nào? |
| `compatibility` (§7.2) | issue | Legacy component này đi về đâu trên target? |
| `severity` (§7.4) | issue | Nó chặn cái gì? |
| `feasibility` (§7.3) | unit | Unit này có thể đi tiếp trong lifecycle không? |

`strategy` (§2.3: `retire | retain | replace | rehost | replatform | refactor | rewrite | hybrid`) là enum thứ năm, cũng ở cấp unit, và độc lập với `feasibility` — một unit `retain` vẫn có feasibility riêng cho các hoạt động của nhánh retain.

### 7.1 Categories

| Category | Ví dụ |
|---|---|
| `language_runtime` | API/feature bị remove, compiler behavior thay đổi |
| `library_framework` | Library không support target, internal library không có tài liệu |
| `platform_os` | Native DLL, shell, filesystem semantics, hardware dependency |
| `data_semantics` | Decimal precision, encoding, collation, date/time, transaction |
| `integration` | MQ, CORBA, COM, proprietary protocol, unavailable endpoint |
| `architecture` | Shared global state, tight coupling, unsupported topology |
| `security_compliance` | Authentication model, data residency, secrets, audit |
| `licensing_vendor` | EOL, commercial license, vendor certification |
| `testability` | Không có runner, test data, golden baseline hoặc environment |
| `non_functional` | Performance, availability, batch window, scalability |
| `operations_cutover` | Deploy, monitoring, reconciliation, rollback chưa sẵn sàng |
| `business_knowledge` | Rule mơ hồ, thiếu SME, behavior cần quyết định retain/change |

### 7.2 Compatibility status

| Status | Ý nghĩa | Hành động mặc định |
|---|---|---|
| `supported` | Target hỗ trợ trực tiếp | Cho phép tiếp tục |
| `upgradeable` | Có upgrade/codemod xác định | Tạo remediation task |
| `replace` | Có replacement đã biết | Cần mapping + verification |
| `wrap` | Cần adapter/anti-corruption layer | Cần architect approval |
| `isolate` | Cần chạy side-by-side | Tạo hybrid deployment plan |
| `redesign` | Không có mapping trực tiếp | Manual architecture work |
| `retain` | Chưa nên migrate | Loại khỏi conversion wave |
| `unknown` | Thiếu evidence | Block cho đến khi triage |
| `blocked` | Không khả thi với target hiện tại | Escalate hoặc đổi strategy |

### 7.3 Feasibility status (cấp unit)

`compatibility` mô tả một issue; `feasibility` là kết luận tổng hợp ở cấp unit và là thứ readiness policy đọc.

| Status | Ý nghĩa | Hệ quả lifecycle |
|---|---|---|
| `ready` | Không còn open blocker; automation mode đã xác định cho stage kế tiếp | Cho phép tiếp tục |
| `conditional` | Có thể tiếp tục nhưng phụ thuộc remediation, adapter hoặc manual action đã có owner | Cho phép tiếp tục khi các điều kiện đã được ghi nhận và assign |
| `blocked` | Còn open blocker/critical chưa có decision hoặc evidence | Chặn stage kế tiếp |
| `unassessed` | Chưa từng chạy feasibility assessment cho unit này | Xem quy tắc rollout ở §9.4 |

`retain` và `retire` **không** phải feasibility status — chúng là `strategy`. Một unit `strategy: retain` vẫn có feasibility riêng (ví dụ `conditional` khi operating plan chưa có owner). UI ở §12.1 phải hiển thị hai chiều này thành hai breakdown, không gộp thành một dãy.

### 7.4 Severity

- `info`: không ảnh hưởng strategy hoặc schedule;
- `warning`: có remediation rõ và không chặn stage hiện tại;
- `blocker`: chặn design/convert/test/cutover;
- `critical`: có thể làm target strategy không khả thi ở project/wave level.

`TraceabilityIssue.severity` hiện là `Literal["blocker", "warning", "info"]` và shape này đã đi ra API response lẫn ba catalog i18n (`en`/`ja`/`vi`). Thêm `critical` là một thay đổi contract, nên chọn một trong hai và ghi rõ:

- **Mở rộng Literal thành bốn giá trị** — cần cập nhật `traceability._issue_sort_key`, priority map, các counter trong `summary`, và cả ba catalog i18n cùng lúc; hoặc
- **Giữ ba giá trị ở projection**: `critical` là thuộc tính riêng của assessment issue, chiếu xuống traceability thành `blocker` kèm cờ `escalated: true`.

Khuyến nghị dùng phương án thứ hai cho MVP: `critical` chỉ khác `blocker` ở *phạm vi* (project/wave thay vì unit), và phạm vi đó đã được biểu diễn bằng `scope` trong issue schema.

---

## 8. Automation boundary

Không nên chỉ hiển thị một phần trăm automation. Dùng mode theo từng stage:

| Mode | Định nghĩa |
|---|---|
| `automatic` | Deterministic tool/recipe chạy được và có automated verification |
| `assisted` | Agent thực hiện nhưng engineer phải review/approve |
| `manual` | Cần SME, architect hoặc operator thực hiện |
| `unavailable` | Chưa có adapter, tool hoặc environment |
| `blocked` | Có open limitation nên stage chưa thể bắt đầu |

`blocked` (automation mode) và `blocked` (compatibility status, §7.2) là hai enum khác nhau: cái đầu nói về *stage của một unit*, cái sau nói về *một component so với target*. Trong artifact chúng luôn nằm ở hai key khác nhau (`automation.<stage>` và `compatibility`), nên không có ambiguity — nhưng UI không được render chung một badge.

**Khoá stage dùng đúng `VALID_PROJECT_PHASES`** (`assess | understand | design | convert | test | cutover`), là vocabulary mà `/aim/meta` đã phục vụ cho frontend. Không tự đặt tên mới (`inventory`, `compare`) vì `inventory` là một *unit phase* còn `compare` không tồn tại trong enum nào. Ánh xạ sang unit phase:

| Automation stage (project phase) | Unit phase đạt được | Pipeline |
|---|---|---|
| `assess` | `inventory` | `aim-assess` |
| `understand` | `understood` | `aim-understand` |
| `design` | `designed` | `aim-design-unit` |
| `convert` | `converted` | `aim-convert-unit` |
| `test` | `equivalent` | `aim-test-compare` |
| `cutover` | `cutover` | `aim-cutover-check` |

Ví dụ:

```yaml
strategy: replatform
feasibility: conditional

automation:
  assess: automatic
  understand: assisted
  design: manual
  convert: assisted
  test: automatic
  cutover: manual

manual_actions:
  - id: MAN-PAY-0001
    owner_role: solution-architect
    action: Select replacement for CORBA integration

open_issues:
  - LIM-PAY-0001
```

Nếu cần số liệu portfolio, có thể tính weighted coverage từ các mode trên, nhưng UI phải luôn hiển thị breakdown và confidence; không được dùng một con số tổng hợp để che blocker.

---

## 9. Limitation lifecycle và artifact model

### 9.1 File layout trong KB

KB hiện tách hai loại nội dung: artifact người đọc/sửa nằm ở root (`modules/`, `mapping/`, `business-rules/`, `decisions/`, `golden/`, `inventory/`), còn state do máy ghi nằm dưới `state/` (`state/transitions/`, `state/links/`, `state/cutover/`, `state/reconciliations/`). Assessment artifacts chia theo đúng ranh giới đó:

```text
assessment/                      # human-reviewable, triage qua PR
  project.yaml
  automation-policy.yaml
  units/
    <module>/
      <unit>.yaml
  issues/
    LIM-<MODULE>-####.yaml       # 4 chữ số, ví dụ LIM-PAY-0001

state/
  probes/                        # machine-written evidence, không sửa tay
    <probe-id>/
      result.json
      stdout.log
      stderr.log
```

`target-contract.yaml` không xuất hiện ở đây: contract thuộc rulebook (§6), nơi đã có version pinning và validation.

Một issue/file phù hợp với collaboration qua Git hơn một file `risks.yaml` lớn và giảm conflict khi nhiều người triage song song. Đổi lại, `assessment/` và `state/probes/` cần được `app.services.aim.reindex` đọc để dựng projection ở §10.2 — đây là một hạng mục công việc, không phải hệ quả tự nhiên của việc thêm file.

### 9.2 Issue schema đề xuất

```yaml
id: LIM-PAY-0001
category: library_framework
scope: core/PAYROLL
legacy_component: vendor-corba-client
target_requirement: java-21

compatibility: redesign
severity: blocker
status: decision_required
confidence: high

detected_by:
  kind: deterministic_probe
  tool: target-compile
  version: "1"

# Cơ sở staleness (§6): issue phát hiện dưới rulebook version nào.
rulebook_version: "1.4.0"

evidence:
  - ref: source:pom.xml
  - ref: code:src/main/java/.../LegacyClient.java#L42
  - ref: probe:compile-java21-0004/result.json

resolution_options:
  - replace_with_supported_client
  - wrap_remote_legacy_service
  - retain_component

selected_resolution: null
owner: solution-architect
decision_ref: null
verification_refs: []
created_at: 2026-08-04T00:00:00Z
updated_at: 2026-08-04T00:00:00Z
```

### 9.3 Lifecycle

```text
detected
  → triaged
  → decision_required
  → planned
  → remediated
  → verified
```

Các terminal state bổ sung:

- `accepted_risk`;
- `waived`;
- `retained`;
- `retired`;
- `superseded`.

Quy tắc:

- Agent có thể tạo issue và đề xuất option.
- Agent không được tự chọn `accepted_risk`, `waived`, `retain` hoặc architectural redesign.
- Blocker chỉ được đóng khi có `decision_ref` và/hoặc `verification_refs` phù hợp policy.
- Thay đổi rulebook version (bao gồm target contract) hoặc source dependency phải đánh dấu assessment liên quan là stale.

Hai terminal state `accepted_risk` và `waived` **là cùng một cơ chế** với open production blocker #5 trong [`aim-production-audit-2026-08-01.md`](../analysis/aim-production-audit-2026-08-01.md): "certification exceptions still need structured dispositions and waivers bound to rule/ADR, artifact and policy hashes, scope, reason, expiry/supersession, and automatic invalidation". Không xây hai hệ thống waiver song song. Cụ thể, waiver của assessment issue phải dùng chung model đó: bind vào ADR, hash của artifact và policy tại thời điểm chấp nhận, scope, lý do, expiry/supersession, và tự động invalidate khi hash đổi. Điều đó cũng làm quy tắc stale ở trên trở thành một trường hợp riêng của automatic invalidation, không phải cơ chế thứ hai.

### 9.4 Rollout và backward compatibility

§7.2 quy định `unknown` phải block cho đến khi triage. Áp dụng nguyên trạng cho các KB đang chạy sẽ đóng băng toàn bộ project hiện có: chưa KB nào có assessment artifact, nên nếu coi "không có dữ liệu" là `unknown` thì mọi unit đều bị chặn ngay ngày tính năng này ship.

Vì vậy quy tắc block phải gắn với `feasibility` cấp unit chứ không phải với sự vắng mặt của dữ liệu:

- Unit chưa từng chạy feasibility assessment ở trạng thái `unassessed`, **không** bị block. Readiness phát một `warning` ("feasibility assessment chưa chạy"), traceability hiển thị nó trong assessment freshness.
- Sau khi feasibility assessment chạy lần đầu cho một unit, mọi `unknown` phát sinh **có** block — vì lúc này `unknown` nghĩa là "đã tìm và không kết luận được", khác hẳn "chưa từng tìm".
- Project có thể chuyển sang chế độ nghiêm ngặt (`unassessed` cũng block) qua `automation-policy.yaml`, mặc định tắt và bật được sau khi pilot xong.

Chuyển đổi này dùng lại cơ chế sẵn có: `readiness.evaluate_pipeline` đã chặn lifecycle work khi `state_schema < 2` và trỏ về đường reconcile. Assessment artifacts nên đi kèm bump `state_schema` lên 3 với cùng kiểu reconcile path, để một KB cũ được nâng cấp một cách tường minh thay vì âm thầm đổi hành vi.

---

## 10. Data model và projection

KB vẫn là system of record. Local database là rebuildable index.

### 10.1 Không mở rộng `complexity` cho production model

Có thể dùng `complexity` để prototype, nhưng production nên có typed artifacts và projection riêng.

### 10.2 Projection đề xuất

`AimUnit` có thể thêm các trường summary để dashboard query nhanh:

```text
recommended_strategy
feasibility_status
automation_class
risk_score
risk_score_basis
open_blocker_count
open_decision_count
assessment_revision
assessment_stale
```

`risk_score` chỉ được tồn tại nếu nó deterministic và giải thích được — nếu không nó rơi đúng vào cái mà §8 và §15 cảnh báo. Ràng buộc:

- Nó là **hàm thuần** của các open issue thuộc unit, không phải LLM judgment: một weighted sum theo `severity`, có thể nhân hệ số theo `confidence`.
- Công thức có version; `risk_score_basis` lưu version đó cùng các count đầu vào (`critical`/`blocker`/`warning`/`unknown`), để một score cũ vẫn đọc được sau khi công thức đổi.
- UI không bao giờ hiển thị `risk_score` một mình; nó luôn đi kèm breakdown từ `risk_score_basis`.
- Không có readiness policy nào chặn dựa trên `risk_score`. Chặn dựa trên issue và feasibility; score chỉ để sắp xếp và ưu tiên.

Thêm bảng projection `aim_limitations` hoặc `aim_assessment_issues`:

```text
id
project_id
unit_id nullable
category
compatibility
severity
status
confidence
owner
decision_ref
kb_path
created_at
updated_at
```

### 10.3 API đề xuất

Mọi endpoint AIM hiện có đều project-scoped dưới `/projects/{project_id}/aim/...` (`summary`, `units`, `traceability`, `readiness`, `rulebook`, `reindex`, `runs`, `approvals`, ...). Assessment API phải theo đúng prefix đó — không có project id thì không resolve được KB root:

```text
GET  /projects/{project_id}/aim/assessment
GET  /projects/{project_id}/aim/assessment/units/{module}/{name}
GET  /projects/{project_id}/aim/assessment/issues
GET  /projects/{project_id}/aim/assessment/issues/{issue_id}
POST /projects/{project_id}/aim/assessment/probes
PUT  /projects/{project_id}/aim/assessment/issues/{issue_id}/triage
POST /projects/{project_id}/aim/assessment/issues/{issue_id}/decision
```

Không thêm `POST .../assessment/reindex` riêng: `POST /projects/{project_id}/aim/reindex` đã tồn tại và nên được mở rộng để dựng luôn projection assessment, giữ một đường rebuild duy nhất từ KB.

Write endpoints phải dùng optimistic revision như KB document editing và giữ decision/evidence audit trail.

---

## 11. Pipeline đề xuất

### 11.1 Mở rộng assessment

```text
inventory
  → fingerprint_source
  → fingerprint_target
  → dependency_scan
  → api_compatibility_scan
  → target_build_probe
  → data_integration_assessment
  → testability_assessment
  → strategy_recommendation
  → architecture_gate
  → feasibility_aware_wave_plan
  → wave_plan_gate
```

Không nên để LLM tự làm những việc scanner/compiler có thể làm. Agent chỉ:

- tổng hợp evidence;
- liên kết finding với unit;
- đề xuất resolution option;
- nhận diện ambiguity;
- soạn decision brief cho human gate.

### 11.2 Readiness policies mới

#### Trước Design

- `feasibility` không phải `blocked`;
- `strategy` là một nhánh có đi qua design (tức không phải `retire`/`retain`/`rehost`/`replace` — xem §11.3);
- critical issues đã triage;
- target contract đã được approve;
- mọi issue `unknown` có owner hoặc investigation plan (unit `unassessed` chỉ cảnh báo — §9.4);
- business decision bắt buộc đã có SME owner.

#### Trước Convert

- không còn open compatibility blocker;
- replacement/wrapper đã có approved mapping;
- decision-required issues đã có ADR;
- target build/compile probe hợp lệ;
- verification contract tồn tại;
- manual work trong scope đã hoàn thành hoặc được tách thành explicit dependency.

#### Trước Equivalent

- conversion verification pass;
- golden provenance hợp lệ;
- data/encoding/precision policy đã được áp dụng;
- accepted differences có rule hoặc ADR;
- integration environment đủ phạm vi.

#### Trước Cutover

- functional equivalence không phải điều kiện duy nhất;
- NFR evidence đạt threshold;
- deployment, monitoring, data reconciliation và rollback đã xác nhận;
- residual risks đã được đúng approver chấp nhận;
- các retained/hybrid dependencies có operational ownership.

### 11.3 Branch theo strategy

```text
retire      → decommission assessment → approval → archive
retain      → risk register → operating plan → revisit date
replace     → product selection → data/integration migration → acceptance
rehost      → infrastructure migration → smoke/NFR validation
replatform  → dependency remediation → build/compare
refactor    → design → convert → compare
rewrite     → capability spec → implementation → dual-run/acceptance
hybrid      → boundary contract → side-by-side routing → gradual cutover
```

Không ép tất cả strategy vào cùng một phase graph.

---

## 12. UI/UX đề xuất

Thêm surface **Assessment & Limits** hoặc **Modernization Readiness**.

### 12.1 Portfolio/project overview

- feasibility distribution (`ready / conditional / blocked / unassessed`);
- recommended strategy distribution (`retire / retain / replace / rehost / replatform / refactor / rewrite / hybrid`) — hiển thị tách khỏi feasibility, không gộp một dãy;
- automation boundary theo stage;
- open blockers và open decisions;
- limitations không có owner;
- assessment freshness;
- risk heatmap theo wave/module;
- manual-effort backlog;
- target-support coverage.

### 12.2 Compatibility matrix

| Legacy component | Target requirement | Status | Scope | Resolution | Owner |
|---|---|---|---|---|---|
| JAXB bundled API | Java 21 | `replace` | 12 units | Maven dependency | Platform team |
| CORBA/RMI-IIOP | Java 21 | `redesign` | 4 units | Decision required | Architect |
| EBCDIC fixed-width | UTF-8 services | `wrap` | 18 units | Canonicalizer + adapter | Data lead |

Cột Status ở đây là `compatibility` (§7.2). Feasibility cấp unit là một cột riêng ở Unit detail, không trộn vào ma trận này.

### 12.3 Unit detail

Thêm các section:

- strategy and feasibility;
- automation by stage;
- compatibility findings;
- evidence/probes;
- decisions and ADRs;
- manual actions;
- residual risk;
- remediation history.

### 12.4 Human decision queue

Mỗi item phải trả lời nhanh:

- quyết định cần đưa ra là gì;
- tại sao agent không thể tự quyết;
- unit/wave nào bị ảnh hưởng;
- evidence nào hỗ trợ;
- các option và trade-off;
- recommendation của AIM;
- approver cần thiết;
- consequence nếu trì hoãn.

### 12.5 Không dùng “green dashboard” giả

Một project không được hiển thị ready chỉ vì:

- tất cả unit có phase hợp lệ;
- build đang xanh;
- compare pass trên smoke case;
- không có workflow đang fail.

Project readiness phải hiển thị cả open decisions, unknown support, manual backlog và evidence freshness.

### 12.6 Ràng buộc i18n

AIM web shell duy trì ba catalog (`web/src/i18n/messages/en.json`, `ja.json`, `vi.json`) và các panel hiện có đã dùng chúng. Surface mới không được hardcode chuỗi: mọi label của category, compatibility status, feasibility, severity và automation mode phải là message key, thêm đồng thời vào cả ba catalog. Đây là điều kiện hoàn thành của hạng mục UI, không phải việc dọn dẹp sau.

---

## 13. Ranh giới Human-in-the-Loop

### 13.1 Có thể tự động hóa

- inventory dependency manifests;
- SBOM generation;
- static dependency/API scan;
- deprecated/removed API detection;
- compile/build/test probes;
- code graph và impact analysis;
- known replacement suggestion từ rulebook;
- repeatable codemod/recipe;
- evidence capture;
- golden-output comparison;
- stale-assessment detection;
- report và decision brief generation.

### 13.2 Agent-assisted, bắt buộc review

- target mapping;
- replacement library recommendation;
- refactor proposal;
- business-rule extraction;
- test generation;
- diff triage;
- wave re-planning;
- remediation code;
- NFR test plan.

### 13.3 Không được tự quyết

- retain/change một legacy behavior;
- lựa chọn architecture có blast radius lớn;
- chấp nhận security/compliance/licensing risk;
- chọn proprietary vendor replacement;
- data-loss hoặc precision-loss exception;
- xác nhận business rule mơ hồ;
- waive test/NFR coverage;
- production cutover/rollback;
- accepted difference không có rule/ADR;
- quyết định retire/retain capability có business impact.

---

## 14. Ví dụ Java 8 → Java 21

Giả sử application có:

- `javax.xml.bind`;
- custom CORBA client;
- library chỉ support Java 8;
- fixed-width EBCDIC files;
- batch window 15 phút;
- chưa có automated test.

Kết quả AIM nên là:

| Finding | Category (§7.1) | Compatibility (§7.2) | Severity (§7.4) | Automation (§8) | Result |
|---|---|---|---|---|---|
| JAXB bị remove khỏi JDK | `library_framework` | `replace` | `warning` | `convert: assisted` | Đề xuất Maven artifact, compile/test probe |
| CORBA/RMI-IIOP không có target equivalent | `integration` | `redesign` | `blocker` | `design: manual` | Block design, yêu cầu ADR |
| Vendor library Java 8-only | `licensing_vendor` | `unknown` | `blocker` | `design: manual` | Yêu cầu vendor support hoặc replacement |
| EBCDIC → UTF-8 | `data_semantics` | `wrap` | `warning` | `convert: assisted` | Data adapter + canonicalizer + golden compare |
| Batch window 15 phút | `non_functional` | `redesign` | `blocker` | `test: assisted` | Performance gate trước cutover |
| Không có automated test | `testability` | `redesign` | `blocker` | `test: assisted` | Capture golden + SME-approved cases |

Tổng hợp ở cấp unit: `strategy: replatform`, `feasibility: blocked` (còn bốn blocker chưa có decision hoặc evidence).

Unit không được chuyển sang `designed` chỉ vì architect đã tạo `mapping.md`. Design readiness phải đợi CORBA decision, vendor-library resolution và testability plan.

---

## 15. Metrics nên đo

### 15.1 Không đo vanity metrics

Tránh dùng:

- số dòng code generated;
- phần trăm file đã convert;
- số agent task completed;
- build-pass rate đơn lẻ.

### 15.2 Metrics có giá trị

- automation mode distribution theo stage;
- predicted vs actual manual effort;
- blocker aging;
- time-to-decision;
- issues reopened vì evidence không đủ;
- assessment false positive/false negative;
- remediation success rate theo rulebook recipe;
- compare pass rate trên trusted coverage;
- human interventions theo category;
- stale evidence count;
- number of retained/hybrid dependencies at cutover;
- escaped defects linked về missed limitation;
- rollback readiness và cutover rehearsal success.

Các metric này dùng để hiệu chỉnh rulebook và automation policy, không dùng để khuyến khích agent che giấu blocker.

---

## 16. Roadmap triển khai

Các bước dưới đây đánh số **F0–F5** (feasibility) để không lẫn với `P0-1`…`P0-5` (open blockers) và `Phase 0`…`Phase 4` trong [`aim-product-production-roadmap-2026-07-28.md`](../plans/aim-product-production-roadmap-2026-07-28.md). Chúng là một luồng công việc song song, không thay thế thứ tự ưu tiên ở đó.

### F0 — Taxonomy, schema và fixtures

- Chốt strategy, feasibility, compatibility, severity, issue lifecycle và automation mode.
- Thêm Pydantic models cho assessment artifacts.
- Thêm `TargetContract` optional vào `RulebookManifest`/`RulebookStack` sao cho rulebook hiện có vẫn parse.
- Thêm KB templates và JSON/YAML schema validation.
- Thêm representative fixtures cho Java 8 → 21.
- Định nghĩa quy tắc stale dựa trên rulebook version (§6).

**Exit criteria:** artifacts parse deterministic, reindex round-trip được, invalid state bị từ chối, rulebook cũ không bị vỡ.

### F1 — Deterministic assessment spine

- Source/target fingerprint.
- Manifest and dependency scan.
- SBOM import/generation adapter.
- Target compile/build probe.
- Removed/deprecated API scanner interface.
- Rulebook support contract validation.
- Issue creation với evidence refs.
- Mở rộng `reindex` để dựng projection từ `assessment/` và `state/probes/`; thêm Alembic revision cho bảng projection.

**Exit criteria:** phát hiện được supported/replace/redesign/unknown trên pilot project mà không phụ thuộc LLM judgment; `reindex` rebuild được toàn bộ projection từ KB.

### F2 — Workflow và readiness gates

- Mở rộng `aim-assess` hoặc thêm `aim-assess-feasibility`.
- Architecture decision gate.
- Readiness block theo open critical/blocker issues.
- Accepted-risk/waiver authorization — **dùng chung** cơ chế waiver/supersession của open blocker #5 trong audit, không xây riêng.
- Bump `state_schema` lên 3 kèm reconcile path, và rollout rule ở §9.4 (`unassessed` cảnh báo, không block).
- Feasibility-aware wave planning — bao gồm việc biến wave assignment từ agent-authored thành deterministic.
- Strategy branch cho retain/retire/hybrid.

**Exit criteria:** unit có unresolved blocker không thể vào design/convert; mọi override có audit trail; KB hiện có nâng cấp được mà không bị đóng băng.

### F3 — UI Assessment & Limits

- Project summary.
- Compatibility matrix.
- Automation boundary.
- Risk heatmap.
- Decision queue.
- Manual backlog.
- Unit assessment detail.
- Evidence and freshness indicators.
- Message keys cho toàn bộ enum labels trong cả ba catalog `en`/`ja`/`vi`.

**Exit criteria:** operator hiểu được “vì sao chưa tự động được” và “ai cần làm gì tiếp theo” mà không đọc raw logs, ở cả ba ngôn ngữ.

### F4 — Remediation playbooks

- Rulebook recipes cho upgrade/replace/wrap/isolate.
- Deterministic verification contract cho từng recipe.
- Pilot cho Java 8 → 21, sau đó .NET Framework → .NET và COBOL → Java.
- Repair loop có budget và escalation.

**Exit criteria:** recipe chỉ được gắn `automatic` khi có repeatable verification và measured success rate.

### F5 — Calibration và production governance

- So sánh predicted vs actual effort.
- Recalibrate support matrix/confidence.
- Evidence-retention policy.
- Role/approver policy.
- Portfolio reporting và export.

---

## 17. MVP khuyến nghị

Không nên bắt đầu bằng một catalog toàn cầu chứa mọi library/version. Catalog như vậy nhanh stale và tạo false confidence.

MVP nên gồm:

1. typed assessment/issue artifacts trong KB;
2. target support contract mở rộng khối `target` của rulebook;
3. dependency manifest scan;
4. target compile/build probe;
5. manual issue/decision workflow có owner và ADR;
6. readiness block khi còn open blocker, kèm rollout rule ở §9.4 để KB hiện có không bị đóng băng;
7. UI compatibility matrix và decision queue (đủ ba catalog i18n);
8. pilot Java 8 → 21 với một số rule deterministic rõ ràng.

Sau khi có dữ liệu pilot mới mở rộng recipe catalog và automation scoring.

---

## 18. Nguyên tắc sản phẩm

1. **A blocker found early is a successful assessment, not a failed automation.**
2. **No compatibility claim without evidence.**
3. **Unknown must remain visible; it must not silently become supported.**
4. **Human work is planned work, not an exception outside AIM.**
5. **Every waiver or accepted risk needs an accountable approver.**
6. **Automation level is stage-specific and can decrease when evidence becomes stale.**
7. **Not every unit must end at cutover; retain/retire/replace are valid outcomes.**
8. **Deterministic tools detect; agents synthesize; humans decide high-impact trade-offs.**
9. **Functional equivalence is necessary but not sufficient for production readiness.**
10. **AIM optimizes safe modernization throughput, not generated-code volume.**

---

## 19. Quyết định kiến trúc đề xuất

Chấp nhận hướng **Modernization Feasibility & Automation Boundary** như một capability mới của AIM, triển khai theo các quyết định sau:

- giữ KB là system of record;
- tạo typed assessment và limitation artifacts riêng, không lạm dụng `complexity`;
- mở rộng khối `target` của rulebook bằng target support contract, dùng rulebook version làm cơ sở staleness;
- mở rộng readiness để block lifecycle theo unresolved limitations, với rollout rule cho KB chưa từng assessment;
- dùng chung cơ chế waiver/supersession đang còn mở trong audit thay vì xây hệ thống thứ hai;
- tái sử dụng vocabulary enum sẵn có (project phase, traceability severity) thay vì đặt tên song song;
- cho phép nhiều modernization strategies thay vì mặc định convert;
- biểu diễn automation theo stage, không chỉ bằng phần trăm;
- coi manual actions và human decisions là first-class work items;
- ưu tiên deterministic scanners/probes trước LLM classification;
- triển khai pilot theo stack trước khi xây catalog rộng.

Hướng này không thay thế các capability AIM hiện có. Nó bổ sung lớp còn thiếu giữa **inventory** và **execution**, giúp AIM trả lời ba câu hỏi bắt buộc của một dự án modernization thực tế:

1. **Có nên migrate unit này theo target architecture đã chọn không?**
2. **Phần nào tự động được, phần nào cần người xử lý, và vì sao?**
3. **Evidence nào chứng minh limitation đã được giải quyết hoặc rủi ro đã được chấp nhận?**
