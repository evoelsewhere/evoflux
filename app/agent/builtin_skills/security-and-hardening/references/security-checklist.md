# Security checklist

Read this file for a focused review or before release.

## Trust boundaries

- Inventory external inputs, identities, secrets, and privileged operations.
- Validate type, size, format, and authorization at the boundary.
- Treat third-party responses and rendered content as untrusted data.
- Keep authentication and authorization checks separate and explicit.

## Data and secrets

- Never log credentials, tokens, private keys, or sensitive payloads.
- Use platform secret storage and short-lived credentials where possible.
- Encrypt sensitive data in transit and at rest.
- Minimize retained data and define deletion behavior.

## Application controls

- Parameterize database queries.
- Encode output for its destination context.
- Restrict file paths to an explicit root; reject traversal and symlinks.
- Apply CSRF, CORS, CSP, and rate limits according to the exposed surface.
- Pin dependencies and review high-severity advisories.

## Verification

- Add negative tests for unauthorized, malformed, oversized, and replayed input.
- Run the project's static analysis and dependency scanners.
- Confirm error responses do not disclose internals.
- Document residual risk and an owner instead of silently accepting it.
