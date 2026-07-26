# Testing patterns

Read this file when selecting the narrowest useful test type.

## Unit

Use for deterministic logic with cheap setup. Test public behavior and boundary
conditions. Avoid asserting private call order unless it is the contract.

## Integration

Use for database queries, filesystem behavior, serialization, queues, and
service boundaries. Prefer real lightweight dependencies over mocks that copy
the implementation.

## Contract

Use at independently deployed boundaries. Validate request/response schemas,
error semantics, and backward compatibility from the consumer's perspective.

## End-to-end

Use for a small set of critical user journeys. Assert observable outcomes, not
framework internals. Keep setup deterministic and capture diagnostics on failure.

## Regression

First reproduce the reported failure. Write a test that fails for the original
reason, implement the smallest fix, then keep the test at the lowest layer that
still proves the behavior.
