---
name: super-research
description: "Runs long-horizon autonomous research that stays comparable, honest, and auditable across many attempts: fixes a contract, records a baseline, logs every attempt including failures to a TSV, and continues to an agreed stopping condition. Covers eight research modes: multi-source topic surveys and literature reviews with cited reports, academic paper drafting and .bib/.tex citation audits, experiment loops that move a measured metric, benchmark comparisons across candidates, ablation studies, root-cause investigations of regressions, hypothesis-first quantitative analysis of CSV/parquet data, and paper reproductions from an arXiv id, DOI, or PDF. Use when the user asks for \"deep research\", \"survey\", \"optimize this metric\", \"compare X vs Y\", \"ablate\", \"why is this broken\", \"reproduce this paper\", \"check every citation\", \"调研\", \"消融实验\", \"复现论文\". Not for a single quick answer or work with no measurable outcome."
---

# Autonomous Research

The value of this skill is not the specific procedure — it is the property that research work done under it is **comparable, honest, and auditable**. Ten cheap experiments, queries, or analyses done to the same standard beat one clever untested claim. This is what lets a human check in eight hours later and trust what they see.

The method is distilled from Karpathy's [autoresearch](https://github.com/karpathy/autoresearch) and generalized to eight research modes.

## Shared discipline (all modes)

Every mode operates under the same five rules. Read them before branching into a mode.

1. **State a contract before you begin.** Infer everything you can from the workspace and the request, then write down the goal, the primary output, and the stopping condition, and get one confirmation. This is your last question. After confirmation you are autonomous.

2. **Establish a baseline as your first artifact.** Every mode has a version of "the answer without any of my work" — the unmodified code, the first three sources found, the raw dataset before any transformation. Record it first. Without a baseline, "better" and "significant" are meaningless.

3. **Log every step in a machine-readable file, including failures.** A tab-separated log (TSV, not CSV — descriptions contain commas) with a header row and one row per attempt. Failed attempts get a `crash` / `dead-end` / `inconclusive` status. Silently discarding attempts is the fastest way to fool yourself and the user; the log is the evidence that the work happened.

4. **Never pause to ask permission mid-loop.** Once the contract is confirmed, do not stop to check in, propose stopping at a "natural break", or ask "should I keep going?". The human may be asleep and expects to wake up to a full log. The loop ends only at the agreed stopping condition or a manual interruption. **This is the single most common failure mode of autonomous runs.**

5. **Never game the metric, the sources, or the analysis.** Do not edit the eval code because it is "clearly wrong". Do not drop a source because it does not fit the thesis. Do not p-hack or cherry-pick a subset that gives a nicer number. If the ground truth looks wrong, log the concern in the description column and keep going — the human decides later.

## Pick a mode

Pick one of the eight modes from the request. If it is ambiguous, pick the closest and state the choice in the contract. Then read the mode's reference file **before writing the contract** — it specifies the mode-specific contract fields, the exact log schema, the loop, and the report format.

| Mode | Triggering signals | Read |
| --- | --- | --- |
| **Experiment loop** | "optimize", "tune", "run experiments", "improve this model", "hill-climb", "get the metric down/up", "自动实验", any measurable code-in-repo goal | [references/experiment-loop.md](references/experiment-loop.md) |
| **Topic survey / 主题调研** | "survey", "literature review", "deep research", "research this topic", "调研", "gather evidence on", "what does the field say about", "state of the art" | [references/topic-survey.md](references/topic-survey.md) |
| **Quantitative analysis / 量化分析** | "analyze this dataset", "量化分析", "test whether X relates to Y", "estimate the effect of", CSV/parquet/dataframe in the workspace | [references/quant-analysis.md](references/quant-analysis.md) |
| **Benchmark comparison / 对比评测** | "compare X vs Y", "which of these should we use", "benchmark these", "选型", "对比评测", picking one candidate from an explicit list | [references/benchmark-comparison.md](references/benchmark-comparison.md) |
| **Root-cause investigation / 根因排查** | "why is X broken", "root cause this", "debug the regression", "why is it flaky", "排查", "定位", "复盘", any "used to work, now doesn't" | [references/root-cause.md](references/root-cause.md) |
| **Ablation study / 消融实验** | "ablate", "which parts of X matter", "attribution study", "消融实验", "is Y pulling its weight", "leave-one-out" | [references/ablation-study.md](references/ablation-study.md) |
| **Paper reproduction / 复现论文** | "复现这篇论文", "paper to code", "implement this method", "reproduce the main table", an arXiv id / DOI / PDF handed over | [references/paper-reproduction.md](references/paper-reproduction.md) |
| **Paper writing + citation audit / 写论文 & 引用校验** | "write a paper on X", "polish this draft", "查引用", "citation check", "校验引用", "detect fabricated references", any `.bib` or `.tex` to audit | [references/paper-writing.md](references/paper-writing.md) |

**Adjacent modes — pick carefully:**
- Experiment loop vs benchmark: the experiment loop *improves one thing* (edit → measure → keep/revert). A benchmark *compares many things* (fair matrix, no tuning of the favorite). A winner among candidates is a benchmark; moving the metric on a single system is an experiment loop.
- Experiment loop vs ablation: both edit and re-measure, but ablation attributes rather than optimizes — keep every result whether the metric moves or not, and never stop early after finding a big effect.
- Root-cause vs experiment loop: root-cause investigates a *broken* baseline; the experiment loop hill-climbs a *working* one. The log schema and stopping rule differ.
- Topic survey vs paper writing: a survey *reads* the literature to answer a question; paper writing *produces* a paper and audits its bibliography. "Write a lit review" is a topic survey followed by paper writing — chain them.
- Paper reproduction vs experiment loop: reproduction targets someone else's numbers (the paper's table); the experiment loop targets a metric on your own system. "Beat the paper's numbers on our task" is an experiment loop starting from a reproduced baseline.

## Paper-writing section guides

In paper-writing mode, read [references/paper-writing.md](references/paper-writing.md) first, then read only the guide that matches the section being written or revised. Do not preload guides for unrelated work.

- Abstract: [references/paper-writing/abstract.md](references/paper-writing/abstract.md)
- Introduction (task framing, technical-challenge paragraphs, pipeline paragraph): [references/paper-writing/introduction.md](references/paper-writing/introduction.md)
- Related work: [references/paper-writing/related-work.md](references/paper-writing/related-work.md)
- Method (module design, motivation, overview subsection): [references/paper-writing/method.md](references/paper-writing/method.md)
- Experiments (comparisons, ablations, tables): [references/paper-writing/experiments.md](references/paper-writing/experiments.md)
- Conclusion: [references/paper-writing/conclusion.md](references/paper-writing/conclusion.md)
- Sentence and paragraph polish of an existing draft: [references/paper-writing/paragraph-flow.md](references/paper-writing/paragraph-flow.md)
- Adversarial pre-submission review: [references/paper-writing/paper-review.md](references/paper-writing/paper-review.md)
- LaTeX/PDF compilation and export: [references/paper-writing/pdf-export.md](references/paper-writing/pdf-export.md)

## Toolbox (scripts/)

Four of the eight modes — topic survey, paper reproduction, paper writing, and the experiment loop's literature-search escalation — rely on three Python scripts that query free scholarly APIs (arXiv, Semantic Scholar, OpenAlex, Crossref). They use only the Python standard library: **no API keys, no MCP servers, no packages to install.** Run them; do not reimplement them.

Run them with the `shell` tool from the working directory where the outputs belong, so output files land in the workspace and not in the skill bundle. The commands below and in the reference files write `scripts/…` relative to this skill's directory (the directory containing this SKILL.md); replace it with the absolute path derived from this file's location:

```bash
# Multi-source paper search (sources: arxiv, s2, openalex, crossref), deduplicated, unified JSON
python3 scripts/paper_search.py "chain of thought reasoning" --sources arxiv,s2,openalex --limit 15 --year-from 2022 --out papers.json

# Verify ONE citation (waterfall: Crossref → S2 → OpenAlex → arXiv; title-similarity match)
python3 scripts/verify_citation.py --title "Attention Is All You Need" --author Vaswani --year 2017

# Audit an entire .bib file → per-entry verdict (VERIFIED / MISMATCH / NOT_FOUND / UNCERTAIN)
python3 scripts/verify_citation.py --bib refs.bib --out citation_audit.json

# Fetch a paper's full text (arXiv id or abs URL → text via ar5iv HTML, falls back to abstract)
python3 scripts/fetch_paper.py 2504.17192 --out paper.txt

# Fetch the original LaTeX source instead (exact equations/tables — prefer for reproduction)
python3 scripts/fetch_paper.py 2504.17192 --latex --out-dir paper_src/
```

`fetch_paper.py` also accepts `--doi <doi>` instead of an arXiv id. Each script prints its full usage with `--help`.

On HTTP 429/5xx the scripts retry with backoff. If a source keeps failing, the script continues with the others and marks the gap — record that gap in the log; never swallow it. When the scripts do not cover a query shape, call the raw APIs; read [references/api-cheatsheet.md](references/api-cheatsheet.md) for endpoints, rate limits, and field syntax.

**Non-negotiables when using this toolbox:**

- **Never fabricate a citation.** Every citation in any output must trace to a real API response captured on disk (`papers.json`, `citation_audit.json`). If verification fails, mark it `[unverified]` or remove it — never guess metadata.
- **URLs come from search results, not memory.** A URL not obtained from an API call is a hallucination.
- **Contradictions are findings, not problems.** If two sources disagree on a paper's year or venue, log both and pick one on defensible grounds — never silently overwrite.

## Reporting

Every mode ends with a compact final report (plain Markdown, delivered as the final message):

- **Contract**: one paragraph, what you set out to do.
- **Baseline vs final**: the numbers or the summary from before and after the work.
- **What worked**: 3–5 items with quantitative or specific-source backing.
- **What didn't**: the dead-ends, crashes, or contradictions — this is high-signal.
- **Open questions / next steps**: what you would do with more time.
- **Where to look**: pointers to the log file, branch, and any generated artifacts.

Keep it under a page. The point is not storytelling — it is letting a human verify the work in five minutes and know what to look at next.
