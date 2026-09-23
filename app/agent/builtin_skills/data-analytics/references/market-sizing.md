# Market Sizing

Produce a defensible estimate of a market, segment, or opportunity (TAM/SAM/SOM, spend or revenue pool, population count, unit volume, expansion upside) from connected data, public sources, transparent assumptions, and auditable calculations.

## Contents

- 1. Frame the market
- 2. Choose a sizing approach
- 3. Gather sources for the inputs
- 4. Separate facts from assumptions
- 5. Build the model
- 6. Test sensitivity
- 7. State the estimate

## 1. Frame the market

Define the boundary before estimating:

- **What** is sized: product category, workflow, problem, use case, activity.
- **Where and when:** geography, segment scope, time horizon, market maturity.
- **Who or what counts:** population, unit of demand, transaction type, included activity.
- **Measure:** spend, revenue, volume, value created, or another unit that fits.
- **Answer type:** TAM/SAM/SOM, market entry, expansion upside, spend pool, population count, unit volume.

## 2. Choose a sizing approach

Pick the simplest sound approach and sketch the calculation chain and major inputs:

- **Top-down** when reliable aggregate market data exists.
- **Bottom-up** when the market can be built from observable units and assumptions (accounts x adoption x price).
- **Value-based** when the estimate should start from value created rather than a published total.

Use a mixed approach only when a cross-check materially improves confidence; say which one you trust most and why. Expect to switch if source checks show another model is more defensible.

## 3. Gather sources for the inputs

Choose sources by the inputs the estimate depends on most. Start with user-named sources; then use the user's structured data for internal inputs, docs and team communication for business meaning and assumption sets (`references/business-context.md` when the right source of truth is unclear), and public sources (`web_fetch` or other research tools) for benchmarks, population estimates, comparable markets, and proxies.

If the strongest source is unavailable or thin, continue with a transparent proxy only when the estimate is still useful, and label the gap and its effect on confidence.

## 4. Separate facts from assumptions

Keep sourced facts, inferred estimates, and judgment calls distinct. When exact data is missing, use a defensible proxy, explain why it is reasonable, and give its confidence. Ground assumptions in how the market actually behaves and what determines its size.

## 5. Build the model

Make these easy to audit and revise: market definition and unit; assumptions with source context; calculation chain and derived values; base case, ranges, and sensitivity logic; validation priorities. Mark each major input's origin: structured data, context source, public source, user input, or proxy assumption. Derive values from formulas or code, never hardcoded outputs.

- For code-based harmonization, calculations, or sensitivity, use a notebook (`references/notebooks.md`).
- When the user wants a spreadsheet, or the model benefits from editable assumptions and sensitivity tables, read the `xlsx-official` skill and build the workbook with live formulas.

## 6. Test sensitivity

Identify the assumptions that move the estimate most and show the estimate as they move up and down. Prefer simple, decision-useful sensitivity over scenario sprawl. Use ranges when uncertainty is material; do not hide thin inputs behind a single point estimate.

## 7. State the estimate

Make explicit:

- market definition and unit;
- estimate or range;
- method and calculation chain;
- key assumptions and their source support;
- main uncertainty drivers and sensitivity takeaways;
- validation priorities and what the number means for the user's decision.

When coverage is thin, name the inputs that rely on proxies and the source that would most improve them. Run `references/pre-share-review.md` before sharing when methodology, assumptions, or source support need review.

Package the estimate as a report (`references/deliverables.md`) unless the user asked for an inline answer, no file, or another artifact. Sensitivity, scenario, funnel, or market-breakdown charts follow `references/visualization.md`.
