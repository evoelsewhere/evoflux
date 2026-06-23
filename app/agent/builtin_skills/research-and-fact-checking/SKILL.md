---
name: research-and-fact-checking
description: Turns an open question into a sourced, confidence-tagged answer through structured web/file/code reconnaissance. Use when you need to gather facts, verify a claim, compare sources, or investigate a topic you cannot answer from memory. Triggers on "research", "find out", "fact-check", "is it true that", or "what's the latest on".
---

# Research & Fact-Checking

## Overview

A confident summary is not a researched one. The failure mode of research is stopping at the first plausible-looking source, paraphrasing it, and presenting the paraphrase as fact. This skill is the discipline of investigating until the question can be answered with confidence backed by **primary sources** — and being honest about what remains unknown.

The deliverable is not "everything I found." It is a direct answer to the original question, each claim traceable to a source, with confidence stated explicitly. Volume is not value; a sourced two-sentence answer beats a three-page unsourced essay.

## When to Use

- A factual question you cannot answer reliably from memory
- A claim that needs verifying before someone acts on it
- Comparing competing sources, products, or approaches on the evidence
- Anything time-sensitive where your training data may be stale (current versions, prices, events, APIs)
- A decision that will rest on facts you are about to assert

**When NOT to use:**

- The user wants an opinion, brainstorm, or draft — not a fact-find
- The answer is general knowledge with no real dispute or stakes
- The user explicitly wants speed over rigour on a low-stakes question

## The Process

Copy this checklist when applying the skill:

```
Research cycle:
- [ ] Step 1: DECOMPOSE — wrote 3–5 sub-questions
- [ ] Step 2: SEARCH WIDE — parallel threads, primary vs secondary sorted
- [ ] Step 3: GO DEEP — fetched full sources, followed citations to origin
- [ ] Step 4: CROSS-CHECK — every key claim confirmed by a 2nd source
- [ ] Step 5: VERIFY QUANTITIES — numbers/dates/versions checked with a tool
- [ ] Step 6: SYNTHESISE — direct answer, gaps named, confidence tagged
```

### Step 1: DECOMPOSE — Break the question apart

Before searching, write 3–5 explicit sub-questions. This is the single highest-leverage step: it prevents scope drift, surfaces hidden assumptions in the question, and gives you a checklist to know when you are *done*.

```
Question: "Is Postgres or SQLite the better fit for our embedded analytics?"
Sub-questions:
1. What are the concurrency limits of each under our read/write mix?
2. What is the storage/footprint cost of embedding each?
3. Which analytical functions (window, CTE, JSON) does each support today?
4. What is the operational/backup story for each in an embedded context?
```

If you cannot decompose the question, it is too vague — clarify it before researching.

### Step 2: SEARCH WIDE — Cast several threads, then sort

Open several parallel searches with different keywords, angles, and source types. As results come in, sort every source into **primary** or **secondary** before reading:

- **Primary:** official docs, source code, specs/RFCs, peer-reviewed papers, datasets, the original statement or filing.
- **Secondary:** blog posts, forum answers, news write-ups, tutorials, AI summaries.

Weight primary sources higher. Secondary sources are useful for *finding* primaries and for context — never as the final word on a contested fact.

### Step 3: GO DEEP — Fetch the source, not the snippet

When a result looks relevant, fetch the **full page or file** — not just the search snippet. Snippets are lossy and often misleading out of context. Follow citations back to their origin: if a blog says "the docs say X," open the docs and read X yourself. A claim is only as strong as the document it ultimately rests on.

For code questions, read the actual source — not just the README, which is frequently out of date with the implementation.

### Step 4: CROSS-CHECK — Confirm every key claim twice

For each load-bearing claim, seek independent confirmation from a second, ideally primary, source. When two sources conflict:

- Report the discrepancy explicitly — do not silently pick one.
- Say which you trust and **why** (recency, authority, primary vs secondary, alignment with other evidence).
- If you cannot resolve it, present both and mark the claim `[unverified]`.

### Step 5: VERIFY QUANTITIES — Measure, don't paraphrase

For anything quantitative — version numbers, dates, counts, prices, benchmark figures, API shapes — confirm with a tool or the primary document rather than trusting a paraphrase. Run code to count, fetch the changelog to confirm a version, check the spec for the exact field name. Numbers copied from secondary sources are the most common way a research answer goes quietly wrong.

### Step 6: SYNTHESISE — Answer, gaps, confidence

Return to the original question and answer it directly. Then surface what you could **not** determine as explicit gaps. Do not fill gaps with inference dressed up as fact — flag inference as inference.

## Source Quality Ladder

From most to least trustworthy:

1. Primary record / official documentation / source code / raw data
2. Peer-reviewed or editorially-reviewed publication
3. Reputable secondary reporting that cites and links primaries
4. Expert commentary / established community knowledge
5. Unattributed or AI-generated summaries — treat as leads to chase, never as evidence

## Confidence Tags

Tag every finding so the reader knows how far to trust it:

| Tag | Meaning |
|-----|---------|
| **[confirmed]** | Multiple independent sources agree, at least one primary |
| **[likely]** | One good (ideally primary) source, no contradicting evidence |
| **[unverified]** | Single weak/secondary source, or sources conflict |

## Operating Rules

- **Never invent a citation.** If you are unsure a URL is correct, fetch it and confirm before citing it.
- **Cite every factual claim** — a URL with access date, or a file path with line/section.
- **Flag time-sensitivity.** When an answer depends on a version, date, or recent change, say so and give the boundary ("as of v3.2 / June 2026").
- **Separate fact from inference.** What the sources *say* is evidence; what you conclude from them is inference — label it.
- **Name the gaps.** A sub-question you couldn't answer is a finding, not a failure. Hiding it is the failure.
- **Right-size the effort.** A low-stakes lookup needs one good source; a decision-grade question needs the full cross-checked cycle.

## Output

```markdown
## Sub-questions
1. ...
2. ...

## Findings
### <Sub-question 1>
<Evidence, cited>  [confirmed | likely | unverified]
- Source: <URL, accessed YYYY-MM-DD | path:line>

### <Sub-question 2>
...

## Gaps & unknowns
- <What could not be determined, and why>

## Answer
<2–4 sentence direct answer to the original question, with overall confidence level>
```

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "The first result looks right, that's enough" | First results are optimised for popularity, not accuracy. One source is a lead, not a confirmation. |
| "The snippet says it, no need to open the page" | Snippets drop the context that flips the meaning. Open the source. |
| "It's probably still the current version" | "Probably" is how stale facts ship. Check the changelog or run the version command. |
| "I'll just say it's unclear" | Vague non-answers waste the reader's time. State what *is* known, tag the rest, and name the specific gap. |
