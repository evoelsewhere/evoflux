# Evaluation-first skill development

## Contents

- Evaluation-driven loop
- Scenario format
- Trigger tests
- Functional tests
- Baseline comparison
- Observing how the agent uses the skill
- Iteration signals
- Common load failures

Write evaluations before extensive documentation, so the skill solves real
gaps instead of imagined ones. Match rigor to the audience: a personal skill
needs a few manual runs; a skill shared across a team deserves a recorded
scenario set that is re-run after every change.

## Evaluation-driven loop

1. **Identify gaps.** Run representative tasks without the skill and record
   the specific failures, questions, and missing context.
2. **Create evaluations.** Write at least three scenarios that exercise those
   gaps.
3. **Establish a baseline.** Record how the agent performs on each scenario
   without the skill.
4. **Write minimal instructions.** Add only enough content to close the gaps.
5. **Iterate.** Run the scenarios with the skill, compare against the
   baseline, refine, and repeat.

Iterating on one hard scenario until it passes, then extracting the winning
approach into the skill, gives faster signal than broad testing. Widen to the
full set once the foundation works.

## Scenario format

```json
{
  "skills": ["processing-pdfs"],
  "query": "Extract all text from this PDF file and save it to output.txt",
  "files": ["test-files/document.pdf"],
  "expected_behavior": [
    "Reads the PDF with an appropriate PDF library or command-line tool",
    "Extracts text from every page without skipping any",
    "Saves the extracted text to output.txt in a clear, readable format"
  ]
}
```

- `skills`: the skills available during the run.
- `query`: the literal user message.
- `files`: input files the scenario needs, relative to the scenario folder.
- `expected_behavior`: observable, checkable outcomes; one per line.

Store scenarios and their input files outside the skill directory, for example
in the session workspace or a `skill-evals/<name>/` folder in the user's
repository. Nothing evaluation-related goes inside the bundle.

## Trigger tests

Goal: the skill is read for matching requests and only then.

```text
Should trigger:
- "Help me set up a new ProjectHub workspace"        (obvious)
- "I need to create a project in ProjectHub"          (paraphrase)
- "Initialize a ProjectHub project for Q4 planning"   (paraphrase)

Should not trigger:
- "Create a spreadsheet of Q4 tasks"                  (near miss: different artifact)
- "Help me write Python code"                         (unrelated)
```

Near misses matter most; they test the boundary the description promises.
Skills with `disable-model-invocation: true` skip this test because only `$name`
activates them; test that `$name` reads the skill and that the body still
refuses out-of-scope work.

Debugging aid: ask the agent "When would you use the <name> skill?" It
paraphrases the description; fix whatever it leaves out.

## Functional tests

Goal: the skill produces correct results.

```text
Scenario: create a project with 5 tasks
Given:    project name "Q4 Planning" and 5 task descriptions
Expect:   the project exists; 5 tasks with the requested fields;
          every task linked to the project; no failed tool calls
```

Cover valid outputs, tool and script calls that succeed, error handling, and
the edge cases users will hit. Run every bundled script on a representative
input.

## Baseline comparison

Run the same scenario with and without the skill and compare:

```text
Without skill: 15 messages, 3 failed tool calls, 12,000 tokens
With skill:     2 clarifying questions, 0 failed tool calls, 6,000 tokens
```

Also check consistency: do 3-5 runs of the same request produce structurally
similar output? Does a new user succeed on the first try?

## Observing how the agent uses the skill

While running scenarios, watch:

- which files the agent reads, and in what order (an unexpected path means the
  structure is not intuitive);
- links the agent never follows (the reference may be unnecessary or poorly
  signposted);
- files it reads on every run (that content may belong in `SKILL.md`);
- steps it skips or reorders (make them explicit and numbered).

Iterate with two roles: one conversation refines the skill, a fresh one uses
it on real tasks. Bring the fresh conversation's behavior back as evidence.

## Iteration signals

| Signal | Diagnosis | Fix |
|---|---|---|
| Not read when it should be; users type `$name` by hand | Under-triggering | Add concrete terms, file types, and phrases to the description |
| Read for unrelated requests | Over-triggering | Add a "Not for ..." boundary; narrow the scope |
| Inconsistent results, failed calls, user corrections | Execution gaps | Sharpen steps, add error handling, replace prose checks with a script |
| Slow or context-heavy runs | Context bloat | Shrink `SKILL.md`; move conditional detail to linked references |

When a real session exposes a failure, encode the fix directly: an explicit
instruction, a troubleshooting entry, or a validation step.

## Common load failures

- **Skill missing from the catalog**: `SKILL.md` is not exactly that filename,
  is nested below `<root>/<name>/`, or the skill is disabled in Settings.
- **Invalid frontmatter**: missing `---` delimiters or malformed YAML
  (unclosed quotes are the usual cause).
- **Invalid name**: capitals, spaces, or underscores; use lowercase with
  hyphens and match the directory name.
- **Loads but instructions are ignored**: rules are buried or verbose. Put
  critical rules first, keep them short, and move detail into references.
