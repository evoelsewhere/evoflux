# Review finding contract

Every reported finding must satisfy all fields:

- **Title:** imperative or causal summary, not a category label.
- **Severity:** based on reachable impact and likelihood in the deployment
  context.
- **Location:** smallest changed line range that reveals the defect.
- **Trigger:** concrete input, state sequence, timing, or version pairing.
- **Impact:** incorrect behavior experienced by a user or operator.
- **Cause:** why the changed code permits that behavior.
- **Fix direction:** narrow contract correction, without implementing it.

## Severity calibration

- Critical: immediate compromise or catastrophic loss with a reachable path.
- High: major data, security, availability, or broad correctness impact.
- Medium: material defect under plausible conditions with bounded impact.
- Low: real but limited behavior issue; omit pure style and maintainability.

Severity is not inherited from category. A theoretical injection primitive
without attacker-controlled input is not automatically high; a quiet data-loss
edge case may be.

## Deduplication

Merge observations when they share one violated invariant and one fix. Keep
them separate when triggers, impacts, or owners differ enough to require
independent remediation.
