import type { HelpArticle, HelpCategory } from '../types'

export const HELP_CATEGORIES_JA: HelpCategory[] = [
  {
    id: 'getting-started',
    label: 'はじめに',
    description: 'インストール、モデル接続、最初のセッション',
  },
  {
    id: 'modes',
    label: 'モード',
    description: 'Work と Coding',
  },
  {
    id: 'chat',
    label: 'チャットとチーム',
    description: 'Lead、specialist、表示、権限',
  },
  {
    id: 'composer',
    label: 'Composer',
    description: 'メンション、添付、スキル、ワークフロー',
  },
  {
    id: 'slash',
    label: 'スラッシュと Goal',
    description: '組み込みスラッシュコマンドと永続 Goal',
  },
  {
    id: 'sessions',
    label: 'セッションとフォルダ',
    description: 'ピン、フォルダ、共有コンテキスト',
  },
  {
    id: 'workbench',
    label: 'Workbench',
    description: 'チャット横のパネル',
  },
  {
    id: 'coding',
    label: 'Coding',
    description: 'Repos、プロジェクト、git、Graph、PR',
  },
  {
    id: 'memory',
    label: 'Memory と Dream',
    description: 'Wiki ナレッジと合成',
  },
  {
    id: 'scheduler',
    label: 'Scheduler',
    description: 'Cron とワンショットのエージェントタスク',
  },
  {
    id: 'browser',
    label: 'Browser と WebBridge',
    description: '内蔵ブラウザと実際の Chrome/Edge',
  },
  {
    id: 'plugins',
    label: 'Plugins',
    description: 'ポータブル Agent Skills と MCP パッケージ',
  },
  {
    id: 'settings',
    label: 'Settings と安全性',
    description: 'Providers、Agents、MCP、sandbox',
  },
  {
    id: 'shortcuts',
    label: 'キーボードショートカット',
    description: 'macOS は Command、Windows/Linux は Ctrl',
  },
  {
    id: 'troubleshooting',
    label: 'トラブルシューティング',
    description: '接続、ヘルス、Diagnostics',
  }
]

export const HELP_ARTICLES_JA: HelpArticle[] = [
  {
    id: 'getting-started',
    category: 'getting-started',
    title: 'EvoFlux をはじめよう',
    summary:
      'デスクトップアプリをインストールするかソースから起動し、BYOM（自分のモデル）プロバイダを接続して sidecar の健全性を確認してから、最初の Work チャット、Coding リポジトリ、または Coding ワークスペースへ進みます。コールド起動からストリーミング検証までのオンボーディング経路です。',
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
      'はじめ',
      'セットアップ',
      'インストール',
      'プロバイダ',
      '接続',
      '初回'
],
    setup:
      'パッケージ版デスクトップは FastAPI sidecar を自動起動します。ソースから: Terminal 1 で `make dev`（API + Vite）、Terminal 2 で `make -C desktop dev`（Tauri シェル）。フロント依存: `cd web && bun install`。最初のチャット前に、プロバイダ資格情報またはローカルデーモン（Ollama など）を用意してください。',
    tricks: [
      'サイドバーフッタの HealthDot をクリックすると、バックエンドが不健全なときに Connection 設定へ直接ジャンプできます。',
      'Settings → Providers が最初の停留所です — API キー、OAuth、またはローカルデーモン（Ollama など）。プロバイダ未設定だと composer はストリームできません。',
      'Appearance → Display language は UI クロムを English / Vietnamese / Japanese に対応。チャット本文はあなたが書いた言語のままです。',
      'コールドスタートでは sidecar とチームレジストリが準備できるまで Welcome が表示されます — チャット再試行や「空のチーム」バグ探しの前に待ちましょう。',
      'プロバイダ接続後、大きなリポジトリを開く前に短い Work メッセージ（「ping — ok と返して」）でエンドツーエンドのストリーミングを検証します。',
      'Coding ではリポジトリをクリックするとワークスペースにフォーカスします。セッション作成は + / New chat です。フォーカスだけではトランスクリプトは始まりません。',
      'Guidelines はサイドバーの Help ボタン（このモーダル）からいつでも開けます。コマンドパレットは Ctrl+P のまま — アクション用で、ドキュメント用ではありません。',
      'HealthDot が緑でもチャットが失敗する場合は、再インストール前に Settings → Diagnostics を開いてください — サブシステム検査の方が全面ワイプより効くことが多いです。',
      'BYOM 資格情報はチャットトランスクリプトに入れず、Settings → Providers だけで設定します。'
],
    blocks: [
      {
        type: 'p',
        text: 'EvoFlux はローカルファーストのデスクトップハーネスです: Tauri シェル → React UI → マシン上の FastAPI sidecar。モデルは BYOM。コアループに、選択したモデルプロバイダ以外のベンダークラウドアカウントは不要です。トランスクリプト、wiki Memory、sandbox ポリシー、git 作業はディスク上に残ります。',
      },
      {
        type: 'p',
        text: 'ローカル所有が製品の賭けです。2 つのモード（Work と Coding）は 1 つのチームハーネス — Lead/specialist、composer、権限、workbench — を共有するので、クロムを一度学べば、仕事に合わせて面を切り替えられます。調査や捨てフォルダは Work、永続リポジトリは Coding です。',
      },
      {
        type: 'p',
        text: 'パッケージ版: OS 向けデスクトップビルドをダウンロードして起動します。シェルは一時ポートとトークンハンドシェイクでバンドル sidecar を起動し、通常バックエンド URL を手入力しません。ソースから: web 依存を入れ（`cd web && bun install`）、API + Vite に `make dev`、Vite URL を指す Tauri ウィンドウに `make -C desktop dev`。',
      },
      {
        type: 'tips',
        items: [
          '1) HealthDot が緑であることを確認（そうでなければ Connection を開き）、Welcome が消えるまで待つ。',
          '2) Settings → Providers → モデルを少なくとも 1 つ接続し、configured と表示されることを確認。',
          '3) Work のまま短い最初のチャットを送るか、Coding に切り替えて git リポジトリを開く。',
          '4) 任意: Coding → リポジトリまたはプロジェクトを開きセッションを開始。',
          '5) セッションができたら workbench ツール（Terminal、Files、Memory、Browser）を探索。',
          '6) 任意の硬化: auto や bypass を有効にする前に Settings → Sandbox の deny glob を見直す。'
],
      },
      {
        type: 'p',
        text: 'HealthDot はテーマトグル横のサイドバーフッタにあります。赤や琥珀は UI が健全なバックエンドに届いていない合図 — チャットやツールエラーを追う前に Connection を直してください。Settings → Diagnostics は、二値ヘルス以上の情報が必要なときにライブのサブシステム検査を実行します。',
      },
      {
        type: 'p',
        text: '初日によくある失敗: Welcome 表示中にチャット送信; 「モデルがない」を接続障害だと決めつけて Providers を開かない; Coding のリポジトリクリックがチャット作成だと仮定; `/scheduler` をブックマーク（ホームへリダイレクト — Ctrl+S を使う）; Guidelines と Ctrl+P パレットを同じ面だと扱う。',
      },
      {
        type: 'tips',
        items: [
          '横断: 最初のチャットが通ったら Memory（Ctrl+M）を開き、永続メモの着地点を把握する。',
          '横断: 実リポジトリをエージェントに編集させる前に権限シールド（キー 1–5）をざっと確認。',
          '横断: ヘルスは緑なのにツールパネルが空なら Ctrl+P → Diagnostics を検索。',
          'ソースのみ: API をすでに配信している `make dev` なしで Tauri シェルを起動しない。'
],
      },
      {
        type: 'p',
        text: '次に読むもの: Work / Coding の使い分けはモード概要; BYOM 設定は Providers; HealthDot が赤のままなら Connection; 順序付き修正チェックリストはトラブルシューティング。',
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
    title: 'Work と Coding モード',
    summary:
      '2 つの製品モードはハーネスを共有しつつ、ワークスペース、specialist、既定ツールが異なります。モードスイッチャーはモードごとの最終ルートを記憶するので、Coding に戻ると離れた場所に着地します。',
    keywords: [
      'mode',
      'work',
      'coding',
      'switch',
      'cowork',
      'route',
      'mode switcher',
      'モード',
      'ワーク',
      'コーディング',
      '切り替え',
      'ルート'
],
    tricks: [
      'モードスイッチャーはモードごとの最終ルートを記憶します — Coding に戻ると離れた同じワークスペースパスに着地します。',
      '折りたたんだサイドバーでもモードレールは出るので、ツリー全体を広げずに切り替えられます。',
      'Settings 中はモードスイッチャーが隠れます。再び切り替えるには Settings を離れます。',
      'Work は調査・ドキュメント・ブラウザ作業・捨てスクリプト向け; Coding は永続リポジトリ向け。',
      '権限モード、スラッシュ、大半の workbench ツールはモード横断; Overview / Graph / Changes / Review は Coding スコープです。',
      'Work で git モノレポを開き Changes/Review を期待しないでください — Coding に切り替えてソースコントロールを付けます。',
      '並列調査スレッドには Work フォルダ + share_context; リポジトリを紐づけたままにするなら Coding プロジェクト。',
      'モード記憶はウィンドウ単位ではなくモード単位 — 空白の Coding ホームを期待したなら、古いワークスペースルートが復元されていないか確認。'
],
    blocks: [
      {
        type: 'p',
        text: 'EvoFlux はサイドバーに 2 つのトップレベルモードを出します: Work（cowork サンドボックス）と Coding（リポジトリとプロジェクト）。各モードに独自のサイドバーツリーとセッション一覧がありますが、Lead/specialist チーム、composer、権限モデルは共通なので、ショートカットと Guidelines はどこでも通じます。',
      },
      {
        type: 'p',
        text: 'モード分離により、一般 cowork が git ワークスペースを汚さず、移行ガバナンス（承認、KB、パイプライン）が日常コーディングチャットに混ざりません。共有クロムがあるので、切り替えても権限・スラッシュ・workbench を学び直す必要はありません。',
      },
      {
        type: 'p',
        text: 'Work セッションはプライベート session folder、または選んだ別のローカルフォルダを使います。永続マルチレポプロジェクトは不要です。Coding は git リポジトリまたはマルチレポプロジェクトを開き、エージェントは Graph、git、worktree、PR Review 付きで実ツリーを編集します。',
      },
      {
        type: 'tips',
        items: [
          'Work — 調査、ドキュメント、ブラウザ作業、クイックスクリプト、フォルダ整理されたチャット。',
          'Coding — 単一レポ、マルチレポプロジェクト、worktree、Graph、Changes、Review。',
          'モード記憶 — 戻ったとき最終ルートが復元される。',
          'Settings — settings ルートを離れるまでモードスイッチャーは非表示。'
],
      },
      {
        type: 'tips',
        items: [
          '横断: Ctrl+B はすべてのモードで同じようにモードサイドバーをトグル。',
          '横断: Scheduler タスクは work または coding モードを明示 — タスク側で正しいモードを設定。',
          '横断: Skills と workflows は Settings でモードスコープ可能; Coding 専用 workflow は Work では隠れます。'
],
      },
      {
        type: 'p',
        text: 'モード切替の手順: (1) モードレールで Work / Coding をクリック、(2) サイドバーツリーが落ち着くのを待つ、(3) セッションを選ぶか作成、(4) プロンプト前に、そのモードで必要な workbench ツールが使えることを確認。',
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
    title: 'Lead と specialist',
    summary:
      'Lead がユーザー向けトランスクリプトを所有し、specialist は需要に応じて起動し共有 mailbox で並列に働きます。Agent / Split / Monitor 表示を切り替えつつ、コンテキスト予算バーを見て長い実行を回復可能に保ちます。',
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
      'エージェント',
      'リード',
      'スプリット',
      'チーム',
      '専門'
],
    setup:
      '任意のセッションを開きます。チームメンバー、モデル、ツールは Settings → Agents（work / coding スコープ）で設定。composer 上のセッション pill は、現在のチャットだけモデル・thinking レベル・fast mode を上書きします。',
    tricks: [
      'Ctrl+V はデスクトップで Agent ↔ Split を循環（フォーカス中フィールドがペーストを使う間は無効）。',
      'コマンドパレットの Next / Previous Agent は worker が活きているとき便利 — identity ドロップダウンを探すより速い。',
      'auto-split が有効だと specialist 起動時に Split が開き、表示メニューを探さずに作業を眺められます。',
      'Monitor 表示は多数の worker が生きているときのチーム横断アクティビティ概要です。',
      'workbench のコンテキスト予算バーはモデルの context_length と summary_trigger_tokens を使います — 上がったら早めに compact。',
      'モデル、スキル、ツール、権限は Settings → Agents でエージェントごとに設定。',
      'composer のセッション pill は現在チャットだけのモデル / thinking / fast mode。',
      '単純タスクは Lead に留め、並列が明らかに壁時計時間を短くするときだけ fan-out。',
      'Lead 専用ツール（ask_user、plan mode ヘルパー、一部 worktree ヘルパー）は specialist に付与されません — worker にプラン承認を期待しないでください。'
],
    blocks: [
      {
        type: 'p',
        text: '各セッションにユーザー向けトランスクリプトを所有する Lead エージェントがあります。複雑な仕事は目標と制約付きのサブタスクに分解され、specialist が需要に応じて起動し、共有 mailbox で結果を交換し、Lead が証拠を評価してからあなたに答えます。',
      },
      {
        type: 'p',
        text: '単純タスクを Lead に留めると不要な fan-out とトークン消費を避けられます。並列 specialist は調査・コーディング・移行・レビューの壁時計時間を縮め、mailbox が調整を構造化し、全 worker のダンプを 1 チャットに流し込みません。',
      },
      {
        type: 'p',
        text: '表示モード: Agent（1 エージェントに集中）、Split（Lead + worker を並べる）、Monitor（アクティビティ概要）。workbench の identity ドロップダウン、またはパレットの Next/Previous Agent で移動。デスクトップでは Ctrl+V が Agent ↔ Split。auto-split 有効時は specialist 起動で Split が自動で開くことがあります。',
      },
      {
        type: 'p',
        text: 'コンテキスト予算 — workbench ヘッダ付近のバーは、有効モデルのコンテキスト窓に対するトークン使用を反映します。summary trigger に近づいたら /compact するか新しいチャットを始めてください。ハード失敗の前に「エージェントが前のファイルを忘れた」ように見えることが多いです。',
      },
      {
        type: 'tips',
        items: [
          'Agent — 1 つのトランスクリプト（Lead または選択した specialist）に深く集中。',
          'Split — Lead と worker を並列ペインで監視。',
          'Monitor — 多数エージェントが活きているときの概要。',
          'チームは Settings → Agents で work / coding にスコープ。',
          'Mailbox — 構造化された specialist 結果; Lead があなた向けに合成。'
],
      },
      {
        type: 'p',
        text: 'マルチエージェントタスクの手順: (1) 成果と制約を Lead に述べる、(2) specialist を起動させる（または並列調査/コーディングを依頼）、(3) Split または Monitor で進捗を見る、(4) ask-user プロンプトに速やかに答える、(5) コンテキストバーが上がったら次の大きな添付ダンプ前に /compact または /new。',
      },
      {
        type: 'p',
        text: 'よくある失敗: specialist が同じファイルを要約している最中に巨大ログを Lead に貼る; composer フォーカス中に Ctrl+V と戦う（ペーストが勝つ）; Monitor に Coding Review PR が出ると期待する（別の workbench ツール）; Agent 表示で specialist を選んだまま「メッセージが無視される」と感じる — Lead に戻す。',
      },
      {
        type: 'tips',
        items: [
          'fan-out するとき — 複数ファイル調査、並列テスト/修正、specialist レーン。',
          'Lead のみに留めるとき — 短い Q&A、単一ファイル編集、権限に敏感な初回パス。',
          '横断: Split と Plan review を組み合わせ、worker がアイドル中にプランを読む。',
          '横断: チーム実行を止めずにメタ質問するなら /btw side chat。'
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
    title: '権限モードと Plan review',
    summary:
      'ask、accept-edits、plan、auto、bypass でツールの自由度を制御し、ツールを Once/Always/Reject で承認し、プランを Accept/Revise/Reject でレビューします。Sandbox の deny glob はすべてのモードの下でなお適用されます。',
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
      '権限',
      'プラン',
      '承認',
      'シールド'
],
    setup:
      'composer 上のシールド / 権限コントロールを開きます。メニューが開いている間はキー 1–5 が効きます。ファイルシステムが広いマシンで auto や bypass を有効にする前に Settings → Sandbox を見直してください。',
    tricks: [
      '権限メニューが開いているとき、キー 1–5 で ask → accept-edits → plan → auto → bypass にジャンプ。',
      'Ask はすべてのツール呼び出し前に一時停止; accept-edits はファイル編集を自動受理しつつシェルと破壊的操作は尋ねます。',
      'Plan モードは提案された編集/シェルを、Plan review パネルで Accept（または Revise / Reject）するまで記録します。',
      'レビューパネルでプラン文を選択すると、composer への revise メッセージに引用できます。',
      'ツール承認が必要なとき、権限バーで Once、Always、Reject を選びます。',
      'エージェントが続行前に構造化回答を必要とするとき ask-user 質問モーダルが出ます — 答えて実行を解放します。',
      'Goal モードはセッションの権限や sandbox スコープを広げません — `/goal` 前にシールドを意図的に設定。',
      'Bypass はすべての権限チェックをスキップ — 最速ですが、使い捨て環境または完全に信頼できるホストだけで使用。',
      'Always は一致ルールに対して粘着 — エージェントが何を走らせたいか学んでいる間は Once を優先。'
],
    blocks: [
      {
        type: 'p',
        text: '各セッションに PermissionMode（ask、accept-edits、plan、auto、bypass）があります。別途、個々のツール呼び出しは Once / Always / Reject を出し得ます。plan モードは Accept / Revise / Reject 付きの専用 Plan review パネルを出します。シールドをセッション既定、権限バーを呼び出し単位の上書きと考えてください。',
      },
      {
        type: 'p',
        text: 'きめ細かい制御により、ask、accept-edits、plan、auto、bypass を選べます。権限は「いつ聞くか」を決め、ファイルシステムツールは workspace と deny glob の検査を継続します。shell コマンドは denied path の best-effort 検査後にホスト上で直接実行されます。',
      },
      {
        type: 'p',
        text: 'composer のシールドコントロールを開き、モードを選ぶ（または 1–5）。plan モードでは Plan review パネルを待つ: Accept は実行、Revise は composer にフォーカス（任意で引用選択）、Reject はプラン停止。ツールプロンプトは Once（この呼び出し）、Always（一致ルールを記憶）、Reject。Ask-user モーダルは実行途中の構造化回答を集めます。',
      },
      {
        type: 'tips',
        items: [
          '1 Ask — すべてのツール呼び出し前に一時停止。',
          '2 Accept edits — ファイル編集は自動; シェル / 破壊的操作は確認。',
          '3 Plan — 実行前にプランして承認。',
          '4 Auto — 操作を自動承認。',
          '5 Bypass — 権限チェックを完全スキップ。',
          'ファイルシステムツール — bypass 下でも deny glob を適用。'
],
      },
      {
        type: 'p',
        text: 'どのモードをいつ使うか: 未知のレポや本番隣接ツリーは ask; ツリーを信頼した日常 Coding は accept-edits; 先に読みたい多段リファクタや大きな変更は plan; 信頼できるホストと予定メンテは auto; bypass は使い捨て環境での短い意図的バーストだけ。',
      },
      {
        type: 'p',
        text: 'よくある失敗: 一晩 bypass のまま; Always を「このエージェントを永遠に信頼」と混同（ルール一致）; 飛行中に plan モードを抜け、保留中プランが受理されたと仮定; ask-user モーダルを無視してチームがハングしたと思う; Goal が無人作業のために権限を緩めると期待。',
      },
      {
        type: 'tips',
        items: [
          '手順 — シールド → Plan (3) → タスク送信 → Plan review → Accept / Revise / Reject。',
          '手順 — ツールプロンプトでは、パターンが明らかに安全になるまで Once を優先。',
          '横断: plan と quote-into-composer で外科的な revise。',
          '横断: マルチレポプロジェクトで auto にする前に Sandbox を締める。'
],
      },
      {
        type: 'p',
        text: 'MCP ツールはネイティブツールと同じ権限ルールを継承します。MCP 呼び出しの Once/Always 承認は同じバー; sandbox とアウトバウンドポリシーも適用。ツールが「突然拒否」されたら、MCP を再設定する前にシールドと Settings → Sandbox を確認。',
      }
],
    related: ['slash-goal', 'sandbox-settings', 'plan-review', 'chat-team', 'agents-settings'],
  },
  {
    id: 'plan-review',
    category: 'chat',
    title: 'Plan review パネル',
    summary:
      'plan 権限モードでは、記録された編集やシェルが走る前にエージェントの markdown プランをレビューします。Accept は実行、Revise は任意引用付きで操縦、Reject は計画パスを中止し、多段作業の制御をあなたに残します。',
    keywords: [
      'plan review',
      'Accept',
      'Revise',
      'Reject',
      'quote',
      'plan mode',
      'markdown plan',
      'Accept & execute',
      'プランレビュー',
      '承認',
      '改訂',
      '拒否'
],
    setup:
      '権限モードを Plan（シールドメニューのキー 3）にし、多段作業が必要なタスクを送ります。Plan review パネルを見える状態に保ち — 保留中プランを Accept / Revise / Reject するまで権限モードを切り替えないでください。',
    tricks: [
      'プラン文書内のテキストを選んで revise メッセージに引用 — 「この節だけ変えて」と言う最速の方法です。',
      'Revise は composer にフォーカスを戻し、プラン全体を拒否せずに操縦できます。',
      'Reject は計画実行パスを止めます。そのプランターンからの半適用ステップを残さず、新しい指示を送れます。',
      '飛行中に plan モードを離れても保留中プランは自動 Accept されません — 促されたら先に Accept / Revise / Reject。',
      'Accept 後、実行中のツールプロンプトを締めたければ accept-edits や ask に落としてもよいです。',
      '大きな目標では Goal 前に plan モードを使い、最初の自律区間が承認済みアウトラインから始まるようにします。',
      'プランが曖昧なら Accept して祈るより、具体的な Definition of Done で Revise。',
      'Split 表示が便利: Plan review を開きつつ specialist 状態をちら見。',
      '引用 revise チップは気が変わったら送信前にクリア — トランスクリプト選択と同じ引用パイプラインです。'
],
    blocks: [
      {
        type: 'p',
        text: 'Plan review は plan 権限モード向けのゲート UI です。エージェントは markdown プランを起草し、編集とシェルは Accept & execute、Revise、または Reject するまで記録されたままです。その計画バッチは Accept まで走るべきではない — それがゲートの意味です。',
      },
      {
        type: 'p',
        text: '方向ミスのコストが高いときに使います: 複数ファイルリファクタ、共有モジュールに触る移行、破壊的シェル、ツール発火前に読めるアウトラインが欲しいタスク。一行修正や ask / accept-edits で十分な些細な Q&A ではスキップ。',
      },
      {
        type: 'p',
        text: 'レビューパネルでプランを上から下へ読む: 目標、手順、ファイル、リスク、検証。任意の節をハイライトし、revise 時に quote-into-composer。Accept は承認プランで続行; Reject はそのプランターンを中止。実行中のツールプロンプトを締めたければ受理後に ask や accept-edits と組み合わせ。',
      },
      {
        type: 'tips',
        items: [
          'Accept — 承認したプランパスを実行。',
          'Revise — composer にフォーカス; 任意の引用選択。',
          'Reject — このプランターンを中止; 新しい指示を送る。',
          'Quote — プラン文を選択 → 下書き上の revise チップ。',
          'Shield 3 — ツール開始後ではなく、タスク前に plan モードへ。'
],
      },
      {
        type: 'p',
        text: '手順: (1) シールド → Plan、(2) 成果と制約を記述、(3) Plan review パネルを待つ、(4) リスクとファイル一覧をざっと見る、(5) Accept、または弱い節を選択 → 引用 → 訂正付き Revise、または Reject して依頼を書き直す、(6) 任意で実行フェーズの権限モードを締める。',
      },
      {
        type: 'p',
        text: 'よくある失敗: 「十分長そう」だから未読プランを Accept; Revise のつもりで Reject（有用な構造を失う）; 「とりあえず走らせる」ために bypass へ切り替え監査跡を失う; Reject が以前のターンの成功したツール呼び出しを消すと仮定 — 止めるのはその計画実行パスだけ。',
      },
      {
        type: 'tips',
        items: [
          '良い revise プロンプトはファイル、テスト、スコープ外を明示。',
          '悪い revise は曖昧（「もっと良く」） — まず弱い箇条を引用。',
          '横断: 無関係なメタ質問は side chat へ送り、プランスレッドを清潔に。',
          '横断: Coding 作業で Accept 後、Changes（Ctrl+G）を開き diff がプランと一致するか確認。'
],
      },
      {
        type: 'p',
        text: 'Plan review を sandbox ポリシーの代わりにしないでください。美しいプランでも触ってほしくないパスを提案し得ます — Settings → Sandbox の deny glob を保ち、シークレット、vendor ディレクトリ、無関係なレポへスコープを広げるプランは Reject。',
      }
],
    related: ['permissions-modes', 'composer-power', 'attachments', 'slash-goal', 'coding-git'],
  },
  {
    id: 'composer-power',
    category: 'composer',
    title: 'Composer の強力機能',
    summary:
      '/、!、@、# スニペット、添付、引用選択、Work フォルダ指定、ネストスキル、RunInputsDialog 付きワークフローを使います。Undo は添付も復元するので、誤送信後も下書きを回復できます。',
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
      '入力',
      '添付',
      'スニペット',
      'メンション'
],
    setup:
      'composer にフォーカス（Ctrl+I）。セッションで添付が有効である必要があります。Work では WorkFolderSelector が composer 近くにあり session folder を付け替えます。Coding では # スニペットにワークスペースまたはグローバル定義が必要です。',
    tricks: [
      'メッセージを ! で始めるとシェルコマンドを実行（または /shell で bang モードを事前入力）。',
      '@ でアクティブワークスペースからランク付きファイル/フォルダパス参照を挿入。',
      'Coding では # でワークスペースまたはグローバルスニペットを composer に展開。',
      'ネストスキルは /skill:parent:child（ネスト名ではコロンとスラッシュは互換）。',
      'ワークフローは必須時に RunInputsDialog を開き、生のスラッシュ文をチャットとして送りません。',
      'Undo は前のユーザーメッセージとその添付を composer に復元。',
      '添付が有効なら画像/ファイルのペーストや composer へのドラッグ&ドロップ。',
      'トランスクリプト文を選択して Add to chat、詳細、または Send to side chat。',
      'ファイル全体を貼るより @ メンションを優先 — ランク付きパスがコンテキストを精密かつ安く保ちます。',
      '.evoflux/commands/ 下のカスタムコマンドは通常 textarea に挿入され、$ARGUMENTS を付け足せます。'
],
    blocks: [
      {
        type: 'p',
        text: 'composer は単なるテキストボックスではありません: スラッシュメニュー（/）、シェル bang（!）、パスメンション（@）、Coding スニペット（#）、ファイル添付、引用コンテキストチップ、Work セッション用 WorkFolderSelector、スキルディレクティブ、承認済みワークフロー。これらのアフォーダンスをマスターすることが、ツリーをプロンプトにダンプすることと精密に操縦することの差です。',
      },
      {
        type: 'p',
        text: 'これらの制御はモデルを洪水にせずコンテキストを精密に保ちます。Skills と workflows は反復手順をパッケージ化; 添付と引用は証拠をピン留め; WorkFolderSelector は Files ツールを開かずに session folder を付け替え。シェル bang は意図的コマンド用で、長い対話セッションが必要なときの Terminal の代替ではありません。',
      },
      {
        type: 'p',
        text: '/ でコマンドメニュー（組み込み、/skill: 下のスキル、ワークフロー、カスタム .evoflux/commands/）。! 接頭辞でシェル。@ でパス選択。Coding では # がスニペット展開。ファイルをバーへ DnD またはペースト。Work セッションでは composer 近くの WorkFolderSelector でプライベート session folder または別ローカルディレクトリを指定。/undo 後、テキストと添付の両方が下書きに戻ります。',
      },
      {
        type: 'tips',
        items: [
          '/ — スラッシュコマンド、スキル、ワークフロー、カスタムコマンド',
          '! — 行の残りをシェルモード',
          '@ — ファイル/フォルダメンション',
          '# — スニペット（Coding ワークスペース）',
          'DnD / ペースト — 有効時の添付',
          '引用選択 — Add to chat または Send to side chat',
          'WorkFolderSelector — Work session folder の付け替え',
          'RunInputsDialog — 起動前のワークフローパラメータ'
],
      },
      {
        type: 'p',
        text: '精密な Coding 依頼の手順: (1) 重要なファイルを @、(2) 必要なときだけスクショやログを添付、(3) 成果とテストを述べる、(4) 任意で既知手順の /skill:…、(5) 権限モードを設定、(6) 送信。Work 調査: WorkFolderSelector を設定、ソース添付、前の回答を引用、それから依頼。',
      },
      {
        type: 'p',
        text: 'よくある失敗: 生の `/workflow name` テキストを送って動くと期待（ワークフローはメニュー/ダイアログ経由）; スペースでネストスキル（`:` / `/` を使う）; Work で # を使い Coding スニペットを期待; Providers 設定ではなく composer にシークレットを貼る; /undo が添付も復元することを忘れ、機微ファイルを不用意に再送。',
      },
      {
        type: 'tips',
        items: [
          '! を使うとき — チャットターンに紐づく短いワンライナー。',
          'Terminal（Ctrl+`）を使うとき — 対話的または長時間プロセス。',
          '@ を使うとき — 既知パス; まだ探索中なら Files ツールで閲覧。',
          '横断: 引用 → Send to side chat で Goal を止めずに /btw。'
],
      },
      {
        type: 'p',
        text: 'ワークフローは承認済みでセッションスコープ（work / coding）に有効でなければ隠れます。Skills は Settings → Skills で検証後にのみ /skill: 下に出ます。コマンドが欠ける場合は、スラッシュバグと決める前にスコープと検証を確認。',
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
    title: '添付、ペースト、引用',
    summary:
      'ドラッグ&ドロップやペーストでファイルを添付し、トランスクリプトやプラン選択を次のメッセージに引用し、/undo で下書きと一緒に添付を復元します。引用とファイルは、手でコンテキストを書き直さずに証拠をピン留めする手段です。',
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
      '添付',
      'ペースト',
      '引用',
      'クリップボード',
      'チップ'
],
    setup:
      'セッション/composer で添付が有効である必要があります。ポリシーでアップロードが無効な環境もあります。ドラッグ&ドロップに頼る前に composer のドロップターゲットがハイライトされることを確認。引用はトランスクリプト選択、Plan review、Send to side chat から使えます。',
    tricks: [
      'クリップボードからペースト（画像/ファイル）するか composer ドロップターゲットへドラッグ — どちらも次のユーザーメッセージにバインド。',
      '引用コンテキストは下書き上のチップとして出ます — 送信前に気が変わったらクリア。',
      'Plan review の引用 → composer はトランスクリプト選択と同じ引用パイプライン。',
      '/undo は取り消したユーザーメッセージの一部だった添付を復元 — テキストとファイルが一緒に戻る。',
      'Send to side chat はメイン実行を中断せず引用を /btw に運びます。',
      '前のアシスタント長文を再貼りするより、短い引用 + 短い依頼を優先。',
      '画像は UI やエラーダイアログのバグに有効; スタックトレースはテキスト貼付または .log 添付の方がトークンを正確にコピーできます。',
      '話題を変える前に古い引用チップをクリア — 残った引用は次ターンを静かにバイアスします。',
      'ペーストが「何もしない」ように見えるときは、フォーカスが composer にあり、セッションで添付が有効か確認。'
],
    blocks: [
      {
        type: 'p',
        text: '添付はユーザーメッセージにバインドされたファイル（多くは画像も含む）です。引用はトランスクリプト、プランパネル、または side-chat ターゲットから選んだテキストで、次の送信のコンテキストになります。合わせて、毎ターン UI 状態やエラーブロックを再説明せずに証拠をピン留めできます。',
      },
      {
        type: 'p',
        text: 'バイトが重要なとき添付を使います: スクショ、PDF、CSV、小さなログ、デザイン書き出し。テキストがすでにトランスクリプトやプランにあり、外科的フォローアップが欲しいときは引用。リポジトリ全体の添付は避け — @ メンション、Files、または Coding graph ツールを使います。',
      },
      {
        type: 'p',
        text: 'ファイルを composer にドロップまたはペースト。トランスクリプトで Add to chat / 詳細 / Send to side chat。Plan review ではプラン文を選んで revise メッセージに引用。undo 後、復元下書き（ファイル含む）を再送または編集。送信前に下書き上の引用チップを確認。',
      },
      {
        type: 'tips',
        items: [
          'ドラッグ&ドロップ — composer ドロップターゲットへファイル',
          'ペースト — フォーカス中 composer へクリップボード画像/ファイル',
          'Add to chat — トランスクリプトをメイン下書きに引用',
          'Send to side chat — /btw 並列依頼へ引用',
          'Plan quote — プラン markdown を選択 → revise チップ',
          '/undo — 前のユーザーテキスト + 添付を復元',
          'チップクリア — 話題が変わったら送信前に引用を削除'
],
      },
      {
        type: 'p',
        text: 'バグレポートの手順: (1) 再現してスクショを撮る、(2) composer にペーストまたはドロップ、(3) 失敗したアシスタント手順やエラー行があれば引用、(4) 期待 vs 実際を述べる、(5) 多数ファイルに触る修正なら ask または plan で送信。',
      },
      {
        type: 'p',
        text: 'よくある失敗: 「コンテキストのためだけ」にシークレット（.env、キーファイル）を添付; コンテキスト予算が跳ねるまで大きなバイナリを 5 つ積む; エージェントがすでに改訂した古いプラン節を引用; side-chat 引用が親履歴にマージされると仮定（しません）。',
      },
      {
        type: 'tips',
        items: [
          '添付しないとき — 巨大ビルド成果物、node_modules zip、フル DB ダンプ。',
          '引用するとき — 1 段落への異議、1 プラン箇条の改訂、「これを説明して」。',
          '横断: /undo 後、再送前に復元添付を確認。',
          '横断: WorkFolderSelector はフォルダを添付せず、セッションルートを付け替えます。'
],
      },
      {
        type: 'p',
        text: 'ポリシー注記: 組織がアップロードを無効にしても、引用と @ メンションは使えます。添付ゲートと戦うよりそれらを優先。Settings → Sandbox のアウトバウンド PII リダクションは、コンテンツがプロバイダへ向かうときなお適用され得ます。',
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
    title: '組み込みスラッシュコマンド',
    summary:
      'composer で / を打ち、stop、compact、undo、init、btw、goal、スキル、ワークフロー、`.evoflux/commands/` のカスタムコマンドを使います。組み込みは即実行; カスタムは通常挿入され引数を仕上げられます。',
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
      'スラッシュ',
      'コマンド',
      'スキル',
      'ワークフロー'
],
    tricks: [
      '組み込みは選択で即実行; カスタムは通常 textarea に挿入され $ARGUMENTS を付け足せます。',
      '最長プレフィックス一致; ネストしたコマンド/スキル名では : と / は互換。',
      'カスタムコマンドはプロジェクトまたはグローバルの .evoflux/commands/（および互換 OpenCode パス）に置きます。',
      'Skills は Settings → Skills で検証後にのみ /skill: 下に出ます。',
      'ワークフローはセッションスコープ（work / coding）で承認・有効でなければ隠れます。',
      'コンテキスト予算バーが上がったら早めに /compact — 失敗待ちはターンを無駄にします。',
      '/init は AGENTS.md 向けの Coding 志向; AGENTS.md 向けです。',
      '/stop は runaway specialist fan-out のパニックボタン; 次の明確な指示と組み合わせ。',
      '長い実行中のメタ質問でメイントランスクリプトを汚すより /btw を優先。'
],
    blocks: [
      {
        type: 'p',
        text: 'スラッシュコマンドは一級の composer アクションです。組み込みはチーム実行を制御; goal サブコマンドは永続目標を管理; スキルとワークフローは構造化挙動を付与; ユーザー定義の Markdown/YAML コマンドはサーバー側で展開。メニューは検索可能 — 数文字打てば絞り込めます。',
      },
      {
        type: 'p',
        text: 'スラッシュは高頻度アクションをメニュー探しなしで発見しやすくし、`.evoflux/commands/` 経由でリポジトリがチーム慣例を同梱できます。カスタムコマンドは共有ランブックとして扱い、シークレットを隠す場所にしないでください。',
      },
      {
        type: 'slash',
        commands: [
          { cmd: '/stop', desc: '稼働中のエージェントをすべて即停止' },
          { cmd: '/continue', desc: '直前のアシスタント応答を続行' },
          { cmd: '/compact', desc: 'このセッションのコンテキストを要約・圧縮' },
          { cmd: '/shell', desc: 'シェルモード（! コマンド）を事前入力' },
          { cmd: '/undo', desc: '直前のユーザーメッセージを取り消し（テキスト + 添付を復元）' },
          { cmd: '/redo', desc: '取り消したメッセージをライブ先端へ戻す' },
          { cmd: '/new', desc: '新しいチーム会話を開始' },
          { cmd: '/init', desc: 'AGENTS.md を作成または更新（Coding ワークスペース）' },
          { cmd: '/btw', desc: 'このセッションへの読み取り専用アクセス付き side chat を開く' },
          { cmd: '/goal <objective>', desc: '永続的な自律 Goal を開始' },
          { cmd: '/goal', desc: 'アクティブな Goal ステータスを確認' },
          { cmd: '/goal:budget <tokens|none>', desc: 'Goal のトークン予算を設定またはクリア' },
          { cmd: '/goal:pause', desc: 'アクティブな Goal を一時停止' },
          { cmd: '/goal:resume', desc: '一時停止中の Goal を再開' },
          { cmd: '/goal:stop', desc: 'セッションの Goal を削除' },
          { cmd: '/skill:…', desc: '次のメッセージにスキルを付与（ネスト: /skill:parent:child）' },
          { cmd: '/workflow <name>', desc: '承認済みワークフローを実行（RunInputsDialog が開く場合あり）' }
],
      },
      {
        type: 'p',
        text: '/ でコマンドを絞り込み。組み込みを選ぶと実行、カスタム/スキル/ワークフローは挿入または起動。カスタムファイルはプロジェクトまたはグローバル EvoFlux 設定の `.evoflux/commands/` に置きます。ネスト名は最長プレフィックス優先; 区切りは `:` または `/`。ワークフローは RunInputsDialog を開くことがあり、生のスラッシュ行を通常チャットとしては送りません。',
      },
      {
        type: 'tips',
        items: [
          '組み込み — 選択で実行',
          'カスタム — 通常は挿入; $ARGUMENTS を付け足す',
          'Skill — Settings → Skills 検証後の /skill:',
          'Workflow — スコープ + 承認が必要、さもなくば非表示',
          '最長プレフィックス — : または / での parent:child ネスト'
],
      },
      {
        type: 'p',
        text: 'カスタムコマンドの手順: (1) `.evoflux/commands/` に Markdown/YAML コマンドを追加、(2) スラッシュメニューを再読込または開き直し、(3) コマンドを選んで挿入、(4) 引数を埋める、(5) 送信。必要なカスタムコマンドだけ追加 — 未使用プロンプトがメニューに出ないのは意図的です。',
      },
      {
        type: 'p',
        text: 'よくある失敗: `/scheduler` でページが開くと期待（Ctrl+S を使う — ルートはホームへリダイレクト）; スコープ/承認が悪いのに欠けたワークフローを composer バグ扱い; /compact が遅すぎてまだ必要な制約が要約で落ちる; /undo が git コミットを戻すと思い込む — 戻すのは前のユーザーメッセージ下書きだけ。',
      },
      {
        type: 'tips',
        items: [
          '/new するとき — 汚染されたコンテキストバーでの話題変更。',
          '/compact するとき — 同じ話題、予算上昇、連続性を保つ。',
          '/stop するとき — runaway ツールや誤った fan-out; その後依頼を言い直す。',
          '横断: 新しいレポを開いたあと /init + Coding Overview。'
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
    title: '永続 Goal モード',
    summary:
      '再接続をまたいで生き残る自律目標を、任意のトークン予算、pause/resume/stop、blocker streak 付きで実行します — 権限や sandbox スコープは広げません。Goal はウィンドウを閉じたあとも続けたい作業向けです。',
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
      'ゴール',
      '予算',
      '一時停止',
      '再開',
      'ブロッカー'
],
    setup:
      '任意のモードで `/goal <objective>` から開始。任意: 実行前または実行中に `/goal:budget <tokens>`。権限モードと Settings → Sandbox を先に意図的に設定 — Goal はそれらを広げません。',
    tricks: [
      'ステータス確認は /goal のみ; 予算変更/クリアは /goal:budget <tokens|none>。',
      '一時停止 / 再開 / 停止は /goal:pause、/goal:resume、/goal:stop。',
      '同じ具体的ブロッカーが 3 ターン連続で報告されると進捗が止まります; UI に blocker streak が出ます。',
      'Goal 状態、経過時間、トークン使用はアプリ再起動と再接続を生き残ります。',
      '隠れた内部ターンは完了、予算一時停止、ユーザー pause/stop、または blocker streak まで続きます。',
      'Goal は権限モードや sandbox スコープを広げません — 開始前に意図的に設定。',
      '無人の一晩実行には明確な目標とトークン予算を優先。',
      '大きな Goal ではまず plan モードで起草し Accept してから `/goal` — 自律が承認済みアウトラインから始まります。',
      'Goal 実行中のメタ質問は /btw — 目標トランスクリプトを脱線させない。'
],
    blocks: [
      {
        type: 'p',
        text: 'Goal モードはセッションに永続的な自律目標を付けます。Lead は目標が完了記録されるか、予算が実行を一時停止するか、あなたが pause/stop するか、blocker streak が発火するまで内部ターンで働き続けます。ウィンドウを閉じても目標を忘れるべきではありません。',
      },
      {
        type: 'p',
        text: '通常チャットはウィンドウを閉じるかターンが終わると止まります。Goal は再接続後も各ステップを再プロンプトせず再開すべき長い目標（「モジュール X を移行」「リファクタチェックリストを完了」）向けです。安全性を bypass する許可証ではありません。',
      },
      {
        type: 'p',
        text: '`/goal ship the login refactor with tests` で開始。`/goal` でステータス。`/goal:budget 200000` でトークン上限; `/goal:budget none` でクリア。`/goal:pause` / `/goal:resume` / `/goal:stop` でライフサイクル制御。Goal UI で経過時間、トークン、blocker streak を監視。権限と sandbox はセッション設定どおりのままです。',
      },
      {
        type: 'slash',
        commands: [
          { cmd: '/goal <objective>', desc: '永続的な自律作業を開始' },
          { cmd: '/goal', desc: 'Goal ステータスを表示' },
          { cmd: '/goal:budget <tokens|none>', desc: 'トークン予算を設定またはクリア' },
          { cmd: '/goal:pause', desc: '実行を一時停止' },
          { cmd: '/goal:resume', desc: '一時停止または予算ホールド後に再開' },
          { cmd: '/goal:stop', desc: 'セッションの Goal をクリア' }
],
      },
      {
        type: 'tips',
        items: [
          '目標には Definition of Done とスコープ外リストを書く。',
          '一晩実行の前にトークン予算を設定。',
          'blocker streak を監視 — 同じブロッカー ×3 で進捗停止。',
          'Goal が ask → bypass に切り替えてくれると期待しない。',
          '同じツリーで大きな手動編集の前に /goal:pause。'
],
      },
      {
        type: 'p',
        text: '使うとき: 数時間の Coding リファクタ、チェックリスト駆動の雑務、睡眠後も続く調査。使わないとき: 対話的な設計議論、ワンショット Q&A、毎分人間の味付けが必要なもの — 通常チャットまたは plan review に留まる。',
      },
      {
        type: 'p',
        text: 'よくある失敗: 広いホームディレクトリ上で bypass のまま Goal 開始; 予算を省略して高額請求で起きる; blocker streak を無視して同じ詰まりを再プロンプト; /goal:stop ではなく /stop（レイヤが違う）; 無関係な目標を 1 行の `/goal` に詰め込む。',
      },
      {
        type: 'tips',
        items: [
          '手順 — シールド + sandbox → 任意の plan Accept → /goal:budget → /goal <objective>。',
          '手順 — 詰まったら → ブロッカーを読む → /goal:pause → 環境を直す → /goal:resume。',
          '横断: Scheduler は cron プロンプト; Goal はセッション内自律。',
          '横断: Dream cron は Settings → Memory 下で別物。'
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
    title: 'セッション、ピン、Work フォルダ',
    summary:
      '重要なチャットをピンし、Work セッションをドラッグ&ドロップでフォルダ整理し、兄弟ダイジェスト用に share_context をトグルし、会話を消さずにフォルダを削除します。ファイリングは整理であり、履歴やモデル設定を書き換えません。',
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
      'フォルダ',
      'ピン',
      'セッション',
      '共有',
      '整理'
],
    setup:
      'Work モードのサイドバー → Folders セクション。Coding は独自のセッションツリー; フォルダファイリングは Work の整理機能です。外部変更後は Ctrl+R で Work セッション一覧を更新。',
    tricks: [
      'セッション行をフォルダヘッダへドラッグ（デスクトップ）、またはタッチでは Move to folder…。',
      'フォルダのリンクアイコンで share_context をトグル — 兄弟は互いの有界ダイジェストを受け取ります。',
      'Folder + はそのフォルダにすでにファイリングされた新チャットを作成。',
      'フォルダ削除はセッションをアンファイルするだけ; 会話はフォルダと一緒に消えません。',
      'Ctrl+R で Work サイドバーのセッション一覧を更新。',
      'セッションをピンすると Today / Yesterday / Older の上に残ります。',
      'ファイリングは folder_id を設定するだけ — 履歴、モデル、ワークスペース設定はセッションに残ります。',
      '兄弟へダイジェストしてはいけない機微なクライアントフォルダでは share_context をオフ。',
      'フォルダ名は日付ではなく成果で（「RFP 調査」「incident 4821」）— 日付は未ファイリングチャットをすでにグループ化します。',
      '兄弟に属さなくなったスレッドは Move to folder… → none でアンファイル。'
],
    blocks: [
      {
        type: 'p',
        text: 'Work セッションはピンし、名前付きフォルダへファイリングできます。フォルダは任意で share_context を有効にし、兄弟チャットが有界ダイジェストを交換します。未ファイリングはなお Pinned / Today / Yesterday / Older でグループ化。と Coding は独自ツリー — そこに Work フォルダを探さないでください。',
      },
      {
        type: 'p',
        text: '長時間 cowork はチャットが増えます。フォルダは各セッション自身の履歴とモデル設定を断片化せず、調査スレッド、クライアント作業、実験を分けます。ピンは毎日開く少数のチャットが Today の下に沈むのを防ぎます。',
      },
      {
        type: 'p',
        text: 'Work サイドバーでフォルダを作成。セッションをフォルダヘッダへドラッグ、またはセッションメニュー → Move to folder…。リンクアイコンで share_context をトグル。フォルダの + でそこにファイリング済みの新チャット。フォルダ削除でアンファイル; 会話自体を消すときだけセッション削除アクションを使う。',
      },
      {
        type: 'tips',
        items: [
          'Pin — 重要なセッションを上部に保持。',
          'share_context — 有界の兄弟ダイジェスト（リンクアイコン）。',
          'Folder + — 事前ファイリングされた新チャット。',
          'フォルダ削除 — アンファイルのみ; チャットは残る。',
          'Ctrl+R — Work セッション一覧を更新。',
          'Move to folder… — タッチ向けファイリング / アンファイリング。',
          'Today / Yesterday / Older — 未ファイリングの自動グループ。'
],
      },
      {
        type: 'p',
        text: 'Work でのプロジェクトセットアップ手順: (1) 案件名のフォルダを作成、(2) 兄弟ダイジェストが役立つときだけ share_context を有効、(3) メインスレッド用に Folder +、(4) 並列調査用に兄弟チャットを生やす、(5) 意思決定ログチャットをピン、(6) 後でフォルダ削除して履歴を失わずアンファイル。',
      },
      {
        type: 'p',
        text: 'share_context を使うとき: 同じ調査質問への並列角度で、ダイジェストが重複作業を防ぐ場合。使わないとき: 規制クライアントデータ、人事トピック、近隣チャットへ要約を漏らしてはいけないもの — リンクアイコンをオフのまま。',
      },
      {
        type: 'p',
        text: 'よくある失敗: フォルダ削除でチャットが消えると期待; ファイリングが WorkFolderSelector のファイルシステムパスをコピーすると仮定; モバイルで Move to folder… を使わずドラッグ; Coding セッションが Work フォルダ下に出ると期待; フォルダ用途が機微作業に変わったあとも share_context をオンのまま。',
      },
      {
        type: 'tips',
        items: [
          '横断: WorkFolderSelector はツール用オンディスクフォルダ; サイドバーフォルダはチャット整理。',
          '横断: 長い案件では意思決定チャットにピン + Goal。',
          '横断: Folder + から始めた場合、フォルダ内の /new はファイリングを維持。',
          '移動したセッションが期待どおり出ないときは Ctrl+R で更新。'
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
    title: 'Workbench ツール',
    summary:
      'Terminal、Browser、Files、Graph、Side chat、Memory、Scheduler、Changes、Review をチャット横で開きます。ショートカットは OS に合わせ、macOS は Command、Windows/Linux は Ctrl を使います。',
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
      'ワークベンチ',
      'パネル',
      'ターミナル',
      'ファイル'
],
    setup:
      'まずセッションを開きます。Coding Overview、Graph、Changes、Review には Coding ワークスペースが必要。内蔵 Browser は Settings → Browser で有効にしてから Ctrl+T が役立ちます。',
    tricks: [
      'workbench バー、ドック、または下記ショートカットからツールを開きます。',
      'Coding Overview はワークスペース選択時のみ表示。',
      'ランタイムショートカットとラベルは OS に合わせ、macOS は Command、Windows/Linux は Ctrl。',
      '実マッピング: Files = Ctrl+F（ラベルは ⌘P の場合あり）; Side chat = Ctrl+;（ラベルは ⌥⌘S の場合あり）。',
      'Graph と Review に専用グローバルショートカットはありません — workbench バーまたはコマンドパレット。',
      'Terminal と Browser は複数タブインスタンス対応; 他ツールは単一インスタンスのトグル。',
      'Changes（Ctrl+G）と Review は Coding のみ; Graph には Coding ワークスペースが必要。',
      '同じツールをもう一度トグルで閉じる — workbench は常設カードの山ではありません。',
      'Coding ワークスペースあり・ツール未選択で workbench を開くと、既定で Overview が開きます。'
],
    blocks: [
      {
        type: 'p',
        text: 'Workbench はチャット横の右（またはドック）ツール面です。ツール: Overview、Terminal、Browser、Files、Graph、Side chat、Memory（wiki）、Scheduler、Changes（ソースコントロール）、Review（pull/merge requests）。チャットが主; ツールはワンショートカット先の検査とアクション面です。',
      },
      {
        type: 'p',
        text: 'エージェントはファイル、diff、ブラウザ手順、スケジュールを生み、セッションを離れずに検査が必要です。Workbench はそれらの面を近くに保ち、検証ごとに 5 つの別アプリへ alt-tab しないで済みます。',
      },
      {
        type: 'shortcuts',
        rows: [
          { keys: 'Ctrl+`', action: 'Terminal' },
          { keys: 'Ctrl+T', action: '内蔵ブラウザ' },
          { keys: 'Ctrl+F', action: 'Files / Changed & Files（ラベルは ⌘P の場合あり）' },
          { keys: 'Ctrl+;', action: 'Side chat（ラベルは ⌥⌘S の場合あり）' },
          { keys: 'Ctrl+M', action: 'Memory（wiki）' },
          { keys: 'Ctrl+S', action: 'Scheduler' },
          { keys: 'Ctrl+K', action: 'Plugins' },
          { keys: 'Ctrl+G', action: 'Git Changes（Coding）' }
],
      },
      {
        type: 'tips',
        items: [
          'Overview — Coding ワークスペース / git / セッション / ツール状態の一覧。',
          'Terminal — アクティブワークスペースでコマンド実行。',
          'Browser — アプリ内ブラウザ（Settings → Browser で有効化）。',
          'Files — ワークスペースファイルと生成成果物。',
          'Graph — 構造コードグラフ（Coding）。',
          'Side chat — /btw 並列質問。',
          'Memory — wiki + 保留メモ。',
          'Scheduler — cron / ワンショットタスク（パネルのみ; /scheduler はホームへリダイレクト）。',
          'Changes — stage、commit、ブランチ操作（Coding）。',
          'Review — 接続ホストの PR/MR 一覧（Coding）。'
],
      },
      {
        type: 'p',
        text: 'workbench バーのツールをクリックするかショートカットを押します。同じツールをもう一度で閉じます。どのツールがアクションを持つか忘れたらコマンドパレット（Ctrl+P）を優先。内蔵 Browser（Ctrl+T）と実 Chrome/Edge 向け WebBridge ペアリングを混同しないでください。',
      },
      {
        type: 'p',
        text: 'よくある失敗: Work モードで Review を探す; フォーカスされた Coding ワークスペースなしで Graph を期待; `/scheduler` をブックマーク; Files に ⌘P ラベルを信じる; composer の ! 向きのワンライナーに Terminal タブを 10 個開く。',
      },
      {
        type: 'tips',
        items: [
          'Terminal vs ! — 対話/長時間 vs 短いチャット紐づきコマンド。',
          'Files vs @ — 閲覧/探索 vs 既知パスを依頼にピン留め。',
          '横断: plan モード Accept 後に Changes で diff を検証。',
          '横断: 調査セッション後に Memory を開き Dream の材料を残す。'
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
    title: 'Side chat（/btw）',
    summary:
      'メインセッションへの読み取り専用アクセス付きで、アクティブ実行を中断せず履歴を戻しマージせずに、焦点を絞った質問をします。Side chat は確認、制約チェック、脇道探索向けの「ちなみに」レーンです。',
    keywords: [
      'side chat',
      'btw',
      '/btw',
      'parallel',
      'Ctrl+;',
      'Send to side chat',
      'read-only',
      'サイドチャット',
      'ちなみに',
      '並列',
      '読み取り専用'
],
    setup:
      '/btw、Ctrl+;、workbench の Side chat ツール、またはセッション行アイコンで開きます。任意でトランスクリプト文を選択 → Send to side chat で引用を運ぶ。ラベルがなお ⌥⌘S でも実ショートカットは Ctrl+;。',
    tricks: [
      '/btw、Ctrl+;、workbench Side chat、またはセッション行アイコンで開く。',
      '引用選択 → Send to side chat で、段落を打ち直さずにタイトなフォローアップ。',
      'Side chat の履歴は親セッションへマージされません — Lead が見る必要がある結論は手動で貼る。',
      'Goal や長い specialist 実行がメインで続く間に、side chat で確認する。',
      'Side chat のショートカットは macOS で ⌘+;、Windows/Linux で Ctrl+;。',
      'Side chat は短く事実ベースに; 長い実装作業は Lead スレッドへ戻す。',
      '終わったらパネルを閉じ、次のメイン指示を誤って /btw に打たない。',
      'Side chat は親コンテキストを読み取り専用で見る — レポ全体リファクタの主エディタにしない。',
      '独自ツール付きの永続並列スレッドが必要なら、/btw を過負荷にするより兄弟 Work セッション（任意で share_context）を優先。'
],
    blocks: [
      {
        type: 'p',
        text: 'Side chat は親セッションコンテキストへの読み取り専用アクセス付きの並列 composer です。「ちなみに」質問、制約の明確化、メイントランスクリプトを汚さずにアイデア探索に最適です。履歴が別なのは意図的です。',
      },
      {
        type: 'p',
        text: '長い Lead/specialist 実行をメタ質問で中断すると、ぎこちない stop/continue が必要になります。Side chat はセッション認識を保ちつつメインを清潔に保ちます。Goal モードでは特に有用 — 詳細を健全性チェックする間も自律が続きます。',
      },
      {
        type: 'p',
        text: '/btw、Ctrl+;、workbench から Side chat、またはセッション行アイコン。任意で Send to side chat によりトランスクリプトを引用。質問し、終わったらパネルを閉じる。答えがメイン実行を操縦すべきなら、自分で Lead composer（またはプランの Revise）に要約を戻す。',
      },
      {
        type: 'tips',
        items: [
          '/btw — composer スラッシュメニューから開く',
          'Ctrl+; — Side chat workbench ツールをトグル',
          'Send to side chat — 選択を /btw へ引用',
          '読み取り専用の親コンテキスト — 履歴の戻しマージなし',
          'セッション行アイコン — スラッシュメニューなしで開く',
          '⌥⌘S ラベル — 無視; 実バインディングは Ctrl+;'
],
      },
      {
        type: 'p',
        text: '長い Coding 実行中の手順: (1) 混乱したアシスタント段落を選択、(2) Send to side chat、(3)「これは X と Y のどちらを主張？」と聞く、(4) Y が誤りならメイン composer に訂正指示または plan revise、(5) Side chat を閉じる。',
      },
      {
        type: 'p',
        text: '使うとき: 用語の明確化、制約確認、ツール結果の短い説明、捨てるかもしれない代替案のブレインストーム。使わないとき: 主実装作業、重要ファイルの唯一コピーの添付、メインセッション履歴内で監査可能でなければならないもの。',
      },
      {
        type: 'p',
        text: 'よくある失敗: 次の「実装して…」を side chat に打って Lead が動かないと不思議がる; side chat が親のプラン承認や ask-user モーダルに答えると期待; Ctrl+; を開いたままどの composer にフォーカスしているか見失う; 引用が双方向に自動同期すると仮定。',
      },
      {
        type: 'tips',
        items: [
          '横断: Plan review 引用と組み合わせ、「この箇条を説明」を Reject せずに。',
          '横断: 重い並列調査は Work 兄弟チャット + share_context。',
          '横断: /stop はなおメインチーム向け — side chat は第二の Lead ではない。',
          'side chat に必要なツールがないなら、おそらく /btw の用途を超えている。'
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
    title: 'Coding ワークスペース、プロジェクト、worktree',
    summary:
      'リポジトリを開き、マルチレポプロジェクトにまとめ、管理 worktree を作り、AGENTS.md に /init を使います。リポジトリクリックはフォーカスであり、チャット開始ではありません — トランスクリプトが欲しければ + / New chat。',
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
      'ワークスペース',
      'プロジェクト',
      'ワークツリー',
      'リポジトリ'
],
    setup:
      'Coding（`/coding`）に切り替え、リポジトリを追加するかプロジェクトを作成。worktree 配置は Settings → Sandbox（repository vs user_data）。慣例を AGENTS.md に置くタイミングでセッション内 /init。',
    tricks: [
      'リポジトリクリックはフォーカス — チャットは始まらない。Repos の +（または New chat）でセッション作成。',
      'プロジェクトは複数リポジトリを 1 つの project_id 下に束ね; graph ツールはクロスレポリンクを自動解決。',
      'Worktree 配置は Settings → Sandbox（repository vs user_data）で制御。',
      '未コミットのソース変更は新しい worktree にコピーされません。',
      '管理 worktree はサイドバーツリーでソースレポの下にネスト。',
      'スタンドアロンレポはプロジェクトなしの有効な単一ワークスペースセッションのまま。',
      'Coding セッションで /init を実行し、エージェント慣例用 AGENTS.md を作成または更新。',
      'ワークスペース選択時に workbench から Coding Overview を開き状態を一覧。',
      '汚れた変更が別の場所でも必要なら worktree 作成前に commit または stash — 新しいツリーには現れません。',
      'サービスがレポ横断で API を共有するならプロジェクト; 変更セットがローカルなら単一レポを優先。'
],
    blocks: [
      {
        type: 'p',
        text: 'Coding モードは git リポジトリ、任意のマルチレポプロジェクト、管理 worktree を扱います。エージェントは Files、Graph、Terminal、Changes、Review をチャット横で使い実ツリーを編集します。永続エンジニアリング作業向けのモードです。',
      },
      {
        type: 'p',
        text: '永続レポは Work の一時フォルダとは異なる UX が必要です: フォーカス vs 新チャット、プロジェクトグループ、sandbox worktree 配置、チーム向け AGENTS.md 慣例。Coding を Work のように扱うのが最も多いオンボーディング混乱です。',
      },
      {
        type: 'p',
        text: 'Coding サイドバーからレポを追加。クリックでフォーカス; + / New chat でセッション。Project を作り複数レポをバインド。レポメニューから worktree を生成; Settings → Sandbox で repository-local vs user_data。/init で AGENTS.md を足場または更新。ワークスペースがアクティブになると Graph と Overview が有効。',
      },
      {
        type: 'tips',
        items: [
          'Focus ≠ chat — クリックは選択; + が作成。',
          'Projects — 1 つの project_id 下のマルチレポ。',
          'Worktrees — クリーンツリー; 未コミットソースはコピーされない。',
          '/init — Coding 慣例用 AGENTS.md。',
          'Sandbox — worktree 配置ポリシー。',
          'Overview — ワークスペースフォーカス後の状態。'
],
      },
      {
        type: 'p',
        text: '最初の Coding セッション手順: (1) Coding へ切り替え、(2) git レポを追加、(3) クリックでフォーカス、(4) + / New chat、(5) AGENTS.md がなければ /init、(6) 権限モード設定、(7) 主要ファイルを @ して変更を記述、(8) Overview でワークスペース健全性を確認。',
      },
      {
        type: 'p',
        text: 'Worktrees: 主チェックアウトを汚さず並列ブランチ/エージェントに使います。新しい worktree はソースコミット状態に対してクリーンに始まることを忘れない — 未コミット編集は後ろに残ります。サイドバーでソースレポ下にネストされると家族関係が見えます。',
      },
      {
        type: 'p',
        text: 'よくある失敗: レポをクリックして始まらないチャットを待つ; 汚れた作業をソースツリーだけに置き、それを欠く worktree を開く; /init を飛ばしてエージェントがレポ慣例を無視すると不思議がる; 単一サブモジュールパスで足りるのにマルチレポプロジェクトを作る; 意図せず user_data 経由で遅いネットワークドライブに worktree を置く。',
      },
      {
        type: 'tips',
        items: [
          'プロジェクトするとき — クロスレポ型、共有契約、マルチサービス変更。',
          'プロジェクトしないとき — めったに触らない vendored 付きの 1 アプリレポ。',
          '横断: graph のクロスレポ解決には project_id が必要。',
          '横断: Review/Changes はフォーカスされたワークスペースに付く。'
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
    title: 'Git、Changes、プルリクエスト',
    summary:
      'Coding の Changes（Ctrl+G）、Review パネル、Settings → Git & reviews から stage、commit、branch、merge、rebase、stash、PR/MR レビューを行います。force-with-lease や巨大 diff の前に安全トグルを意図的に。',
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
      'ギット',
      'プルリクエスト',
      'コミット',
      'ブランチ'
],
    setup:
      'git ワークスペース付き Coding モード。リモート PR/MR 操作は Settings → Git & reviews でホスト接続。積極的操作の前にタイムアウト、max diff size、force-with-lease を確認。',
    tricks: [
      'Ctrl+G で Changes（ソースコントロール）を開く。',
      'Diff レビューパネルからエージェントに Create PR を促せます。',
      'Force-with-lease と max diff size はバージョンコントロール設定でゲート。',
      'Review workbench は接続時に GitHub、GitLab、Bitbucket、Gitea、Azure DevOps の PR/MR を一覧。',
      'エージェントも権限モードと sandbox に従いツール経由で git 操作可能。',
      'stash / branch / rebase は快適さに応じて Changes またはエージェントツールから。',
      '小さなコミットと明確なメッセージを優先 — エージェントはきれいな履歴に対してより良いフォローアップを書きます。',
      'Create PR を頼む前にホスト接続 — さもなくばローカルコミットは成功しリモート段階で遅く失敗。',
      'diff が巨大なら max diff size は一時的にだけ上げる — 過大レビューはリスクを隠します。'
],
    blocks: [
      {
        type: 'p',
        text: 'Coding はローカルソースコントロール（Changes）とリモートレビュー（Review）を公開します。ローカル操作には stage、commit、branch、merge、rebase、cherry-pick、stash、worktree 対応フローが含まれます。Settings → Git & reviews 設定時、リモートホストが PR/MR 一覧とレビューアクションを支えます。',
      },
      {
        type: 'p',
        text: 'git をエージェントトランスクリプトの隣に置くことで、検証ごとに外部 IDE へ切り替えず edit → review → commit → PR ループが短くなります。安全ポリシー（タイムアウト、max diff size、force-with-lease）は Settings にあり、積極的 git 操作が意図的なままです。',
      },
      {
        type: 'p',
        text: 'Ctrl+G を押すか workbench から Changes を開く。diff をレビューし、stage し、commit。接続済み PR/MR は Review。ホスト、タイムアウト、安全トグルは Settings → Git & reviews。ホスト接続準備ができたら diff レビューから Create PR を依頼。',
      },
      {
        type: 'tips',
        items: [
          'Ctrl+G — Changes / ソースコントロール',
          'Review — 接続ホストの PR/MR 一覧',
          'GitHub / GitLab / Bitbucket / Gitea / Azure DevOps — ホスト連携',
          'force-with-lease — ゲート済み; 気軽な既定ではない',
          'max diff size — 必要なときだけ上げる',
          'stash / branch / rebase — UI またはエージェントツール'
],
      },
      {
        type: 'p',
        text: 'PR ループ手順: (1) accept-edits または plan でエージェントが編集、(2) Ctrl+G で diff 検査、(3) 関連 hunk を stage、(4) why 重視のメッセージで commit、(5) エージェントまたはいつものリモートフローで push、(6) 接続ホストで Review / Create PR、(7) フォローアップチャットでレビューコメント対応。',
      },
      {
        type: 'p',
        text: 'エージェントに git を任せる vs 自分で: diff がプランに一致し権限モードが適切なら stage/commit を任せる; 保護ブランチでチームが人間儀式を求めるなら merge/rebase は自分で。共有ブランチで force-with-lease を気軽に有効にしない。',
      },
      {
        type: 'p',
        text: 'よくある失敗: deny glob 外の新規ファイルで sandbox が捕まえなかったシークレットをコミット; ホスト認証前に PR を依頼; エージェント駆動の 1 コミットに無関係ファイルを混ぜる; Work モードで Review が動くと仮定; force-with-lease を単なる `--force` のように扱う。',
      },
      {
        type: 'tips',
        items: [
          '横断: Plan Accept → Changes で、プランが期待どおりの diff になったか確認。',
          '横断: worktree は実験コミットを主チェックアウトから遠ざける。',
          '横断: 本番リモートへの初 push 前は権限 ask モード。'
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
    title: '構造コードグラフ',
    summary:
      'リポジトリ単位のインデックスがソース検索、構造パターン、正確なシンボルナビゲーションを統合します。許可された全リポジトリを 1 つの code_context ツールで扱います。',
    keywords: [
      'code graph',
      'symbols',
      'cross-repo',
      'index',
      'code_context',
      'tree-sitter',
      'コードグラフ',
      'シンボル',
      'インデックス',
      '構造'
],
    setup:
      'Coding ワークスペースまたはプロジェクト — 最初のクエリが変更済みソースを増分更新します。Graph で現在の動的スナップショットを確認できます。',
    tricks: [
      'Coding スキルは統一された code_context ワークフローを段階的に提示します。',
      '発見には code_context search、コード形状には grep、既知の正確なシンボルには graph action を使います。',
      'Graph workbench ツールを開き視覚探索し、必要なら再インデックス。',
      'クロスレポ関係は import、module path、一意な定義から動的に解決され、resolver job や永続化された推測エッジはありません。',
      'code_context の graph action は definition、callers、callees、references、impact、neighborhood。',
      '編集後は refresh=true、同一バージョン直後の追跡クエリだけ refresh=false を使います。',
      '「パッケージ全体を読んで」ではなく構造質問（「誰が X を呼ぶ？」）。',
      'マルチレポプロジェクトはクロスレポエッジ; スタンドアロンレポも 1 ツリー内で恩恵。',
      'Coding モードは skill 本文を注入せず、生のリクエスト文をキーワードで graph query にルーティングしません。'
],
    blocks: [
      {
        type: 'p',
        text: '各リポジトリは AST 対応チャンク、シンボル、関係、FTS ソースを持つローカル managed index を所有します。ネイティブ code_context がこれらを検索し、Graph は動的スナップショットを表示します。',
      },
      {
        type: 'p',
        text: 'ファイル全体ダンプはコンテキストを燃やします。Graph 優先ナビはプロジェクト内の「誰が X を呼ぶ？」やクロスレポ質問にトークン効率が良く、静的解決が足りないときはなお grep/LSP/テストが可能です。graph は地図として扱い、ホットパス読解を置き換える真実の根拠にはしない。',
      },
      {
        type: 'tips',
        items: [
          'code_context search — 識別子、リテラル、コメント、概念',
          'code_context grep — 例示による構造マッチ',
          'code_context definition/callers/callees — 正確なシンボルナビゲーション',
          'code_context references/impact/neighborhood — 境界付き関係探索'
],
      },
      {
        type: 'p',
        text: 'Coding ワークスペースで code_context を使います。最初のクエリが追加・更新・削除をリポジトリ単位の target に反映します。マルチレポエッジは、クエリまたは可視化時に現在許可された target 集合から解決されます。',
      },
      {
        type: 'p',
        text: '調査手順: (1) search で識別子、または grep でコード形状を発見、(2) exact-symbol action を実行、(3) 重複定義を path/repository で解消、(4) limitation を確認、(5) 動的挙動をテスト、ログ、ランタイム証拠で検証。',
      },
      {
        type: 'p',
        text: 'graph vs grep: 型付きシンボル、呼び出しエッジ、クロスファイルアーキテクチャは graph; エラー文字列、コメント、フィーチャフラグ、YAML キー、パーサが飛ばし得る生成コードは grep。graph だけを信じないとき: マクロ、重いリフレクション、コンパイル時にシンボルを消すテンプレート。',
      },
      {
        type: 'p',
        text: 'よくある失敗: exact-symbol action に文章を渡す、ディレクトリ全体をダンプする、未許可の sibling を検索する、外部編集後に refresh しない、suggestion を解決済み root と扱う。',
      },
      {
        type: 'tips',
        items: [
          '横断: graph ヒットと Changes を組み合わせ、編集セットが呼び出し近傍と一致するか見る。',
          '横断: AGENTS.md で graph 優先ナビを指示できる。',
          '横断: specialist は Settings → Agents ごとにツールを継承 — worker がコード検索できることを確認。'
],
      }
],
    related: ['coding-workspaces', 'agents-settings', 'composer-power', 'coding-git'],
    openAction: { type: 'workbench', tool: 'graph' },
  },
  {
    id: 'memory-dream',
    category: 'memory',
    title: 'Memory wiki と Dream',
    summary:
      'Markdown wiki（topics、entities、notes、imports）を検査し、cron（既定 `0 2 * * *`）または Run Dream で手動の Dream 合成を実行します。Memory はチャットを不透明なモデル重みではなく、引用可能な永続ページに変えます。',
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
      'メモリ',
      'ドリーム',
      'ノート',
      'ウィキ'
],
    setup:
      'Ctrl+M または workbench ツールで Memory を開く。Dream は Settings → Memory（cron と関連オプション）で設定。スケジュールを触らなければ既定 Dream cron は `0 2 * * *`。',
    tricks: [
      'Pending notes/ は Dream が curated wiki ページへ合成するまで読み取り専用。',
      '既定 Dream cron は 0 2 * * *; settings またはコマンドパレットから Run Dream now。',
      'Wiki セクションには topics、entities、notes、imports、INDEX.md、追記専用 LOG.md。',
      'Dream ページは引用、信頼度、関連ページメタデータを持つ — 盲目的に信じる前に検査。',
      'Memory は workbench パネルであり、別製品モードではありません。',
      '任意エージェントプロンプトが必要なときだけ Dream を Scheduler と組み合わせ; Dream には独自スケジュールがあります。',
      '一晩の Dream 後は LOG.md をざっと見て、チャットでページを引用する前に何が変わったか確認。',
      '来週モデルが覚えてくれると祈るより、日中に短い pending notes を書くことを優先。',
      'Dream 信頼度が低いページは下書き仮説として扱い、ソースシステムで検証。'
],
    blocks: [
      {
        type: 'p',
        text: 'Memory はディスク上の検査可能な Markdown wiki です。Dream は未処理セッションとメモを、引用と信頼度メタデータ付きの curated ページへ統合する、スケジュール（または手動）合成エージェントです。他のドキュメント同様に開き、diff し、訂正できます。',
      },
      {
        type: 'p',
        text: 'チャット履歴だけでは長期ナレッジベースとして弱いです。開き、diff し、引用できる wiki は、夜間の自動統合を許しつつ永続事実を不透明なモデル重みの外に保ちます。Memory は永続知識; トランスクリプトはアクティブ会話向けです。',
      },
      {
        type: 'p',
        text: 'Ctrl+M または workbench で Memory を開く。topics/、entities/、notes/、imports/、INDEX.md、LOG.md を閲覧。notes/ 下のメモは合成待ちで読み取り専用。Dream cron は Settings → Memory（既定 `0 2 * * *`）または Run Dream now。Dream 後、新規/更新ページと LOG.md を確認。',
      },
      {
        type: 'tips',
        items: [
          'topics/ — curated 主題ページ',
          'entities/ — 人、システム、コンポーネント',
          'notes/ — Dream まで保留・読み取り専用',
          'imports/ — 取り込まれた外部素材',
          'INDEX.md — エントリマップ',
          'LOG.md — 追記専用の合成ログ',
          'Ctrl+M — Memory workbench を開く',
          'Run Dream — 手動合成トリガ'
],
      },
      {
        type: 'p',
        text: '日次習慣の手順: (1) 作業中に短いメモを Memory へ、(2) notes/ を保留のまま、(3) cron または一日の終わりに Run Dream、(4) LOG.md を読む、(5) 誤った引用は wiki ページ自体で直す、(6) 関連するとき後のチャットで訂正ページに言及。',
      },
      {
        type: 'p',
        text: 'Memory vs Work フォルダのチャット: 単一案件を超えて生きる事実は Memory; アクティブな並列スレッドはフォルダ。Dream だけに頼らないとき: 人間が書いた真実の源が必要な規制判断 — ページを自分で書き Dream は補助として扱う。',
      },
      {
        type: 'p',
        text: 'よくある失敗: notes/ を編集して権威が残ると期待（保留）; Dream の Settings → Memory cron を Scheduler cron タスクと混同; INDEX.md を一度も開かず「Memory が空」と主張; 散らかった一週間のチャット後、リンク証拠を確認せず高信頼ページを引用。',
      },
      {
        type: 'tips',
        items: [
          '横断: 任意プロンプトは Scheduler; wiki 合成だけが Dream。',
          '横断: 大きな調査やコーディングの後、Run Dream で新しい事実を wiki 形へ。',
          '横断: Dream コンテンツが後でチャット経由でプロバイダへ流れるときも sandbox/アウトバウンドポリシーは重要。'
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
    title: 'スケジュールタスク',
    summary:
      'Scheduler workbench パネルから cron またはワンショットのエージェントプロンプトを作成 — `/scheduler` ルートはホームへリダイレクトするので Ctrl+S を使います。タスクはチャットウィンドウをフォーカスせず、一致モードのチーム Lead へプロンプトを届けます。',
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
      'スケジュール',
      'クロン',
      'リマインダー',
      'タスク'
],
    setup:
      'Ctrl+S（workbench ツール）で Scheduler を開く。`/scheduler` ルートはホームへリダイレクト — 常にパネルを使う。タスクで work または coding モードを選び、正しい Lead に届くようにする。',
    tricks: [
      '次の cron tick を待たずパネルから pause、resume、trigger。',
      'Coding コンテキストは新規タスクにワークスペース/モードを事前入力できる。',
      'タスクは一致モード（work または coding）のチーム Lead へプロンプトを届ける。',
      'リマインダーはワンショット; 反復メンテや自分で持つ Dream 隣接ルーチンは cron。',
      'Scheduler を Settings → Memory 下の Dream 独自 cron と混同しない。',
      '一晩 cron を信頼する前に、プロンプト編集後に手動 Trigger で検証。',
      'スケジュールプロンプトは冪等に — 再実行が乱れた副作用を複製しないように。',
      'バックエンドがローカルのみでウィンドウを逃すなら、長いノート PC スリープ前にタスクを Pause。',
      'タスク名は成果で（「平日レポ雑務」）— パネルがスキャンしやすくなる。'
],
    blocks: [
      {
        type: 'p',
        text: 'スケジュールタスクは cron 式またはワンショット実行で、チャットウィンドウを開いたままにせずエージェントチームへプロンプトを送ります。管理 UI は Scheduler workbench ツールのみ — 持続する `/scheduler` ページはありません。',
      },
      {
        type: 'p',
        text: '反復運用（ステータスダイジェスト、レポ雑務、リマインダー）はあなたがトランスクリプトにいることに依存すべきではありません。Scheduler は「いつ」を「どのチャットがフォーカスか」から切り離し、よそにいてもメンテが進みます。',
      },
      {
        type: 'p',
        text: 'Ctrl+S を押すか workbench から Scheduler を開く。モード（work/coding）、スケジュール、プロンプトでタスク作成。同じパネルから pause/resume/trigger。`/scheduler` のブックマークは無視 — 空ルートに詰まらないよう設計でホームへリダイレクト。',
      },
      {
        type: 'tips',
        items: [
          'Ctrl+S — Scheduler パネルを開く',
          'Cron — 反復エージェントプロンプト',
          'One-shot — 単発の将来実行 / リマインダー',
          'Pause / resume / trigger — パネル内ライフサイクル制御',
          'Mode — work または coding の Lead ターゲット',
          '/scheduler — ホームへリダイレクト; ブックマークしない',
          'Dream cron — Settings → Memory 下で別物'
],
      },
      {
        type: 'p',
        text: '最初の cron タスク手順: (1) Ctrl+S、(2) タスク作成、(3) coding または work を選択、(4) cron 式を設定、(5) 明示的 Definition of Done 付きプロンプトを書く、(6) 一度 Trigger して検証、(7) 良いドライラン後だけ有効のまま、(8) 再利用の可能性があるならすぐ削除せず obsolete 時に Pause。',
      },
      {
        type: 'p',
        text: 'Scheduler vs Goal vs Dream: Scheduler は時計で離散プロンプトを発火; Goal はセッション内自律目標を継続; Dream は独自 cron で Memory wiki を合成。仕事ごとに 1 機構を選ぶ — 同じ雑務に 3 つ全部を積むと重複作業になりがちです。',
      },
      {
        type: 'p',
        text: 'よくある失敗: `/scheduler` をブックマークして Scheduler が壊れたと思う; Coding 雑務を work モードに向ける; UI フォーカスや開いた Terminal タブを前提にしたプロンプト; 逃したローカル sidecar ウィンドウを cron パーサバグと混同; Settings → Memory ではなく Scheduler で「Dream を実行」。',
      },
      {
        type: 'tips',
        items: [
          '横断: スケジュールプロンプトが当たるセッションの権限モードを慎重に。',
          '横断: ローカル sidecar で cron が発火するとき HealthDot が緑である必要。',
          '横断: wiki 統合は Dream; 「毎週月曜に Lead へ聞く」は Scheduler。',
          '冪等プロンプト — トリガが二度走っても安全。'
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
    title: '内蔵ブラウザと WebBridge',
    summary:
      'アプリ内ブラウザ（Ctrl+T）を使うか、teach モードとチャット単位の有効化付き WebBridge 拡張で実 Chrome/Edge セッションをペアします。WebBridge はデスクトップアプリの CDP コンパニオンであり、EvoFlux の Web 版ではありません。',
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
      'ブラウザ',
      '拡張機能',
      'ティーチ',
      'ペアリング'
],
    setup:
      '内蔵: Settings → Browser で有効化し Ctrl+T。WebBridge: Chrome/Edge 拡張をインストールし、Settings → Browser でマスターポリシーを有効化、デスクトップのステータスコントロールからペアし、使うチャットごとに WebBridge を有効化。',
    tricks: [
      'Ctrl+T は内蔵ブラウザ workbench をトグル — WebBridge ペアリングではありません。',
      'WebBridge はチャット単位で有効化可能; マスターポリシーは Settings → Browser。',
      'Teach モードは意味のあるブラウザ操作（生キーストロークではない）を記録し、確認付きで再生可能なリプレイにします。',
      'ペアリングはスコープ付き資格情報とワンタイムセッションチケット; ペアリング取り消しでライブ中継が閉じます。',
      '実ブラウザからの選択とページコンテキストは信頼できない入力として扱います。',
      'WebBridge は EvoFlux の Web 版ではなく、デスクトップアプリの CDP コンパニオンです。',
      'サンドボックスされたエージェント閲覧は内蔵 Browser; 実 SSO Cookie や企業拡張が必要なら WebBridge。',
      'マシンを貸すときやアクセスローテ時はペアリングを取り消し — 未処理チケットも取り消しと共に死にます。',
      '監視結果をエージェントループへ共有する前に teach リプレイを確認。'
],
    blocks: [
      {
        type: 'p',
        text: 'ブラウザ経路は 2 つあります: (1) EvoFlux 内のエージェント駆動ページ向け内蔵アプリ内ブラウザ workbench、(2) ドメインポリシーと監査跡付きで実 Chrome/Edge プロファイルへ CDP 制御を中継する拡張 WebBridge。タスクのログインと信頼モデルに合う経路を選びます。',
      },
      {
        type: 'p',
        text: 'サンドボックスされたアプリ内ビューが必要なタスクもあれば、実ログイン済みブラウザ（SSO、企業 Cookie、拡張）が必要なタスクもあります。WebBridge はそのギャップを埋めつつ、EvoFlux をクラウド Web IDE にはしません。どちらでもページ内容は信頼できないものとして扱います。',
      },
      {
        type: 'p',
        text: '内蔵: Settings → Browser → 有効化、その後 Ctrl+T または Browser ツール。WebBridge: 拡張を入れ、Settings → Browser でポリシー有効化、デスクトップ WebBridge ステータスコントロールでペアし、使うチャットで WebBridge を有効化。Teach でレビュー可能な操作列を記録; 監視結果共有前に確認。',
      },
      {
        type: 'tips',
        items: [
          'Ctrl+T — 内蔵ブラウザのみ',
          'Status control — WebBridge のペア / 解除',
          'Per-chat toggle — このセッションで実ブラウザを許可',
          'Teach — 意味のある操作、生キーストロークなし',
          'Revoke pairing — 中継 + 未処理チケットを殺す',
          'Settings → Browser — 両経路のマスターポリシー',
          'Untrusted input — 実ブラウザからの選択/ページコンテキスト'
],
      },
      {
        type: 'p',
        text: 'WebBridge 手順: (1) Chrome/Edge 拡張をインストール、(2) Settings → Browser でマスターポリシー有効化、(3) デスクトップステータスコントロールからペア、(4) 対象チャットを開く、(5) そのチャットで WebBridge を有効化、(6) 任意でフローを Teach しリプレイ確認、(7) マシンや案件が終わったらペアリング取り消し。',
      },
      {
        type: 'p',
        text: '内蔵 vs WebBridge: ハーネス内の捨て閲覧とデモは内蔵; すでに Chrome/Edge で使う認証済み企業アプリは WebBridge。WebBridge を使わないとき: 実プロファイルの Cookie をエージェント制御へ晒したくない公開の信頼できないサイト。',
      },
      {
        type: 'p',
        text: 'よくある失敗: Ctrl+T で拡張がペアすると期待; マスターポリシーを有効にして per-chat トグルを忘れる; teach 記録を生キーロガースクリプトとして扱う; 共有ノート PC に古いペアリングを残す; WebBridge ページ文を疑いなくプロンプトへ貼る。',
      },
      {
        type: 'tips',
        items: [
          '横断: プロバイダへ出るものにはなお sandbox/アウトバウンドポリシーが適用。',
          '横断: WebBridge がオフラインなら再インストール前にトラブルシューティングを確認。',
          '横断: side chat はメインブラウザ実行を止めずにページ引用を明確化できる。'
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
    title: 'Providers とモデル（BYOM）',
    summary:
      'Anthropic、OpenAI、Gemini、Bedrock、Ollama など — 1 つのストリーミング抽象の裏にある 12 連携 — を接続し、エージェントまたはセッションごとにモデルを選びます。EvoFlux は単一ベンダーモデルにロックしません。',
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
      'プロバイダ',
      'モデル',
      'APIキー',
      '認証'
],
    openAction: { type: 'settings', path: 'providers' },
    setup:
      'Settings → Providers。API キー、OAuth アクセス、または稼働中のローカルデーモン URL を用意。空のモデル一覧をネットワーク障害としてデバッグする前に HealthDot が緑であることを確認。',
    tricks: [
      'Settings → Agents でエージェントごとにモデルを独立選択。',
      'composer のセッション pill は現在チャットのモデル、thinking レベル、fast mode を設定。',
      'プロバイダ一覧はファジーモデル検索に対応。',
      'ローカルデーモン（Ollama など）は必要時に base URL 上書き。',
      'モデル一覧が空なら通常は設定済みプロバイダがゼロ — チャットデバッグ前に Providers を直す。',
      'コンテキスト予算バーはレジストリの選択モデル context_length を使う。',
      'コストが重要なら Lead トリアージは速いモデル、Coding specialist は強いモデル。',
      'キーローテ後は Goal 開始前に小さな Work ping で再テスト。',
      'OAuth プロバイダも成功した接続状態が必要 — 途中の OAuth はモデルなしのまま。'
],
    blocks: [
      {
        type: 'p',
        text: 'Providers は 1 つのストリーミング層経由でモデルを公開する BYOM 連携（API キー、OAuth、またはローカルデーモン）です。対応ファミリーには Anthropic、OpenAI、Google Gemini、AWS Bedrock、Ollama、DeepSeek、xAI、Vertex AI、GitHub Copilot など。資格情報はチャットではなく Settings に置きます。',
      },
      {
        type: 'p',
        text: 'EvoFlux は単一ベンダーモデルにロックしません。UI ハーネスを変えずに、エージェントごとに異なるモデル（速い Lead トリアージ vs 深い specialist コーディング）を使えます。セッション pill はエージェント既定を編集せず 1 チャットだけ上書きできます。',
      },
      {
        type: 'p',
        text: 'Settings → Providers を開き、資格情報または base URL を追加し、configured 表示を確認し、Agents で既定を割り当てるか composer pill でセッション上書き。キーが正しそうでもストリームが失敗するなら Diagnostics。長いモデル一覧にはファジー検索が役立ちます。',
      },
      {
        type: 'tips',
        items: [
          'API key / OAuth / local daemon — 3 つの接続スタイル',
          'Settings → Agents — エージェントごとの既定モデル',
          'Composer pills — セッションごとのモデル / thinking / fast mode',
          'context_length — コンテキスト予算バーを駆動',
          'Ollama — 既定ポート以外なら base URL を設定',
          '空のモデル一覧 — まず Providers を設定'
],
      },
      {
        type: 'p',
        text: '最初のプロバイダ手順: (1) HealthDot 緑、(2) Settings → Providers、(3) キーまたは OAuth またはデーモン URL を追加、(4) configured 状態を確認、(5) Agents で Lead 既定を選ぶ、(6) 短い Work ping を送る、(7) それから大きな Coding タスクや Goal。',
      },
      {
        type: 'p',
        text: 'よくある失敗: API キーをトランスクリプトに貼る; 「モデルがない」を sidecar クラッシュとしてデバッグ; セッション pill がエージェント既定を恒久変更したと仮定; デスクトップ sandbox 内から誤ったホストへ Ollama を向ける; HealthDot が緑のままレート制限エラーを無視。',
      },
      {
        type: 'tips',
        items: [
          '横断: 資格情報が正しそうでもストリームが失敗したら Diagnostics。',
          '横断: 強いモデルは context_length を上げる — /compact 習慣に注意。',
          '横断: 完璧なモデルでも MCP とツールにはなお権限モードが必要。'
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
    title: 'Agent Plugins：インストール、信頼確認、設定、開発',
    summary:
      'Plugin Center でポータブル Agent Plugin を検証、インポート、確認、設定、有効化、編集、pack、更新、削除します。パッケージ境界、trust review、資格情報、Skill 検出、MCP runtime、ready にならない場合の確認手順を説明します。',
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
      '資格情報',
      '信頼確認',
      'org.evoelsewhere.evoflux',
      '拡張名前空間'
],
    setup:
      'Work または Coding のサイドバーから Plugins を開きます。`.evoplugin`/ZIP は Add plugin → Import package、展開済みディレクトリは Link development folder、読み取り専用検査は Validate folder、scaffold と内蔵 editor は Create plugin を使います。',
    tricks: [
      'ポータブル plugin は `plugin.json`、直下の `skills/*/SKILL.md`、任意の root `mcp.json` からデータとコードを提供し、EvoFlux UI を任意に注入できません。',
      'Import と Link は既定で disabled のままインストールされます。Trust and enable の前に trust review を読みます。',
      'Trust review は実行コマンドと引数、remote host、環境 field 名、capabilities を表示し、secret 値は表示しません。',
      '不明な項目があれば Keep disabled を選びます。disabled のままでもファイル編集と credentials 設定はできます。',
      'Credentials は installation ごとに package 外へ保存され、その plugin の stdio MCP process だけへ注入されます。',
      '新規 package は `org.evoelsewhere.evoflux.credentials` と `org.evoelsewhere.evoflux.mcp` を使います。',
      '旧 alias `evoflux.credentials` と `evoflux.mcp` も読み取れます。両方ある場合 canonical が優先です。',
      'Plugin MCP server は Settings → MCP servers に plugin badge 付きで表示され、global MCP config へコピーされません。',
      'Plugin Skill は installation が enabled で Skill が valid の間だけ検出されます。',
      'Link は local directory を直接使う開発向け、Import は managed copy、Pack は deterministic `.evoplugin` ZIP を作ります。',
      'Disable は MCP runner を停止/reconcile し、Skill を catalog から外しますが installation data は削除しません。',
      'Uninstall は既定で plugin data を保持します。credentials と mutable state も消す場合だけ data 削除を選びます。'
],
    blocks: [
      {
        type: 'p',
        text: 'Agent Plugins 1.0 はポータブル package contract です。EvoFlux は Agent Skills と MCP stdio / Streamable HTTP をサポートします。plugin は root `plugin.json` を持つ展開済み directory で、`.evoplugin` は deterministic ZIP 配布 wrapper にすぎません。legacy SSE 宣言は診断されますが起動しません。Managed Agent Plugins は trusted な in-process legacy Python hooks と分離されています。',
      },
      {
        type: 'tips',
        items: [
          '必須 — Agent Plugins 1.0 `$schema`、小文字 portable name、任意の version/description を持つ `plugin.json`。',
          'Skills — `skills/<skill-name>/SKILL.md` の直下だけ。深くネストした Skill directory は resource で、追加 Skill として検出されません。',
          'MCP — 任意の root `mcp.json`。各 server は独立して失敗し、1 entry の異常で正常な sibling は隠れません。',
          '可変データ — `${PLUGIN_DATA}` を使い、bundle の読み取り専用 file は `${PLUGIN_ROOT}` から解決します。',
          'Host extension — EvoFlux 固有宣言は `plugin.json` の canonical reverse-domain namespace 以下へ置きます。'
],
      },
      {
        type: 'p',
        text: '安全な導入手順: (1) Add plugin、(2) archive を import または directory を link、(3) package/component diagnostics を読む、(4) enable trust review を確認、(5) command・host・environment field・capability が不明なら disabled を維持、(6) 宣言があれば Credentials を設定、(7) toggle をオンにして Trust and enable、(8) Skills と MCP status を確認、(9) ask permission mode で無害な最初の tool を実行します。',
      },
      {
        type: 'p',
        text: 'Trust review は静的です。EvoFlux は plugin code を起動せず宣言だけを読みます。Executable には stdio server の program と引数配列、remote には host・URL・transport、environment には `mcp.json` と credential schema 由来の名前だけを表示します。Capabilities は Agent Skills、MCP transport、宣言済み EvoFlux server capability です。インストールは global grant ではなく、全 tool call に通常の permissions と sandbox が適用されます。',
      },
      {
        type: 'p',
        text: 'Credentials: plugin card → Actions → Credentials。field type は text、secret、URL、boolean です。required field が揃うと form が complete になります。secret は読み取り時に mask され、package 外へ厳しい file permission で保存されます。値は stdio env を overlay し、その後 EvoFlux が安全な `PLUGIN_ROOT` と `PLUGIN_DATA` を強制します。Streamable HTTP は保存済み値を受け取りません。portable header に本物の secret を置かないでください。',
      },
      {
        type: 'p',
        text: 'Runtime: enabled plugin の valid Skill は metadata catalog に入り、activate 時だけ本文が load されます。plugin Skill を load すると同じ installation の ready MCP tools がその run で利用可能になりますが permission は維持されます。Settings → Skills は discovery/validation、Settings → MCP servers は plugin badge、runtime state、tool names を表示します。runtime name には installation hash があるため、Skill 内では生成 prefix ではなく安定した server/tool suffix を案内します。',
      },
      {
        type: 'p',
        text: '開発: Add plugin → Create plugin で portable scaffold を作り内蔵 editor を開きます。file tree から `plugin.json`、Skill instruction、scripts、`mcp.json` を開き、entry 作成/削除、Save、Validate、Pack を行います。live 開発は directory を Link します。宣言や実装変更後は再検証し、access 変更を確認してから再 enable します。plugin は独自 settings page や任意 frontend を ship できず、Plugin Center が lifecycle、credentials、diagnostics、runtime UI を所有します。',
      },
      {
        type: 'tips',
        items: [
          'Install できない — inspection diagnostics を開き、fatal `plugin.json`、unsafe path、archive collision、symlink、size、digest error を修正。',
          'Skill がない — installation を enable、`skills/<name>/SKILL.md` が直下で frontmatter が valid か、上位 project/user Skill に shadow されていないか確認。',
          'Settings に MCP がない — plugin enabled、`mcp.json` valid、transport が SSE ではなく stdio または Streamable HTTP か確認。',
          'MCP が error — runtime row を開き executable path、args、working directory、startup log、required credentials、stdio protocol 専用 stdout を確認。',
          'Credentials が unsupported — `plugin.json` に `org.evoelsewhere.evoflux.credentials.fields` を追加し Validate 後に戻る。',
          'Remote server が ready でない — URL/host と literal headers を確認。保存済み plugin credentials は Streamable HTTP へ意図的に注入されません。',
          'Chat で tool が選ばれない — 対応 plugin Skill を activate するか agent に plugin MCP server を明示選択。install だけでは全 tool を grant しません。',
          '変更が古い — Save/Validate、Plugin Center refresh、disable/enable で runtime を reconcile。'
],
      },
      {
        type: 'p',
        text: 'CLI 対応: `evoflux plugin inspect`, `create`, `link`, `install`, `show`, `enable`, `disable`, `pack`, `update`, `uninstall`。CLI install/link も既定で disabled です。`show <installation-id>` の `inspection.trust` を確認してから `enable` します。`--enabled` は独立した trust gate を持つ non-interactive automation だけで使います。',
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
    title: 'Authoring reference：manifest、Skills、MCP、extensions',
    summary:
      '具体的な directory layout と JSON 例で標準互換 plugin を作ります。portable 宣言と EvoFlux 固有 extension を分け、検証して package 化する方法です。',
    keywords: ['plugin authoring', 'manifest', 'plugin.json 例', 'mcp.json 例', 'skill frontmatter', 'credentials schema', 'capabilities', 'package layout'],
    setup: 'Add plugin → Create plugin から始めるか、directory を作成して Link/Pack 前に `evoflux plugin inspect ./my-plugin` を実行します。',
    blocks: [
      { type: 'heading', text: 'Package layout と各 file の役割' },
      {
        type: 'code',
        language: 'text',
        caption: 'Portable directory',
        code: 'my-plugin/\n├── plugin.json\n├── skills/\n│   └── release-audit/\n│       ├── SKILL.md\n│       ├── references/\n│       └── scripts/\n├── mcp.json\n├── server.py\n├── README.md\n└── LICENSE',
      },
      {
        type: 'table',
        columns: ['Path', '必須', '意味'],
        rows: [
          ['plugin.json', 'はい', 'Portable identity と host extensions。'],
          ['skills/<name>/SKILL.md', '任意', '直下 Agent Skill。references/scripts は Skill directory 内。'],
          ['mcp.json', '任意', 'stdio、Streamable HTTP、legacy SSE 宣言。'],
          ['Implementation files', '必要時', 'MCP 宣言から呼ぶ bundled server code。'],
          ['README / LICENSE', '推奨', '利用者 setup、provenance、制約、license。'],
        ],
      },
      { type: 'heading', text: '最小 plugin.json' },
      {
        type: 'code',
        language: 'json',
        caption: 'Portable manifest',
        code: '{\n  "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",\n  "name": "release-audit",\n  "version": "0.1.0",\n  "description": "ガイドと read-only tools で release を監査します。",\n  "author": { "name": "Example Team" },\n  "repository": "https://example.com/plugins/release-audit",\n  "license": "MIT",\n  "keywords": ["release", "audit"],\n  "extensions": {}\n}',
      },
      {
        type: 'callout',
        title: 'Manifest rule',
        text: '名前は 1–64 文字の小文字 ASCII、数字、dot、hyphen。先頭/末尾は英数字で、-- と .. は不可です。未知の root field は warning 後に無視され、client 固有データは extensions に置きます。',
      },
      { type: 'heading', text: 'Agent Skill contract' },
      {
        type: 'code',
        language: 'markdown',
        caption: 'skills/release-audit/SKILL.md',
        code: '---\nname: release-audit\ndescription: 公開前に release evidence、checks、risk を確認します。\n---\n\n# Release audit\n\n1. bounded evidence を収集。\n2. live data が必要なときだけ MCP tool を使用。\n3. fact、inference、不足 evidence を分離。\n4. 明示 authorization なしに publish/mutate しない。',
      },
      {
        type: 'p',
        text: 'Skill name は Agent Skills naming contract に従います。description は discovery に使われるため正確に書きます。主 workflow は SKILL.md、大きな reference は必要時のみ load。EvoFlux runtime prefix は installation ごとに変わるため、MCP tool は安定 suffix で案内します。',
      },
      { type: 'heading', text: 'MCP stdio と Streamable HTTP' },
      {
        type: 'code',
        language: 'json',
        caption: 'mcp.json',
        code: '{\n  "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",\n  "mcpServers": {\n    "local": {\n      "type": "stdio",\n      "command": "python",\n      "args": ["${PLUGIN_ROOT}/server.py"],\n      "env": { "CACHE_DIR": "${PLUGIN_DATA}/cache" },\n      "cwd": "${PLUGIN_ROOT}"\n    },\n    "remote": {\n      "type": "streamable-http",\n      "url": "https://api.example.com/mcp",\n      "headers": { "X-Client": "evoflux-plugin" }\n    }\n  }\n}',
      },
      {
        type: 'table',
        columns: ['Transport', '用途', '重要な制約'],
        rows: [
          ['stdio', 'Server code を plugin と同梱。', 'shell string 不可、stdout は protocol 専用、credentials 注入可。'],
          ['streamable-http', '独立運用 remote endpoint。', 'redirect 無効、header は literal、stored credentials は非注入。'],
          ['sse', 'legacy 宣言互換のみ。', 'validate/diagnose するが EvoFlux は起動しない。'],
        ],
      },
      { type: 'heading', text: 'Credentials と capability extensions' },
      {
        type: 'code',
        language: 'json',
        caption: 'plugin.json extensions 抜粋',
        code: '{\n  "extensions": {\n    "org.evoelsewhere.evoflux.credentials": {\n      "fields": [\n        { "key": "endpoint", "label": "Service URL", "type": "url", "env": "SERVICE_URL", "required": true },\n        { "key": "token", "label": "API token", "type": "secret", "env": "SERVICE_TOKEN", "required": true }\n      ]\n    },\n    "org.evoelsewhere.evoflux.mcp": {\n      "servers": { "local": { "capabilities": ["webbridge-safe"] } }\n    }\n  }\n}',
      },
      {
        type: 'callout',
        tone: 'warning',
        title: '実 secret を package しない',
        text: 'Credential 宣言は field metadata だけで value は含めません。token の commit、Streamable HTTP header への埋め込み、log/stdout 出力、chat への貼り付け依頼は禁止です。',
      },
      { type: 'heading', text: 'Validate、Link、Pack、Update' },
      {
        type: 'code',
        language: 'shell',
        caption: 'Authoring loop',
        code: 'evoflux plugin inspect ./my-plugin\nevoflux plugin link ./my-plugin\nevoflux plugin show <installation-id>\nevoflux plugin enable <installation-id>\nevoflux plugin pack ./my-plugin\nevoflux plugin update <installation-id> ./my-plugin.evoplugin',
      },
      {
        type: 'p',
        text: 'contract 変更ごとに Inspect します。component validation、startup、無害な tool call、failure isolation、secret masking、result bounds、disable/enable reconciliation を test。valid directory だけを Pack し、archive を新しい contract として扱いません。',
      },
    ],
    related: ['agent-plugins', 'agent-plugins-runtime-security', 'agent-plugins-troubleshooting'],
    openAction: { type: 'workbench', tool: 'plugins' },
  },
  {
    id: 'agent-plugins-runtime-security',
    category: 'plugins',
    title: 'Runtime と security：trust、credentials、permissions、data',
    summary:
      'static inspection から enable までの動作、data/credentials が runtime 境界を渡る方法、trust 後も残る protection を正確に説明します。',
    keywords: ['plugin security', 'trust model', 'environment', 'plugin data', 'permission', 'sandbox', 'runtime manager', 'precedence', 'secret masking'],
    setup: 'Package を Import/Link し disabled のまま、enable 前に trust review と source files を比較します。',
    blocks: [
      { type: 'heading', text: 'Lifecycle state machine' },
      {
        type: 'table',
        columns: ['Stage', 'Code 実行?', 'EvoFlux の動作'],
        rows: [
          ['Validate', 'いいえ', 'schema、path、URL、component、extension、digest を parse。'],
          ['Install / Link', '既定はいいえ', 'disabled の managed copy/developer directory を登録。'],
          ['Trust review', 'いいえ', 'commands、remote hosts、環境名、Skills/transports、capabilities を開示。'],
          ['Enable', 'はい', 'valid Skills を publish し MCP runners を reconcile。'],
          ['Disable', '停止', 'Skills を外し MCP を停止/reconcile、data は保持。'],
          ['Uninstall', 'いいえ', '登録/package を削除、明示時だけ data も削除。'],
        ],
      },
      { type: 'heading', text: 'Trust review の読み方' },
      {
        type: 'table',
        columns: ['開示', 'Source', '確認する質問'],
        rows: [
          ['Executable + args', 'mcp.json stdio', '期待した interpreter/binary と bundled entrypoint か?'],
          ['Remote host + URL', 'Streamable HTTP/SSE', 'operator、destination、port、path を信頼するか?'],
          ['Environment 名', 'stdio env + credential schema', '各 variable がなぜ必要か?'],
          ['Capabilities', 'Skills、MCP transports、EvoFlux extension', 'plugin の目的に合う scope か?'],
        ],
      },
      {
        type: 'callout',
        tone: 'warning',
        title: 'Trust は permission bypass ではない',
        text: 'Trust は宣言 component を runtime に参加させるだけです。各 MCP tool call は agent selection、permission mode、sandbox を通ります。Skill activation は destructive 操作の authorization ではありません。',
      },
      { type: 'heading', text: 'Process と data の境界' },
      {
        type: 'code',
        language: 'text',
        caption: 'Host-mediated flow',
        code: 'plugin package (read-only files)\n        │ validate + trust review\n        ▼\ninstallation registry ── enabled? ──► Skill catalog\n        │                              MCP manager\n        └── private data/<id>/ ──────► PLUGIN_DATA + credentials env',
      },
      {
        type: 'p',
        text: '各 installation は package 外に安定 private data directory を持ちます。Update は installation ID と PLUGIN_DATA を保持。Credentials は厳しい permission で保存され、宣言 env 名を通じ stdio だけへ注入。host は override 後に PLUGIN_ROOT/PLUGIN_DATA を強制します。path、symlink、archive、URL、header、cwd、placeholder は runtime 前に validate されます。',
      },
      { type: 'heading', text: 'Skill と tool の visibility' },
      {
        type: 'table',
        columns: ['Concern', 'Rule'],
        rows: [
          ['Skill precedence', 'Project/user/admin > enabled plugins > EvoFlux built-ins。'],
          ['MCP configuration', 'Plugin は別 in-memory manager を使い global mcp.json を変更しない。'],
          ['Agent availability', '明示 MCP selection または同 installation Skill activation で ready tools を run に追加。'],
          ['WebBridge', '明示 safe capability のみ non-browser server を WebBridge run に保持。'],
          ['Failure isolation', '不正 Skill/server は隔離、fatal manifest/package は reject。'],
        ],
      },
      { type: 'heading', text: 'Enable 前 checklist' },
      {
        type: 'tips',
        items: [
          'publisher/source、digest、license、version を確認。',
          'SKILL.md の隠れ mutation、secret 要求、広すぎる claim を確認。',
          'executable、args、scripts、dependencies、cwd、write destination を確認。',
          'remote owner と header に live credential がないことを確認。',
          'environment field/capability がすべて必要か確認。',
          'least-privilege credential で無害な read-only call を test。',
          'behavior と result bounds を理解するまで permission ask を維持。',
        ],
      },
    ],
    related: ['agent-plugins', 'agent-plugins-authoring', 'permissions-modes', 'sandbox-settings'],
    openAction: { type: 'workbench', tool: 'plugins' },
  },
  {
    id: 'agent-plugins-troubleshooting',
    category: 'plugins',
    title: 'Agent Plugins troubleshooting と diagnostics',
    summary:
      'installation、Skill discovery、credentials、MCP startup、missing tools、stale link、packaging failure を決まった順序で診断します。',
    keywords: ['plugin error', 'mcp not ready', 'skill missing', 'credentials unsupported', 'plugin logs', 'validation diagnostic', 'stale plugin', 'archive error'],
    setup: 'package error 調査中は plugin を disabled に保ち、global MCP 変更や EvoFlux 再インストール前に Plugin Center diagnostics と `evoflux plugin inspect/show` を使います。',
    blocks: [
      { type: 'heading', text: '症状 → 原因 → 次の確認' },
      {
        type: 'table',
        columns: ['症状', 'よくある原因', '次の確認'],
        rows: [
          ['Import rejected', 'fatal manifest、unsafe archive/path、symlink、duplicate、size/ratio', 'package diagnostics と展開 directory inspect。'],
          ['Valid だが Skill がない', 'disabled、invalid/deep Skill、name collision', 'enable、直下 SKILL.md、precedence。'],
          ['Settings に MCP がない', 'disabled、invalid mcp.json、SSE のみ', 'server diagnostics と transport。'],
          ['MCP starting のまま', 'initialize しない、stdout 汚染', 'entrypoint 手動実行、log は stderr、dependency 確認。'],
          ['MCP error', 'command/args/cwd、credential、network/TLS', 'runtime error と trust/config 比較。'],
          ['Credentials unsupported', 'credential extension なし', 'fields を追加、Save、Validate、Refresh。'],
          ['Credentials incomplete', 'required field 不足、URL/type invalid', 'required を入力、設定済み secret の空欄は保持目的のみ。'],
          ['Agent に tool がない', 'server not ready、未 select/activate', 'agent MCP 選択または同 plugin Skill activate。'],
          ['Linked code が古い', '未 Save、runtime 未 reconcile', 'Save、Validate、Refresh、Disable/Enable。'],
          ['Update fail', 'replacement invalid、安全検査失敗', '新 package を update 前に inspect。'],
        ],
      },
      { type: 'heading', text: '順序付き diagnostic loop' },
      {
        type: 'code',
        language: 'shell',
        caption: 'CLI evidence',
        code: 'evoflux plugin inspect ./plugin-dir\nevoflux plugin list\nevoflux plugin show <installation-id>\nevoflux plugin disable <installation-id>\n# file/credentials を修正後:\nevoflux plugin enable <installation-id>',
      },
      {
        type: 'tips',
        items: [
          '1) plugin.json invalid のまま component debug せず package-level error を先に修正。',
          '2) source_type、root、version、digest、enabled state を確認。',
          '3) Skill と MCP diagnostics を個別確認。',
          '4) trust review と実 file/dependency を比較。',
          '5) required credentials を設定し value は chat/log に出さない。',
          '6) Settings → MCP servers の runtime error と tool names を確認。',
          '7) 同じ cwd と非 secret placeholder で entrypoint を test。',
          '8) 再 enable 後 ask mode で bounded read-only tool call。',
        ],
      },
      { type: 'heading', text: 'よくある stdio protocol mistake' },
      {
        type: 'table',
        columns: ['Mistake', 'Effect', 'Fix'],
        rows: [
          ['stdout に log', 'JSON-RPC stream 破損', '運用 log は stderr。'],
          ['shell expression を command に使用', 'shell 展開されず executable not found', 'command と args array を分離。'],
          ['caller cwd 前提の relative file', '手動成功、host 失敗', 'PLUGIN_ROOT または contained cwd。'],
          ['managed package へ書き込み', 'update で state 消失/permission fail', 'mutable state は PLUGIN_DATA。'],
          ['unbounded result/startup', '遅い/巨大 response', 'timeout、pagination、limit、sanitized error。'],
        ],
      },
      {
        type: 'callout',
        title: 'Global Settings で plugin MCP を「修正」しない',
        text: 'Plugin MCP は意図的に別管理です。plugin の mcp.json/credentials を修正して Validate/Reconcile します。duplicate global server は別 identity を作り本当の package 問題を隠します。',
      },
      { type: 'heading', text: 'Bug report に必要な evidence' },
      {
        type: 'tips',
        items: [
          'EvoFlux version/OS、packaged または dev。',
          'Plugin name/version/source type/digest（credential value は除外）。',
          'Package、Skill、MCP diagnostic code/message。',
          'Runtime state、sanitized error、transport、stable tool suffix。',
          '最小 plugin tree と redact 済み plugin.json/mcp.json。',
          'import/link/update/enable の正確な操作と disable/enable の差。',
        ],
      },
    ],
    related: ['agent-plugins', 'agent-plugins-authoring', 'agent-plugins-runtime-security', 'troubleshooting-connection'],
    openAction: { type: 'workbench', tool: 'plugins' },
  },
  {
    id: 'agents-settings',
    category: 'settings',
    title: 'Agents、Skills、MCP',
    summary:
      'Settings 下で Markdown エージェント、スキルパック、MCP サーバーを設定 — ツールはネイティブと同じ権限ルールを継承します。チームは work / coding にスコープされ、各モードに正しい specialist が出ます。',
    keywords: [
      'agents',
      'skills',
      'mcp',
      'stdio',
      'http',
      'sse',
      'tools',
      'frontmatter',
      'スキル',
      'エージェント',
      'MCP',
      'ツール'
],
    setup:
      'チームメンバーは Settings → Agents; パック検証は Settings → Skills; サーバー追加は Settings → MCP。チャットからは /skill: またはコマンドパレットの New Agent / New Skill ショートカット。',
    tricks: [
      'エージェントは YAML frontmatter 付き .md — diff 可能でバージョン管理しやすい。',
      'Settings → Skills では Work、Coding、Both ごとにスキルを作成・編集・表示・絞り込みでき、有効なスキルは一致するセッションの /skill: にだけ表示されます。',
      'MCP ステータスドット: ready / starting / auth / error / stopped。',
      'MCP ツールはネイティブと同じ権限ルールを継承。',
      'チームは work / coding にスコープ。',
      'コマンドパレットで Edit <agent>… や新規エージェント/スキル作成へジャンプ。',
      'tools_opt_out で code-owned ツール既定を無効化し、割り当て済み skill は skills リストから直接削除。',
      'Lead 専用ツール（ask_user、plan mode ヘルパー、一部 worktree ヘルパー）は specialist に付与されません。',
      'MCP サーバーが auth に留まるなら、composer スラッシュメニューを責める前に認証フローを完了。'
],
    blocks: [
      {
        type: 'p',
        text: 'Agents は役割、モデル、ツール、システムプロンプトを定義します。Skills は /skill: 経由で需要に応じて読み込む指示パック。MCP サーバーは stdio、HTTP、または SSE で外部ツールを公開。合わせて、製品をフォークせずチーム挙動を形作ります。',
      },
      {
        type: 'p',
        text: 'Markdown エージェントとスキルは git でレビューしやすい状態を保ちます。MCP はコア製品をフォークせずツール面を拡張しつつ、権限/sandbox がなお実行をゲートします。MCP は他のツールプロバイダ同様 — 最小権限から広げます。',
      },
      {
        type: 'p',
        text: 'Settings → Agents でチームメンバー編集; Settings → Skills でパック検証; Settings → MCP でサーバー追加とステータスドット監視。チャットでは /skill: またはパレットの New Agent / New Skill。Lead 専用ツール（ask_user、plan mode、worktree ヘルパー）は specialist に付与されません。',
      },
      {
        type: 'tips',
        items: [
          'Agents — .md + YAML frontmatter',
          'Skills — 検証後の /skill:',
          'MCP — stdio / HTTP / SSE',
          'Status dots — ready / starting / auth / error / stopped',
          'tools_opt_out — code-owned ツール既定を無効化',
          'Mode scope — work / coding チーム',
          'Lead-only tools — specialist には付かない'
],
      },
      {
        type: 'p',
        text: 'MCP サーバー追加手順: (1) Settings → MCP、(2) トランスポート選択、(3) コマンドまたは URL を設定、(4) ready を待つ（必要なら認証完了）、(5) ツール表示を確認、(6) ask モードで無害なツールを実行、(7) それから権限を緩める。',
      },
      {
        type: 'p',
        text: 'よくある失敗: 無効スキルがスラッシュメニューに出ると期待; 頭の中で specialist に Lead 専用ツールを付与; MCP を error のままチャットを再試行; 公開レポにコミットしたエージェント markdown へシークレットを入れる; モードスコープを忘れ Coding specialist が Work に出ない。',
      },
      {
        type: 'tips',
        items: [
          '横断: 有効化された Coding スキルが workflow を案内し、ネイティブ code_context がすべての retrieval action を検証・実行します。',
          '横断: workflows と skills はどちらも / に出るにはスコープ有効性が必要。',
          '横断: 権限 Always ルールは MCP ツールにも適用 — まず Once を優先。'
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
    title: 'Sandbox とアウトバウンド保護',
    summary:
      'ファイルシステムツールの deny glob、worktree 配置、プロセス制限、shell 環境、アウトバウンド PII リダクションを設定します。',
    keywords: [
      'sandbox',
      'deny',
      'isolation',
      'pii',
      'outbound',
      'worktree',
      'user_data',
      'glob',
      'サンドボックス',
      '拒否',
      '隔離',
      '保護'
],
    openAction: { type: 'settings', path: 'sandbox' },
    setup:
      'Settings → Sandbox。積極的な auto/bypass 権限モードの前に deny パターンを見直す。ページ上のヘルプポップオーバーが ** と * の glob 構文を説明します。',
    tricks: [
      'Deny パターンは ** と * glob; Settings のヘルプポップオーバーが構文を説明。',
      'Worktree 配置（repository vs user_data）は Sandbox ページにあります。',
      'アウトバウンド redact/block は有効時、コンテンツがプロバイダへ届く前に走ります。',
      'Sandbox は Goal モード下でも適用 — Goal はスコープを広げません。',
      'ブロックされたルートへのシンボリックリンクは拒否; シェルコマンドは拒否パス検査のためトークン化。',
      '日常コーディング速度には accept-edits または auto と厳しめ denylist を組み合わせ。',
      'モデルを信頼していても資格情報キャッシュや無関係ディスクを deny。',
      'glob 編集後はサンプルツール呼び出しで再テスト — 静かな誤 glob は「ツールが壊れた」ように感じます。',
      'ファイルシステム denylist を Settings → Browser ドメインポリシーと WebBridge 向けに組み合わせ。'
],
    blocks: [
      {
        type: 'p',
        text: '組み込みファイルシステムツールは、すべての権限モードで workspace root、read-only root、deny pattern を適用します。shell コマンドは明らかな denied path を検査しますが、OS レベルの containment なしでホスト上に直接実行されます。',
      },
      {
        type: 'p',
        text: '権限モードはいつ聞くかを決めます。組み込みツールにはアプリケーションレベルのパス検査が残り、shell コマンド検査はセキュリティ境界ではなくガードレールです。Goal モードも同じポリシーを維持します。',
      },
      {
        type: 'p',
        text: 'Settings → Sandbox を開く。deny glob を追加し、Coding の worktree 配置、プロセス制限、shell 環境を設定し、必要ならアウトバウンド PII redact/block を有効化。変更後にサンプルツール呼び出しで再テスト。WebBridge 向けに Settings → Browser ドメインポリシーと組み合わせ。',
      },
      {
        type: 'tips',
        items: [
          'Deny globs — ** と * パターン',
          'Worktree location — repository vs user_data',
          'Outbound PII — プロバイダ前に redact/block',
          'Symlinks — ブロックルートへの進入を拒否',
          'Shell tokenization — コマンドへの拒否パス検査',
          'Goal — sandbox スコープを広げない'
],
      },
      {
        type: 'p',
        text: 'Coding ノート PC 硬化手順: (1) 機微ルート（キー、クラウド同期、他クライアント）を列挙、(2) deny glob を追加、(3) worktree 配置を意図的に設定、(4) ポリシーが求めるならアウトバウンド redact を有効化、(5) ask 下でプローブツール実行、(6) それから速度のため accept-edits または auto を検討。',
      },
      {
        type: 'p',
        text: 'よくある失敗: ホームディレクトリワークスペースで空 denylist のまま bypass; シンボリックリンクを忘れる; アウトバウンド redact がシークレットを貼らないことの代替になると仮定; worktree を user_data に置きディスク使用が移動したと不思議がる; deny ヒットを MCP 認証失敗と混同。',
      },
      {
        type: 'tips',
        items: [
          '横断: プランが拒否パスを狙うときは sandbox と戦わず plan Reject。',
          '横断: 「ツール拒否」トラブルシューティングにはシールド + denylist が含まれる。',
          '横断: Coding worktree は Sandbox 配置ポリシーに従う。'
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
    title: 'Connection 設定',
    summary:
      'UI をバンドルローカル sidecar か、アクセスキー付きの外部 EvoFlux サーバー URL へ向けます — HealthDot が赤になったときの最初の停留所です。パッケージ版は一時ポートとトークンハンドシェイクのバンドル sidecar が既定です。',
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
      '接続',
      'サイドカー',
      'バックエンド',
      'アクセスキー'
],
    openAction: { type: 'settings', path: 'connection' },
    setup:
      'Settings → Connection（または HealthDot をクリック）。パッケージ版はバンドル sidecar が既定。ソースからは `make -C desktop dev` 前に `make dev` が上がっていることを確認。',
    tricks: [
      'バンドル sidecar は一時ポートとトークンハンドシェイク — 通常 URL を設定しません。',
      '外部モードには到達可能なサーバー URL とアクセスキーが必要。',
      'ソースからは `make -C desktop dev` 前に `make dev` を上げる。',
      '接続モード切替後、チャット送信前に Welcome/チーム準備を待つ。',
      'URL は問題ないがサブシステムが落ちているとき Diagnostics が Connection を補完。',
      'いつでも HealthDot をクリックして Connection へのショートカット。',
      '固まったバンドル sidecar は、無関係な設定を触る前にパッケージ版アプリを再起動。',
      '外部モード設定時にアクセスキーをチャットトランスクリプトへ貼らない。',
      'external → bundled へ切り替えたら、Providers が壊れたと仮定する前に HealthDot が緑に戻ることを確認。'
],
    blocks: [
      {
        type: 'p',
        text: 'Connection 設定はバンドルローカル FastAPI sidecar と外部 EvoFlux バックエンドを選びます。HealthDot は UI が健全なサーバーに届くかを反映します。大半のデスクトップユーザーはバンドルモードを離れません。',
      },
      {
        type: 'p',
        text: '誤った接続モードは Providers が完璧でも「チャットが死んだ」ように見えます。Connection を Providers と Diagnostics から分けると時間が節約されます: まず健全なバックエンドへ到達し、それから資格情報とサブシステムを確認。',
      },
      {
        type: 'p',
        text: 'Settings → Connection を開く。通常デスクトップ利用はバンドルのまま。リモートまたは別起動 API を意図するときだけ外部へ。いつでも HealthDot でここへショートカット。変更後、チャット送信前に Welcome/チーム準備を待つ。',
      },
      {
        type: 'tips',
        items: [
          'Bundled — 一時ポート + トークンハンドシェイク',
          'External — サーバー URL + アクセスキー',
          'HealthDot — Connection へのショートカット',
          'Welcome — sidecar/チーム準備を待つ',
          'From source — `make dev` のあと `make -C desktop dev`',
          'Diagnostics — URL は良いがサブシステムが失敗するとき'
],
      },
      {
        type: 'p',
        text: '赤 HealthDot 回復手順（パッケージ版）: (1) HealthDot をクリック、(2) バンドルモードを確認、(3) アプリを再起動して sidecar をリスタート、(4) Welcome が消えるまで待つ、(5) なお不健全なら Diagnostics、(6) それから Providers を触る。',
      },
      {
        type: 'p',
        text: '外部モード手順: (1) リモート/ローカル API を起動または特定、(2) base URL とアクセスキーをコピー、(3) Settings → Connection → external、(4) 保存、(5) ヘルスを待つ、(6) 小さなチャットで検証。通常の単機デスクトップ運用に戻るなら bundled へ戻す。',
      },
      {
        type: 'p',
        text: 'よくある失敗: Vite URL を API URL として打つ; `make dev` 前に Tauri シェルを起動; 「デバッグ」で external に切り替えて忘れる; Welcome 中にチャット送信; 緑 HealthDot を全サブシステム（MCP、git ホスト、WebBridge）健全の証明と扱う — それには Diagnostics。',
      },
      {
        type: 'tips',
        items: [
          '横断: はじめにのコールドスタート順は Connection 回復と一致。',
          '横断: ローカル sidecar 上の Scheduler cron はマシンが起きて健全である必要。',
          '横断: トラブルシューティングチェックリストは HealthDot → Connection から始まる。'
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
    title: 'Settings マップ',
    summary:
      'すべての設定ページの地図: providers、agents、skills、MCP、memory、connection、git、sandbox、browser、notifications、appearance、telemetry、diagnostics。どの関心事がどのページかを知ると探し回りを避けられます。',
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
      '設定',
      'マップ',
      '外観',
      '診断'
],
    openAction: { type: 'settings', path: '' },
    tricks: [
      'デスクトップはサイドバーレールに設定カテゴリを表示; モバイルは About ハブをナビ一覧として使う。',
      'Guidelines（このヘルプ）は Settings → About からもリンク。',
      'Telemetry は Settings → Telemetry に加え /telemetry にフルページがあります。',
      'Git & reviews は PR 接続と安全ポリシー（タイムアウト、max diff、force-with-lease）をホスト。',
      'Appearance にはテーマ、アクセント、フォント、モーション、ロケール（en / vi / ja）。',
      'Diagnostics はライブサブシステム検査 — HealthDot の二値信号を補完。',
      'Intelligence vs System vs Application のグループが、リスクのあるトグルをテーマ選択と混ぜない。',
      'Notifications にはテスト ping — フォーカス外アラートを信頼する前に使う。',
      'どの設定ページがトグルを持つか忘れたらコマンドパレットを開く。'
],
    blocks: [
      {
        type: 'p',
        text: 'Settings は Intelligence（Providers、Agents、Skills、MCP）、Knowledge（Memory / Dream）、System（Connection、Git & reviews、Sandbox、Browser、Notifications）、Application（Appearance、Telemetry、Diagnostics）、および About にグループ化されます。関心事は分かるがページ名が分からないときにこの地図を使います。',
      },
      {
        type: 'p',
        text: 'どのページがどの関心事を持つか知ると探し回りを避けられます: モデル vs エージェント vs sandbox vs ブラウザポリシーは意図的に分離され、リスクのあるトグルが意図的なままです。テーマ変更はメンタルモデルで force-with-lease の隣に置かないでください。',
      },
      {
        type: 'tips',
        items: [
          'Providers — API キー、OAuth、ローカルデーモン、モデルレジストリ',
          'Agents — チームメンバーごとのモデル、ツール、システムプロンプト',
          'Skills — /skill: 用の指示パック',
          'MCP servers — stdio / HTTP / SSE 外部ツール',
          'Memory — 長期 wiki + Dream スケジュール',
          'Connection — バンドル sidecar vs 外部 URL / アクセスキー',
          'Git & reviews — ホスト接続、タイムアウト、diff サイズ、force-with-lease',
          'Sandbox — deny glob、プロセス制限、worktree 配置、アウトバウンド PII',
          'Browser — 内蔵 WebView + WebBridge マスターポリシー',
          'Notifications — フォーカス外のデスクトップ/モバイルアラート; テスト ping',
          'Appearance — テーマ、アクセント、フォント、モーション、ロケール（en / vi / ja）',
          'Telemetry — トレースと要約（/telemetry も）',
          'Diagnostics — ライブサブシステムヘルス検査',
          'About — アプリ情報 + Guidelines リンク'
],
      },
      {
        type: 'p',
        text: '新マシンチェックリスト手順: (1) Connection 健全、(2) Providers 接続、(3) Agents モデル割当、(4) Sandbox denylist 見直し、(5) PR が必要なら Git & reviews ホスト、(6) 必要なら Browser/WebBridge ポリシー、(7) Appearance ロケール、(8) Notifications テスト ping、(9) About から Guidelines を一度開きヘルプ動作を確認。',
      },
      {
        type: 'p',
        text: 'よくある失敗: チャット失敗時に Appearance をいじる; Dream cron を Scheduler 下に探す; PR ホストトークンを Providers 下に探す; モバイル設定クロムがデスクトップレールレイアウトと一致すると期待; HealthDot が緑だから Diagnostics を無視。',
      },
      {
        type: 'tips',
        items: [
          '横断: 主要な Guidelines 記事は利用可能なとき openAction で正しいページへディープリンク。',
          '横断: ロケール変更は UI クロムのみ — チャット本文は書いたまま。',
          '横断: 空の telemetry はしばしば extras 無効を意味し、チャット障害ではない。'
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
    title: 'キーボードショートカット',
    summary:
      'EvoFlux は OS 標準の主要修飾キーを使います — macOS は Command、Windows/Linux は Ctrl。Guidelines（Help）はコマンドパレットとは別です。',
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
      'ショートカット',
      'キーボード',
      'ホットキー',
      'パレット'
],
    tricks: [
      '主要修飾キー + P はコマンドパレット（サイドバーの Search）。Help はこの Guidelines モーダルを開く — パレットではない。',
      'ショートカット表示は自動更新: macOS は ⌘、Windows/Linux は Ctrl。',
      '入力中は copy/paste/select/undo のネイティブ編集操作を優先し、ペースト時は表示循環ショートカットを抑止。',
      'Ctrl+B はすべてのモードサイドバー向けに AppShell が一度所有。',
      'Ctrl+R は Work セッションのみ更新（アプリ全体のリロードではない）。',
      'バインディングを忘れたらアクション名で Ctrl+P 検索を優先。',
      'キー 1–5 はシールドメニューが開いているときだけ権限モードを切り替え。',
      'Ctrl+I はチャット入力にフォーカス — workbench パネルを渡り歩いたあとに便利。'
],
    blocks: [
      {
        type: 'p',
        text: 'グローバルナビと workbench ショートカットは macOS で Command、Windows/Linux で Ctrl を使います。表示バッジと実際のバインディングは同じ platform ルールから解決されます。',
      },
      {
        type: 'p',
        text: '入力欄にフォーカスがある間はネイティブ編集ショートカットが優先されます。それ以外では下表が OS の主要修飾キーを使います。',
      },
      {
        type: 'shortcuts',
        rows: [
          { keys: 'Ctrl+P', action: 'コマンドパレット' },
          { keys: 'Ctrl+N', action: '新しいチームチャット' },
          { keys: 'Ctrl+B', action: 'サイドバーをトグル' },
          { keys: 'Ctrl+V', action: 'Agent ↔ Split を循環（デスクトップ; ペースト中は除く）' },
          { keys: 'Ctrl+F', action: 'Files / Changed & Files（ラベルは ⌘P の場合あり）' },
          { keys: 'Ctrl+M', action: 'Memory wiki' },
          { keys: 'Ctrl+S', action: 'Scheduler' },
          { keys: 'Ctrl+K', action: 'Plugins' },
          { keys: 'Ctrl+T', action: '内蔵ブラウザ' },
          { keys: 'Ctrl+G', action: 'Git Changes（Coding）' },
          { keys: 'Ctrl+`', action: 'Terminal' },
          { keys: 'Ctrl+I', action: 'チャット入力にフォーカス' },
          { keys: 'Ctrl+;', action: 'Side chat（ラベルは ⌥⌘S の場合あり）' },
          { keys: 'Ctrl+R', action: 'Work セッションを更新' },
          { keys: '1–5', action: 'シールドメニューが開いているときの権限モード' }
],
      },
      {
        type: 'p',
        text: 'バインディングを忘れたらコマンドパレット（Ctrl+P）を優先 — 大半のアクションは名前で検索可能。Guidelines（Help）は別のままなのでパレット検索はコマンド中心。Graph と Review は専用グローバルショートカットがないため workbench バーまたはパレットに依存。',
      },
      {
        type: 'tips',
        items: [
          'Help ボタン — Guidelines モーダル（ドキュメント）',
          'Ctrl+P — コマンドパレット（アクション）',
          '⌘P / ⌥⌘S ラベル — 古い; Ctrl+F / Ctrl+; を使う',
          'Ctrl+V — ペースト中は表示循環が抑止',
          'Ctrl+R — Work セッション更新のみ',
          '1–5 — シールドメニューが開いているときだけ'
],
      },
      {
        type: 'p',
        text: 'よくある失敗: macOS で Cmd+P を押してパレットを期待; Ctrl+R でアプリ全体リロードと思い込む; composer ペースト中に Ctrl+V と戦う; Graph に隠れたホットキーがあると仮定; パレットのつもりで Help（またはその逆）を開く。',
      },
      {
        type: 'tips',
        items: [
          '横断: 権限シールド + 1–5 はモードクリックより速い。',
          '横断: Goal 中に /stop なしで Ctrl+; side chat。',
          '横断: plan Accept 後に Ctrl+G で diff 検証。'
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
    title: '接続と Diagnostics',
    summary:
      'バックエンドが落ちた、セッションが失敗した、ヘルス検査が赤になったとき — HealthDot、Connection、Diagnostics、よくある修正チェックリストを使います。再インストール前に接続、プロバイダ、権限、WebBridge 失敗を切り分けます。',
    keywords: [
      'troubleshoot',
      'connection',
      'health',
      'diagnostics',
      'sidecar',
      'HealthDot',
      'make dev',
      'error',
      '接続',
      '診断',
      'トラブル',
      'エラー',
      'ヘルス'
],
    setup:
      'サイドバーフッタの HealthDot から始める。Settings → Connection と Settings → Diagnostics を近くに。ソースからは 2 ターミナル準備: `make dev` と `make -C desktop dev`。',
    tricks: [
      'HealthDot → Connection をクリックし、バンドル vs 外部バックエンドを確認。',
      'Settings → Diagnostics はサブシステム横断のライブ検査を実行。',
      'コールドスタートでは sidecar とチーム準備まで Welcome — チャット再試行前に待つ。',
      'ソースから: Terminal 1 `make dev`、Terminal 2 `make -C desktop dev`。',
      'モデル一覧が空 → 何より先に Settings → Providers。',
      'ツールが突然拒否 → 権限モード + Sandbox deny glob。',
      'WebBridge オフライン → 拡張インストール、ペアリング有効、Browser 設定有効、per-chat トグルオン。',
      '空の telemetry → observability/DuckDB extras が無効の可能性 — 必ずしもチャット障害ではない。',
      'Goal が詰まった → blocker streak、予算一時停止、または /goal:stop を確認。',
      '/scheduler が 404 っぽい → Ctrl+S パネルを使う; ルートはホームへリダイレクト。'
],
    blocks: [
      {
        type: 'p',
        text: '大半の「EvoFlux が壊れた」報告は接続、プロバイダ、権限、または WebBridge ペアリングの問題です。HealthDot は二値信号; Diagnostics は詳細パネル; Connection は UI が話すバックエンドを選びます。再インストール前にその順で直します。',
      },
      {
        type: 'p',
        text: 'UI は上がっていても、sidecar がなお起動中、誤った URL を指している、またはプロバイダ資格情報が欠けることがあります。それらの失敗モードを分けると時間が節約され、本当の原因を隠す破壊的な「全部リセット」反射を避けられます。',
      },
      {
        type: 'p',
        text: 'HealthDot を確認。不健全なら Connection を開きバンドル sidecar vs 外部 URL/キーを確認。ソースからは `make dev` と `make -C desktop dev` の両方が走っていることを確認。パッケージ版は再起動で sidecar をリスタート。その後 Diagnostics でサブシステム検査。ヘルスが緑になってから Providers、権限モード、Sandbox、Browser/WebBridge を検証。',
      },
      {
        type: 'tips',
        items: [
          'HealthDot 赤/琥珀 → Connection + Welcome/チーム準備を待つ',
          'ソース実行 → `make dev` のあと `make -C desktop dev`',
          'モデルなし → Settings → Providers',
          'ヘルス緑でストリームエラー → モデル/プロバイダ資格情報またはレート制限',
          'ツール拒否 → 権限モード（ask/plan）+ Sandbox deny glob',
          'WebBridge オフライン → 拡張、ペアリング、Browser ポリシー、per-chat 有効化',
          '空の telemetry → observability extras 無効（しばしば非ブロッキング）',
          'Goal 詰まり → blocker streak、予算一時停止、または /goal:stop を確認',
          '/scheduler が 404 っぽい → Ctrl+S パネル; ルートはホームへリダイレクト',
          '古い graph → 巨大な外部編集後に Graph ツールから再インデックス'
],
      },
      {
        type: 'p',
        text: '順序付きチェックリスト: (1) HealthDot、(2) Connection モード、(3) Welcome/チーム準備、(4) Diagnostics、(5) Providers、(6) 権限シールド、(7) Sandbox denylist、(8) Browser/WebBridge、(9) モード固有ツール（Changes/Graph/Review は Coding のみ）。最初に失敗した層で止める。',
      },
      {
        type: 'p',
        text: 'よくある失敗: 欠けたプロバイダキーのために再インストール; HealthDot が赤のうちに MCP をデバッグ; 緑ヘルスを Ollama 稼働の証明と扱う; Ctrl+R でフルリロードを期待する強制更新（Work セッション更新のみ）。',
      },
      {
        type: 'tips',
        items: [
          '横断: はじめにのコールドスタート順はこのチェックリストと一致。',
          '横断: Accept 待ちの plan review はハングではない — パネルを解決。',
          '横断: side chat フォーカスの誤りは「Lead が無視した」ように見える。',
          '迷ったら — Diagnostics + 小さな Work ping が推測リセットに勝つ。'
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
