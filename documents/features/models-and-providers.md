# Models and providers

EvoFlux uses a provider-neutral streaming schema while preserving each model's
actual capabilities. Model availability, model metadata and adapter support are
separate facts and are intersected before the UI or runtime enables a control.

## Provider catalogue

Providers come in three tiers, in the order of how much EvoFlux knows about
each:

| Tier | Count | What it is |
|---|---|---|
| **Curated** | ~37 | A hand-written integration: OAuth or cloud credential flows, a wire dialect, attribution headers, a deliberate endpoint, a dedicated adapter class. Declared in `app/agent/providers/registry.py`. |
| **Plugin** | any | Installed through the provider plugin registry. |
| **Catalogue** | ~165 | Everything else models.dev lists that is reachable from a base URL and a bearer token. No code, no entry — the row, the credential form, the endpoint and model discovery are all derived. |

That means every provider on models.dev — around 200, API-key and
subscription plans alike — can be configured and used, while only the ones
that need code carry any.

A settings row is *derived*, never restated. Connection facts (label,
credential variable, endpoint, docs link, auth mode) come from the registry;
catalogue facts (display name, credential names, endpoint, model docs, logo)
come from models.dev. What is left in `catalog.py`'s `_OVERRIDES` is only
what neither can say: the one-line description a person wrote, the
multi-field credential forms cloud providers need, curated fallback model
lists, OAuth commands, and metadata aliases. A test fails if an override
restates a derivable field.

Curated rows keep their identity where EvoFlux renamed a provider —
`googlegenai` reads `google`, `qwencloud` reads `alibaba` — and the
catalogue tier skips those IDs so the same endpoint is never offered twice.
A rename is only claimed when the catalogue ID is not itself an EvoFlux
provider: Codex reads OpenAI's model rows through
`metadata_source_provider` without taking them over.

The long tail is not contacted when the settings page loads, and lists its
models only when the user asks. Beyond saving 165 requests, several
providers share one credential variable across regional and plan variants
(`XIAOMI_API_KEY`, `MINIMAX_API_KEY`, `ZHIPU_API_KEY`), and a key must not
be sent to a variant nobody selected.

### Suggestion order

With ~200 providers reachable, a flat alphabetical list makes the choice
harder rather than easier, so the settings page leads with a short
**Recommended** group: the frontier vendors most agents are written against,
the subscriptions a user may already pay for (Codex, Copilot), and MiMo.
`RECOMMENDED_PROVIDERS` in `registry.py` is that list — a product judgement,
deliberately a plain ordered tuple rather than something inferred from model
counts or pricing. MiMo-Code ranks its own provider prompts the same way.
Everything else curated follows under **Also supported**, alphabetically.

### Plan and regional variants

Several vendors publish one API under several catalogue rows: a
pay-as-you-go endpoint plus regional and subscription-plan variants, whose
model lists differ. A user on a plan endpoint configures the curated
provider and points its base URL at the plan, so their models resolve under
`xiaomi:` and would miss every sibling row's metadata.

Sibling rows are matched on two signals together, because either alone is
wrong: a **shared credential variable** (two rows reading the same secret
are the same account at the same vendor) *and* a **name that marks the
candidate as a variant** of that row (`xiaomi` → `xiaomi-token-plan-sgp`).
The credential alone would fuse genuinely different products — Kimi Code and
the Moonshot platform both read `MOONSHOT_API_KEY`. Local providers are
excluded outright: a quantized checkpoint shares its name with the hosted
model but not its limits.

Sibling metadata fills **gaps only**. A model the provider's own row
describes always wins, because that row matches the endpoint EvoFlux
resolves by default.

### Provider logos

models.dev publishes a mark for every provider it lists, at
`https://models.dev/logos/{id}.svg`, drawn with `fill="currentColor"` so it
inherits the UI's text colour in either theme. EvoFlux proxies and caches it
at `GET /api/settings/providers/{id}/logo` rather than linking it, so the
renderer makes no third-party request and the icons keep working offline
after first fetch. The providers most users connect first keep a bundled
glyph so they paint with no request at all; a provider in neither set falls
back to its initial. Fetched SVGs are rejected unless they are plain markup
— no script, no `foreignObject`, no event handlers — because the cached file
is served back by this API.

### Model detail in settings

The per-provider model list renders what the catalogue knows about each
model — display name, description, context window, knowledge cutoff,
reasoning levels, and vision/tools/files flags — rather than the bare
`provider:model` string it used to show, which told a reader nothing they
had not already typed. `POST /providers/{id}/models` returns that as
`model_details`; models the catalogue has never seen still list, with just
their ID.

### Alternate service tiers

A tier is the same model served differently: OpenAI's `service_tier:
priority`, Anthropic's fast-mode beta, Codex's subscription fast lane. Each
is selected by a small body patch — some also by a header — and each bills at
its own rate.

Those patches come from the catalogue's `experimental.modes` and are carried
**verbatim**: nothing in EvoFlux knows what `speed` or `service_tier` mean,
only where to put them, which is what lets a tier work as soon as the
catalogue lists it. `PROVIDER_MODES` adds the tiers no catalogue publishes
because they belong to a plan rather than a model's public API — Codex's
fast lane — in the same shape, and its patch holds the *wire* value so no
consumer repeats the translation.

`service_tier_fields()` resolves a requested tier into `(body, headers)`,
applied by the Chat Completions, Responses and Anthropic request builders.
On OpenAI-shaped endpoints an explicit tier the catalogue does not describe
is still forwarded verbatim, because `service_tier` is a real field there
and `flex`/`priority` are documented; on Anthropic it is not, so nothing is
invented.

A fast lane commonly bills at **2-2.5x** the standard output rate, so the
composer's Speed control states the multiplier before it is switched on.
It comes from the tier's own published rate (`mode_cost_multiplier`); a tier
with no rate is reported as unknown rather than as parity.

### Reasoning controls in the UI

Two questions have different answers, and conflating them is how a setting
gets silently dropped:

- **Will this request be honoured?** — `selectable_levels()`. For a
  toggle-only model the answer is yes at every level: the payload that
  switches reasoning on has to be sent regardless, and on GLM it also
  carries `clear_thinking: false`, which is what keeps the trace in the
  response.
- **Does the choice change anything?** — `offered_levels()`, which is what
  the model catalogue endpoint advertises and every picker renders. Here the
  toggle dialects have to say no: GLM sends the same bytes at every level,
  so a ladder would be several ways to press one switch. A model whose level
  really does reach the wire keeps its ladder — MiMo publishes a bare toggle
  but takes a token budget, so `low` and `high` buy different amounts of
  thinking.

The chat composer, Agent/Team settings and the agent-spawn dialog all read
`offered_levels`, and every validator — the chat route, the agent-spawn
check, the WebBridge route, Copilot's per-model allowlist and the runtime
execution policy — reads `accepts_thinking_level`, which is backed by
`selectable_levels`. Before they were consolidated each answered from its
own source, with two consequences: a level the picker offered could be
rejected with a 422, and the runtime clamped a request for `high` on a
toggle-only model down to `none` — thinking switched off precisely when the
most was asked for, and silently.

Level names are normalized on both sides, so a provider's live catalogue
reporting `ultra` matches a request for `max`.

### Free models

Around 600 models across 70 providers cost nothing per token: genuinely free
tiers, and models included in a subscription plan. The model catalogue
endpoint marks these `free`, the picker badges them and offers a filter, and
each provider row shows how many of its models are free before you connect.
All of them still need that provider's own credential.

## Model identity and selection

Runtime model IDs use `provider:model`. A default model can be set during
initialization, then overridden per agent or per session. Reasoning level and
other controls are validated against the effective capability profile before a
turn starts.

Settings can discover live models, test credentials, retain a visible-model
subset and show provider usage where an adapter supports it. Credentials are
stored in the config `.env` or the provider's OAuth/cloud store; API responses
mask secrets.

QwenCloud uses `DASHSCOPE_API_KEY` and defaults to the international
pay-as-you-go OpenAI-compatible root
`https://dashscope-intl.aliyuncs.com/compatible-mode/v1`. Pay-as-you-go,
Token Plan and Coding Plan keys are not interchangeable: subscription keys
must be paired with the complete Base URL shown for that plan through
`DASHSCOPE_BASE_URL`. The adapter supports both Chat Completions and Responses,
disables server-side Responses storage, and preserves Qwen `reasoning_content`
across supported multi-turn tool flows. Media generation/realtime endpoints and
QwenCloud-hosted built-in tools are outside this integration.

QwenCloud documents that Token Plan Individual is for interactive programming
and agent tools and may prohibit automated scripts, application backends and
non-interactive batch use. Users must verify their plan terms before selecting
that credential for EvoFlux schedules or other unattended runs.

## What the catalogue owns, and what the code owns

The dividing line is deliberate: anything an upstream catalogue publishes is
read, not restated. Restating it produces a constant that is correct on the day
it is written and silently wrong afterwards, which is how a provider moving its
API or a model gaining a reasoning level becomes a bug report instead of a
refresh.

`models.dev` owns, per provider: the endpoint (`api`), the credential variable
names (`env`), the display name, the model documentation link, and the adapter
package (`npm`) that implies the wire protocol. Per model it owns: context and
output limits, per-token prices including long-context tiers, input/output
modalities, tool-call/attachment/temperature/structured-output support,
lifecycle (`status`, release and update dates, knowledge cutoff), the field its
reasoning trace streams in (`interleaved`), any alternate service tiers
(`experimental.modes`), and — the piece that removed the most code —
`reasoning_options`.

EvoFlux owns only what no catalogue publishes:

- **Wire dialect.** How a named effort is spelled: `reasoning_effort`,
  `thinking.budget_tokens`, `thinkingConfig`, `reasoningConfig`. See
  `app/agent/providers/thinking.py`.
- **Deliberate endpoint divergences,** such as Cohere's OpenAI-compatibility
  root rather than its native v2 surface. A curated `base_url` is an *override*;
  where the catalogue already publishes the same URL, the field is absent and a
  test fails if one is reintroduced.
- **Endpoints no catalogue carries** — local daemons, and the ~18 first-party
  providers whose `api` the catalogue leaves null because their SDK hardcodes it.
- **Attribution headers, OAuth flows, and plan-level service tiers** such as
  Codex's fast lane, which belongs to a ChatGPT subscription rather than to any
  model's public API. Attribution is applied by
  `options.provider_request_headers()` from every request builder, so a
  gateway can attribute the traffic.

  The catalogue's own `experimental.modes` — OpenAI's `service_tier: priority`,
  Anthropic's fast-mode beta — is read and carried in model metadata but is
  *not* advertised as available, because no request builder puts those patches
  on the wire yet and they bill at a multiple of the standard rate. The model
  catalogue endpoint reports only tiers EvoFlux can actually use, so the
  composer's Fast toggle never appears for a tier that would do nothing.
  Wiring one up is a table entry plus the request-builder change that makes it
  real.
- **Adapter constraints** — controls a model documents that EvoFlux's own
  transport cannot express.

Provider envelopes and per-model metadata are both bundled
(`provider_catalog.json` at ~42 KB, `model_registry.json` at ~4.4 MB) so a
cold, offline install resolves every provider *and* knows what every model
can do. The whole catalogue is bundled rather than the curated subset: since
EvoFlux can use any provider models.dev lists, restricting it would leave the
long tail with real credentials, a real endpoint and every limit and price
reading "unknown" until the catalogue downloads — a silent failure, and a
worse trade than the bytes. `--curated-only` keeps the smaller shape for
anyone who wants it. Refresh both with
`python scripts/update_model_registry.py`; `--check` fails when they are
stale.

### Reasoning controls

`reasoning_options` is a *list*, because one model often exposes several
controls at once. They compose:

| Option | Meaning | Effect |
|---|---|---|
| `effort` | Named efforts, e.g. `["low","medium","high","xhigh","max"]` | Becomes the selectable ladder |
| `toggle` | Reasons by default, can be switched off | Adds `none` to the ladder |
| `budget_tokens` | Continuous knob, optional `min`/`max` | Bounds the budget; alone, the ladder is sampled at low/medium/high |

`control` names the strongest present — efforts beat a budget, a budget beats a
bare toggle — and that is what selects the wire form. It is why Gemini 3 gets
`thinkingLevel` while Gemini 2.5 gets `thinkingBudget`, and why a Claude
generation publishing named efforts gets the adaptive descriptor while one
publishing a budget gets `budget_tokens`, with no model-name matching anywhere.

Budgets are the product's per-level ceiling clamped into the bounds the model
publishes, never at or above the completion allowance.

A model absent from the catalogue is unknown, not unsupported: it falls back to
what its dialect accepts. An explicit empty `reasoning_options` is the
catalogue asserting there are no controls, and is respected as such.

## Capability resolution

The resolver combines:

1. live provider catalogue facts;
2. bundled registry and refreshed `models.dev` metadata for missing fields;
3. local `model_registry.yaml` corrections;
4. the actual features implemented by the selected adapter.

Unknown capabilities default off. Name/prefix guessing is not sufficient to
enable vision, tools or reasoning. `Default` means omit an override; `Off` is
shown only when the provider has an explicit off wire value.

See [Provider model capability flow](../architecture/model-capability-flow.md).

## Generic runtime contract

Adapters translate generic system/human/assistant/tool messages, content parts,
tool schemas, reasoning settings, usage and streamed chunks to provider-specific
wire formats. Provider exceptions are normalized for retry/fallback and safe
display. Provider payload shapes do not leak into the team/session API.

Model calls can include bounded multimodal content only when both the model and
adapter advertise support. Tool call IDs/results are normalized across APIs.

## Cost accounting

Every rate comes from the catalogue, per million tokens, and three things
move a turn off the headline price — all three published, all three applied:

- **Long-context tiers.** Past a threshold the provider bills the *whole*
  request at a higher rate, not just the tokens beyond it. A 300K-token turn
  on a model with a 200K tier costs double what the headline implies.
- **Alternate service tiers.** A `fast` lane bills at its own rate, so a turn
  that used one is priced at that rate rather than the standard one.
- **Separately metered reasoning.** Where a model quotes `cost.reasoning`,
  thinking tokens are billed at it and removed from the output count, so
  they are not charged twice.

Components are recorded per turn — input, output, cache read, cache write,
reasoning — and each becomes its own span attribute. A total alone cannot
show that most of a model's spend was cache traffic, which is the half a
caller can act on. The Models tab aggregates them into a burn report, plus a
blended **$/1M** that folds in cache efficiency: two models on the same
headline price diverge there entirely on how well their prefix cached, which
is the comparison a price list cannot make.

## Prompt caching and cost accounting

EvoFlux preserves provider-reported total input while tracking cache reads and
cache writes as disjoint subsets. Estimated token cost prices ordinary input,
cache reads, cache writes and output separately when the selected
`provider:model` has matching registry prices. Codex, Copilot, Kimi Code and
Ollama are subscription/local integrations rather than token-billed API
surfaces, so EvoFlux does not present registry-equivalent token prices as
actual spend for them.

Provider cache behavior remains adapter-specific:

- Anthropic and Foundry-hosted Claude use Anthropic's top-level ephemeral
  automatic cache control.
- Supported Anthropic Claude and Amazon Nova models on Bedrock Converse receive
  one trailing cache checkpoint. Other Bedrock families are left unchanged.
- DeepSeek, Gemini/Vertex, QwenCloud, Z.AI and Xiaomi retain their provider-side
  implicit cache behavior and normalize their reported cache-hit tokens.
- Native OpenAI/Foundry OpenAI and Codex receive an opaque stable
  `prompt_cache_key`; OpenRouter receives `session_id`; xAI Chat Completions
  receives `x-grok-conv-id`. The key is derived from, but does not expose, the
  local session ID.
- OpenRouter Anthropic routes use top-level automatic caching. Other
  OpenRouter models retain their upstream provider's implicit behavior.

Explicit Qwen/GPT-5.6 breakpoints and managed Gemini cached-content resources
are not enabled automatically because cache writes can cost more than ordinary
input when a prefix is not reused. Cache controls never change tool permission,
outbound redaction or sandbox boundaries.

## EASD role guidance for GPT-5.6 family

When the Codex OAuth catalogue exposes the GPT-5.6 family, EASD benchmarks and
high-assurance runs prefer:

| Role | Model | Typical reasoning |
|---|---|---|
| Lead/convergence owner | `codex:gpt-5.6-sol` | high/xhigh |
| Architect or independent verifier | `codex:gpt-5.6-sol` | high |
| Builder mission | `codex:gpt-5.6-terra` | medium/high |
| Narrow repeatable exploration | `codex:gpt-5.6-luna` or Terra | medium |

This is a role policy, not hard-coded routing. Provider availability, visible
models, per-agent configuration, capability validation, user overrides, and
budget remain authoritative. Official OpenAI documentation recommends GPT-5.6
for demanding multi-step agents, Terra for efficient read-heavy workers, and
Luna for narrow repeatable work.

## Source and tests

Primary code: `app/agent/providers/registry.py` (provider resolution),
`model_registry.py` (catalogue normalization), `model_metadata.py` (per-model
resolution), `thinking.py` (effort translation), `catalog.py`, `factory.py`,
`capabilities.py`, `model_discovery.py`, provider subpackages, Settings routes
and model-picker components. `scripts/update_model_registry.py` regenerates the
bundled snapshots.

Every provider has adapter/factory tests; shared suites cover streaming,
capability resolution, discovery, tool content, unconfigured providers and
model metadata.
