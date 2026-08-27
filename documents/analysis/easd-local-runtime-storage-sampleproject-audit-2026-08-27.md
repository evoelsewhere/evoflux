# EASD local runtime storage — sampleproject audit

Date: 2026-08-27

Repository: `evoflux-easd-ux-audit.qr9KP5/sampleproject`

## Before migration

The existing setup used the Git-visible legacy layout:

- 2 Run directories under `documents/easd/runs/`;
- 18 operational Run files, 27,169 bytes;
- 31 byte-identical generated templates and placeholder READMEs, 7,512 bytes;
- `.evoflux/easd/.local/` was ignored, but Run/evidence/event files were not.

The manifest correctly reported `upgrade_required`; inspecting it did not move
or delete any file.

## Manifest upgrade

Setup added:

```json
{
  "runtime_storage": "local",
  "runtime_directory": ".evoflux/easd/.local/runs",
  "templates_directory": ".evoflux/easd/.local/templates",
  "publish_converged_runs": "manual"
}
```

Upgrade created the ignored local directories and left both legacy Runs intact
and readable. Setup then displayed the exact legacy Run count and offered an
explicit migration preview.

## Confirmed localization

The migration preview reported each source/target, Run ID, file count and byte
count. Execution moved both regular Run directories with atomic rename. It also
removed 31 generated files only after their contents matched the bundled
defaults byte-for-byte.

After migration:

- 2 existing Runs remained visible with statuses `authoring` and `planned`;
- `documents/easd/runs/` contained no Run directories;
- `.evoflux/easd/.local/runs/` contained both Runs and was ignored by the nested
  `.gitignore`;
- legacy Run count and generated-file count were both zero;
- accepted Spec catalogue files remained Git-visible;
- project-customized files would be preserved by content-mismatch policy, as
  covered by service tests.

## New-Run proof

A third Run, **Local runtime storage audit**, was created after migration:

- its `run.yaml` was created only under ignored local runtime storage;
- no copy appeared under `documents/easd/runs/`;
- `git add -n .` reported 18 candidates before Run creation and 18 afterward;
- the Run remained queryable through the public EASD API.

## Git-visible result

Dry-run Git add included the manifest, rules, portable project Skills, knowledge
index/README, and accepted Spec catalogue. It included no operational Run,
mission, evidence, event, Recovery, Realtime, or runtime-template files.

## Conclusion

Default EASD operation no longer produces per-attempt Git noise. Git carries
accepted contracts and explicit project knowledge; local runtime carries active
execution. Cross-host continuation now requires explicit publication or a
shared service rather than implicit event-file merging.
