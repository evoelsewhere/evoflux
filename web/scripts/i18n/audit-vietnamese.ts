import fs from 'node:fs'
import path from 'node:path'

const WEB_ROOT = path.resolve(import.meta.dir, '../..')
const MESSAGES_ROOT = path.join(WEB_ROOT, 'src', 'i18n', 'messages')
const ENGLISH_PATH = path.join(MESSAGES_ROOT, 'en.json')
const VIETNAMESE_PATH = path.join(MESSAGES_ROOT, 'vi.json')

type Catalog = Record<string, string>

interface TermRule {
  source: RegExp
  mistranslations: RegExp
  preferred?: string
}

// These words are product/developer vocabulary in EvoFlux. Keeping them in
// English is clearer than literal Vietnamese such as "đại lý", "cam kết", or
// "đường ống".
const TECHNICAL_TERMS: TermRule[] = [
  { source: /\bagents?\b/i, mistranslations: /(?:đại lý|tác nhân(?: AI)?|agents)/giu, preferred: 'agent' },
  { source: /\bbranch(?:es)?\b/i, mistranslations: /(?:chi nhánh|nhánh|branches)/giu, preferred: 'branch' },
  { source: /\bcherry-pick(?:ed|ing)?\b/i, mistranslations: /(?:chọn anh đào|hái anh đào|anh đào hái)/giu, preferred: 'cherry-pick' },
  { source: /\bcommit(?:s|ted|ting)?\b/i, mistranslations: /(?:cam kết|committed|committing|commits?)/giu, preferred: 'commit' },
  { source: /\bcredits?\b/i, mistranslations: /tín dụng/giu },
  { source: /\bfetch(?:ed|ing)?\b/i, mistranslations: /(?:tìm nạp|fetched|fetching)/giu, preferred: 'fetch' },
  { source: /\bhealth\b/i, mistranslations: /sức khỏe/giu },
  { source: /\bhooks?\b/i, mistranslations: /móc/giu },
  { source: /\binventory\b/i, mistranslations: /(?:hàng tồn kho|khoảng không quảng cáo)/giu },
  { source: /\bmodels?\b/i, mistranslations: /(?:người mẫu|mẫu|models)/giu, preferred: 'model' },
  { source: /\bmonospaced?\b/i, mistranslations: /(?:đơn cách|một khoảng cách)/giu },
  { source: /\bobservability\b/i, mistranslations: /khả năng quan sát/giu },
  { source: /\bpipelines?\b/i, mistranslations: /(?:đường ống|pipelines)/giu, preferred: 'pipeline' },
  { source: /\bpull[- ]requests?\b/i, mistranslations: /(?:yêu cầu kéo|pull requests)/giu, preferred: 'pull request' },
  { source: /\bpull(?:ed|ing)?\b/i, mistranslations: /(?:kéo|pulled|pulling)/giu, preferred: 'pull' },
  { source: /\bpush(?:ed|ing)?\b/i, mistranslations: /(?:đẩy|pushed|pushing)/giu, preferred: 'push' },
  { source: /\bremotes?\b/i, mistranslations: /(?:điều khiển từ xa|từ xa|remotes)/giu, preferred: 'remote' },
  { source: /\brepositor(?:y|ies)\b/i, mistranslations: /(?:kho lưu trữ|kho|repositories)/giu, preferred: 'repository' },
  { source: /\brepos?\b/i, mistranslations: /(?:kho lưu trữ|kho|repos)/giu, preferred: 'repo' },
  { source: /\brefs?\b/i, mistranslations: /giới thiệu/giu },
  { source: /\bseeds?\b/i, mistranslations: /hạt giống/giu },
  { source: /\bspans?\b/i, mistranslations: /(?:khoảng cách|khoảng|nhịp|spans)/giu, preferred: 'span' },
  { source: /\bstacks?\b/i, mistranslations: /ngăn xếp/giu },
  { source: /\bstash(?:es)?\b/i, mistranslations: /(?:kho nhạc pop|kho lưu trữ|kho|cất giữ|cất giấu|stashes)/giu, preferred: 'stash' },
  { source: /\b(?:un)?staged?\b/i, mistranslations: /(?:chưa được dàn dựng|được dàn dựng|dàn dựng|giai đoạn)/giu },
  { source: /\btokens?\b/i, mistranslations: /(?:mã thông báo|tokens)/giu, preferred: 'token' },
  { source: /\btraces?\b/i, mistranslations: /(?:dấu vết|traces)/giu, preferred: 'trace' },
  { source: /\btriggers?\b/i, mistranslations: /trình kích hoạt/giu },
  { source: /\bupstream\b/i, mistranslations: /thượng nguồn/giu },
  { source: /\bwaves?\b/i, mistranslations: /(?:làn sóng|waves)/giu, preferred: 'wave' },
  { source: /\bworktrees?\b/i, mistranslations: /(?:sơ đồ công việc|cây công việc|cây làm việc|worktrees)/giu, preferred: 'worktree' },
  { source: /\bbackends?\b/i, mistranslations: /(?:phần phụ trợ|chương trình phụ trợ|phụ trợ|backends)/giu, preferred: 'backend' },
  { source: /\bcoding\b/i, mistranslations: /mã hóa/giu, preferred: 'lập trình' },
  { source: /\bbaseline\b/i, mistranslations: /đường cơ sở/giu },
  { source: /\bsidecars?\b/i, mistranslations: /(?:xe sidecar|sidecar)/giu },
  { source: /\btransports?\b/i, mistranslations: /vận chuyển/giu },
  { source: /\bwaves?\b/i, mistranslations: /(?:sóng biển|sóng)/giu, preferred: 'wave' },
  { source: /\bartifacts?\b/i, mistranslations: /(?:hiện vật|cấu phần phần mềm|artifacts)/giu, preferred: 'artifact' },
  { source: /\bcontexts?\b/i, mistranslations: /bối cảnh/giu, preferred: 'ngữ cảnh' },
  { source: /\bcutover\b/i, mistranslations: /(?:cắt bỏ|cắt giảm)/giu },
  { source: /\bdream\b/i, mistranslations: /(?:giấc mơ|ước mơ)/giu },
  { source: /\bModel Context Protocol\b/i, mistranslations: /Giao thức bối cảnh mô hình/giu },
  { source: /\bmutations?\b/i, mistranslations: /(?:đột biến|mutations)/giu, preferred: 'mutation' },
  { source: /\bsandbox(?:es)?\b/i, mistranslations: /hộp cát/giu },
  { source: /\bworkbenches?\b/i, mistranslations: /bàn làm việc/giu },
  { source: /\bfailed\b/i, mistranslations: /không thành công/giu, preferred: 'thất bại' },
  { source: /\bcut over\b/i, mistranslations: /cắt bỏ/giu, preferred: 'cutover' },
  { source: /\bleases?\b/i, mistranslations: /hợp đồng thuê/giu, preferred: 'lease' },
  { source: /\bmanifests?\b/i, mistranslations: /bảng kê khai/giu, preferred: 'manifest' },
]

const CURATED_TRANSLATIONS: Catalog = {
  '— idle —': '— đang chờ —',
  ', refreshing': ', đang làm mới',
  '; the local index says': '; chỉ mục cục bộ cho biết',
  '{0} {1} matched with logical OR. One match blocks access.':
    '{0} {1} được kết hợp bằng OR logic. Chỉ cần một điều kiện khớp là quyền truy cập sẽ bị chặn.',
  '{0} blocker{1}': '{0} trở ngại{1}',
  '{0} ok': '{0} OK',
  '{0} tracks {1}': '{0} theo dõi {1}',
  'A safe sample will be scaffolded at': 'Một mẫu an toàn sẽ được tạo tại',
  'Access key': 'Khóa truy cập',
  'Active usage': 'Mức sử dụng hiện tại',
  'Active claim': 'Claim đang hoạt động',
  'Accent': 'Điểm nhấn',
  'accent': 'điểm nhấn',
  'Applies to every surface except code blocks, which stay monospaced.':
    'Áp dụng cho toàn bộ giao diện, ngoại trừ khối mã luôn dùng font monospace.',
  'Arguments': 'Đối số',
  'arguments': 'đối số',
  'Assignee': 'Người được giao',
  'Assignees': 'Người được giao',
  'Attention queue': 'Hàng đợi cần chú ý',
  'Best effort': 'Cố gắng tối đa',
  'Binary asset': 'Tệp nhị phân',
  'Blocker': 'Trở ngại',
  'blocker': 'trở ngại',
  'Blockers': 'Trở ngại',
  'Backend connection': 'Kết nối backend',
  'Browser menu': 'Menu trình duyệt',
  'Checks': 'Kiểm tra',
  'checks': 'kiểm tra',
  'Choose a branch before pushing': 'Chọn branch trước khi push',
  'Cherry-pick commit': 'Cherry-pick commit',
  'Claiming todo': 'Đang nhận todo',
  'cell': 'ô',
  'Committed': 'Đã commit',
  'Configure git user.name and user.email before committing':
    'Cấu hình git user.name và user.email trước khi commit',
  'Collapse': 'Thu gọn',
  'collapse': 'thu gọn',
  'Compaction failed': 'Thu gọn thất bại',
  'Compact': 'Thu gọn',
  'compact': 'thu gọn',
  'compacting': 'đang thu gọn',
  'compaction': 'thu gọn',
  'Confidence': 'Độ tin cậy',
  'Context Usage': 'Mức sử dụng ngữ cảnh',
  'Close lightbox': 'Đóng trình xem ảnh',
  'comparisons': 'so sánh',
  'claim': 'claim',
  'claims': 'claim',
  'delegation': 'ủy quyền',
  'Delivery': 'Bàn giao',
  'deletions': 'mục đã xóa',
  'Drop stash': 'Xóa stash',
  'Elapsed': 'Thời gian đã chạy',
  'entry': 'mục',
  'execution graph': 'biểu đồ thực thi',
  'Expand pane': 'Mở rộng khung',
  'Editor': 'Trình soạn thảo',
  'editor': 'trình soạn thảo',
  'Explorer': 'Trình khám phá',
  'explorer': 'trình khám phá',
  'Filter agents': 'Lọc agent',
  'Fast unavailable': 'Fast không khả dụng',
  'Finding': 'Phát hiện',
  'Fit graph': 'Đưa biểu đồ vừa khung',
  'flow': 'luồng',
  'Font family': 'Font chữ',
  'form': 'biểu mẫu',
  'function': 'hàm',
  'generated': 'đã tạo',
  'grabbing': 'đang lấy',
  'hidden': 'ẩn',
  'Force push': 'Force push',
  'Force with lease': 'Force-with-lease',
  'Allow force with lease pushes': 'Cho phép push bằng force-with-lease',
  'gate': 'điểm kiểm duyệt',
  'human gate': 'điểm kiểm duyệt thủ công',
  'Intelligence': 'Trí tuệ',
  'Hit': 'Hit',
  'Hit rate': 'Tỷ lệ hit',
  'Hit tokens': 'Hit tokens',
  'Image lightbox': 'Trình xem ảnh',
  'In flight': 'Đang xử lý',
  'In progress': 'Đang thực hiện',
  'Imported sources': 'Nguồn đã nhập',
  'Idle': 'Đang chờ',
  'idle': 'đang chờ',
  'Lead': 'Lead',
  'lead': 'lead',
  'Lease expired': 'Lease đã hết hạn',
  'Light': 'Sáng',
  'light': 'sáng',
  'Live usage': 'Mức sử dụng hiện tại',
  'Loading pipelines': 'Đang tải pipeline',
  'Monospaced across the interface': 'Dùng font monospace trên toàn bộ giao diện',
  'Markdown note': 'Ghi chú Markdown',
  'Mask': 'Che dữ liệu',
  'menu': 'Menu',
  'Miss': 'Miss',
  'Miss tokens': 'Miss tokens',
  'more': 'thêm',
  'Next Fire': 'Lần chạy tiếp theo',
  'No open': 'Không có mục đang mở',
  'number': 'số',
  'Open Memory': 'Mở Memory',
  'Open Providers': 'Mở Providers',
  'Orange': 'Cam',
  'orange': 'cam',
  'Parent': 'Mục cha',
  'pattern is': 'mẫu là',
  'patterns are': 'các mẫu là',
  'Previous match': 'Kết quả khớp trước',
  'Next match': 'Kết quả khớp tiếp theo',
  'match': 'kết quả khớp',
  'matches': 'kết quả khớp',
  'Static match': 'Kết quả khớp tĩnh',
  'Session compacted': 'Đã thu gọn phiên',
  'Session compacting': 'Đang thu gọn phiên',
  'Scheduler': 'Bộ lập lịch',
  'scheduler': 'bộ lập lịch',
  'Secure transport and force-push protection are enabled.':
    'Đã bật transport an toàn và bảo vệ force-push.',
  'Pop stash': 'Áp dụng và xóa stash',
  'queue': 'hàng đợi',
  'Ran commands': 'Đã chạy lệnh',
  'Ran tools': 'Đã chạy công cụ',
  'redact': 'ẩn dữ liệu nhạy cảm',
  'Repository concurrency': 'Số repository chạy đồng thời',
  'Run monitor': 'Chạy Monitor',
  'Search agents': 'Tìm agent',
  'Search commands': 'Tìm command',
  'Spawning': 'Đang tạo',
  'Spawning {0}': 'Đang tạo {0}',
  'spawn': 'tạo',
  'Stage': 'Stage',
  'Stage file': 'Stage file',
  'Span aggregates & latency': 'Tổng hợp Span và độ trễ',
  'Span aggregates, latency and recent traces': 'Tổng hợp Span, độ trễ và các Trace gần đây',
  'State': 'Trạng thái',
  'State: {0}': 'Trạng thái: {0}',
  'Stop generation': 'Dừng tạo phản hồi',
  'Source-of-truth mismatch': 'Source of truth không khớp',
  'stale': 'đã cũ',
  'Stored in EvoFlux data, outside the source repo. Uncommitted source changes are not copied.':
    'Dữ liệu được lưu trong EvoFlux, bên ngoài source repo. Các thay đổi source chưa commit sẽ không được sao chép.',
  'this host': 'máy này',
  'Theme, accent, font, scale and motion': 'Chủ đề, điểm nhấn, font, tỷ lệ và hiệu ứng chuyển động',
  'tooltip': 'chú thích',
  'Transient retries': 'Thử lại khi gặp lỗi tạm thời',
  'Turn completed': 'Lượt đã hoàn tất',
  'turn done': 'lượt đã xong',
  'Unstage all': 'Unstage tất cả',
  'Unstage file': 'Unstage file',
  'use builtin': 'dùng bản tích hợp sẵn',
  'Use builtin': 'Dùng bản tích hợp sẵn',
  'Usage': 'Mức sử dụng',
  'usage': 'mức sử dụng',
  'wait': 'chờ',
  'Worker agent': 'Worker agent',
  'Workbench tools': 'Công cụ workbench',
}

const KEEP_ENGLISH = new Set([
  'AIM',
  'Anthropic Sans',
  'Artifacts',
  'Backend',
  'Bitbucket Cloud',
  'Breadcrumb',
  'Builtin sidecar',
  'Codex',
  'Doc',
  'Docstring',
  'Geist',
  'Inter',
  'Inventory',
  'Markdown',
  'MCP transport',
  'Rebase',
  'Repository',
  'Repository actions',
  'Sandbox',
  'Shell',
  'Source Control',
  'Stdio',
  'Telemetry',
  'Terminal',
  'Transport',
  'Trace',
  'WebBridge',
  'X-High',
  'aim',
  'alertdialog',
  'alert',
  'anthropic-sans',
  'artifacts',
  'backend',
  'bash',
  'breadcrumb',
  'checkbox',
  'codex',
  'columnheader',
  'combobox',
  'dialog',
  'drawio',
  'fish',
  'flex',
  'geist',
  'ghost',
  'grid',
  'group relative',
  'ini',
  'inter',
  'listbox',
  'markdown',
  'menuitem',
  'monospace',
  'monitor',
  'oauth',
  'object',
  'orchestrator',
  'radiogroup',
  'rebase',
  'repository',
  'rowgroup',
  'rst',
  'sass',
  'shell',
  'span',
  'spring',
  'stdio',
  'stroke',
  'separator',
  'progressbar',
  'swift',
  'table',
  'terminal',
  'trace',
  'webbridge',
  'backdrop',
])

function looksLikeTechnicalLiteral(source: string): boolean {
  if (KEEP_ENGLISH.has(source)) return true
  if (/\b[a-z]+[A-Z][A-Za-z]*\b/.test(source)) return true
  if (/^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)+$/.test(source)) return true
  if (/^[\w-]+(?::[\w-]*)+$/.test(source)) return true
  if (/^\{\d+\}(?:-[a-z]+)+(?:-\{\d+\})?$/.test(source)) return true
  if (/^(?:[a-z]{2}|true|false|null|undefined)$/.test(source)) return true
  if (/^(?:GET|POST|PUT|PATCH|DELETE)\s+\//.test(source)) return true
  if (/^(?:GET|POST|PUT|PATCH|DELETE)\b/.test(source)) return true
  if (/^\{\d+\}\/(?:_|[a-z])/.test(source) || /^\/(?:_|[a-z])/.test(source)) return true
  if (/^(?:\[[^\]]+\]|['"].*(?:sans-serif|monospace))/.test(source)) return true
  if (/(?:=>|document\.|"use strict"|&#\d+;)/.test(source) || source.includes(String.fromCharCode(27))) return true
  if (/[├└│]─/.test(source)) return true
  if (/\b(?:data|aria|role)-[\w-]+\s*=/.test(source)) return true
  if (/\b(?:object|whitespace|break|font|text|bg|border|flex|grid|items|justify|rounded|overflow|transition|cursor|stroke)-[\w:[\]./@()-]+/.test(source)) return true
  if (/^[\w@{}.-]+(?:[/_:][\w@{}.?=&-]+)+$/.test(source)) return true
  return false
}

function looksLikeDenseTechnicalCopy(source: string): boolean {
  if (source.length < 120) return false
  const terms = source.match(/\b(?:agent|api|branch|commit|context|credential|file|git|manifest|mcp|model|pipeline|provider|remote|repo|repository|review|runtime|sandbox|server|shell|source|token|tool|trace|workspace|worktree)s?\b/gi) ?? []
  return new Set(terms.map((term) => term.toLowerCase())).size >= 2
}

function sourceTerm(source: string, rule: TermRule): string | null {
  const pattern = rule.source
  const match = source.match(pattern)
  if (!match) return null
  if (!rule.preferred) return match[0]
  return /^[A-Z]/.test(match[0])
    ? `${rule.preferred.charAt(0).toUpperCase()}${rule.preferred.slice(1)}`
    : rule.preferred
}

function preserveTechnicalTerms(source: string, translation: string): string {
  let result = translation
  for (const rule of TECHNICAL_TERMS) {
    const term = sourceTerm(source, rule)
    if (term) result = result.replace(rule.mistranslations, term)
  }
  return result
}

const english = JSON.parse(fs.readFileSync(ENGLISH_PATH, 'utf8')) as Catalog
const vietnamese = JSON.parse(fs.readFileSync(VIETNAMESE_PATH, 'utf8')) as Catalog
let literalsReset = 0
let curated = 0
let terminologyFixed = 0

for (const [source, original] of Object.entries(vietnamese)) {
  let audited = original
  if (looksLikeTechnicalLiteral(source) || looksLikeDenseTechnicalCopy(source)) {
    audited = english[source] ?? source
    if (audited !== original) literalsReset += 1
  } else if (CURATED_TRANSLATIONS[source]) {
    audited = CURATED_TRANSLATIONS[source]
    if (audited !== original) curated += 1
  } else {
    audited = preserveTechnicalTerms(source, original)
    if (audited !== original) terminologyFixed += 1
  }
  vietnamese[source] = audited
}

fs.writeFileSync(VIETNAMESE_PATH, `${JSON.stringify(vietnamese, null, 2)}\n`)
console.log(`Vietnamese audit: ${literalsReset} technical literals reset, ${terminologyFixed} terminology fixes, ${curated} curated rewrites`)
