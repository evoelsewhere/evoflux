import type { HelpArticle, HelpCategory } from '../types'

export const HELP_CATEGORIES_VI: HelpCategory[] = [
  {
    id: 'getting-started',
    label: 'Bắt đầu',
    description: 'Cài đặt, kết nối model, chạy session đầu tiên',
  },
  {
    id: 'modes',
    label: 'Modes',
    description: 'Work và Coding',
  },
  {
    id: 'chat',
    label: 'Chat & team',
    description: 'Lead, specialist, view và permissions',
  },
  {
    id: 'composer',
    label: 'Composer',
    description: 'Mention, attachment, skill và workflow',
  },
  {
    id: 'slash',
    label: 'Slash & Goal',
    description: 'Slash command có sẵn và Goal bền vững',
  },
  {
    id: 'sessions',
    label: 'Session & folder',
    description: 'Pin, folder và share_context',
  },
  {
    id: 'workbench',
    label: 'Workbench',
    description: 'Panel bên cạnh chat',
  },
  {
    id: 'coding',
    label: 'Coding',
    description: 'Repo, project, git, Graph và PR',
  },
  {
    id: 'memory',
    label: 'Memory & Dream',
    description: 'Wiki kiến thức và tổng hợp',
  },
  {
    id: 'scheduler',
    label: 'Scheduler',
    description: 'Cron và one-shot agent task',
  },
  {
    id: 'browser',
    label: 'Browser & WebBridge',
    description: 'Browser trong app và Chrome/Edge thật',
  },
  {
    id: 'plugins',
    label: 'Plugins',
    description: 'Gói Agent Skills và MCP portable',
  },
  {
    id: 'settings',
    label: 'Settings',
    description: 'Providers, Agents, MCP, sandbox',
  },
  {
    id: 'shortcuts',
    label: 'Phím tắt',
    description: 'Command trên macOS, Ctrl trên Windows/Linux',
  },
  {
    id: 'troubleshooting',
    label: 'Xử lý sự cố',
    description: 'Connection, health và Diagnostics',
  }
]

export const HELP_ARTICLES_VI: HelpArticle[] = [
  {
    id: 'getting-started',
    category: 'getting-started',
    title: 'Bắt đầu với EvoFlux',
    summary:
      'Cài app desktop hoặc chạy từ source, kết nối BYOM provider, xác nhận sidecar khỏe, rồi gửi chat Work đầu tiên, mở repo Coding, hoặc mở workspace Coding. Đây là lộ trình từ lần mở app lạnh đến session streaming ổn định.',
    keywords: [
      'start',
      'install',
      'setup',
      'provider',
      'first',
      'onboarding',
      'desktop',
      'make dev',
      'sidecar',
      'HealthDot',
      'BYOM',
      'Welcome',
      'bun install',
      'bắt đầu',
      'cài đặt',
      'kết nối',
      'Providers'
],
    setup:
      'App desktop đóng gói tự khởi động FastAPI sidecar. Chạy từ source: Terminal 1 `make dev` (API + Vite), Terminal 2 `make -C desktop dev` (Tauri shell). Frontend: `cd web && bun install`. Chuẩn bị sẵn ít nhất một API key / OAuth / daemon local (Ollama…) trước khi chat lần đầu.',
    tricks: [
      'Bấm HealthDot ở footer sidebar để nhảy thẳng vào Connection khi backend trông không khỏe.',
      'Settings → Providers là bước đầu tiên — API key, OAuth, hoặc daemon local (Ollama…). Không có provider thì composer không stream được.',
      'Appearance → Display language hỗ trợ English, Vietnamese, Japanese cho UI; nội dung chat vẫn theo ngôn ngữ bạn gõ.',
      'Lần mở app lạnh vẫn hiện Welcome đến khi sidecar và team registry sẵn sàng — đợi xong mới chat, tránh soi nhầm “team trống”.',
      'Sau khi có provider, gửi một tin Work ngắn (“ping — reply with ok”) để verify streaming end-to-end trước khi mở repo lớn.',
      'Trong Coding, click repo chỉ focus workspace; dùng + / New chat để tạo session. Focus một mình không bao giờ mở transcript.',
      'Trong Coding, mở repo hoặc project từ sidebar rồi bắt đầu session trên workspace đó.',
      'Mở Guidelines bất cứ lúc nào từ nút Help trên sidebar (modal này); Ctrl+P vẫn là command palette — dành cho action nhanh, không phải docs.',
      'HealthDot xanh mà chat vẫn fail → mở Settings → Diagnostics trước khi reinstall; check subsystem thường đủ, không cần wipe sạch.',
      'Đừng dán credential BYOM vào transcript; chỉ cấu hình trong Settings → Providers.'
],
    blocks: [
      {
        type: 'p',
        text: 'EvoFlux là app desktop chạy local trên máy bạn: Tauri shell → React UI → FastAPI sidecar. Model theo kiểu BYOM — bạn mang provider của mình. Không cần tài khoản cloud của EvoFlux ngoài model provider bạn chọn. Transcript, wiki Memory, sandbox policy và git đều nằm trên đĩa local.',
      },
      {
        type: 'p',
        text: 'Dữ liệu local là hướng đi của sản phẩm. Hai mode (Work và Coding) dùng chung một team UI — Lead/specialist, composer, permissions và workbench — học một lần, đổi surface theo việc. Work cho research và folder tạm; Coding cho repo bền.',
      },
      {
        type: 'p',
        text: 'Bản đóng gói: tải build desktop theo OS rồi mở. Shell tự start sidecar trên ephemeral port kèm token handshake — thường bạn không cần gõ URL backend. Từ source: cài web deps (`cd web && bun install`), chạy `make dev` cho API + Vite, rồi `make -C desktop dev` để mở cửa sổ Tauri trỏ vào Vite URL.',
      },
      {
        type: 'tips',
        items: [
          '1) HealthDot xanh (hoặc mở Connection nếu không) và đợi Welcome tắt.',
          '2) Settings → Providers → kết nối ít nhất một model; xác nhận đã configured.',
          '3) Ở Work gửi chat ngắn đầu tiên, hoặc sang Coding mở git repository.',
          '5) Khi đã có session, thử workbench (Terminal, Files, Memory, Browser).',
          '6) Trước khi bật auto hoặc bypass: xem lại Settings → Sandbox deny globs.'
],
      },
      {
        type: 'p',
        text: 'HealthDot nằm ở footer sidebar cạnh theme toggle. Đỏ hoặc hổ phách nghĩa là UI chưa tới được backend khỏe — sửa Connection trước khi đuổi lỗi chat hay tool. Settings → Diagnostics chạy check subsystem live khi bạn cần tín hiệu chi tiết hơn “xanh/đỏ”.',
      },
      {
        type: 'p',
        text: 'Sai lầm ngày đầu hay gặp: gửi chat khi Welcome còn hiện; coi “không có model” là lỗi connection thay vì mở Providers; tưởng click repo Coding là tạo chat; bookmark `/scheduler` (route redirect về home — dùng Ctrl+S); coi Guidelines và Ctrl+P palette là cùng một thứ.',
      },
      {
        type: 'p',
        text: 'Khi nào ở Work, khi nào nhảy mode: Work cho browser task, docs, research theo folder, không cần vòng đời git. Sang Coding ngay khi cần Changes, Graph, Review, worktree hoặc AGENTS.md.',
      },
      {
        type: 'tips',
        items: [
          'Sau chat đầu thành công, mở Memory (Ctrl+M) để biết note bền sẽ nằm đâu.',
          'Lướt permission shield (phím 1–5) trước khi cho agent sửa repo thật.',
          'Ctrl+P → Search “Diagnostics” nếu health xanh mà panel tool vẫn trống.',
          'Chỉ khi chạy từ source: đừng mở Tauri khi `make dev` chưa phục vụ API.'
],
      },
      {
        type: 'p',
        text: 'Đọc tiếp: modes overview để chọn Work / Coding; Providers cho BYOM; Connection nếu HealthDot đỏ dai; Troubleshooting cho checklist sửa theo thứ tự.',
      }
],
    related: [
      'modes-overview',
      'providers-settings',
      'connection-settings',
      'troubleshooting-connection',
      'keyboard-shortcuts'
],
    openAction: { type: 'settings', path: 'providers' },
  },
  {
    id: 'modes-overview',
    category: 'modes',
    title: 'Work và Coding',
    summary:
      'Hai product mode dùng chung team UI nhưng khác workspace, specialist và tool mặc định. Mode switcher nhớ route cuối của từng mode — quay lại Coding là về đúng chỗ bạn rời.',
    keywords: [
      'mode',
      'work',
      'coding',
      'switch',
      'cowork',
      'route',
      'mode switcher',
      'chế độ',
      'Work',
      'Coding'
],
    tricks: [
      'Mode switcher nhớ last route theo mode — quay Coding là về đúng workspace path trước đó.',
      'Sidebar biến mất hoàn toàn khi thu gọn; dùng Ctrl+B hoặc nút sidebar nổi để mở lại.',
      'Khi đang ở Settings, mode switcher bị ẩn; thoát Settings rồi mới đổi mode lại.',
      'Work hợp research, docs, browser task, script tạm; Coding cho repo bền.',
      'Permission mode, slash và hầu hết workbench tool chạy xuyên mode; Overview / Graph / Changes / Review chỉ trong Coding.',
      'Đừng mở git monorepo trong Work rồi chờ Changes/Review — sang Coding để tool source-control gắn vào.',
      'Work: folder + share_context cho research song song; Coding: project khi các repo phải gắn với nhau.',
      'Mode memory theo mode, không theo window — nếu tưởng về Coding home trống, kiểm tra xem route workspace cũ có bị restore không.'
],
    blocks: [
      {
        type: 'p',
        text: 'Sidebar có hai mode cấp cao: Work (cowork sandbox) và Coding (repository và project). Mỗi mode có cây sidebar và danh sách session riêng, nhưng đội Lead/specialist, composer và model permissions vẫn quen — shortcut và Guidelines áp dụng mọi nơi.',
      },
      {
        type: 'p',
        text: 'Tách mode để cowork chung không làm bẩn git workspace, và để governance migration (approval, KB, pipeline) không tràn vào chat coding thường ngày. UI dùng chung nghĩa là bạn không phải học lại permissions, slash hay workbench mỗi lần đổi mode.',
      },
      {
        type: 'p',
        text: 'Work dùng private session folder hoặc folder local bạn chọn; không bắt buộc multi-repo project. Coding mở git repo hoặc multi-repo project; agent sửa cây thật với Graph, git, worktree và PR review. ',
      },
      {
        type: 'tips',
        items: [
          'Work — research, document, browser task, script nhanh, chat theo folder.',
          'Coding — single repo, multi-repo project, worktree, Graph, Changes, Review.',
          'Mode memory — last route mỗi mode được restore khi quay lại.',
          'Settings — mode switcher ẩn cho đến khi bạn rời settings route.'
],
      },
      {
        type: 'p',
        text: 'Khi nào dùng gì: Work khi output là note, bằng chứng browser, hoặc folder dùng rồi bỏ. Coding khi cần commit, PR, worktree hoặc AGENTS.md.',
      },
      {
        type: 'tips',
        items: [
          'Ctrl+B toggle sidebar giống nhau ở mọi mode.',
          'Scheduler task nhắm work hoặc coding mode tường minh — chọn đúng mode trên task.',
          'Skill và workflow có thể scope theo mode trong Settings; workflow chỉ Coding sẽ ẩn ở Work.'
],
      },
      {
        type: 'p',
        text: 'Đổi mode từng bước: (1) mở sidebar nếu đang thu gọn, (2) bấm Work hoặc Coding trong mode switcher, (3) chọn hoặc tạo session, (4) xác nhận workbench tool bạn cần có sẵn cho mode đó trước khi prompt agent.',
      }
],
    related: [
      'coding-workspaces',
      'getting-started',
      'sessions-folders',
      'workbench-tools'
],
  },
  {
    id: 'chat-team',
    category: 'chat',
    title: 'Lead và specialist',
    summary:
      'Lead sở hữu transcript bạn thấy; specialist bật theo nhu cầu và làm song song qua mailbox dùng chung. Đổi Agent, Split, Monitor trong khi theo dõi context budget bar để run dài vẫn cứu được.',
    keywords: [
      'lead',
      'specialist',
      'team',
      'agent',
      'split',
      'monitor',
      'mailbox',
      'Ctrl+V',
      'context budget',
      'auto-split',
      'đội',
      'Lead',
      'specialist'
],
    setup:
      'Mở bất kỳ session nào. Cấu hình team, model và tool trong Settings → Agents (scope work / coding). Session pills trên composer override model, thinking level và fast mode chỉ cho chat hiện tại.',
    tricks: [
      'Ctrl+V xoay Agent ↔ Split trên desktop (tắt khi field đang focus dùng paste).',
      'Command palette có Next / Previous Agent khi worker đang chạy — nhanh hơn lục identity dropdown.',
      'Auto-split có thể mở khi specialist activate để bạn theo dõi mà không tìm view menu.',
      'Monitor cho overview hoạt động cả đội khi nhiều worker live.',
      'Context budget bar trên workbench dùng context_length và summary_trigger_tokens của model — /compact sớm nếu thanh leo.',
      'Cấu hình model, skill, tool, permission từng agent trong Settings → Agents.',
      'Session pills trên composer set model, thinking level, fast mode chỉ cho chat hiện tại.',
      'Việc đơn giản để Lead làm; chỉ fan-out khi parallelism rõ ràng rút wall time.',
      'Tool chỉ Lead (ask_user, plan mode helper, một số worktree helper) không bao giờ cấp cho specialist — đừng chờ worker approve plan.'
],
    blocks: [
      {
        type: 'p',
        text: 'Mỗi session có một Lead agent sở hữu transcript hướng tới bạn. Việc phức tạp được tách thành subtask với goal và ràng buộc; specialist bật theo nhu cầu, trao kết quả qua mailbox dùng chung, Lead đánh giá evidence trước khi trả lời bạn.',
      },
      {
        type: 'p',
        text: 'Giữ việc đơn trên Lead tránh fan-out thừa và đốt token. Specialist song song rút wall time cho research, coding, migration và review; mailbox giữ coordination có cấu trúc thay vì đổ toàn bộ dump worker vào một chat.',
      },
      {
        type: 'p',
        text: 'View: Agent (focus một agent), Split (Lead + worker cạnh nhau), Monitor (overview hoạt động). Dùng identity dropdown trên workbench để nhảy agent, hoặc palette Next/Previous Agent. Ctrl+V toggle Agent ↔ Split trên desktop. Bật auto-split thì khi specialist activate có thể tự mở Split.',
      },
      {
        type: 'p',
        text: 'Context budget — thanh gần header workbench phản ánh token so với context window của model đang dùng. Gần summary trigger thì /compact hoặc chat mới, đừng chờ hard failure. Áp lực budget thường hiện như “agent quên file trước đó” trước khi hiện lỗi rõ.',
      },
      {
        type: 'tips',
        items: [
          'Agent — focus sâu một transcript (Lead hoặc specialist đã chọn).',
          'Split — xem Lead và worker song song.',
          'Monitor — overview khi nhiều agent đang chạy.',
          'Team scope theo work / coding trong Settings → Agents.',
          'Mailbox — kết quả specialist có cấu trúc; Lead tổng hợp cho bạn.'
],
      },
      {
        type: 'p',
        text: 'Task đa agent từng bước: (1) nêu outcome và ràng buộc cho Lead, (2) để specialist activate (hoặc yêu cầu research/coding song song), (3) sang Split hoặc Monitor theo dõi, (4) trả lời ask-user prompt kịp, (5) khi context bar leo thì /compact hoặc /new trước khi đổ attachment lớn tiếp.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: paste log khổng lồ vào Lead trong khi specialist đang tóm cùng file; đánh Ctrl+V khi composer đang focus (paste thắng); chờ Monitor hiện Coding Review PR (đó là workbench tool khác); để Agent view đứng trên specialist rồi thắc mắc tin nhắn bị “bơ” — chuyển về Lead.',
      },
      {
        type: 'tips',
        items: [
          'Nên fan-out — điều tra nhiều file, test/fix song song, lane specialist.',
          'Nên Lead-only — Q&A ngắn, sửa một file, lượt đầu nhạy permission.',
          'Ghép Split với Plan review để đọc plan khi worker chờ.',
          '/btw side chat cho câu meta mà không dừng team run.'
],
      }
],
    related: [
      'permissions-modes',
      'composer-power',
      'agents-settings',
      'keyboard-shortcuts',
      'side-chat'
],
  },
  {
    id: 'permissions-modes',
    category: 'chat',
    title: 'Permission mode và plan review',
    summary:
      'Điều khiển độ tự do của tool bằng ask, accept-edits, plan, auto hoặc bypass — rồi duyệt tool Once/Always/Reject và review plan bằng Accept/Revise/Reject. Tool filesystem áp deny glob dưới mọi mode.',
    keywords: [
      'permission',
      'ask',
      'accept-edits',
      'plan',
      'auto',
      'bypass',
      'approve',
      'shield',
      'Once',
      'Always',
      'Reject',
      'ask-user',
      'plan review',
      'quyền',
      'phê duyệt',
      'sandbox'
],
    setup:
      'Mở shield / permission control trên composer. Phím 1–5 hoạt động khi menu đó mở. Xem Settings → Sandbox trước khi bật auto hoặc bypass trên máy có quyền filesystem rộng.',
    tricks: [
      'Menu permission đang mở thì phím 1–5 nhảy ask → accept-edits → plan → auto → bypass.',
      'Ask dừng trước mọi tool call; accept-edits tự nhận file edit nhưng vẫn hỏi shell và thao tác phá hủy.',
      'Plan mode ghi nhận edit/shell đề xuất đến khi bạn Accept trong Plan review — hoặc Revise / Reject.',
      'Bôi đen text plan trong review panel để quote vào tin revise trên composer.',
      'Khi tool cần duyệt, chọn Once, Always hoặc Reject trên permission bar.',
      'Ask-user modal hiện khi agent cần câu trả lời có cấu trúc trước khi tiếp tục — trả lời để mở khóa run.',
      'Goal không bao giờ nới permission hay sandbox scope của session — set shield chủ đích trước `/goal`.',
      'Bypass bỏ mọi permission check — nhanh nhất, chỉ dùng trong môi trường disposable hoặc host bạn hoàn toàn tin cậy.',
      'Always dính theo rule khớp — ưu tiên Once khi còn đang học agent muốn chạy gì.'
],
    blocks: [
      {
        type: 'p',
        text: 'Mỗi session có PermissionMode: ask, accept-edits, plan, auto hoặc bypass. Song song, từng tool call vẫn có thể hiện Once / Always / Reject; plan mode có Plan review riêng với Accept / Revise / Reject. Coi shield là mặc định session, permission bar là override theo call.',
      },
      {
        type: 'p',
        text: 'Kiểm soát mịn giúp bạn giữ tay trên việc rủi ro (ask), nhanh hơn với edit (accept-edits), buộc cổng plan rõ (plan), chạy không người canh trong cây tin cậy (auto), hoặc bỏ prompt hẳn (bypass). Permission quyết định khi nào hỏi; tool filesystem vẫn kiểm tra workspace và deny glob. Lệnh shell chạy trực tiếp trên host sau bước quét denied path ở mức best effort.',
      },
      {
        type: 'p',
        text: 'Mở shield trên composer, chọn mode (hoặc 1–5). Ở plan mode, đợi Plan review: Accept chạy, Revise focus composer (có thể kèm selection đã quote), Reject dừng plan. Prompt tool đưa Once (call này), Always (nhớ theo rule khớp), hoặc Reject. Ask-user modal thu câu trả lời có cấu trúc giữa run.',
      },
      {
        type: 'tips',
        items: [
          '1 Ask — dừng trước mọi tool call.',
          '2 Accept edits — tự nhận file edit; hỏi shell / destructive.',
          '3 Plan — lập plan rồi duyệt trước khi chạy.',
          '4 Auto — tự approve thao tác.',
          '5 Bypass — bỏ permission check hoàn toàn.',
          'Tool filesystem — vẫn áp deny glob kể cả dưới bypass.'
],
      },
      {
        type: 'p',
        text: 'Chọn mode nào: ask cho repo lạ và cây sát production; accept-edits cho Coding ngày thường khi đã tin cây; plan cho refactor nhiều bước và thay đổi lớn bạn muốn đọc trước; auto cho host tin cậy và bảo trì theo lịch; bypass chỉ dùng theo burst ngắn, có chủ đích trong môi trường disposable.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: để bypass qua đêm; nhầm Always với “tin agent mãi mãi” (nó khớp theo rule); thoát plan mode giữa chừng rồi tưởng plan pending đã Accept; bỏ qua ask-user modal rồi nghĩ team treo; chờ Goal nới permission cho việc chạy không người canh.',
      },
      {
        type: 'tips',
        items: [
          'Bước — shield → Plan (3) → gửi task → Plan review → Accept / Revise / Reject.',
          'Bước — trên tool prompt, ưu tiên Once đến khi pattern rõ ràng an toàn.',
          'Ghép plan với quote-into-composer để revise đúng chỗ.',
          'Siết Sandbox trước khi auto trên multi-repo project.'
],
      },
      {
        type: 'p',
        text: 'MCP tool chịu cùng rule permission như tool native. Duyệt MCP call Once/Always theo cùng bar; sandbox và outbound policy vẫn áp. Tool “bị deny bất ngờ” → kiểm shield và Settings → Sandbox trước khi cấu hình lại MCP.',
      }
],
    related: ['slash-goal', 'sandbox-settings', 'plan-review', 'chat-team', 'agents-settings'],
  },
  {
    id: 'plan-review',
    category: 'chat',
    title: 'Plan review panel',
    summary:
      'Ở plan permission mode, đọc markdown plan của agent trước khi edit hay shell đã ghi nhận chạy. Accept thực thi, Revise chỉnh hướng (có thể kèm quote), Reject hủy đường plan — bạn giữ kiểm soát việc nhiều bước.',
    keywords: [
      'plan review',
      'Accept',
      'Revise',
      'Reject',
      'quote',
      'plan mode',
      'markdown plan',
      'Accept & execute',
      'xem kế hoạch',
      'chấp nhận',
      'plan'
],
    setup:
      'Set permission mode sang Plan (phím 3 trong shield menu), rồi gửi task cần nhiều bước. Giữ Plan review panel hiện — đừng đổi permission mode đến khi Accept, Revise hoặc Reject plan đang pending.',
    tricks: [
      'Bôi text trong plan document để quote vào tin revise — cách nhanh nhất để nói “chỉ đổi đoạn này”.',
      'Revise trả focus về composer để bạn chỉnh hướng mà không Reject cả plan.',
      'Reject dừng đường thực thi đã lập; sau đó gửi instruction mới mà không còn nửa bước nửa vời từ lượt plan đó.',
      'Thoát plan mode giữa chừng không tự Accept plan pending — giải Accept / Revise / Reject trước khi được nhắc.',
      'Sau Accept, cân nhắc hạ xuống accept-edits hoặc ask nếu muốn tool prompt chặt hơn lúc thực thi.',
      'Dùng plan mode trước Goal cho objective lớn để đoạn tự hành đầu bắt đầu từ outline đã duyệt.',
      'Plan mơ hồ thì Revise với Definition of Done cụ thể, đừng Accept rồi cầu may.',
      'Split hữu ích: giữ Plan review mở trong khi liếc trạng thái specialist.',
      'Chip quote revise xóa được trước khi send nếu đổi ý — cùng pipeline quote như selection trên transcript.'
],
    blocks: [
      {
        type: 'p',
        text: 'Plan review là UI cổng cho plan permission mode. Agent soạn markdown plan; edit và shell được ghi nhận đến khi bạn Accept & execute, yêu cầu Revise, hoặc Reject. Không gì trong batch plan đó nên chạy trước Accept — đó chính là ý nghĩa của cổng.',
      },
      {
        type: 'p',
        text: 'Dùng khi hướng sai đắt: refactor nhiều file, migration chạm module dùng chung, shell phá hủy, hoặc task bạn muốn outline đọc được trước khi tool nổ. Bỏ qua với fix một dòng và Q&A tầm thường — ask hoặc accept-edits đủ.',
      },
      {
        type: 'p',
        text: 'Đọc plan trong review panel từ trên xuống: goal, bước, file, rủi ro, verification. Highlight đoạn cần và quote-into-composer khi revise. Accept tiếp tục với plan đã duyệt; Reject hủy lượt plan đó. Sau Accept có thể hạ ask hoặc accept-edits nếu muốn tool prompt chặt hơn lúc chạy.',
      },
      {
        type: 'tips',
        items: [
          'Accept — thực thi đường plan đã duyệt.',
          'Revise — focus composer; optional selection đã quote.',
          'Reject — hủy lượt plan này; gửi instruction mới.',
          'Quote — chọn text plan → chip revise phía trên draft.',
          'Shield 3 — vào plan mode trước task, không phải sau khi tool đã chạy.'
],
      },
      {
        type: 'p',
        text: 'Từng bước: (1) mở shield → Plan, (2) mô tả outcome và ràng buộc, (3) đợi Plan review, (4) lướt rủi ro và danh sách file, (5) Accept, hoặc chọn đoạn yếu → quote → Revise, hoặc Reject rồi viết lại ask, (6) tùy chọn siết permission mode cho giai thực thi.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: Accept plan chưa đọc vì “trông dài đủ”; Reject khi ý là Revise (mất cấu trúc hữu ích); nhảy bypass để “chạy luôn” rồi mất audit trail bạn muốn; tưởng Reject xóa tool call thành công từ lượt trước — nó chỉ dừng đường thực thi plan đó.',
      },
      {
        type: 'tips',
        items: [
          'Revise tốt nêu rõ file, test và out-of-scope.',
          'Revise xấu mơ hồ (“làm tốt hơn”) — quote bullet yếu trước.',
          'Câu meta không liên quan đẩy sang side chat để thread plan sạch.',
          'Sau Accept việc Coding, mở Changes (Ctrl+G) xem diff có khớp plan không.'
],
      },
      {
        type: 'p',
        text: 'Đừng dùng plan review thay sandbox policy. Plan đẹp vẫn có thể đề xuất path bạn không bao giờ muốn chạm — giữ deny globs trong Settings → Sandbox, và Reject plan nới scope vào secret, vendor dir hoặc repo không liên quan.',
      }
],
    related: ['permissions-modes', 'composer-power', 'attachments', 'slash-goal', 'coding-git'],
  },
  {
    id: 'composer-power',
    category: 'composer',
    title: 'Composer — tính năng mạnh',
    summary:
      'Dùng /, !, @, # snippet, attachment, quote selection, Work folder targeting, skill lồng nhau và workflow với RunInputsDialog. Undo cũng khôi phục attachment — draft còn cứu được sau lần send hỏng.',
    keywords: [
      'composer',
      'mention',
      '@',
      '#',
      'snippet',
      'attach',
      'drag',
      'paste',
      'skill',
      'workflow',
      'RunInputsDialog',
      'WorkFolderSelector',
      'quote',
      '!',
      'shell',
      'soạn thảo',
      'đính kèm',
      'đề cập'
],
    setup:
      'Focus composer (Ctrl+I). Attachment phải được bật cho session. Ở Work, WorkFolderSelector nằm gần composer để đổi session folder. Ở Coding, # snippet cần định nghĩa workspace hoặc global.',
    tricks: [
      'Bắt đầu tin bằng ! để chạy shell (hoặc chọn /shell để prefill bang mode).',
      'Gõ @ để chèn path file/folder xếp hạng từ workspace đang active.',
      'Ở Coding, gõ # để bung workspace hoặc global snippet vào composer.',
      'Skill lồng dùng /skill:parent:child (`:` và `/` đổi cho nhau được với tên nested).',
      'Workflow mở RunInputsDialog khi cần tham số và không bao giờ gửi raw slash text như chat thường.',
      'Undo khôi phục user message trước và cả attachment vào composer.',
      'Paste ảnh/file hoặc kéo-thả lên composer khi attachment được bật.',
      'Bôi transcript để Add to chat, more details, hoặc Send to side chat.',
      'Ưu tiên @ mention hơn paste cả file — path xếp hạng giữ context gọn và rẻ hơn.',
      'Custom command dưới .evoflux/commands/ thường insert vào textarea để bạn nối $ARGUMENTS.'
],
    blocks: [
      {
        type: 'p',
        text: 'Composer không chỉ là ô text: slash menu (/), shell bang (!), path mention (@), Coding snippet (#), file attachment, chip quote, WorkFolderSelector cho session Work, skill directive và workflow đã duyệt. Nắm các affordance này là khác biệt giữa đổ cả cây vào prompt và lái chính xác.',
      },
      {
        type: 'p',
        text: 'Các control này giữ context đúng chỗ, không ngập model. Skill và workflow đóng gói quy trình lặp; attachment và quote ghim evidence; WorkFolderSelector đổi session folder mà không cần mở Files. Shell bang cho lệnh chủ đích — không thay Terminal khi cần session tương tác dài.',
      },
      {
        type: 'p',
        text: 'Gõ / mở command menu (built-in, skill dưới /skill:, workflow, custom .evoflux/commands/). Prefix ! cho shell. Dùng @ chọn path. Ở Coding, # bung snippet. Kéo-thả hoặc paste file lên bar. Session Work: WorkFolderSelector gần composer để trỏ private session folder hoặc thư mục local khác. Sau /undo, cả text và attachment về draft.',
      },
      {
        type: 'tips',
        items: [
          '/ — slash command, skill, workflow, custom command',
          '! — shell mode cho phần còn lại của dòng',
          '@ — mention file/folder',
          '# — snippet (Coding workspace)',
          'DnD / paste — attachment khi được bật',
          'Quote selection — Add to chat hoặc Send to side chat',
          'WorkFolderSelector — đổi Work session folder',
          'RunInputsDialog — tham số workflow trước khi launch'
],
      },
      {
        type: 'p',
        text: 'Ask Coding chính xác từng bước: (1) @ các file quan trọng, (2) attach screenshot hoặc log chỉ khi cần, (3) nêu outcome và test, (4) tùy chọn /skill:… cho quy trình quen, (5) set permission mode, (6) send. Research Work: set WorkFolderSelector, attach nguồn, quote câu trả lời trước, rồi hỏi.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: gửi raw `/workflow name` mong nó chạy (workflow launch qua menu/dialog); nest skill bằng space thay vì `:` / `/`; dùng # ở Work chờ snippet Coding; paste secret vào composer thay vì cấu hình Providers; quên /undo cũng restore attachment — gửi lại cẩn nếu file nhạy cảm.',
      },
      {
        type: 'tips',
        items: [
          'Khi dùng ! — one-liner ngắn gắn với lượt chat.',
          'Khi dùng Terminal (Ctrl+`) — process tương tác hoặc chạy lâu.',
          'Khi dùng @ — path đã biết; Files browse khi còn đang khám.',
          'Quote → Send to side chat cho /btw mà không dừng Goal.'
],
      },
      {
        type: 'p',
        text: 'Workflow phải được approve và hợp scope session (work / coding) nếu không sẽ ẩn. Skill hiện dưới /skill: chỉ sau khi validate trong Settings → Skills. Command thiếu → kiểm scope và validation trước khi đổ lỗi slash.',
      }
],
    related: [
      'slash-commands',
      'attachments',
      'side-chat',
      'coding-workspaces',
      'agents-settings'
],
  },
  {
    id: 'attachments',
    category: 'composer',
    title: 'Attachment, paste và quote',
    summary:
      'Đính file bằng kéo-thả hoặc paste, quote selection từ transcript hoặc plan vào tin tiếp, và dựa vào /undo để khôi phục attachment cùng draft. Quote và file là cách ghim evidence mà không viết lại context tay.',
    keywords: [
      'attachment',
      'drag and drop',
      'paste',
      'quote',
      'Add to chat',
      'image',
      'file',
      'chip',
      'clipboard',
      'đính kèm',
      'dán',
      'trích dẫn'
],
    setup:
      'Attachment phải được bật cho session/composer; một số môi trường tắt upload vì policy. Xác nhận drop target của composer highlight trước khi tin kéo-thả. Quote hoạt động từ selection trên transcript, Plan review và Send to side chat.',
    tricks: [
      'Paste từ clipboard (ảnh/file) hoặc kéo lên drop target composer — cả hai gắn vào user message tiếp theo.',
      'Context đã quote hiện chip phía trên draft — xóa nếu đổi ý trước khi send.',
      'Quote từ Plan review → composer dùng cùng pipeline với selection trên transcript.',
      '/undo khôi phục attachment thuộc user message vừa undo — text và file về cùng nhau.',
      'Send to side chat mang quote vào /btw mà không ngắt run chính.',
      'Ưu tiên quote gọn + ask ngắn hơn paste lại cả bài assistant trước.',
      'Ảnh giúp bug UI và error dialog; stack trace thì paste text hoặc attach .log để model copy token đúng.',
      'Xóa chip quote cũ trước khi đổi chủ đề — quote sót âm thầm bias lượt sau.',
      'Paste “không làm gì” → kiểm focus đang trên composer và attachment đã bật cho session.'
],
    blocks: [
      {
        type: 'p',
        text: 'Attachment là file (thường cả ảnh) gắn với user message. Quote là text chọn từ transcript, plan panel hoặc targeting side-chat, trở thành context cho lần send tiếp. Cùng nhau chúng ghim evidence — bạn khỏi mô tả lại UI state hay khối lỗi mỗi lượt.',
      },
      {
        type: 'p',
        text: 'Dùng attachment khi byte quan trọng: screenshot, PDF, CSV, log nhỏ, design export. Dùng quote khi text đã nằm trong transcript hoặc plan và bạn muốn follow-up chính xác. Đừng attach cả repository — dùng @ mention, Files hoặc Coding graph tool.',
      },
      {
        type: 'p',
        text: 'Drop hoặc paste file lên composer. Bôi text trên transcript cho Add to chat / more details / Send to side chat. Trong Plan review, chọn text plan để quote vào tin revise. Sau undo, gửi lại hoặc sửa draft đã restore kèm file. Nhìn chip quote phía trên draft trước khi bấm send.',
      },
      {
        type: 'tips',
        items: [
          'Drag-drop — file lên drop target composer',
          'Paste — ảnh/file clipboard vào composer đang focus',
          'Add to chat — quote transcript vào draft chính',
          'Send to side chat — quote vào /btw song song',
          'Plan quote — chọn markdown plan → chip revise',
          '/undo — khôi phục text user trước + attachment',
          'Clear chip — bỏ quote trước send nếu đã đổi chủ đề'
],
      },
      {
        type: 'p',
        text: 'Báo bug từng bước: (1) reproduce và chụp screenshot, (2) paste hoặc drop lên composer, (3) quote bước assistant lỗi hoặc dòng error nếu có, (4) nêu expected vs actual, (5) send dưới ask hoặc plan nếu fix chạm nhiều file.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: attach secret (.env, key file) “cho có context”; xếp năm binary lớn đến khi context budget nhảy; quote đoạn plan cũ sau khi agent đã revise; tưởng quote side-chat tự merge vào history parent (không).',
      },
      {
        type: 'tips',
        items: [
          'Không nên attach — artifact build khổng lồ, zip node_modules, dump DB đầy.',
          'Nên quote — bất đồng một đoạn, revise một bullet plan, hỏi “explain this”.',
          'Sau /undo, xem lại attachment đã restore trước khi gửi lại.',
          'WorkFolderSelector không attach folder; nó đổi session root trên đĩa.'
],
      },
      {
        type: 'p',
        text: 'Policy: org tắt upload thì bạn vẫn còn quote và @ mention — ưu tiên các đường đó thay vì vật lộn với cổng attachment. Outbound PII redaction trong Settings → Sandbox vẫn có thể áp khi nội dung đi ra provider.',
      }
],
    related: [
      'composer-power',
      'plan-review',
      'side-chat',
      'slash-commands',
      'sandbox-settings'
],
  },
  {
    id: 'slash-commands',
    category: 'slash',
    title: 'Slash command có sẵn',
    summary:
      'Gõ / trong composer cho stop, compact, undo, init, btw, goal, skill, workflow và custom command từ .evoflux/commands/. Built-in chạy ngay; custom thường insert để bạn điền argument.',
    keywords: [
      'slash',
      '/stop',
      '/compact',
      '/undo',
      '/init',
      '/btw',
      '/goal',
      '/workflow',
      '/skill',
      'command',
      '.evoflux/commands',
      'lệnh',
      'lệnh tùy chỉnh'
],
    tricks: [
      'Built-in chạy ngay khi chọn; custom thường insert vào textarea để bạn nối $ARGUMENTS.',
      'Khớp longest-prefix; `:` và `/` đổi cho nhau với tên command/skill nested.',
      'Custom command nằm dưới project hoặc global .evoflux/commands/ (và path OpenCode tương thích).',
      'Skill hiện dưới /skill: chỉ sau khi validate trong Settings → Skills.',
      'Workflow phải approve và hợp scope session (work / coding) nếu không sẽ ẩn.',
      '/compact sớm khi context budget bar leo — chờ failure phí một lượt.',
      '/init hướng Coding cho AGENTS.md; nó hướng tới AGENTS.md.',
      '/stop là nút panic khi specialist fan-out loạn; kèm instruction rõ hơn sau đó.',
      'Ưu tiên /btw hơn làm bẩn transcript chính bằng câu meta trong run dài.'
],
    blocks: [
      {
        type: 'p',
        text: 'Slash command là lối tắt chính trên composer. Built-in điều khiển team run; goal subcommand quản objective bền; skill và workflow gắn hành vi có cấu trúc; command Markdown/YAML do bạn định nghĩa được server bung ra. Menu có search — gõ vài chữ để lọc.',
      },
      {
        type: 'p',
        text: 'Slash giúp action hay dùng dễ tìm, không phải lục menu, và để repo mang convention của đội qua `.evoflux/commands/` đi cùng project. Coi custom command là runbook dùng chung — không phải chỗ giấu secret.',
      },
      {
        type: 'slash',
        commands: [
          { cmd: '/stop', desc: 'Dừng mọi agent đang làm việc ngay' },
          { cmd: '/continue', desc: 'Tiếp tục phản hồi assistant gần nhất' },
          { cmd: '/compact', desc: 'Tóm tắt và compact context của session này' },
          { cmd: '/shell', desc: 'Prefill shell mode (! command)' },
          { cmd: '/undo', desc: 'Undo user message trước (khôi phục text + attachment)' },
          { cmd: '/redo', desc: 'Khôi phục message đã undo về tip live' },
          { cmd: '/new', desc: 'Bắt đầu conversation team mới' },
          { cmd: '/init', desc: 'Tạo hoặc cập nhật AGENTS.md (Coding workspace)' },
          { cmd: '/btw', desc: 'Mở side chat với quyền read-only tới session này' },
          { cmd: '/goal <objective>', desc: 'Bắt đầu Goal tự hành bền vững' },
          { cmd: '/goal', desc: 'Xem trạng thái Goal đang active' },
          { cmd: '/goal:budget <tokens|none>', desc: 'Đặt hoặc xóa token budget của Goal' },
          { cmd: '/goal:pause', desc: 'Tạm dừng Goal đang active' },
          { cmd: '/goal:resume', desc: 'Tiếp tục Goal đã pause' },
          { cmd: '/goal:stop', desc: 'Gỡ Goal khỏi session' },
          { cmd: '/skill:…', desc: 'Gắn skill cho tin tiếp (nested: /skill:parent:child)' },
          { cmd: '/workflow <name>', desc: 'Chạy workflow đã duyệt (có thể mở RunInputsDialog)' }
],
      },
      {
        type: 'p',
        text: 'Gõ / để lọc command. Chọn built-in để chạy, hoặc custom/skill/workflow để insert hoặc launch. Đặt file custom dưới `.evoflux/commands/` trong project hoặc config EvoFlux global. Tên nested ưu tiên longest prefix; dùng `:` hoặc `/` làm separator. Workflow có thể mở RunInputsDialog và không gửi raw slash line như chat thường.',
      },
      {
        type: 'tips',
        items: [
          'Built-in — chạy ngay khi chọn',
          'Custom — thường insert; nối $ARGUMENTS',
          'Skill — /skill: sau Settings → Skills validation',
          'Workflow — cần scope + approval nếu không sẽ ẩn',
          'Longest prefix — nest parent:child với : hoặc /'
],
      },
      {
        type: 'p',
        text: 'Custom command từng bước: (1) thêm Markdown/YAML dưới `.evoflux/commands/`, (2) reload hoặc mở lại slash menu, (3) chọn command để insert, (4) điền argument, (5) send. Chỉ thêm custom command bạn cần — prompt không dùng cố tình không vào menu.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: chờ `/scheduler` mở trang (dùng Ctrl+S — route redirect home); coi workflow thiếu là bug composer khi scope/approval sai; /compact quá muộn đến mức summary mất constraint vẫn cần; dùng /undo tưởng revert git commit — nó chỉ restore draft user message trước.',
      },
      {
        type: 'tips',
        items: [
          'Khi /new — đổi chủ đề mà context bar đã bẩn.',
          'Khi /compact — cùng chủ đề, budget leo, cần giữ continuity.',
          'Khi /stop — tool chạy loạn hoặc fan-out sai; rồi nêu lại ask.',
          '/init + Coding Overview sau khi mở repo mới.'
],
      }
],
    related: [
      'slash-goal',
      'side-chat',
      'composer-power',
      'coding-workspaces'
],
  },
  {
    id: 'slash-goal',
    category: 'slash',
    title: 'Goal mode bền vững',
    summary:
      'Chạy objective tự hành sống sót qua reconnect, kèm token budget tùy chọn, pause/resume/stop và blocker streak — mà không nới permission hay sandbox. Goal dành cho việc nên tiếp tục sau khi bạn đóng cửa sổ.',
    keywords: [
      'goal',
      '/goal',
      'budget',
      'autonomous',
      'pause',
      'resume',
      'blocker',
      'blocker streak',
      '/goal:pause',
      '/goal:resume',
      '/goal:stop',
      '/goal:budget',
      'mục tiêu',
      'ngân sách',
      'tạm dừng'
],
    setup:
      'Bắt đầu bằng `/goal <objective>` ở bất kỳ mode nào. Tùy chọn: `/goal:budget <tokens>` trước hoặc trong lúc chạy. Set permission mode và Settings → Sandbox chủ đích trước — Goal không bao giờ nới chúng.',
    tricks: [
      '/goal một mình để xem status; /goal:budget <tokens|none> để đổi hoặc xóa budget.',
      'Pause / resume / stop bằng /goal:pause, /goal:resume, /goal:stop.',
      'Cùng một blocker cụ thể báo ba lượt liên tiếp thì dừng tiến độ; UI hiện blocker streak.',
      'Goal state, thời gian đã chạy và token usage sống sót qua restart app và reconnect.',
      'Turn nội bộ ẩn tiếp tục đến khi hoàn thành, budget pause, bạn pause/stop, hoặc blocker streak.',
      'Goal không nới permission mode hay sandbox — set chúng chủ đích trước khi start.',
      'Objective rõ + token budget cho run overnight không người canh.',
      'Objective lớn: draft bằng plan mode trước, Accept, rồi `/goal` để autonomy bắt đầu từ outline đã duyệt.',
      'Dùng /btw cho câu meta khi Goal đang chạy để không lệch transcript objective.'
],
    blocks: [
      {
        type: 'p',
        text: 'Goal mode gắn objective tự hành bền vào session. Lead làm việc qua turn nội bộ đến khi objective ghi nhận hoàn thành, budget pause, bạn pause/stop, hoặc blocker streak kích. Đóng cửa sổ không được quên objective.',
      },
      {
        type: 'p',
        text: 'Chat thường dừng khi bạn đóng cửa sổ hoặc hết lượt. Goal dành cho objective dài hơn (“migrate module X”, “xong checklist refactor”) cần resume sau reconnect mà không phải prompt lại từng bước. Đó không phải giấy phép bỏ qua an toàn.',
      },
      {
        type: 'p',
        text: 'Chạy `/goal ship the login refactor with tests` để bắt đầu. `/goal` hiện status. `/goal:budget 200000` đặt trần token; `/goal:budget none` xóa. `/goal:pause` / `/goal:resume` / `/goal:stop` điều khiển vòng đời. Theo dõi UI Goal cho thời gian, token và blocker streak. Permission và sandbox giữ đúng cấu hình session.',
      },
      {
        type: 'slash',
        commands: [
          { cmd: '/goal <objective>', desc: 'Bắt đầu việc tự hành bền vững' },
          { cmd: '/goal', desc: 'Hiện trạng thái Goal' },
          { cmd: '/goal:budget <tokens|none>', desc: 'Đặt hoặc xóa token budget' },
          { cmd: '/goal:pause', desc: 'Tạm dừng thực thi' },
          { cmd: '/goal:resume', desc: 'Tiếp sau pause hoặc budget hold' },
          { cmd: '/goal:stop', desc: 'Xóa Goal khỏi session' }
],
      },
      {
        type: 'tips',
        items: [
          'Viết objective kèm Definition of Done và danh sách out-of-scope.',
          'Đặt token budget trước run overnight.',
          'Theo dõi blocker streak — cùng blocker ×3 thì dừng tiến độ.',
          'Đừng chờ Goal tự flip ask → bypass giúp bạn.',
          'Dùng /goal:pause trước khi sửa tay lớn trên cùng cây.'
],
      },
      {
        type: 'p',
        text: 'Nên dùng: refactor Coding nhiều giờ, chore theo checklist, research cần tiếp sau khi ngủ. Không nên: tranh luận design tương tác, Q&A một phát, hoặc việc cần phán đoán của người mỗi phút — ở chat thường hoặc plan review.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: start Goal dưới bypass trên home directory rộng; quên budget rồi dậy thấy bill khổng lồ; bỏ qua blocker streak rồi prompt lại bước kẹt; dùng /stop thay /goal:stop (khác lớp); nhồi nhiều objective không liên quan vào một dòng `/goal`.',
      },
      {
        type: 'tips',
        items: [
          'Bước — shield + sandbox → optional plan Accept → /goal:budget → /goal <objective>.',
          'Bước — kẹt → đọc blocker → /goal:pause → sửa môi trường → /goal:resume.',
          'Scheduler cho cron prompt; Goal là autonomy trong session.',
          'Dream cron riêng dưới Settings → Memory.'
],
      }
],
    related: [
      'permissions-modes',
      'slash-commands',
      'chat-team',
      'plan-review',
      'scheduler-tasks'
],
  },
  {
    id: 'sessions-folders',
    category: 'sessions',
    title: 'Session, ghim và thư mục Work',
    summary:
      'Ghim (pin) chat quan trọng, xếp session Work vào thư mục (folder) bằng kéo-thả, bật/tắt share_context để nhận bản tóm tắt ngắn từ các session khác trong cùng folder, và xóa thư mục mà không xóa conversation. Filing chỉ là tổ chức — không viết lại history hay model settings.',
    keywords: [
      'folder',
      'pin',
      'session',
      'drag',
      'share context',
      'share_context',
      'Move to folder',
      'unfile',
      'Ctrl+R',
      'Today',
      'Pinned',
      'thư mục',
      'ghim',
      'phiên',
      'chia sẻ ngữ cảnh'
],
    setup:
      'Sidebar Work → section Folders. Coding dùng cây session riêng; folder filing là tính năng tổ chức của Work. Ctrl+R refresh danh sách session Work sau thay đổi bên ngoài.',
    tricks: [
      'Kéo hàng session lên header folder (desktop), hoặc dùng Move to folder… trên touch.',
      'Icon link trên folder bật/tắt share_context — các session cùng folder nhận bản tóm tắt ngắn (bounded) của nhau.',
      'Folder + tạo chat mới đã nằm sẵn trong folder đó.',
      'Xóa folder chỉ un-file session; conversation không bị xóa theo folder.',
      'Ctrl+R refresh danh sách session sidebar Work.',
      'Pin session để giữ chúng trên cùng, trên Today / Yesterday / Older.',
      'Filing chỉ set folder_id — history, model và workspace settings vẫn theo session.',
      'Transcript dài preload history cũ trước mép trên vài màn hình; cuộn nhanh lên vẫn giữ đoạn đang đọc ổn định khi turn cũ xuất hiện.',
      'Tắt share_context với folder client nhạy cảm — không để tóm tắt lọt sang session khác.',
      'Đặt tên folder theo outcome (“RFP research”, “incident 4821”), không theo ngày — ngày đã nhóm chat chưa file.',
      'Unfile qua Move to folder… → none khi thread không còn thuộc sibling.'
],
    blocks: [
      {
        type: 'p',
        text: 'Session Work có thể pin và xếp vào folder có tên. Folder tùy chọn bật share_context để chat sibling trao đổi bản tóm tắt ngắn có giới hạn. Session chưa file vẫn nhóm theo Pinned / Today / Yesterday / Older. và Coding giữ cây riêng — đừng tìm Work folder ở đó.',
      },
      {
        type: 'p',
        text: 'Cowork dài ngày tích nhiều chat. Folder giữ research thread, việc client hoặc thí nghiệm tách bạch mà không cắt nhỏ history và model settings của từng session. Pin giữ vài chat bạn mở hàng ngày khỏi chìm dưới Today.',
      },
      {
        type: 'p',
        text: 'Tạo folder trên sidebar Work. Kéo session lên header folder, hoặc mở session menu → Move to folder…. Bấm icon link để toggle share_context. Dùng + trên folder để mở chat mới đã file sẵn. Xóa folder để unfile session; chỉ dùng action xóa session khi bạn thật sự muốn xóa conversation.',
      },
      {
        type: 'tips',
        items: [
          'Pin — giữ session quan trọng trên cùng.',
          'share_context — bản tóm tắt ngắn giữa sibling (icon link).',
          'Folder + — chat mới đã pre-file.',
          'Xóa folder — chỉ unfile; chat vẫn còn.',
          'Ctrl+R — refresh danh sách session Work.',
          'Move to folder… — file / unfile thân thiện touch.',
          'Today / Yesterday / Older — nhóm tự động cho chat chưa file.'
],
      },
      {
        type: 'p',
        text: 'Setup project trong Work: (1) tạo folder đặt tên theo engagement, (2) bật share_context chỉ khi tóm tắt giữa các session thật sự giúp, (3) Folder + cho thread chính, (4) mở thêm chat sibling cho research song song, (5) pin chat decision log, (6) sau này xóa folder để unfile mà không mất history.',
      },
      {
        type: 'p',
        text: 'Khi dùng share_context: góc nhìn song song trên cùng câu research, bản tóm tắt giúp tránh làm trùng. Khi không: dữ liệu client có quy định, chủ đề HR, hoặc thứ không được để tóm tắt lọt sang chat bên cạnh — để icon link tắt.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: xóa folder tưởng chat biến mất; tưởng filing copy path filesystem của WorkFolderSelector; kéo trên mobile mà không dùng Move to folder…; chờ session Coding hiện dưới Work folder; để share_context bật sau khi folder đổi sang việc nhạy cảm.',
      },
      {
        type: 'tips',
        items: [
          'WorkFolderSelector set folder trên đĩa cho tool; sidebar folder tổ chức chat.',
          'Pin + Goal trên chat quyết định cho engagement dài.',
          '/new trong folder giữ filing nếu bạn bắt đầu từ Folder +.',
          'Ctrl+R nếu session vừa chuyển không hiện đúng chỗ.'
],
      }
],
    related: [
      'composer-power',
      'modes-overview',
      'getting-started',
      'slash-goal',
      'side-chat'
],
  },
  {
    id: 'workbench-tools',
    category: 'workbench',
    title: 'Workbench tools',
    summary:
      'Mở Terminal, Browser, Files, Graph, Side chat, Memory, Scheduler, Changes và Review bên cạnh chat — shortcut tự theo OS: Command trên macOS, Ctrl trên Windows/Linux.',
    keywords: [
      'workbench',
      'panel',
      'terminal',
      'files',
      'dock',
      'overview',
      'graph',
      'Changes',
      'Review',
      'Ctrl+F',
      'Ctrl+;',
      '⌘P',
      '⌥⌘S',
      'bảng',
      'bảng công cụ'
],
    setup:
      'Mở session trước. Coding Overview, Graph, Changes và Review cần Coding workspace. Built-in Browser phải bật trong Settings → Browser trước khi Ctrl+T hữu ích.',
    tricks: [
      'Mở tool từ workbench bar, dock, hoặc shortcut bên dưới.',
      'Coding Overview chỉ hiện khi đã chọn workspace.',
      'Shortcut runtime và label tự theo OS: Command trên macOS, Ctrl trên Windows/Linux.',
      'Mapping sống: Files = Ctrl+F (label có thể hiện ⌘P); Side chat = Ctrl+; (label có thể hiện ⌥⌘S).',
      'Graph và Review không có global shortcut riêng — dùng workbench bar hoặc command palette.',
      'Terminal và Browser hỗ trợ nhiều tab; tool khác là toggle single-instance.',
      'Changes (Ctrl+G) và Review chỉ Coding; Graph cần Coding workspace.',
      'Toggle cùng tool lần nữa để đóng — workbench không phải đống card vĩnh viễn.',
      'Mở workbench với Coding workspace mà chưa chọn tool thì Overview mở mặc định.'
],
    blocks: [
      {
        type: 'p',
        text: 'Workbench là surface tool bên phải (hoặc dock) cạnh chat. Tool: Overview, Terminal, Browser, Files, Graph, Side chat, Memory (wiki), Scheduler, Changes (source control) và Review (pull/merge request). Chat vẫn là chính; tool là mặt kiểm tra và hành động cách một shortcut.',
      },
      {
        type: 'p',
        text: 'Agent tạo file, diff, bước browser và lịch cần kiểm mà không rời session. Workbench giữ các surface đó gần để bạn khỏi alt-tab năm app khác mỗi lần verify.',
      },
      {
        type: 'shortcuts',
        rows: [
          { keys: 'Ctrl+`', action: 'Terminal' },
          { keys: 'Ctrl+T', action: 'Built-in browser' },
          { keys: 'Ctrl+F', action: 'Files / Changed & Files (label có thể hiện ⌘P)' },
          { keys: 'Ctrl+;', action: 'Side chat (label có thể hiện ⌥⌘S)' },
          { keys: 'Ctrl+M', action: 'Memory (wiki)' },
          { keys: 'Ctrl+S', action: 'Scheduler' },
          { keys: 'Ctrl+K', action: 'Plugins' },
          { keys: 'Ctrl+G', action: 'Git Changes (Coding)' }
],
      },
      {
        type: 'tips',
        items: [
          'Overview — Coding workspace / git / session / tool status một nhìn.',
          'Terminal — chạy lệnh trong workspace đang active.',
          'Browser — browser trong app (bật trong Settings → Browser).',
          'Files — file workspace và artifact sinh ra.',
          'Graph — code graph cấu trúc (Coding).',
          'Side chat — câu hỏi song song /btw.',
          'Memory — wiki + note pending.',
          'Scheduler — cron / one-shot (chỉ panel; /scheduler redirect home).',
          'Changes — stage, commit, branch (Coding).',
          'Review — danh sách PR/MR host đã kết nối (Coding).'
],
      },
      {
        type: 'p',
        text: 'Bấm tool trên workbench bar hoặc nhấn shortcut. Toggle cùng tool lần nữa để đóng. Quên tool nào làm gì thì Ctrl+P. Đừng nhầm built-in Browser (Ctrl+T) với WebBridge pairing cho Chrome/Edge thật.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: lục Review ở Work; chờ Graph khi chưa focus Coding workspace; bookmark `/scheduler`; tin nhãn ⌘P cho Files; mở mười tab Terminal cho one-liner nên gửi bằng ! trên composer.',
      },
      {
        type: 'tips',
        items: [
          'Terminal vs ! — tương tác/dài vs lệnh ngắn gắn chat.',
          'Files vs @ — browse/khám vs ghim path đã biết vào ask.',
          'Changes sau Accept plan mode để verify diff.',
          'Memory sau session research để Dream có nguyên liệu.'
],
      }
],
    related: [
      'side-chat',
      'memory-dream',
      'scheduler-tasks',
      'coding-git',
      'keyboard-shortcuts',
      'browser-webbridge'
],
  },
  {
    id: 'side-chat',
    category: 'workbench',
    title: 'Side chat (/btw)',
    summary:
      'Hỏi tập trung với quyền read-only session chính, không ngắt run đang chạy và không merge history ngược. Side chat là làn “btw” cho làm rõ, check ràng buộc và khám phụ.',
    keywords: [
      'side chat',
      'btw',
      '/btw',
      'parallel',
      'Ctrl+;',
      'Send to side chat',
      'read-only',
      'chat phụ',
      'hỏi thêm'
],
    setup:
      'Mở bằng /btw, Ctrl+;, tool Side chat trên workbench, hoặc icon hàng session. Tùy chọn: chọn text transcript → Send to side chat để mang quote. Shortcut sống là Ctrl+; kể cả khi label còn hiện ⌥⌘S.',
    tricks: [
      'Mở bằng /btw, Ctrl+;, Side chat trên workbench, hoặc icon hàng session.',
      'Quote selection → Send to side chat cho follow-up gọn mà không gõ lại đoạn.',
      'Side chat không merge history về parent — paste kết luận tay nếu Lead cần thấy.',
      'Dùng side chat làm rõ trong khi Goal hoặc specialist run dài tiếp trên transcript chính.',
      'Side chat dùng Command+; trên macOS và Ctrl+; trên Windows/Linux.',
      'Giữ side chat ngắn và thực tế; việc implement dài đẩy về thread Lead.',
      'Đóng panel khi xong để khỏi gõ instruction chính vào /btw.',
      'Side chat thấy parent context read-only — không phải editor chính cho refactor cả repo.',
      'Cần thread song song bền với tool riêng thì ưu tiên sibling Work session (có thể share_context) thay vì nhồi /btw.'
],
    blocks: [
      {
        type: 'p',
        text: 'Side chat là composer song song với quyền read-only context session parent. Hợp câu “btw”, làm rõ ràng buộc, hoặc thử ý mà không làm bẩn transcript chính. History tách cố ý.',
      },
      {
        type: 'p',
        text: 'Ngắt Lead/specialist run dài để hỏi meta buộc chu kỳ stop/continue khó chịu. Side chat giữ thread chính sạch mà bạn vẫn hưởng awareness của session. Goal đặc biệt lợi — autonomy tiếp trong khi bạn sanity-check một chi tiết.',
      },
      {
        type: 'p',
        text: 'Chạy /btw, nhấn Ctrl+;, mở Side chat từ workbench, hoặc dùng icon hàng session. Tùy chọn quote transcript qua Send to side chat. Hỏi xong đóng panel. Nếu câu trả lời phải lái run chính, tự tóm tắt lại vào composer Lead (hoặc Revise plan).',
      },
      {
        type: 'tips',
        items: [
          '/btw — mở từ slash menu composer',
          'Ctrl+; — toggle Side chat workbench',
          'Send to side chat — quote selection vào /btw',
          'Parent context read-only — không merge history ngược',
          'Icon hàng session — mở không cần slash menu',
          'Nhãn ⌥⌘S — bỏ qua; binding sống là Ctrl+;'
],
      },
      {
        type: 'p',
        text: 'Trong Coding run dài: (1) chọn đoạn assistant khó hiểu, (2) Send to side chat, (3) hỏi “đang claim X hay Y?”, (4) nếu Y sai, về composer chính với instruction sửa hoặc plan revise, (5) đóng Side chat.',
      },
      {
        type: 'p',
        text: 'Nên dùng: làm rõ thuật ngữ, check ràng buộc, giải thích nhanh kết quả tool, brainstorm phương án có thể bỏ. Không nên: việc implement chính, attach bản duy nhất của file quan trọng, hoặc thứ phải audit được trong history session chính.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: gõ “please implement…” vào side chat rồi thắc mắc Lead không làm; chờ side chat approve plan hoặc trả ask-user cho parent; để Ctrl+; mở rồi mất dấu composer nào đang focus; tưởng quote tự sync hai chiều.',
      },
      {
        type: 'tips',
        items: [
          'Ghép quote Plan review để “explain bullet này” mà không Reject.',
          'Sibling Work chat + share_context cho research song song nặng hơn.',
          '/stop vẫn nhắm team chính — side chat không phải Lead thứ hai.',
          'Side chat thiếu tool bạn cần thường nghĩa bạn đã vượt use case /btw.'
],
      }
],
    related: [
      'composer-power',
      'workbench-tools',
      'slash-commands',
      'slash-goal',
      'plan-review'
],
    openAction: { type: 'workbench', tool: 'side-chat' },
  },
  {
    id: 'coding-workspaces',
    category: 'coding',
    title: 'Coding workspace, project và worktree',
    summary:
      'Mở repo, nhóm thành multi-repo project, tạo managed worktree, và dùng /init cho AGENTS.md. Click repo chỉ focus — không mở chat; dùng + / New chat khi cần transcript.',
    keywords: [
      'workspace',
      'project',
      'worktree',
      'repo',
      'multi-repo',
      'AGENTS.md',
      '/init',
      'sandbox',
      'user_data',
      'dự án',
      'kho mã',
      'cây làm việc'
],
    setup:
      'Sang Coding (`/coding`) và thêm repository hoặc tạo project. Cấu hình vị trí worktree trong Settings → Sandbox (repository vs user_data). Chạy /init trong session khi convention nên sống trong AGENTS.md.',
    tricks: [
      'Click repo chỉ focus — không mở chat. Dùng + trên Repos (hoặc New chat) để tạo session.',
      'Project gom nhiều repository dưới một project_id; graph tool resolve link cross-repo tự động.',
      'Vị trí worktree điều khiển trong Settings → Sandbox (repository vs user_data).',
      'Thay đổi source chưa commit không được copy vào worktree mới.',
      'Managed worktree nest dưới source repo trên cây sidebar.',
      'Repo standalone vẫn là single-workspace session hợp lệ không cần project.',
      'Chạy /init trong Coding session để tạo hoặc cập nhật AGENTS.md cho convention agent.',
      'Mở Coding Overview từ workbench khi workspace đã chọn để xem status một nhìn.',
      'Commit hoặc stash trước khi spawn worktree nếu cần dirty change ở chỗ khác — chúng không xuất hiện trên cây mới.',
      'Ưu tiên project khi service chia sẻ API giữa repo; ưu tiên single repo khi changeset local.'
],
    blocks: [
      {
        type: 'p',
        text: 'Coding mode quản git repository, multi-repo project tùy chọn và managed worktree. Agent sửa cây thật với Files, Graph, Terminal, Changes và Review cạnh chat. Đây là mode cho việc engineering bền.',
      },
      {
        type: 'p',
        text: 'Repo bền cần UX khác folder tạm của Work: focus vs new chat, nhóm project, vị trí worktree trong sandbox, và convention AGENTS.md cho đội. Coi Coding như Work là nhầm onboarding phổ biến nhất.',
      },
      {
        type: 'p',
        text: 'Thêm repo từ sidebar Coding. Click để focus; + / New chat cho session. Tạo Project để bind nhiều repo. Spawn worktree từ menu repo; chọn repository-local vs user_data trong Settings → Sandbox. Dùng /init để scaffold hoặc refresh AGENTS.md. Graph và Overview bật khi workspace active.',
      },
      {
        type: 'tips',
        items: [
          'Focus ≠ chat — click chọn; + tạo.',
          'Projects — multi-repo dưới một project_id.',
          'Worktrees — cây sạch; source chưa commit không copy.',
          '/init — AGENTS.md cho convention Coding.',
          'Sandbox — policy vị trí worktree.',
          'Overview — status khi workspace đã focus.'
],
      },
      {
        type: 'p',
        text: 'Session Coding đầu: (1) sang Coding, (2) thêm git repo, (3) click focus, (4) + / New chat, (5) /init nếu thiếu AGENTS.md, (6) set permission mode, (7) @ file then chốt và mô tả thay đổi, (8) mở Overview xác nhận workspace khỏe.',
      },
      {
        type: 'p',
        text: 'Worktree: dùng cho branch/agent song song mà không bẩn checkout chính. Worktree mới bắt đầu sạch theo commit state nguồn — edit chưa commit ở lại sau. Nest dưới source repo trên sidebar giúp thấy quan hệ gia đình.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: click repo rồi chờ chat không bao giờ tới; để dirty work chỉ trên source rồi mở worktree thiếu chúng; bỏ /init rồi thắc mắc agent bỏ qua convention repo; tạo multi-repo project khi một path submodule đủ; để worktree trên mạng chậm qua user_data mà không chủ đích.',
      },
      {
        type: 'tips',
        items: [
          'Nên project — type cross-repo, contract dùng chung, đổi multi-service.',
          'Không nên project — một app repo với vendored code ít đụng.',
          'Graph cross-repo cần project_id.',
          'Review/Changes gắn workspace đang focus.'
],
      }
],
    related: [
      'coding-git',
      'coding-graph',
      'slash-commands',
      'sandbox-settings',
      'modes-overview'
],
    openAction: { type: 'route', to: '/coding' },
  },
  {
    id: 'coding-git',
    category: 'coding',
    title: 'Git, Changes và pull request',
    summary:
      'Stage, commit, branch, merge, rebase, stash và review PR/MR từ Coding qua Changes (Ctrl+G), panel Review và Settings → Git & reviews. Giữ safety toggle chủ đích trước force-with-lease hoặc diff khổng lồ.',
    keywords: [
      'git',
      'commit',
      'branch',
      'pr',
      'mr',
      'merge',
      'rebase',
      'stash',
      'review',
      'Ctrl+G',
      'source control',
      'force-with-lease',
      'GitHub',
      'GitLab',
      'Bitbucket',
      'Gitea',
      'Azure DevOps',
      'kéo yêu cầu',
      'cam kết'
],
    setup:
      'Coding mode với git workspace. Kết nối host trong Settings → Git & reviews cho action PR/MR remote. Xem lại timeout, max diff size và force-with-lease trước thao tác mạnh.',
    tricks: [
      'Ctrl+G mở Changes (source control).',
      'Panel diff review có thể prompt agent Create PR.',
      'Force-with-lease và max diff size bị gate trong version-control settings.',
      'Review workbench liệt kê PR/MR cho GitHub, GitLab, Bitbucket, Gitea và Azure DevOps khi đã kết nối.',
      'Agent cũng chạy git qua tool, chịu permission mode và sandbox.',
      'Stash / branch / rebase từ Changes hoặc agent tool tùy mức thoải mái.',
      'Ưu tiên commit nhỏ, message rõ — agent follow-up tốt hơn trên history sạch.',
      'Kết nối host trước khi hỏi Create PR; không thì commit local thành công rồi bước remote fail muộn.',
      'Diff khổng lồ thì nâng max diff size tạm — review quá lớn che rủi ro.'
],
    blocks: [
      {
        type: 'p',
        text: 'Coding mở source control local (Changes) và review remote (Review). Thao tác local gồm stage, commit, branch, merge, rebase, cherry-pick, stash và flow biết worktree. Host remote cung cấp list PR/MR và action review khi Settings → Git & reviews đã cấu hình.',
      },
      {
        type: 'p',
        text: 'Giữ git cạnh transcript agent rút vòng edit → review → commit → PR mà không nhảy IDE ngoài mỗi bước. Safety policy (timeout, max diff size, force-with-lease) nằm trong Settings để git ops mạnh vẫn chủ đích.',
      },
      {
        type: 'p',
        text: 'Nhấn Ctrl+G hoặc mở Changes từ workbench. Xem diff, stage, commit. Mở Review cho PR/MR đã kết nối. Cấu hình host, timeout và safety toggle trong Settings → Git & reviews. Nhờ agent tạo PR từ diff review khi host connection sẵn.',
      },
      {
        type: 'tips',
        items: [
          'Ctrl+G — Changes / source control',
          'Review — danh sách PR/MR host đã kết nối',
          'GitHub / GitLab / Bitbucket / Gitea / Azure DevOps — tích hợp host',
          'force-with-lease — bị gate; không phải mặc định tùy tiện',
          'max diff size — chỉ nâng khi thật sự cần',
          'stash / branch / rebase — UI hoặc agent tool'
],
      },
      {
        type: 'p',
        text: 'Vòng PR: (1) agent sửa dưới accept-edits hoặc plan, (2) Ctrl+G xem diff, (3) stage hunk liên quan, (4) commit với message giải thích lý do (why), (5) push qua agent hoặc flow remote quen, (6) mở Review / Create PR trên host đã nối, (7) xử lý comment review trong chat follow-up.',
      },
      {
        type: 'p',
        text: 'Khi để agent chạy git vs tự làm: để agent stage/commit khi diff khớp plan và permission mode phù hợp; tự merge/rebase trên branch được bảo vệ nếu đội yêu cầu nghi thức người. Đừng bật force-with-lease tùy tiện trên shared branch.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: commit secret mà sandbox không bắt vì file mới ngoài deny globs; hỏi PR trước khi host auth; trộn file không liên quan trong một commit do agent; tưởng Review chạy ở Work; coi force-with-lease như `--force` thuần.',
      },
      {
        type: 'tips',
        items: [
          'Plan Accept → Changes để verify plan thành diff bạn kỳ vọng.',
          'Worktree giữ commit thí nghiệm khỏi checkout chính.',
          'Permission ask trước lần push đầu lên remote production.'
],
      }
],
    related: [
      'coding-workspaces',
      'workbench-tools',
      'settings-safety',
      'permissions-modes',
      'plan-review'
],
    openAction: { type: 'workbench', tool: 'source-control' },
  },
  {
    id: 'coding-graph',
    category: 'coding',
    title: 'Repository code context',
    summary:
      'Index riêng từng repository kết hợp source search, structural pattern và điều hướng exact symbol. Một tool code_context hoạt động trên toàn bộ repository được cấp quyền.',
    keywords: [
      'code graph',
      'symbols',
      'cross-repo',
      'index',
      'code_context',
      'tree-sitter',
      'đồ thị mã',
      'biểu tượng'
],
    setup:
      'Coding workspace hoặc project — query đầu tiên refresh các source component đã đổi. Mở Graph để xem snapshot động hiện tại.',
    tricks: [
      'Các Coding skill load dần một workflow code_context thống nhất.',
      'Dùng code_context search để khám phá, grep để tìm code shape, và graph action cho exact symbol đã biết.',
      'Mở Graph workbench để khám trực quan và reindex khi cần.',
      'Quan hệ cross-repo được resolve động từ import, module path và unique definition; không có resolver job hay guessed edge lưu lâu dài.',
      'Graph action của code_context gồm definition, callers, callees, references, impact và neighborhood.',
      'Dùng refresh=true sau edit; chỉ dùng refresh=false cho follow-up ngay trên cùng version.',
      'Hỏi câu cấu trúc (“ai gọi X?”) thay vì “đọc cả package”.',
      'Multi-repo project có edge cross-repo; repo standalone vẫn lợi trong một cây.',
      'Skill body không bao giờ bị inject theo Coding mode, và prose thô của request không bao giờ bị route bằng keyword thành graph query.'
],
    blocks: [
      {
        type: 'p',
        text: 'Mỗi repository có managed index local chứa AST-aware chunk, symbol, relation và FTS source. Native code_context query các target này; Graph render snapshot động.',
      },
      {
        type: 'p',
        text: 'Đổ cả file đốt context. Điều hướng graph-first tiết token cho “ai gọi X?” và câu cross-repo trong project, vẫn cho phép grep/LSP/test khi static resolution không đủ. Coi graph là bản đồ — không phải ground truth thay việc đọc hot path.',
      },
      {
        type: 'tips',
        items: [
          'code_context search — identifier, literal, comment và concept',
          'code_context grep — structural matching bằng ví dụ',
          'code_context definition/callers/callees — điều hướng exact symbol',
          'code_context references/impact/neighborhood — traverse quan hệ có giới hạn'
],
      },
      {
        type: 'p',
        text: 'Mở Coding workspace rồi query code_context. Query đầu tiên reconcile file thêm, sửa, xóa vào target riêng từng repository. Edge multi-repo được resolve trên tập target đang được cấp quyền khi query hoặc visualize.',
      },
      {
        type: 'p',
        text: 'Điều tra từng bước: (1) tìm identifier bằng search hoặc code shape bằng grep, (2) gọi exact-symbol action, (3) disambiguate definition trùng bằng path/repository, (4) kiểm limitation, (5) verify hành vi dynamic bằng test, log hoặc runtime evidence.',
      },
      {
        type: 'p',
        text: 'Graph vs grep: graph cho typed symbol, call edge và kiến trúc cross-file; grep cho error string, comment, feature flag, YAML key và generated code parser có thể bỏ. Không tin graph một mình: macro, reflection nặng và template xóa symbol lúc compile.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: truyền prose vào exact-symbol action; đổ cả thư mục vào chat; query sibling không được cấp quyền; bỏ refresh sau external edit; hoặc coi suggestion là graph root đã resolve.',
      },
      {
        type: 'tips',
        items: [
          'Ghép hit graph với Changes xem edit set có khớp call neighborhood không.',
          'AGENTS.md có thể bảo agent ưu tiên graph-first.',
          'Specialist kế thừa tool theo Settings → Agents — đảm bảo worker search được code.'
],
      }
],
    related: ['coding-workspaces', 'agents-settings', 'composer-power', 'coding-git'],
    openAction: { type: 'workbench', tool: 'graph' },
  },
  {
    id: 'evo-agent-specs',
    category: 'coding',
    title: 'Agent Specification-Driven Development (EASD)',
    summary:
      'Dùng Evo Agent Specs để chấp nhận specification có version, bind mission agent vào acceptance criteria, thu evidence gắn code snapshot, ghi deviation và chỉ converge khi mọi gate bắt buộc đạt.',
    keywords: [
      'EASD',
      'Evo Agent Specs',
      'specification',
      'SDD',
      'ADD',
      'acceptance criteria',
      'mission',
      'evidence',
      'deviation',
      'convergence',
    ],
    setup:
      'Mở Coding workspace và initialize mọi repository với EASD knowledge base được version-control; tài liệu project hiện có vẫn giữ nguyên vị trí. Tạo Intent, review flow direct/planned do agent đề xuất rồi Approve specification. Direct đi thẳng Implement; planned thêm Run/Approve plan. Cả hai đều qua Review → Verify → Converge.',
    tricks: [
      'Mỗi repository chỉ cần initialize một lần; project chưa cho tạo run cho tới khi mọi repository đang hoạt động đều ready.',
      'Initialization cài năm project Skill chỉ dành cho Coding: easd-specify, easd-plan, easd-implement, easd-review và easd-verify. Skill chỉ được discover từ repository thuộc Coding scope hiện tại.',
      'Chat handoff EASD chỉ chọn Skill của pha hiện tại: Specify khi draft, Plan chỉ cho accepted planned flow, Implement cho direct hoặc Plan đã duyệt, Review là challenge bắt buộc và Verify cho final gate.',
      'Mỗi EASD Skill đều đọc lại phase và hash đã persist. Plan, mission, review snapshot hoặc verification result bị stale sẽ dừng thay vì tiếp tục theo chat memory.',
      'Core rule “Fix the Spec, Not the Code—before approval”: xử lý mơ hồ ngay trong draft trước khi code; sau approval phải sửa code vi phạm hoặc tạo Spec revision mới để user duyệt, không được hạ contract.',
      'Create run chỉ persist Intent; chưa có specification revision và implementation vẫn bị khóa.',
      'Draft specification in chat bind một Coding session đúng scope và đang idle. Lead đọc instructions, docs, source/config và tests, hỏi clarification rồi submit draft hoàn chỉnh qua typed tool chỉ dành cho lead.',
      'Sau khi submit Spec hoặc Plan thành công, tool result trong chat hiển thị Review specification hoặc Review plan và mở đúng Run trong EASD workbench. Retry drafting/planning lặp attempt bị gián đoạn; Redraft/Replan giữ draft cũ cho tới khi replacement được persist.',
      'Proof command là một argv-style command không qua shell trên mỗi dòng. Dùng command canonical như `python -m pytest tests/test_simple.py`; shell chain, redirection, pipeline và `python -c` snippet sẽ bị reject.',
      'Panel chỉ đổi phase sau durable repository write; lời agent không thể mở khóa approve Spec/Plan bắt buộc, implementation, Review, Verify hay Converge.',
      'Action rail ở Run header hiển thị Intent → Spec → Plan → Implement → Review → Verify → Done. Direct flow đánh dấu Plan là skipped, rail nêu next action và blocker do server tính trước khi bấm; approve Spec, approve Plan và Converge đều cần confirmation.',
      'Review outcome, Scope, risk, evidence policy từng AC và commands; edit bằng revision draft mới rồi tự Approve specification. Agent không thể approve.',
      'Spec đề xuất flow direct hoặc planned. Direct chỉ skip Plan cho thay đổi low-risk một boundary; planned persist mission graph typed và chỉ user Approve plan mới mở khóa implementation.',
      'Dùng Board để theo dõi workflow, Table để so sánh hoặc List để điều hướng gọn. Search theo title, status, risk và repository.',
      'Accept đóng băng Spec revision/hash và publish một bản immutable cùng hash vào specs catalogue chung; thay đổi sau đó tạo revision mới.',
      'Run review là phase read-only riêng. Delegated evidence phải khớp approved review mission và dùng runtime reviewer identity; Run verify vẫn là action riêng của user.',
      'team_delegate EASD luôn có run ID, exact Spec hash, AC ownership và accepted Scope. Planned cần thêm exact Plan hash/mission ID; direct phải bỏ hai field đó.',
      'Machine evidence chỉ đến từ CompletionContract. Mỗi accepted Proof command có verification mission; Verify tạo được contract mới gắn revision mà không sửa file. Runtime chạy command không qua shell, chặn changed path ngoài Scope; mission worktree phải chờ merge được chấp nhận.',
      'Ghi scope drift thành deviation thay vì âm thầm mở rộng specification.',
      'Converge chỉ nhận run ở Verify phase và là server gate, không phải confidence claim của agent.',
    ],
    blocks: [
      {
        type: 'p',
        text: 'EASD là Evo Agent Specification-Driven Development. Đây là protocol Agent-Driven Development được specification quản trị: SDD định nghĩa contract chuẩn tắc, ADD thực thi bằng mission agent có giới hạn.',
      },
      {
        type: 'p',
        text: 'Initialization thêm `.evoflux/easd/config.json`, `RULES.md`, năm Coding Skill và EASD knowledge skeleton vào thư mục dữ liệu repository (mặc định `documents/easd`): specs, features, architecture, reference, guides, development, records, images, templates và runs. Tài liệu project hiện có không bị move hoặc copy; `.local/` chỉ chứa lock/session binding có thể rebuild và bị ignore.',
      },
      {
        type: 'p',
        text: 'Project Skill hướng dẫn Specify, Plan tùy flow, Implement, Review và Verify. Skill không cấp lifecycle authority: user approve Spec, approve Plan khi planned, tự bắt đầu phase sau và invoke Converge.',
      },
      {
        type: 'p',
        text: 'Tạo Intent, để lead draft specification cùng flow recommendation rồi Approve specification. Direct đi implementation mà không có Plan artifact; planned persist mission graph acyclic và user approve riêng. Cả hai vẫn bắt buộc Review và Verify.',
      },
      {
        type: 'tips',
        items: [
          'Draft — specification còn sửa được.',
          'Accepted revision — payload immutable và SHA-256 hash.',
          'Accepted plan — mission graph immutable tùy chọn cho planned flow.',
          'Mission — DelegationTask bền gắn AC.',
          'Evidence — provenance machine, review, manual hoặc waiver.',
          'Deviation — contract/scope drift hiển thị rõ.',
          'Convergence — mọi gate AC và mission bắt buộc đã đạt.',
        ],
      },
      {
        type: 'p',
        text: 'Với run cross-layer và critical, convergence còn cần independent review evidence. Thiếu planned verification command, deviation blocking còn open/approved, AC chưa cover, evidence fail hoặc mission chưa terminal sẽ trả structured reasons thay vì Done giả.',
      },
      {
        type: 'p',
        text: 'Panel và public API chỉ thêm evidence manual, review hoặc waiver; không thể tự khai machine evidence hay reviewer independence. Runtime tool sở hữu các trust level đó.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: bỏ Plan khi bắt buộc, tự bịa Plan identity cho direct, delegate thiếu Spec/AC/scope identity, coi review là convergence hoặc giấu scope expansion.',
      },
    ],
    related: ['coding-workspaces', 'permissions-modes', 'plan-review', 'coding-git', 'coding-graph'],
    openAction: { type: 'workbench', tool: 'easd' },
  },
  {
    id: 'memory-dream',
    category: 'memory',
    title: 'Memory wiki và Dream',
    summary:
      'Xem Markdown wiki (topics, entities, notes, imports) và chạy Dream synthesis theo cron (mặc định 0 2 * * *) hoặc thủ công qua Run Dream. Memory biến chat thành trang bền, cite được — không phải trọng số model mờ đục.',
    keywords: [
      'memory',
      'wiki',
      'dream',
      'notes',
      'INDEX',
      'LOG.md',
      'topics',
      'entities',
      'imports',
      'Ctrl+M',
      '0 2 * * *',
      'Run Dream',
      'trí nhớ',
      'wiki',
      'ghi chú'
],
    setup:
      'Mở Memory bằng Ctrl+M hoặc workbench tool. Cấu hình Dream trong Settings → Memory (cron và tùy chọn liên quan). Cron Dream mặc định `0 2 * * *` nếu bạn không đụng lịch.',
    tricks: [
      'notes/ pending read-only đến khi Dream tổng hợp thành trang wiki curated.',
      'Cron Dream mặc định 0 2 * * *; Run Dream now từ settings hoặc command palette.',
      'Section wiki gồm topics, entities, notes, imports, INDEX.md và LOG.md append-only.',
      'Trang Dream mang citation, confidence và metadata trang liên quan — xem trước khi tin mù.',
      'Memory là panel workbench, không phải product mode riêng.',
      'Ghép Dream với Scheduler chỉ khi cần agent prompt tùy ý; Dream có lịch riêng.',
      'Lướt LOG.md sau Dream overnight để biết đổi gì trước khi cite trang trong chat.',
      'Viết note pending ngắn trong ngày hơn là hy vọng model nhớ tuần sau.',
      'Dream confidence thấp thì coi trang là giả thuyết nháp và verify trên hệ nguồn.'
],
    blocks: [
      {
        type: 'p',
        text: 'Memory là Markdown wiki trên đĩa, mở xem được. Dream là agent tổng hợp theo lịch (hoặc trigger tay) gom session và note chưa xử lý thành trang curated kèm citation và confidence. Bạn mở, diff và sửa file như docs khác.',
      },
      {
        type: 'p',
        text: 'Chỉ chat history là knowledge base dài hạn kém. Wiki bạn mở, diff và cite được giữ fact bền khỏi trọng số model mờ đục, vẫn cho phép tổng hợp tự động ban đêm. Memory cho kiến thức bền; transcript cho hội thoại đang chạy.',
      },
      {
        type: 'p',
        text: 'Nhấn Ctrl+M hoặc mở Memory trên workbench. Duyệt topics/, entities/, notes/, imports/, INDEX.md và LOG.md. Note dưới notes/ read-only chờ synthesis. Cấu hình Dream cron trong Settings → Memory (mặc định `0 2 * * *`) hoặc Run Dream now. Sau Dream, xem trang mới/cập nhật và entry LOG.md.',
      },
      {
        type: 'tips',
        items: [
          'topics/ — trang chủ đề curated',
          'entities/ — người, hệ thống, component',
          'notes/ — pending, giữ read-only đến khi Dream chạy',
          'imports/ — material ngoài đã ingest',
          'INDEX.md — bản đồ vào',
          'LOG.md — log synthesis append-only',
          'Ctrl+M — mở Memory workbench',
          'Run Dream — trigger synthesis tay'
],
      },
      {
        type: 'p',
        text: 'Thói quen ngày: (1) trong lúc làm, ghi note ngắn vào Memory, (2) để notes/ pending, (3) để Dream chạy cron hoặc Run Dream cuối ngày, (4) đọc LOG.md, (5) sửa citation sai ngay trên trang wiki, (6) nhắc trang đã sửa trong chat sau khi liên quan.',
      },
      {
        type: 'p',
        text: 'Memory vs Work folder chat: Memory cho fact sống lâu hơn một engagement; folder cho thread song song đang active. Không dựa Dream một mình: quyết định có quy định cần nguồn do người viết — tự viết trang và coi Dream là hỗ trợ.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: sửa notes/ tưởng chúng vẫn authoritative (chúng là pending); nhầm cron Scheduler với Dream cron ở Settings → Memory; không mở INDEX.md rồi bảo “Memory trống”; cite trang high-confidence mà không check evidence liên kết sau tuần chat rối.',
      },
      {
        type: 'tips',
        items: [
          'Scheduler cho prompt tùy ý; Dream chỉ tổng hợp wiki.',
          'Sau đợt research hoặc coding lớn, Run Dream để fact mới vào dạng wiki.',
          'Sandbox/outbound policy vẫn quan trọng khi nội dung Dream sau này chảy ra provider qua chat.'
],
      }
],
    related: [
      'scheduler-tasks',
      'workbench-tools',
      'settings-safety',
      'sessions-folders'
],
    openAction: { type: 'workbench', tool: 'wiki' },
  },
  {
    id: 'scheduler-tasks',
    category: 'scheduler',
    title: 'Scheduled tasks',
    summary:
      'Tạo cron hoặc one-shot agent prompt từ panel Scheduler trên workbench — route /scheduler redirect về home; dùng Ctrl+S. Task gửi prompt tới Lead của mode tương ứng mà không cần giữ cửa sổ chat focus.',
    keywords: [
      'scheduler',
      'cron',
      'schedule',
      'reminder',
      'one-shot',
      'Ctrl+S',
      '/scheduler',
      'pause',
      'resume',
      'trigger',
      'lịch',
      'đặt lịch',
      'nhắc nhở'
],
    setup:
      'Mở Scheduler bằng Ctrl+S (workbench tool). Route `/scheduler` redirect home — luôn dùng panel. Chọn work hoặc coding mode trên task để prompt xuống đúng Lead.',
    tricks: [
      'Pause, resume hoặc trigger task từ panel mà không chờ tick cron tiếp.',
      'Context Coding có thể prefill workspace/mode cho task mới.',
      'Task gửi prompt tới Lead của mode khớp (work hoặc coding).',
      'One-shot cho reminder; cron cho bảo trì định kỳ hoặc routine gần Dream do bạn sở hữu.',
      'Đừng nhầm Scheduler với Dream cron riêng dưới Settings → Memory.',
      'Trigger tay sau khi sửa prompt để verify trước khi tin cron overnight.',
      'Giữ prompt lịch idempotent — chạy lại không tạo side effect rối trùng.',
      'Pause task trước khi laptop ngủ dài nếu backend chỉ local và sẽ miss window.',
      'Đặt tên task theo outcome (“weekday repo chore”) để panel dễ quét.'
],
    blocks: [
      {
        type: 'p',
        text: 'Scheduled task gửi prompt tới đội agent theo cron expression hoặc one-shot, không cần giữ cửa sổ chat mở. UI quản lý chỉ nằm trong Scheduler workbench — không có trang `/scheduler` bền.',
      },
      {
        type: 'p',
        text: 'Việc định kỳ (status digest, chore repo, reminder) không nên phụ thuộc bạn đang ở transcript. Scheduler tách “khi nào” khỏi “chat nào đang focus” — bảo trì chạy khi bạn ở chỗ khác.',
      },
      {
        type: 'p',
        text: 'Nhấn Ctrl+S hoặc mở Scheduler từ workbench. Tạo task với mode (work/coding), lịch và prompt. Pause/resume/trigger trên cùng panel. Đừng bookmark `/scheduler` — nó redirect home cố ý để bạn không kẹt route trống.',
      },
      {
        type: 'tips',
        items: [
          'Ctrl+S — mở panel Scheduler',
          'Cron — agent prompt định kỳ',
          'One-shot — chạy một lần trong tương lai / reminder',
          'Pause / resume / trigger — điều khiển vòng đời trong panel',
          'Mode — nhắm Lead work hoặc coding',
          '/scheduler — redirect home; đừng bookmark',
          'Dream cron — riêng dưới Settings → Memory'
],
      },
      {
        type: 'p',
        text: 'Cron task đầu: (1) Ctrl+S, (2) tạo task, (3) chọn coding hoặc work, (4) set cron expression, (5) viết prompt kèm Definition of Done rõ, (6) Trigger một lần để validate, (7) chỉ để enabled sau dry run ổn, (8) Pause khi chore lỗi thời thay vì xóa ngay nếu còn tái dùng.',
      },
      {
        type: 'p',
        text: 'Scheduler vs Goal vs Dream: Scheduler bắn prompt rời trên đồng hồ; Goal tiếp objective tự hành trong session; Dream tổng hợp Memory wiki trên cron riêng. Một việc một cơ chế — xếp cả ba lên cùng chore thường tạo việc trùng.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: bookmark `/scheduler` rồi nghĩ Scheduler hỏng; trỏ chore Coding sang work mode; viết prompt giả định UI focus hoặc Terminal tab đang mở; nhầm cửa sổ sidecar local miss với bug parser cron; dùng Scheduler để “chạy Dream” thay Settings → Memory.',
      },
      {
        type: 'tips',
        items: [
          'Set permission mode cẩn trên session mà scheduled prompt sẽ đụng.',
          'HealthDot phải xanh khi cron bắn trên sidecar local.',
          'Tổng hợp wiki dùng Dream; “hỏi Lead mỗi thứ Hai” dùng Scheduler.',
          'Prompt idempotent — an toàn nếu trigger chạy hai lần.'
],
      }
],
    related: [
      'memory-dream',
      'workbench-tools',
      'slash-goal',
      'troubleshooting-connection'
],
    openAction: { type: 'workbench', tool: 'scheduler' },
  },
  {
    id: 'browser-webbridge',
    category: 'browser',
    title: 'Built-in browser và WebBridge',
    summary:
      'Dùng browser trong app (Ctrl+T), hoặc pair session Chrome/Edge thật qua extension WebBridge với teach mode và bật theo chat. WebBridge là companion CDP cho app desktop — không phải bản web của EvoFlux.',
    keywords: [
      'browser',
      'webbridge',
      'extension',
      'chrome',
      'edge',
      'cdp',
      'Ctrl+T',
      'teach',
      'pairing',
      'per-chat',
      'trình duyệt',
      'tiện ích',
      'dạy'
],
    setup:
      'Built-in: bật trong Settings → Browser, rồi Ctrl+T. WebBridge: cài extension Chrome/Edge, bật master policy trong Settings → Browser, pair từ desktop status control, rồi bật WebBridge theo từng chat cần dùng.',
    tricks: [
      'Ctrl+T toggle built-in browser workbench — không phải WebBridge pairing.',
      'WebBridge bật theo chat; master policy nằm trong Settings → Browser.',
      'Teach mode ghi action browser có nghĩa (không keystroke thô) để replay có xác nhận.',
      'Pairing dùng credential có scope và one-time session ticket; revoke pairing đóng relay live.',
      'Selection và page context từ browser thật được coi là input không tin cậy.',
      'WebBridge không phải bản web EvoFlux — là companion CDP của app desktop.',
      'Built-in Browser cho browse agent trong sandbox; WebBridge khi cần cookie SSO thật hoặc extension doanh nghiệp.',
      'Revoke pairing khi cho mượn máy hoặc rotate access — ticket còn lại chết cùng revoke.',
      'Xác nhận teach replay trước khi chia sẻ kết quả monitored vào vòng agent.'
],
    blocks: [
      {
        type: 'p',
        text: 'Hai đường browser: (1) built-in browser workbench trong app cho trang agent-driven trong EvoFlux, và (2) WebBridge — extension relay CDP tới profile Chrome hoặc Edge thật kèm domain policy và audit trail. Chọn đường khớp login và trust model của việc.',
      },
      {
        type: 'p',
        text: 'Có việc cần view trong app có sandbox; có việc cần browser đã login thật (SSO, cookie doanh nghiệp, extension). WebBridge bắc cầu khoảng trống đó mà không biến EvoFlux thành cloud web IDE. Coi nội dung trang là không tin cậy dù dùng đường nào.',
      },
      {
        type: 'p',
        text: 'Built-in: Settings → Browser → enable, rồi Ctrl+T hoặc tool Browser. WebBridge: cài extension, bật policy trong Settings → Browser, mở desktop WebBridge status control để pair, rồi bật WebBridge cho chat cần dùng. Dùng Teach để ghi chuỗi action xem lại được; xác nhận trước khi kết quả monitored được chia sẻ.',
      },
      {
        type: 'tips',
        items: [
          'Ctrl+T — chỉ built-in browser',
          'Status control — pair / unpair WebBridge',
          'Per-chat toggle — cho phép browser thật cho session này',
          'Teach — action có nghĩa, không raw keystroke',
          'Revoke pairing — giết relay + ticket còn lại',
          'Settings → Browser — master policy cho cả hai đường',
          'Untrusted input — selection/page context từ browser thật'
],
      },
      {
        type: 'p',
        text: 'WebBridge từng bước: (1) cài extension Chrome/Edge, (2) bật master policy trong Settings → Browser, (3) pair từ desktop status control, (4) mở chat đích, (5) bật WebBridge cho chat đó, (6) tùy chọn Teach một flow và xác nhận replay, (7) revoke pairing khi xong máy hoặc engagement.',
      },
      {
        type: 'p',
        text: 'Built-in vs WebBridge: built-in cho browse tạm và demo trong app; WebBridge cho app doanh nghiệp đã auth bạn đang dùng trong Chrome/Edge. Tránh WebBridge với site public không tin cậy — cookie profile thật không nên lộ cho agent control.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: Ctrl+T chờ extension pair; bật master policy mà quên per-chat toggle; coi teach recording như script keylogger thô; để pairing cũ sống trên laptop dùng chung; paste text trang WebBridge vào prompt không hoài nghi.',
      },
      {
        type: 'tips',
        items: [
          'Sandbox/outbound policy vẫn áp với thứ đi ra provider.',
          'WebBridge offline → xem Troubleshooting trước khi reinstall app.',
          'Side chat làm rõ quote trang mà không dừng browser run chính.'
],
      }
],
    related: [
      'workbench-tools',
      'settings-safety',
      'troubleshooting-connection',
      'sandbox-settings'
],
    openAction: { type: 'settings', path: 'browser' },
  },
  {
    id: 'providers-settings',
    category: 'settings',
    title: 'Providers và models (BYOM)',
    summary:
      'Kết nối Anthropic, OpenAI, Gemini, Bedrock, Ollama và hơn nữa — mười hai tích hợp sau một lớp streaming — rồi chọn model theo agent hoặc theo session. EvoFlux không khóa bạn vào một vendor model.',
    keywords: [
      'provider',
      'model',
      'api key',
      'oauth',
      'ollama',
      'byom',
      'Anthropic',
      'OpenAI',
      'Gemini',
      'Bedrock',
      'DeepSeek',
      'xAI',
      'Vertex',
      'Copilot',
      'Providers',
      'API key',
      'Ollama'
],
    openAction: { type: 'settings', path: 'providers' },
    setup:
      'Settings → Providers. Chuẩn bị API key, OAuth, hoặc URL daemon local đang chạy. Xác nhận HealthDot xanh trước khi coi danh sách model trống là outage mạng.',
    tricks: [
      'Chọn model độc lập theo agent trong Settings → Agents.',
      'Session pills trên composer set model, thinking level và fast mode cho chat hiện tại.',
      'Danh sách provider hỗ trợ fuzzy model search.',
      'Daemon local (Ollama…) dùng base URL override khi cần.',
      'Không có model listed thường nghĩa chưa cấu hình provider nào — sửa Providers trước khi debug chat.',
      'Context budget bar dùng context_length của model đã chọn từ registry.',
      'Model nhanh cho Lead triage và model mạnh hơn cho Coding specialist khi quan tâm chi phí.',
      'Sau khi rotate key, test lại bằng Work ping nhỏ trước khi start Goal.',
      'OAuth vẫn cần trạng thái connect thành công — OAuth dở dang để bạn không có model.'
],
    blocks: [
      {
        type: 'p',
        text: 'Providers là tích hợp BYOM (API key, OAuth hoặc daemon local) phơi model qua một lớp streaming. Họ hỗ trợ gồm Anthropic, OpenAI, Google Gemini, AWS Bedrock, Ollama, DeepSeek, xAI, Vertex AI, GitHub Copilot và hơn nữa. Credential nằm trong Settings, không trong chat.',
      },
      {
        type: 'p',
        text: 'EvoFlux không khóa bạn vào một vendor model. Agent khác nhau dùng model khác (Lead triage nhanh vs specialist coding sâu) mà không đổi UI. Session pills cho phép override một chat mà không sửa mặc định agent.',
      },
      {
        type: 'p',
        text: 'Mở Settings → Providers, thêm credential hoặc base URL, xác nhận provider hiện configured, rồi gán mặc định dưới Agents hoặc override theo session qua composer pills. Dùng Diagnostics nếu stream fail sau khi key trông đúng. Fuzzy search giúp khi provider phơi danh sách model dài.',
      },
      {
        type: 'tips',
        items: [
          'API key / OAuth / daemon local — ba kiểu kết nối',
          'Settings → Agents — model mặc định theo agent',
          'Composer pills — model / thinking / fast mode theo session',
          'context_length — dẫn context budget bar',
          'Ollama — set base URL khi không dùng port mặc định',
          'Danh sách model trống — cấu hình Providers trước'
],
      },
      {
        type: 'p',
        text: 'Provider đầu: (1) HealthDot xanh, (2) Settings → Providers, (3) thêm key hoặc OAuth hoặc daemon URL, (4) xác nhận trạng thái configured, (5) chọn mặc định trên Lead dưới Agents, (6) gửi Work ping ngắn, (7) rồi mới mở Coding task lớn hoặc Goal.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: paste API key vào transcript; debug “no models” như sidecar crash; tưởng session pills đổi mặc định agent vĩnh viễn; trỏ Ollama sai host từ trong desktop sandbox; bỏ qua lỗi rate-limit khi HealthDot vẫn xanh.',
      },
      {
        type: 'tips',
        items: [
          'Diagnostics sau khi credential trông đúng mà stream fail.',
          'Model mạnh hơn nâng context_length — để ý thói quen /compact.',
          'MCP và tool vẫn cần permission mode dù model hoàn hảo.'
],
      }
],
    related: [
      'agents-settings',
      'getting-started',
      'connection-settings',
      'troubleshooting-connection'
],
  },
  {
    id: 'agent-plugins',
    category: 'plugins',
    title: 'Agent Plugins: cài đặt, kiểm tra trust, cấu hình và phát triển',
    summary:
      'Dùng Plugin Center để validate, import, kiểm tra, cấu hình, enable, sửa code, pack, update và gỡ Agent Plugin portable. Tài liệu này giải thích rõ package contract, trust review, credentials, Skill discovery, MCP runtime và cách xử lý khi plugin chưa ready.',
    keywords: [
      'plugin',
      'plugins',
      'agent plugins',
      'plugin center',
      'evoplugin',
      'plugin.json',
      'mcp.json',
      'skill.md',
      'portable skills',
      'stdio',
      'streamable http',
      'credentials',
      'trust review',
      'enable',
      'link folder',
      'pack archive',
      'thông tin xác thực',
      'kiểm tra tin cậy',
      'org.evoelsewhere.evoflux',
      'namespace mở rộng'
],
    setup:
      'Mở Plugins từ sidebar Work hoặc Coding. Chọn Add plugin → Import package cho `.evoplugin`/ZIP, Link development folder cho thư mục đã giải nén, Validate folder để chỉ kiểm tra, hoặc Create plugin để scaffold rồi sửa trực tiếp trong editor.',
    tricks: [
      'Plugin portable đóng góp dữ liệu và code qua `plugin.json`, `skills/*/SKILL.md` ở đúng một cấp con và `mcp.json` tùy chọn; plugin không được inject UI tùy ý vào EvoFlux.',
      'Import và Link luôn cài ở trạng thái disabled mặc định. Đọc trust review trước khi bấm Trust and enable.',
      'Trust review liệt kê executable cùng arguments, remote hosts, tên field môi trường và capabilities — không bao giờ hiện giá trị secret.',
      'Chọn Keep disabled nếu có mục lạ; khi disabled bạn vẫn sửa file và cấu hình credentials được.',
      'Credentials thuộc riêng từng installation, lưu ngoài package và chỉ inject vào process MCP stdio của plugin đó.',
      'Package mới phải dùng `org.evoelsewhere.evoflux.credentials` và `org.evoelsewhere.evoflux.mcp`.',
      'Alias cũ `evoflux.credentials` và `evoflux.mcp` vẫn đọc được; canonical thắng nếu khai báo cả hai.',
      'MCP của plugin hiện trong Settings → MCP servers với badge plugin; EvoFlux không copy chúng vào MCP config global.',
      'Plugin Skill chỉ discover được khi installation đang enabled và Skill validate thành công.',
      'Link dành cho development trực tiếp trên thư mục local; Import tạo bản managed. Pack tạo ZIP `.evoplugin` deterministic.',
      'Disable sẽ reconcile/dừng MCP runner và loại Skill khỏi catalog nhưng không xóa installation data.',
      'Uninstall mặc định giữ plugin data; chỉ xóa data khi bạn chủ đích xóa credentials và mutable state.'
],
    blocks: [
      {
        type: 'p',
        text: 'Agent Plugins 1.0 là package contract portable. EvoFlux hỗ trợ Agent Skills cùng MCP stdio và Streamable HTTP. Plugin là một thư mục đã giải nén có `plugin.json` ở root; `.evoplugin` chỉ là ZIP distribution deterministic. Khai báo SSE legacy được validate và báo diagnostic nhưng không được start. Managed Agent Plugins tách hoàn toàn khỏi legacy Python hooks chạy trusted trong process.',
      },
      {
        type: 'tips',
        items: [
          'Bắt buộc — `plugin.json` dùng `$schema` Agent Plugins 1.0, tên portable chữ thường, version/description nếu có.',
          'Skills — chỉ direct child: `skills/<skill-name>/SKILL.md`; thư mục Skill lồng sâu chỉ là resource, không phải Skill discover thêm.',
          'MCP — `mcp.json` tùy chọn ở root; từng server lỗi độc lập nên một entry hỏng không làm ẩn sibling khỏe.',
          'Dữ liệu thay đổi — dùng `${PLUGIN_DATA}`; file bundled chỉ đọc resolve từ `${PLUGIN_ROOT}`.',
          'Host extensions — mọi khai báo riêng của EvoFlux đặt dưới canonical reverse-domain namespace trong `plugin.json`.'
],
      },
      {
        type: 'p',
        text: 'Quy trình cài an toàn: (1) mở Add plugin, (2) import archive hoặc link thư mục, (3) đọc diagnostic package/component, (4) xem trust review trước enable, (5) giữ disabled nếu command, host, environment field hoặc capability chưa rõ, (6) cấu hình Credentials nếu plugin khai báo, (7) bật toggle và xác nhận Trust and enable, (8) kiểm tra Skills và MCP status, (9) chạy tool vô hại đầu tiên dưới permission ask.',
      },
      {
        type: 'p',
        text: 'Trust review là kiểm tra tĩnh: EvoFlux chỉ đọc khai báo, chưa chạy code plugin. Phần executable hiển thị đúng program và mảng argument của stdio server. Phần remote hiển thị host, URL và transport. Phần environment chỉ có tên lấy từ `mcp.json` và credential schema. Capabilities gồm Agent Skills, MCP transports và EvoFlux server capabilities đã khai báo. Cài plugin không đồng nghĩa cấp quyền toàn cục; mọi tool call vẫn qua permissions và sandbox.',
      },
      {
        type: 'p',
        text: 'Credentials: mở card plugin → Actions → Credentials. Field hỗ trợ text, secret, URL và boolean. Form chỉ complete khi đủ required fields. Secret bị mask khi đọc và lưu ngoài package với file permission chặt. Giá trị credentials overlay env của stdio, sau đó EvoFlux ép lại `PLUGIN_ROOT` và `PLUGIN_DATA` an toàn. Streamable HTTP không nhận các giá trị đã lưu này; không đặt secret thật trong portable headers.',
      },
      {
        type: 'p',
        text: 'Runtime: Skill hợp lệ của plugin enabled đi vào metadata catalog và chỉ load khi activate. Khi load một plugin Skill, MCP tools ready cùng installation được đưa vào run đó nhưng vẫn chịu permission. Settings → Skills cho biết discovery/validation; Settings → MCP servers hiển thị runtime badge plugin và tool names. Runtime name chứa installation hash nên hướng dẫn trong Skill phải nhắc stable server/tool suffix, không copy generated prefix.',
      },
      {
        type: 'p',
        text: 'Phát triển: Add plugin → Create plugin tạo scaffold portable và mở editor có sẵn. Dùng file tree để mở `plugin.json`, nội dung Skill, scripts và `mcp.json`; tạo/xóa entry, Save, Validate rồi Pack. Link thư mục để development live. Sau khi sửa declaration hoặc implementation, validate lại và chỉ re-enable sau khi review access đã thay đổi. Plugin không được ship settings page hay frontend tùy ý; Plugin Center sở hữu lifecycle, credentials, diagnostics và runtime UI.',
      },
      {
        type: 'tips',
        items: [
          'Không install được — mở inspection diagnostics; sửa lỗi fatal `plugin.json`, unsafe path, archive collision, symlink, size hoặc digest.',
          'Không thấy Skill — enable installation; kiểm tra `skills/<name>/SKILL.md` nằm đúng một cấp, frontmatter hợp lệ và không bị project/user Skill có precedence cao hơn shadow.',
          'Không thấy MCP trong Settings — kiểm tra plugin enabled, `mcp.json` valid và transport là stdio hoặc Streamable HTTP, không phải SSE.',
          'MCP báo error — mở rộng runtime row; kiểm executable path, args, working directory, startup log, credentials bắt buộc và bảo đảm stdout chỉ dành cho stdio protocol.',
          'Credentials báo unsupported — thêm `org.evoelsewhere.evoflux.credentials.fields` vào `plugin.json`, Validate rồi quay lại.',
          'Remote server chưa ready — kiểm URL/host và literal headers; stored plugin credentials cố ý không inject vào Streamable HTTP.',
          'Chat không chọn tool — activate Skill tương ứng hoặc chọn plugin MCP server rõ ràng trong agent; cài đặt một mình không grant toàn bộ tool.',
          'Thay đổi chưa cập nhật — Save/Validate lại, refresh Plugin Center rồi disable/enable để reconcile runtime.'
],
      },
      {
        type: 'p',
        text: 'CLI tương đương: `evoflux plugin inspect`, `create`, `link`, `install`, `show`, `enable`, `disable`, `pack`, `update`, `uninstall`. CLI install/link cũng disabled mặc định. Chạy `show <installation-id>`, đọc `inspection.trust`, rồi mới `enable`; chỉ dùng `--enabled` khi automation đã có trust gate độc lập.',
      }
],
    related: [
      'agents-settings',
      'permissions-modes',
      'workbench-tools',
      'troubleshooting-connection'
    ],
    openAction: { type: 'workbench', tool: 'plugins' },
  },
  {
    id: 'agent-plugins-authoring',
    category: 'plugins',
    title: 'Authoring reference: manifest, Skills, MCP và extensions',
    summary:
      'Tạo plugin directory đúng chuẩn bằng layout và JSON mẫu cụ thể. Phân biệt phần portable với phần mở rộng riêng của EvoFlux, sau đó validate và đóng gói đúng cách.',
    keywords: ['viết plugin', 'manifest', 'plugin.json mẫu', 'mcp.json mẫu', 'skill frontmatter', 'credential schema', 'capabilities', 'package layout'],
    setup: 'Bắt đầu bằng Add plugin → Create plugin, hoặc tự tạo thư mục rồi chạy `evoflux plugin inspect ./my-plugin` trước khi Link/Pack.',
    blocks: [
      { type: 'heading', text: 'Layout package và trách nhiệm từng file' },
      {
        type: 'code',
        language: 'text',
        caption: 'Thư mục portable',
        code: 'my-plugin/\n├── plugin.json\n├── skills/\n│   └── release-audit/\n│       ├── SKILL.md\n│       ├── references/\n│       └── scripts/\n├── mcp.json\n├── server.py\n├── README.md\n└── LICENSE',
      },
      {
        type: 'table',
        columns: ['Đường dẫn', 'Bắt buộc', 'Ý nghĩa'],
        rows: [
          ['plugin.json', 'Có', 'Identity portable và host extensions.'],
          ['skills/<name>/SKILL.md', 'Không', 'Agent Skill ở đúng một cấp con; references/scripts nằm trong thư mục Skill.'],
          ['mcp.json', 'Không', 'Khai báo stdio, Streamable HTTP hoặc SSE legacy.'],
          ['Implementation files', 'Theo nhu cầu', 'Code server bundled được MCP declaration gọi.'],
          ['README / LICENSE', 'Khuyến nghị', 'Setup cho người dùng, provenance, giới hạn và license.'],
        ],
      },
      { type: 'heading', text: 'plugin.json tối thiểu' },
      {
        type: 'code',
        language: 'json',
        caption: 'Portable manifest',
        code: '{\n  "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",\n  "name": "release-audit",\n  "version": "0.1.0",\n  "description": "Audit release bằng hướng dẫn và tool read-only.",\n  "author": { "name": "Example Team" },\n  "repository": "https://example.com/plugins/release-audit",\n  "license": "MIT",\n  "keywords": ["release", "audit"],\n  "extensions": {}\n}',
      },
      {
        type: 'callout',
        title: 'Rule của manifest',
        text: 'Tên dài 1–64 ký tự ASCII chữ thường, số, dấu chấm hoặc gạch ngang; đầu/cuối phải là chữ hoặc số, không chứa hai dấu gạch nối hoặc hai dấu chấm liên tiếp. Root field lạ chỉ cảnh báo và bị bỏ qua. Dữ liệu riêng của client phải nằm dưới extensions.',
      },
      { type: 'heading', text: 'Contract của Agent Skill' },
      {
        type: 'code',
        language: 'markdown',
        caption: 'skills/release-audit/SKILL.md',
        code: '---\nname: release-audit\ndescription: Kiểm tra evidence, checks và risk trước khi publish release.\n---\n\n# Release audit\n\n1. Thu thập evidence có giới hạn.\n2. Chỉ gọi MCP tool khi cần dữ liệu live.\n3. Tách fact, inference và evidence còn thiếu.\n4. Không publish hay mutate release nếu chưa được authorize rõ ràng.',
      },
      {
        type: 'p',
        text: 'Tên Skill phải đúng Agent Skills naming contract. Description cần chính xác vì dùng cho discovery. Giữ workflow chính trong SKILL.md, chỉ load reference lớn khi cần. Nhắc MCP tool bằng stable suffix vì EvoFlux thêm runtime prefix riêng theo installation.',
      },
      {
        type: 'p',
        text: 'EvoFlux không giới hạn tổng dung lượng resource của bundle Skill. Giới hạn từng file và số entry, path containment, kiểm tra regular-file/symlink và preview Settings có giới hạn vẫn được giữ nguyên. Giới hạn attachment và upload của chat là hệ thống riêng, không thay đổi.',
      },
      { type: 'heading', text: 'MCP stdio và Streamable HTTP' },
      {
        type: 'code',
        language: 'json',
        caption: 'mcp.json',
        code: '{\n  "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",\n  "mcpServers": {\n    "local": {\n      "type": "stdio",\n      "command": "python",\n      "args": ["${PLUGIN_ROOT}/server.py"],\n      "env": { "CACHE_DIR": "${PLUGIN_DATA}/cache" },\n      "cwd": "${PLUGIN_ROOT}"\n    },\n    "remote": {\n      "type": "streamable-http",\n      "url": "https://api.example.com/mcp",\n      "headers": { "X-Client": "evoflux-plugin" }\n    }\n  }\n}',
      },
      {
        type: 'table',
        columns: ['Transport', 'Khi nào dùng', 'Giới hạn quan trọng'],
        rows: [
          ['stdio', 'Server code ship cùng plugin.', 'Không dùng shell command string; stdout chỉ cho protocol; có thể nhận credentials.'],
          ['streamable-http', 'Remote endpoint được vận hành độc lập.', 'Không follow redirect; headers là literal; stored credentials không inject.'],
          ['sse', 'Chỉ để tương thích khai báo legacy.', 'Được validate/diagnose nhưng EvoFlux không start.'],
        ],
      },
      { type: 'heading', text: 'Credentials và capability extensions' },
      {
        type: 'code',
        language: 'json',
        caption: 'Đoạn extensions trong plugin.json',
        code: '{\n  "extensions": {\n    "org.evoelsewhere.evoflux.credentials": {\n      "fields": [\n        { "key": "endpoint", "label": "Service URL", "type": "url", "env": "SERVICE_URL", "required": true },\n        { "key": "token", "label": "API token", "type": "secret", "env": "SERVICE_TOKEN", "required": true }\n      ]\n    },\n    "org.evoelsewhere.evoflux.mcp": {\n      "servers": {\n        "local": { "capabilities": ["webbridge-safe"] }\n      }\n    }\n  }\n}',
      },
      {
        type: 'callout',
        tone: 'warning',
        title: 'Không đóng gói secret thật',
        text: 'Credential declaration chỉ chứa metadata của field, không chứa value. Không commit token, đặt token trong Streamable HTTP headers, in token vào log/stdout hay yêu cầu người dùng paste token vào chat.',
      },
      { type: 'heading', text: 'Validate, Link, Pack và Update' },
      {
        type: 'code',
        language: 'shell',
        caption: 'Vòng lặp authoring',
        code: 'evoflux plugin inspect ./my-plugin\nevoflux plugin link ./my-plugin\nevoflux plugin show <installation-id>\nevoflux plugin enable <installation-id>\nevoflux plugin pack ./my-plugin\nevoflux plugin update <installation-id> ./my-plugin.evoplugin',
      },
      {
        type: 'p',
        text: 'Inspect sau mỗi thay đổi contract. Test validation từng component, startup, một tool call vô hại, failure isolation, secret masking, result bounds và disable/enable reconciliation. Chỉ Pack thư mục valid; archive là distribution format chứ không phải contract mới.',
      },
    ],
    related: ['agent-plugins', 'agent-plugins-runtime-security', 'agent-plugins-troubleshooting'],
    openAction: { type: 'workbench', tool: 'plugins' },
  },
  {
    id: 'agent-plugins-runtime-security',
    category: 'plugins',
    title: 'Runtime và security: trust, credentials, permissions và data',
    summary:
      'Hiểu chính xác điều gì xảy ra từ static inspection đến enable, dữ liệu/credentials đi qua biên runtime thế nào và protection nào vẫn áp dụng sau khi trust plugin.',
    keywords: ['bảo mật plugin', 'trust model', 'environment', 'plugin data', 'permission', 'sandbox', 'runtime manager', 'precedence', 'mask secret'],
    setup: 'Import hoặc Link package, giữ disabled và so sánh trust review với source files trước khi enable.',
    blocks: [
      { type: 'heading', text: 'State machine của lifecycle' },
      {
        type: 'table',
        columns: ['Giai đoạn', 'Code chạy?', 'EvoFlux làm gì'],
        rows: [
          ['Validate', 'Không', 'Parse schema, path, URL, component, extensions và package digest.'],
          ['Install / Link', 'Mặc định không', 'Đăng ký managed copy hoặc developer directory ở trạng thái disabled.'],
          ['Trust review', 'Không', 'Hiện command, remote host, tên environment, Skills/transports và capabilities.'],
          ['Enable', 'Có', 'Publish Skill valid và reconcile MCP runner valid.'],
          ['Disable', 'Dừng code', 'Loại Skill, dừng/reconcile MCP; giữ data.'],
          ['Uninstall', 'Không', 'Xóa registration/package; chỉ xóa data nếu yêu cầu rõ.'],
        ],
      },
      { type: 'heading', text: 'Ý nghĩa của trust review' },
      {
        type: 'table',
        columns: ['Thông tin', 'Nguồn', 'Câu hỏi cần trả lời'],
        rows: [
          ['Executable + args', 'stdio trong mcp.json', 'Đúng interpreter/binary và entrypoint bundled không?'],
          ['Remote host + URL', 'Streamable HTTP/SSE', 'Có tin operator, destination, port và path này không?'],
          ['Tên environment', 'stdio env + credential schema', 'Process cần từng biến để làm gì?'],
          ['Capabilities', 'Skills, MCP transports, EvoFlux extension', 'Scope khai báo có đúng mục đích plugin không?'],
        ],
      },
      {
        type: 'callout',
        tone: 'warning',
        title: 'Trust không bypass permission',
        text: 'Trust chỉ cho component đã khai báo tham gia runtime. Mỗi MCP tool call vẫn qua agent selection, permission mode và sandbox. Activate một Skill không phải authorization cho hành động destructive.',
      },
      { type: 'heading', text: 'Biên process và data' },
      {
        type: 'code',
        language: 'text',
        caption: 'Luồng do host kiểm soát',
        code: 'plugin package (file read-only)\n        │ validate + trust review\n        ▼\ninstallation registry ── enabled? ──► Skill catalog\n        │                              MCP manager\n        └── private data/<id>/ ──────► PLUGIN_DATA + credentials env',
      },
      {
        type: 'p',
        text: 'Mỗi installation có private data directory ổn định nằm ngoài package. Update giữ installation ID và PLUGIN_DATA. Credentials lưu tại đây với permission chặt và chỉ inject qua env name đã khai báo vào stdio. Host ép lại PLUGIN_ROOT/PLUGIN_DATA sau mọi override. Path, symlink, archive entry, URL, header, cwd và placeholder expansion đều được validate trước runtime.',
      },
      { type: 'heading', text: 'Visibility của Skill và tool' },
      {
        type: 'table',
        columns: ['Concern', 'Rule'],
        rows: [
          ['Skill precedence', 'Project/user/admin override plugin enabled; plugin enabled override EvoFlux built-in.'],
          ['MCP configuration', 'Plugin dùng manager in-memory riêng, không sửa global mcp.json.'],
          ['Agent availability', 'Explicit MCP selection hoặc activate Skill cùng installation đưa ready tools vào run.'],
          ['WebBridge', 'Chỉ capability an toàn khai báo rõ mới giữ non-browser server trong WebBridge run.'],
          ['Failure isolation', 'Skill/server hỏng bị cô lập; manifest/package fatal sẽ reject package.'],
        ],
      },
      { type: 'heading', text: 'Checklist trước enable' },
      {
        type: 'tips',
        items: [
          'Xác minh publisher/source, package digest, license và version mong đợi.',
          'Đọc SKILL.md để tìm mutation ẩn, yêu cầu secret hoặc claim quá rộng.',
          'Kiểm executable, args, bundled scripts, dependencies, cwd và nơi ghi file.',
          'Xác minh remote owner và chắc chắn header không có credential thật.',
          'Đảm bảo mọi environment field và capability đều cần thiết.',
          'Dùng service credential least-privilege, test bằng call read-only vô hại.',
          'Giữ permission ask đến khi hiểu behavior và result bounds.',
        ],
      },
    ],
    related: ['agent-plugins', 'agent-plugins-authoring', 'permissions-modes', 'sandbox-settings'],
    openAction: { type: 'workbench', tool: 'plugins' },
  },
  {
    id: 'agent-plugins-troubleshooting',
    category: 'plugins',
    title: 'Troubleshooting và diagnostics cho Agent Plugins',
    summary:
      'Chẩn đoán lỗi cài đặt, Skill discovery, credentials, MCP startup, tool bị thiếu, development link stale và lỗi đóng gói theo thứ tự xác định.',
    keywords: ['lỗi plugin', 'mcp không ready', 'không thấy skill', 'credentials unsupported', 'plugin logs', 'validation diagnostic', 'plugin stale', 'archive lỗi'],
    setup: 'Giữ plugin disabled trong lúc kiểm package error. Dùng Plugin Center diagnostics và `evoflux plugin inspect/show` trước khi sửa global MCP hoặc reinstall EvoFlux.',
    blocks: [
      { type: 'heading', text: 'Triệu chứng → nguyên nhân → bước tiếp theo' },
      {
        type: 'table',
        columns: ['Triệu chứng', 'Nguyên nhân thường gặp', 'Bước kiểm tiếp'],
        rows: [
          ['Import bị reject', 'Manifest fatal, archive/path unsafe, symlink, duplicate, size/ratio limit', 'Đọc package diagnostics; inspect thư mục đã giải nén.'],
          ['Plugin valid nhưng thiếu Skill', 'Disabled, Skill invalid/nằm sâu, name collision', 'Enable; kiểm direct-child SKILL.md và precedence.'],
          ['MCP không có trong Settings', 'Disabled, mcp.json invalid, chỉ có SSE', 'Đọc server diagnostics và transport hỗ trợ.'],
          ['MCP starting mãi', 'Process không initialize hoặc làm bẩn stdout', 'Chạy entrypoint thủ công; log sang stderr; kiểm dependency.'],
          ['MCP error', 'Sai command/args/cwd, thiếu credential, network/TLS', 'Mở runtime error và so với trust/config.'],
          ['Credentials unsupported', 'Không có credential extension', 'Thêm fields extension, Save, Validate, Refresh.'],
          ['Credentials incomplete', 'Thiếu required field hoặc URL/type sai', 'Điền field; secret đã config để trống chỉ khi muốn giữ nguyên.'],
          ['Agent không thấy tool', 'Server chưa ready hoặc chưa select/activate', 'Chọn MCP cho agent hoặc activate Skill cùng plugin.'],
          ['Linked code stale', 'File chưa Save hoặc runtime chưa reconcile', 'Save, Validate, Refresh, Disable/Enable.'],
          ['Update fail', 'Replacement invalid hoặc package safety fail', 'Inspect package mới trước update; giữ installation cũ.'],
        ],
      },
      { type: 'heading', text: 'Vòng diagnostic theo thứ tự' },
      {
        type: 'code',
        language: 'shell',
        caption: 'Thu evidence bằng CLI',
        code: 'evoflux plugin inspect ./plugin-dir\nevoflux plugin list\nevoflux plugin show <installation-id>\nevoflux plugin disable <installation-id>\n# sửa file/credentials, sau đó:\nevoflux plugin enable <installation-id>',
      },
      {
        type: 'tips',
        items: [
          '1) Sửa package-level error trước; component debugging không đáng tin khi plugin.json invalid.',
          '2) Xác nhận đúng source_type, root, version, digest và enabled state.',
          '3) Kiểm Skill và MCP diagnostics độc lập.',
          '4) So trust review với file thật và dependency dự kiến.',
          '5) Cấu hình required credentials nhưng không lộ value trong chat/log.',
          '6) Xem Settings → MCP servers: runtime error và tool names đăng ký.',
          '7) Test entrypoint với cùng cwd và placeholder không chứa secret.',
          '8) Enable lại rồi gọi một read-only tool có giới hạn dưới ask mode.',
        ],
      },
      { type: 'heading', text: 'Lỗi stdio protocol phổ biến' },
      {
        type: 'table',
        columns: ['Sai', 'Hậu quả', 'Cách sửa'],
        rows: [
          ['In log ra stdout', 'JSON-RPC stream hỏng', 'Gửi operational log sang stderr.'],
          ['Dùng shell expression làm command', 'Không shell-expand; executable not found', 'Tách command và args array.'],
          ['Relative file phụ thuộc caller cwd', 'Chạy tay được, host fail', 'Dùng PLUGIN_ROOT hoặc cwd nằm trong package.'],
          ['Ghi vào managed package', 'Update mất state hoặc permission fail', 'Ghi mutable state dưới PLUGIN_DATA.'],
          ['Result/startup không giới hạn', 'Tool chậm hoặc response quá lớn', 'Thêm timeout, pagination, limit và sanitized error.'],
        ],
      },
      {
        type: 'callout',
        title: 'Không “sửa” plugin MCP trong global Settings',
        text: 'Plugin MCP được quản lý riêng có chủ đích. Sửa mcp.json/credentials của plugin rồi Validate/Reconcile. Thêm server global trùng tạo identity thứ hai và che lỗi thật của package.',
      },
      { type: 'heading', text: 'Evidence cần có khi báo bug' },
      {
        type: 'tips',
        items: [
          'EvoFlux version/OS và packaged hay dev.',
          'Plugin name/version/source type/content digest — không gửi credential value.',
          'Diagnostic code/message của package, Skill và MCP.',
          'Runtime state, sanitized error, transport và stable tool suffix.',
          'Plugin tree tối thiểu cùng plugin.json/mcp.json đã redact.',
          'Operation chính xác: import/link/update/enable và disable/enable có thay đổi gì.',
        ],
      },
    ],
    related: ['agent-plugins', 'agent-plugins-authoring', 'agent-plugins-runtime-security', 'troubleshooting-connection'],
    openAction: { type: 'workbench', tool: 'plugins' },
  },
  {
    id: 'agents-settings',
    category: 'settings',
    title: 'Agents, Skills và MCP',
    summary:
      'Cấu hình Markdown agent, skill pack và MCP server trong Settings — tool kế thừa cùng rule permission như tool native. Team scope theo work / coding để specialist đúng mode hiện đúng chỗ.',
    keywords: [
      'agents',
      'skills',
      'mcp',
      'stdio',
      'http',
      'sse',
      'tools',
      'frontmatter',
      'kỹ năng',
      'tác nhân',
      'máy chủ mcp',
      'MCP',
      'Skills'
],
    setup:
      'Settings → Agents cho thành viên team; Settings → Skills để validate pack; Settings → MCP để thêm server. Từ chat, dùng /skill: hoặc command palette cho shortcut New Agent / New Skill.',
    tricks: [
      'Agent là file .md với YAML frontmatter — diff và version được.',
      'Settings → Skills cho phép tạo, sửa, hiển thị và lọc theo Work, Coding hoặc Both; skill hợp lệ chỉ hiện dưới /skill: trong session đúng mode.',
      'Chấm trạng thái MCP: ready / starting / auth / error / stopped.',
      'MCP tool chịu cùng rule permission như tool native.',
      'Team scope theo work / coding.',
      'Command palette nhảy tới Edit <agent>… hoặc tạo agent và skill mới.',
      'Dùng tools_opt_out để tắt default tool code-owned; bỏ skill đã assign trực tiếp khỏi danh sách skills.',
      'Tool chỉ Lead (ask_user, plan mode helper, một số worktree helper) không bao giờ cấp cho specialist.',
      'MCP server kẹt auth thì hoàn tất auth flow trước khi đổ lỗi slash menu composer.'
],
    blocks: [
      {
        type: 'p',
        text: 'Agent định nghĩa role, model, tool và system prompt. Skill là instruction pack load theo nhu cầu qua /skill:. MCP server phơi tool ngoài qua stdio, HTTP hoặc SSE. Cùng nhau là cách bạn định hình hành vi đội mà không fork sản phẩm.',
      },
      {
        type: 'p',
        text: 'Markdown agent và skill review được trong git. MCP mở rộng bề mặt tool mà không fork core; permissions/sandbox vẫn gate thực thi. Coi MCP như mọi tool provider khác — least privilege rồi mới nới.',
      },
      {
        type: 'p',
        text: 'Settings → Agents để sửa thành viên team; Settings → Skills để validate pack; Settings → MCP để thêm server và xem chấm trạng thái. Từ chat, gõ /skill: hoặc mở palette cho New Agent / New Skill. Tool chỉ Lead (ask_user, plan mode, worktree helper) không bao giờ cấp cho specialist.',
      },
      {
        type: 'tips',
        items: [
          'Agents — .md + YAML frontmatter',
          'Skills — /skill: sau validation',
          'MCP — stdio / HTTP / SSE',
          'Status dots — ready / starting / auth / error / stopped',
          'tools_opt_out — tắt default tool code-owned',
          'Mode scope — team work / coding',
          'Lead-only tools — không bao giờ trên specialist'
],
      },
      {
        type: 'p',
        text: 'Thêm MCP server: (1) Settings → MCP, (2) chọn transport, (3) cấu hình command hoặc URL, (4) chờ ready (hoàn auth nếu cần), (5) xác nhận tool hiện, (6) chạy tool vô hại dưới ask mode, (7) rồi mới nới permission.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: chờ skill invalid trong slash menu; “cấp” specialist tool chỉ Lead trong đầu; để MCP lỗi rồi retry chat; nhét secret vào agent markdown commit public; quên mode scope nên Coding specialist không bao giờ hiện ở Work.',
      },
      {
        type: 'tips',
        items: [
          'Coding skill đã activate hướng dẫn workflow; code_context native validate và thực thi mọi retrieval action.',
          'Workflow và skill đều cần scope hợp lệ mới hiện trong /.',
          'Rule Always của permission áp cả MCP tool — ưu tiên Once trước.'
],
      }
],
    related: [
      'composer-power',
      'permissions-modes',
      'coding-graph',
      'slash-commands'
],
    openAction: { type: 'settings', path: 'agents' },
  },
  {
    id: 'sandbox-settings',
    category: 'settings',
    title: 'Sandbox và outbound protection',
    summary:
      'Cấu hình deny glob cho tool filesystem, vị trí worktree, giới hạn process, môi trường shell và PII redaction outbound.',
    keywords: [
      'sandbox',
      'deny',
      'isolation',
      'pii',
      'outbound',
      'worktree',
      'user_data',
      'glob',
      'hộp cát',
      'chặn',
      'bảo vệ'
],
    openAction: { type: 'settings', path: 'sandbox' },
    setup:
      'Settings → Sandbox. Xem lại deny pattern trước khi bật permission auto/bypass mạnh. Help popover trên trang giải thích cú pháp glob ** và *.',
    tricks: [
      'Deny pattern dùng glob ** và *; help popover trong Settings giải thích cú pháp.',
      'Vị trí worktree (repository vs user_data) nằm trên trang Sandbox.',
      'Outbound redact/block chạy trước khi nội dung tới provider khi bật.',
      'Sandbox vẫn áp dưới Goal mode — Goal không nới scope.',
      'Symlink vào root bị chặn bị reject; shell command được tokenize để check path bị deny.',
      'Ghép accept-edits hoặc auto với denylist chặt cho tốc độ coding ngày thường.',
      'Deny credential cache và đĩa không liên quan dù bạn tin model.',
      'Test lại một tool call mẫu sau khi sửa globs — glob sai im lặng giống “tool hỏng”.',
      'Ghép filesystem denylist với domain policy Settings → Browser cho WebBridge.'
],
    blocks: [
      {
        type: 'p',
        text: 'Tool filesystem tích hợp enforce workspace root, read-only root và deny pattern dưới mọi permission mode. Lệnh shell được quét các denied path rõ ràng nhưng chạy trực tiếp trên host, không có containment cấp hệ điều hành.',
      },
      {
        type: 'p',
        text: 'Permission mode quyết định khi nào hỏi. Kiểm tra path ở application-level vẫn áp dụng cho tool tích hợp, còn quét lệnh shell chỉ là guardrail chứ không phải security boundary. Goal giữ nguyên policy này.',
      },
      {
        type: 'p',
        text: 'Mở Settings → Sandbox. Thêm deny glob, set vị trí worktree cho Coding, cấu hình giới hạn process và môi trường shell, rồi bật outbound PII redact/block khi cần. Test lại một tool call mẫu sau thay đổi. Ghép với domain policy Settings → Browser cho WebBridge.',
      },
      {
        type: 'tips',
        items: [
          'Deny globs — pattern ** và *',
          'Worktree location — repository vs user_data',
          'Outbound PII — redact/block trước provider',
          'Symlinks — reject vào root bị chặn',
          'Shell tokenization — check path bị deny trên lệnh',
          'Goal — không bao giờ nới sandbox scope'
],
      },
      {
        type: 'p',
        text: 'Cứng hóa laptop Coding: (1) liệt kê root nhạy cảm (key, cloud sync, client khác), (2) thêm deny globs, (3) set vị trí worktree chủ đích, (4) bật outbound redact nếu policy yêu cầu, (5) chạy probe tool dưới ask, (6) rồi mới cân nhắc accept-edits hoặc auto cho tốc độ.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: bật bypass với denylist trống trên workspace home directory; quên symlink; tưởng outbound redact thay thế việc không paste secret; để worktree trên user_data rồi thắc mắc dung lượng đĩa chuyển chỗ; nhầm deny hit với MCP auth fail.',
      },
      {
        type: 'tips',
        items: [
          'Plan Reject khi plan nhắm path bị deny thay vì vật lộn với sandbox.',
          'Checklist Troubleshooting “tools denied” gồm shield + denylist.',
          'Coding worktree theo policy vị trí Sandbox.'
],
      }
],
    related: [
      'permissions-modes',
      'settings-safety',
      'coding-workspaces',
      'slash-goal'
],
  },
  {
    id: 'connection-settings',
    category: 'settings',
    title: 'Connection settings',
    summary:
      'Trỏ UI vào sidecar local đóng gói hoặc URL server EvoFlux ngoài kèm access key — điểm dừng đầu khi HealthDot đỏ. App đóng gói mặc định sidecar kèm ephemeral port và token handshake.',
    keywords: [
      'connection',
      'sidecar',
      'external',
      'access key',
      'HealthDot',
      'backend',
      'URL',
      'token handshake',
      'ephemeral port',
      'kết nối',
      'máy chủ'
],
    openAction: { type: 'settings', path: 'connection' },
    setup:
      'Settings → Connection (hoặc bấm HealthDot). App đóng gói mặc định sidecar đóng gói. Từ source, đảm bảo `make dev` lên trước `make -C desktop dev`.',
    tricks: [
      'Sidecar đóng gói dùng ephemeral port và token handshake — thường bạn không set URL.',
      'External mode cần server URL tới được và access key.',
      'Từ source, đảm bảo `make dev` lên trước `make -C desktop dev`.',
      'Sau khi đổi connection mode, đợi Welcome/team ready trước khi gửi chat.',
      'Diagnostics bổ sung Connection khi URL ổn mà subsystem down.',
      'Bấm HealthDot bất cứ lúc nào để shortcut vào Connection.',
      'Relaunch app đóng gói để restart sidecar kẹt trước khi sửa settings không liên quan.',
      'Đừng paste access key vào transcript khi cấu hình external mode.',
      'Toggle external → bundled thì xác nhận HealthDot xanh lại trước khi tưởng Providers hỏng.'
],
    blocks: [
      {
        type: 'p',
        text: 'Connection settings chọn giữa FastAPI sidecar local đóng gói và backend EvoFlux ngoài. HealthDot phản ánh UI có tới được server khỏe không. Hầu hết user desktop không rời bundled mode.',
      },
      {
        type: 'p',
        text: 'Sai connection mode trông như “chat chết” dù Providers hoàn hảo. Tách Connection khỏi Providers và Diagnostics tiết thời gian: trước hết tới backend khỏe, rồi mới kiểm credential và subsystem.',
      },
      {
        type: 'p',
        text: 'Mở Settings → Connection. Giữ bundled cho dùng desktop thường. Sang external chỉ khi bạn chủ đích chạy API remote hoặc launch riêng. Bấm HealthDot bất cứ lúc nào để shortcut tới đây. Sau thay đổi, đợi Welcome/team ready trước khi gửi chat.',
      },
      {
        type: 'tips',
        items: [
          'Bundled — ephemeral port + token handshake',
          'External — server URL + access key',
          'HealthDot — shortcut vào Connection',
          'Welcome — đợi sidecar/team ready',
          'Từ source — `make dev` rồi `make -C desktop dev`',
          'Diagnostics — khi URL ổn nhưng subsystem fail'
],
      },
      {
        type: 'p',
        text: 'Khôi phục HealthDot đỏ (bản đóng gói): (1) bấm HealthDot, (2) xác nhận bundled mode, (3) relaunch app để restart sidecar, (4) đợi Welcome tắt, (5) mở Diagnostics nếu vẫn không khỏe, (6) rồi mới đụng Providers.',
      },
      {
        type: 'p',
        text: 'External mode: (1) start hoặc xác định API remote/local, (2) copy base URL và access key, (3) Settings → Connection → external, (4) save, (5) đợi health, (6) verify chat nhỏ. Revert bundled nếu bạn trở lại workflow desktop một máy bình thường.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: gõ Vite URL làm API URL; mở Tauri shell trước `make dev`; sang external “để debug” rồi quên; gửi chat khi Welcome còn; coi HealthDot xanh là chứng mọi subsystem (MCP, git host, WebBridge) ổn — dùng Diagnostics cho việc đó.',
      },
      {
        type: 'tips',
        items: [
          'Thứ tự cold-start Getting started khớp recovery Connection.',
          'Cron Scheduler trên sidecar local vẫn cần máy thức và khỏe.',
          'Checklist Troubleshooting bắt đầu ở HealthDot → Connection.'
],
      }
],
    related: [
      'troubleshooting-connection',
      'getting-started',
      'settings-safety',
      'providers-settings'
],
  },
  {
    id: 'settings-safety',
    category: 'settings',
    title: 'Bản đồ Settings',
    summary:
      'Bản đồ mọi trang settings: providers, agents, skills, MCP, memory, connection, git, sandbox, browser, notifications, appearance, telemetry và diagnostics. Biết trang nào sở hữu concern nào tránh lục lung tung.',
    keywords: [
      'settings',
      'connection',
      'appearance',
      'notifications',
      'telemetry',
      'diagnostics',
      'git',
      'version-control',
      'memory',
      'mcp',
      'cài đặt',
      'bản đồ',
      'Settings'
],
    openAction: { type: 'settings', path: '' },
    tricks: [
      'Desktop hiện category settings trên sidebar rail; mobile dùng hub About làm nav list.',
      'Guidelines (help này) cũng link từ Settings → About.',
      'Telemetry có trang đầy đủ tại /telemetry cũng như Settings → Telemetry.',
      'Git & reviews chứa kết nối PR và safety policy (timeout, max diff, force-with-lease).',
      'Appearance gồm theme, accent, fonts, motion và locale (en / vi / ja).',
      'Diagnostics cho check subsystem live — bổ sung tín hiệu nhị phân của HealthDot.',
      'Nhóm Intelligence vs System vs Application giữ toggle rủi ro khỏi lẫn với chọn theme.',
      'Notifications có test ping — dùng trước khi tin alert khi không focus.',
      'Mở command palette nếu quên trang settings nào sở hữu toggle.'
],
    blocks: [
      {
        type: 'p',
        text: 'Settings nhóm thành Intelligence (Providers, Agents, Skills, MCP), Knowledge (Memory / Dream), System (Connection, Git & reviews, Sandbox, Browser, Notifications) và Application (Appearance, Telemetry, Diagnostics), cộng About. Dùng bản đồ này khi biết concern nhưng không nhớ tên trang.',
      },
      {
        type: 'p',
        text: 'Biết trang nào sở hữu concern nào tránh lục: models vs agents vs sandbox vs browser policy tách cố ý để toggle rủi ro vẫn chủ đích. Đổi theme không nên nằm cạnh force-with-lease trong mental model của bạn.',
      },
      {
        type: 'tips',
        items: [
          'Providers — API key, OAuth, daemon local, model registry',
          'Agents — model, tool, system prompt theo thành viên team',
          'Skills — instruction pack cho /skill:',
          'MCP servers — tool ngoài stdio / HTTP / SSE',
          'Memory — wiki dài hạn + lịch Dream',
          'Connection — sidecar đóng gói vs URL ngoài / access key',
          'Git & reviews — kết nối host, timeout, diff size, force-with-lease',
          'Sandbox — deny glob, giới hạn process, vị trí worktree, outbound PII',
          'Browser — built-in WebView + master policy WebBridge',
          'Notifications — alert desktop/mobile khi không focus; test ping',
          'Appearance — theme, accent, fonts, motion, locale (en / vi / ja)',
          'Telemetry — trace và summary (cũng /telemetry)',
          'Diagnostics — check health subsystem live',
          'About — thông tin app + link Guidelines'
],
      },
      {
        type: 'p',
        text: 'Checklist máy mới: (1) Connection khỏe, (2) Providers kết nối, (3) Agents gán model, (4) xem denylist Sandbox, (5) Git & reviews host nếu cần PR, (6) policy Browser/WebBridge nếu cần, (7) Appearance locale, (8) Notifications test ping, (9) mở Guidelines từ About một lần để xác nhận help chạy.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: đổi Appearance khi chat fail; tìm Dream cron dưới Scheduler; tìm token host PR dưới Providers; chờ layout Settings mobile giống rail desktop; bỏ qua Diagnostics vì HealthDot xanh.',
      },
      {
        type: 'tips',
        items: [
          'Mỗi bài Guidelines lớn deep-link qua openAction tới đúng trang khi có.',
          'Locale chỉ đổi phần giao diện dùng chung — nội dung chat giữ như bạn viết.',
          'Telemetry trống thường nghĩa extras tắt, không phải chat outage.'
],
      }
],
    related: [
      'providers-settings',
      'agents-settings',
      'sandbox-settings',
      'connection-settings',
      'troubleshooting-connection'
],
  },
  {
    id: 'keyboard-shortcuts',
    category: 'shortcuts',
    title: 'Phím tắt',
    summary:
      'EvoFlux dùng modifier chính theo hệ điều hành — Command trên macOS, Ctrl trên Windows/Linux. Guidelines (Help) vẫn tách khỏi command palette.',
    keywords: [
      'shortcut',
      'keyboard',
      'ctrl',
      'hotkey',
      'palette',
      'Ctrl+P',
      'Ctrl+N',
      'Ctrl+B',
      'Ctrl+V',
      'macOS',
      'phím tắt',
      'bàn phím'
],
    tricks: [
      'Modifier chính + P mở command palette (Search trên sidebar). Help mở modal Guidelines này — không phải palette.',
      'Badge shortcut tự đổi: ⌘ trên macOS, Ctrl trên Windows/Linux.',
      'Khi gõ trong input, các phím copy/paste/select/undo vẫn giữ hành vi edit native; shortcut xoay view bị chặn lúc paste.',
      'Ctrl+B do AppShell sở hữu một lần cho mọi mode sidebar.',
      'Ctrl+R chỉ refresh session Work (không reload cả app).',
      'Quên binding thì Ctrl+P search theo tên action.',
      'Phím 1–5 chỉ đổi permission mode khi shield menu đang mở.',
      'Ctrl+I focus chat input — hữu ích sau khi click qua panel workbench.'
],
    blocks: [
      {
        type: 'p',
        text: 'Shortcut điều hướng toàn cục và workbench dùng Command trên macOS, Ctrl trên Windows/Linux. Badge và binding sống dùng chung một quy tắc platform.',
      },
      {
        type: 'p',
        text: 'Các shortcut edit native được ưu tiên khi focus nằm trong input. Ngoài vùng nhập liệu, bảng dưới dùng modifier chính của hệ điều hành.',
      },
      {
        type: 'shortcuts',
        rows: [
          { keys: 'Ctrl+P', action: 'Command palette' },
          { keys: 'Ctrl+N', action: 'New team chat' },
          { keys: 'Ctrl+B', action: 'Toggle sidebar' },
          { keys: 'Ctrl+V', action: 'Cycle Agent ↔ Split (desktop; không lúc paste)' },
          { keys: 'Ctrl+F', action: 'Files / Changed & Files (label có thể hiện ⌘P)' },
          { keys: 'Ctrl+M', action: 'Memory wiki' },
          { keys: 'Ctrl+S', action: 'Scheduler' },
          { keys: 'Ctrl+K', action: 'Plugins' },
          { keys: 'Ctrl+T', action: 'Built-in browser' },
          { keys: 'Ctrl+G', action: 'Git Changes (Coding)' },
          { keys: 'Ctrl+`', action: 'Terminal' },
          { keys: 'Ctrl+I', action: 'Focus chat input' },
          { keys: 'Ctrl+;', action: 'Side chat (label có thể hiện ⌥⌘S)' },
          { keys: 'Ctrl+R', action: 'Refresh Work sessions' },
          { keys: '1–5', action: 'Permission modes khi shield menu đang mở' }
],
      },
      {
        type: 'p',
        text: 'Quên binding thì ưu tiên command palette (Ctrl+P) — hầu hết action search theo tên. Guidelines (Help) tách riêng để palette search còn tập trung command. Graph và Review dựa workbench bar hoặc palette vì không có global shortcut riêng.',
      },
      {
        type: 'tips',
        items: [
          'Nút Help — modal Guidelines (docs)',
          'Ctrl+P — command palette (actions)',
          'Nhãn ⌘P / ⌥⌘S — cũ; dùng Ctrl+F / Ctrl+;',
          'Ctrl+V — xoay view bị suppress lúc paste',
          'Ctrl+R — chỉ refresh session Work',
          '1–5 — chỉ khi shield menu mở'
],
      },
      {
        type: 'p',
        text: 'Sai thường gặp: Cmd+P trên macOS chờ palette; Ctrl+R tưởng reload cả app; đánh Ctrl+V trên composer lúc paste; tưởng Graph có hotkey ẩn; mở Help khi ý là palette (hoặc ngược lại).',
      },
      {
        type: 'tips',
        items: [
          'Permission shield + 1–5 nhanh hơn click mode.',
          'Ctrl+; side chat trong Goal mà không /stop.',
          'Ctrl+G sau plan Accept để verify diff.'
],
      }
],
    related: [
      'workbench-tools',
      'getting-started',
      'permissions-modes',
      'side-chat'
],
    openAction: { type: 'palette' },
  },
  {
    id: 'troubleshooting-connection',
    category: 'troubleshooting',
    title: 'Connection và Diagnostics',
    summary:
      'Khi backend down, session fail hoặc health check đỏ — dùng HealthDot, Connection, Diagnostics và checklist sửa thường gặp. Tách lỗi connection, provider, permission và WebBridge trước khi reinstall.',
    keywords: [
      'troubleshoot',
      'connection',
      'health',
      'diagnostics',
      'sidecar',
      'HealthDot',
      'make dev',
      'error',
      'lỗi',
      'sự cố',
      'chẩn đoán'
],
    setup:
      'Bắt đầu ở HealthDot footer sidebar. Giữ Settings → Connection và Settings → Diagnostics gần tay. Từ source, chuẩn bị hai terminal: `make dev` và `make -C desktop dev`.',
    tricks: [
      'Bấm HealthDot → Connection để xác nhận backend bundled vs external.',
      'Settings → Diagnostics chạy check live qua các subsystem.',
      'Lần mở app lạnh vẫn hiện Welcome đến khi sidecar và team ready — đợi xong mới retry chat.',
      'Từ source: Terminal 1 `make dev`, Terminal 2 `make -C desktop dev`.',
      'Không có model listed → Settings → Providers trước mọi thứ khác.',
      'Tool bị deny bất ngờ → permission mode + Sandbox deny globs.',
      'WebBridge offline → extension đã cài, pairing còn, Browser settings bật, per-chat toggle on.',
      'Telemetry trống → extras observability/DuckDB có thể tắt — không nhất thiết chat outage.',
      'Goal kẹt → xem blocker streak, budget pause, hoặc /goal:stop.',
      '/scheduler cảm giác 404 → dùng panel Ctrl+S; route redirect home.'
],
    blocks: [
      {
        type: 'p',
        text: 'Hầu hết báo cáo “EvoFlux hỏng” là connection, provider, permission hoặc pairing WebBridge. HealthDot là tín hiệu nhị phân; Diagnostics là panel chi tiết; Connection chọn backend UI nói chuyện. Sửa theo thứ tự đó trước khi reinstall.',
      },
      {
        type: 'p',
        text: 'UI có thể lên trong khi sidecar còn boot, trỏ sai URL, hoặc thiếu credential provider. Tách các failure mode tiết thời gian và tránh phản xạ “reset hết” che nguyên nhân thật.',
      },
      {
        type: 'p',
        text: 'Xem HealthDot. Không khỏe thì mở Connection và xác nhận sidecar bundled vs URL/key ngoài. Từ source, đảm bảo cả `make dev` và `make -C desktop dev` đang chạy. App đóng gói nên relaunch để restart sidecar. Rồi mở Diagnostics cho check subsystem. Chỉ sau khi health xanh mới verify Providers, permission mode, Sandbox và Browser/WebBridge.',
      },
      {
        type: 'tips',
        items: [
          'HealthDot đỏ/hổ phách → Connection + đợi Welcome/team ready',
          'Chạy source → `make dev` rồi `make -C desktop dev`',
          'Không có model → Settings → Providers',
          'Lỗi stream mà health xanh → credential model/provider hoặc rate limit',
          'Tool bị deny → permission mode (ask/plan) + Sandbox deny globs',
          'WebBridge offline → extension, pairing, Browser policy, per-chat enable',
          'Telemetry trống → extras observability tắt (thường không chặn)',
          'Goal kẹt → xem blocker streak, budget pause, hoặc /goal:stop',
          '/scheduler cảm giác 404 → panel Ctrl+S; route redirect home',
          'Graph cũ → reindex từ Graph tool sau edit ngoài lớn'
],
      },
      {
        type: 'p',
        text: 'Checklist theo thứ tự: (1) HealthDot, (2) Connection mode, (3) Welcome/team ready, (4) Diagnostics, (5) Providers, (6) permission shield, (7) Sandbox denylist, (8) Browser/WebBridge, (9) tool theo mode (Changes/Graph/Review chỉ Coding). Dừng ở lớp fail đầu tiên.',
      },
      {
        type: 'p',
        text: 'Sai thường gặp: reinstall vì thiếu provider key; debug MCP khi HealthDot đỏ; tưởng health xanh nghĩa là Ollama lên; force-refresh bằng Ctrl+R chờ reload đầy đủ (nó chỉ refresh session Work).',
      },
      {
        type: 'tips',
        items: [
          'Thứ tự cold-start Getting started khớp checklist này.',
          'Plan review đang chờ Accept không phải hang — giải panel.',
          'Nhầm focus side chat trông như “Lead bỏ qua tôi.”',
          'Khi nghi — Diagnostics + Work ping nhỏ thắng speculative reset.'
],
      }
],
    related: [
      'getting-started',
      'connection-settings',
      'settings-safety',
      'providers-settings',
      'browser-webbridge'
],
    openAction: { type: 'settings', path: 'diagnostics' },
  }
]
