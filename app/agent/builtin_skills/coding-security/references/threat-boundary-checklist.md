# Threat-boundary checklist

Read only the sections relevant to the concrete path.

## Identity and authorization

- Is identity bound to the request, resource, tenant, and action at the owning
  boundary?
- Can user-controlled identifiers select another tenant's object?
- Can stale roles, cached policy, delegated credentials, or background jobs
  outlive a privilege change?
- Are create, read, update, delete, export, and administrative actions checked
  independently?

## Interpretation boundaries

- SQL, shell, templates, expressions, regular expressions, archive paths,
  file paths, URLs, headers, and serialized objects require context-specific
  construction—not generic escaping.
- Canonicalize once, validate the canonical form, and preserve the validated
  value through the sink.
- Treat redirects, DNS resolution, symbolic links, and archive extraction as
  potential boundary changes.

## Secrets and privileged work

- Keep credentials out of client output, logs, errors, caches, and generated
  artifacts.
- Scope tokens by action, audience, resource, and lifetime.
- Ensure privileged workers re-check authorization or consume a signed,
  narrowly scoped capability rather than trusting queued user fields.

## Abuse and failure

- Bound input size, expansion ratio, fan-out, recursion, concurrency, and retry.
- Fail closed for policy uncertainty; distinguish unavailable dependencies from
  denied access without leaking sensitive existence.
- Record security-relevant decisions without logging secrets or raw sensitive
  payloads.
