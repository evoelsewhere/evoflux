# Settling the brief

A document is a set of decisions — reader, purpose, length, register, house
style — and a request rarely states them. Guessing all of them silently
produces a valid file that is wrong in every way that matters.

The rule: **ask once, about what would change the document, and only what the
material and the request cannot already answer.**

## Answer from context first

- The source material fixes subject, depth, and usually the section order.
- The user's own words fix register: "contract", "memo to the board",
  "customer notice", and "internal note" each imply a reader, a length, and a
  tone.
- The workspace fixes house style when it holds a template, an earlier
  document of the same kind, or a style guide. Look before asking.
- Anything the user already said in this session is already answered.

## When to skip entirely

- The brief is explicit about reader, purpose, and length.
- The task is an edit or a template fill rather than a new document.
- A template in the workspace already answers structure and style.
- The user asked for speed or has declined questions once in this session.

## What is worth asking

At most three questions, in one `ask_user` call, options with a marked
recommendation:

1. **Reader and decision.** Who reads it and what should they do afterwards?
   A document with no decision behind it becomes a description, and
   descriptions have no shape.
2. **Length and depth.** A page budget or a section list. The difference
   between a two-page memo and a twenty-page report is two different
   documents, not one document at two lengths.
3. **Register and constraints.** Only where it is genuinely open: signature
   blocks, confidentiality marking, legal review, a required house template.

Page size, fonts, margins, and file name are defaults you take yourself and
state in the plan. Ask A4 or Letter only when locale does not imply it.

## How to ask

Use `ask_user` with concrete options rather than an open prompt, your
recommendation first and marked. Give each option its consequence, not a
label. Ask everything in one call.

If the tool is unavailable or unanswered, take the recommended defaults, write
each assumption into the plan, and continue. An unanswered question becomes a
stated assumption, never a silent one.

## The plan, and the gate

Before writing the document, put in front of the user:

- the heading tree, one line per section, with what each section must
  establish;
- the style basis: template, house style, or the defaults you chose;
- the assumptions you took for everything you did not ask;
- every fact, figure, date, name, or citation the material does not support.

That last list is the one that matters. A gap named in the plan is filled by
the user in seconds; a gap filled silently becomes a fabricated clause in a
contract.

Wait for approval. Do not treat silence as approval. Skip the gate only for
an edit small enough to describe in one line.

After approval the plan is the contract. If drafting forces a departure, say
so and adjust the plan rather than shipping something that was never approved.
