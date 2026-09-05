# Settling the brief

PDF work splits into two halves that need opposite amounts of asking.
Extraction and transformation are usually fully specified by the file and the
verb: read them, do them, report what you found. Composition — building a
document that does not exist yet — carries the same open decisions as any
other document and deserves the same one round of questions.

The rule: **probe the file first, then ask only what the file and the request
cannot answer.**

## Probe before asking

The probe answers more than any question would: page count, page sizes and
rotation, encryption, whether an interactive form is present, whether the
first pages carry a text layer. Run it before composing a single question.

A scan and a text-layer PDF need different work; a form and a flat page need
different work. Asking the user which one they have, when the file says so, is
a wasted turn.

## When to skip entirely

- Any extraction: pull the text, tables, metadata, or images and answer.
- Any single transformation with named inputs: merge these, rotate those,
  split at page ten, add this watermark.
- Filling a form whose values the user supplied.
- The user asked for speed or already declined questions this session.

Most PDF requests land here. Do not manufacture an interview for them.

## What is worth asking — composition only

At most three, one `ask_user` call, options with a marked recommendation:

1. **Reader and use.** Printed or read on screen, kept or discarded, formal
   record or working draft? This decides page size, margins, and whether the
   document needs outline entries and page numbers.
2. **Content boundaries.** What must appear, and what must not — figures the
   data does not support, terms not yet agreed, names not yet confirmed.
3. **Fidelity constraints.** A required template, letterhead, font, or
   accessibility obligation. Fonts especially: an unregistered font silently
   substitutes and changes every line break.

## Two questions that are never optional

Ask these regardless of phase, whenever they apply, because proceeding without
the answer causes harm rather than rework:

- **An encrypted file.** Ask the user to supply the password or unlock it. Do
  not attempt to work around protection.
- **A destructive edit.** Cropping is not redaction, and altering a signed
  document invalidates its signature. Say what the change would break and let
  the user decide before doing it.

## How to ask

`ask_user`, concrete options, recommendation first and marked, one call. If
unanswered, take the defaults and state the assumptions — except for the two
questions above, which are not defaultable.

## The plan, and the gate

For composition, put the page model in front of the user before building: page
size and margins, the section order, what flows and what is fixed, the fonts
you will register, and every value the source material does not supply. Wait
for approval.

For extraction and transformation there is no gate, but there is still a
report: say what you did, what the file did not contain, and which pages
needed recognition rather than extraction.
