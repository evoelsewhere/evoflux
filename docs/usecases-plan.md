# Plan: `.evoflux/` Use Cases with File References

## Overview

Support a `.evoflux/` folder in projects that defines reusable use cases for Knowledge Base workflows. Use cases can reference other markdown files via `@include` directives, allowing modular, composable definitions.

## Folder Structure

```
project-root/
├── .evoflux/                          ← Excluded from KB indexing
│   ├── usecases/                      ← Parsed by usecase parser
│   │   ├── code-review.md
│   │   ├── bug-fix.md
│   │   ├── feature-impl.md
│   │   └── shared/
│   │       ├── standards.md
│   │       ├── security-rules.md
│   │       └── error-handling.md
│   ├── skills/                        ← Same format as usecases, different trigger
│   │   ├── security-audit.md
│   │   └── performance-opt.md
│   └── config.yml                     ← Project-level config
├── src/                               ← Indexed into KB
├── docs/                              ← Indexed into KB
└── README.md                          ← Indexed into KB
```

**Key distinction:**
- `.evoflux/` is **excluded** from KB indexing (added to default exclude patterns)
- `.evoflux/usecases/` is read **separately** by the usecase parser
- KB indexes `src/`, `docs/`, `README.md` etc. → chunks → embeddings
- Usecase parser reads `.evoflux/usecases/*.md` → parsed definitions
- When KB node runs in `usecase` mode: parser reads definition → runs `kb_queries` against KB → formats context

## End-to-End Flow

```
User has project: /Users/user/myproject/
  └── .evoflux/usecases/code-review.md
  └── src/ (indexed into KB)

User creates workflow in Evolux:
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ Manual   │───→│ KB       │───→│ AI       │───→│ Git      │
│ Trigger  │    │ (usecase)│    │ Agent    │    │ Ops      │
└──────────┘    └──────────┘    └──────────┘    └──────────┘

KB Node config:
  mode: "usecase"
  knowledge_base_id: "kb-xxx"     ← KB that indexed the project
  project_path: "/Users/user/myproject/"  ← local folder
  usecase_name: "code-review"     ← .evoflux/usecases/code-review.md
  input: "{trigger.task}"         ← from manual trigger

Execution:
1. Parser reads /Users/user/myproject/.evoflux/usecases/code-review.md
2. Resolves @include directives (shared/standards.md etc.)
3. Runs kb_queries against KB kb-xxx
4. Formats context_template with:
   - {kb_result_0} ← result of first kb_query
   - {kb_result_1} ← result of second kb_query
   - {input} ← task from manual trigger
5. Outputs formatted context

AI Agent receives:
  task: from manual trigger
  context: formatted context from KB node
  codebase_path: "/Users/user/myproject/"
```

## Use Case File Format

### Basic Structure

```markdown
<!-- .evoflux/usecases/code-review.md -->
---
name: Code Review
description: Review code changes against project standards
version: 1.0
author: team
tags: [review, quality, security]
kb_queries:
  - "coding standards and conventions"
  - "architecture patterns"
  - "security best practices"
context_template: |
  ## Standards
  {include:shared/standards.md}

  ## Security Rules
  {include:shared/security-rules.md}

  ## Code to Review
  {input}
output_format: |
  ## Review Summary
  - Issues: [count]
  - Severity: [level]

  ## Issues Found
  [list with line references]

  ## Recommendations
  [actionable items]
tools: [read_file, grep, bash]
max_iterations: 15
---
Review the provided code against project standards.
Focus on correctness, security, and performance.
```

### `@include` Directive Syntax

```markdown
{include:relative/path/to/file.md}        # Include file content
{include:relative/path/to/file.md#section} # Include specific section (by heading)
{include:*.md}                              # Include all .md files in directory
{include:shared/*.md}                       # Include all .md in shared/
```

### Resolution Rules

| Pattern | Behavior |
|---|---|
| `{include:shared/standards.md}` | Include full file content |
| `{include:shared/standards.md#Security}` | Include only "Security" section |
| `{include:shared/*.md}` | Include all .md files, concatenated |
| `{include:../common/guidelines.md}` | Relative to usecase file |
| Nested includes | Resolved recursively (max depth: 5) |
| Circular includes | Detected and reported as error |

### Template Placeholders

| Placeholder | Resolved To |
|---|---|
| `{include:path}` | File content (resolved before other placeholders) |
| `{input}` | Input from previous node in workflow |
| `{kb_result_0}` | Result of first kb_query |
| `{kb_result_1}` | Result of second kb_query |
| `{kb_result_N}` | Result of Nth kb_query |
| `{kb_results_all}` | All kb_query results concatenated |
| `{project_path}` | Project path from config |
| `{usecase_name}` | Name from frontmatter |

### Example: Modular Use Case

**code-review.md:**
```markdown
---
name: Code Review
kb_queries:
  - "coding standards"
  - "security patterns"
context_template: |
  {include:shared/standards.md}
  {include:shared/security-rules.md}
  {include:shared/error-handling.md}
  ## Code to Review
  {input}
tools: [read_file, grep, bash]
---
Review code against all project standards.
```

**shared/standards.md:**
```markdown
# Coding Standards

## TypeScript
- Use strict mode
- Prefer const over let
- Use explicit return types

## Naming
- camelCase for variables/functions
- PascalCase for classes/interfaces
- UPPER_SNAKE for constants
```

**shared/security-rules.md:**
```markdown
# Security Rules

## Input Validation
- Validate all user inputs
- Sanitize SQL queries (use parameterized)
- Escape HTML output

## Authentication
- Never store passwords in plaintext
- Use bcrypt for hashing
- Implement rate limiting
```

## Implementation

### Step 1: Parser (`src/engine/usecase/parser.ts`)

```typescript
interface UsecaseDefinition {
  name: string
  description: string
  version?: string
  author?: string
  tags?: string[]
  kb_queries: string[]
  context_template: string
  output_format?: string
  tools?: string[]
  max_iterations?: number
  raw_content: string      // Full content after @include resolution
  source_path: string      // Path to the usecase file
  includes: string[]       // List of included files
}

// Parse .evoflux/usecases/*.md files
// Resolve @include directives recursively
// Max include depth: 5
// Detect circular includes
// Cache parsed results by file hash
```

### Step 2: Executor (`src/engine/usecase/executor.ts`)

```typescript
interface UsecaseExecution {
  usecase: UsecaseDefinition
  kb_id: string                    // KB to search
  project_path: string             // Project root
  kb_results: Map<string, string[]>  // query → search results
  context: string                     // Final formatted context
  input: string                       // User input
}

async function executeUsecase(
  projectPath: string,
  usecaseName: string,
  kbId: string,
  input: string,
  aiChat: Function
): Promise<UsecaseExecution> {
  // 1. Find and parse usecase file
  // 2. Resolve all @include directives
  // 3. Run kb_queries against KB
  // 4. Format context_template with results
  // 5. Replace {input} with user input
  // 6. Return formatted context
}
```

### Step 3: KB Node Integration

Add `usecase` field to knowledge-retrieval config:

```typescript
interface KnowledgeRetrievalConfig {
  mode: 'search' | 'ingest' | 'kb_search' | 'usecase'
  knowledge_base_id?: string
  project_path?: string          // NEW: local project folder
  usecase_name?: string          // NEW: reference to .evoflux/usecases/*.md
  // ... existing fields
}
```

When `mode === 'usecase'`:
1. Find `.evoflux/usecases/{name}.md` in `project_path`
2. Resolve all `@include` directives
3. Run `kb_queries` against the KB
4. Format `context_template` with results
5. Output formatted context

### Step 4: IPC Handlers

```typescript
// New IPC handlers
ipcMain.handle('usecase:list', async (_event, projectPath) => {
  // Scan .evoflux/usecases/*.md
  // Return list of usecase names + descriptions
})

ipcMain.handle('usecase:get', async (_event, projectPath, name) => {
  // Parse specific usecase file
  // Return full definition
})

ipcMain.handle('usecase:resolve', async (_event, projectPath, name, kbId, input) => {
  // Execute usecase: KB queries + formatting
  // Return formatted context
})

ipcMain.handle('usecase:selectFolder', async () => {
  // Open folder dialog for project path
})
```

### Step 5: Config Form

Add usecase selector to knowledge-retrieval node config:

```
Mode: [Search Memory ▼] [Search KB ▼] [Use Case ▼]

When "Use Case" selected:
  Knowledge Base: [kb-xxx ▼]
  Project Path: [/path/to/project] [Browse]
  Use Case: [code-review ▼]  ← auto-populated from .evoflux/usecases/
  Input: [text area for input]
```

### Step 6: UI — Usecase Browser

Add to KB Detail sidebar or as a new tab:

```
┌─────────────────────────────────────┐
│ 📁 .evoflux/usecases/               │
│   📄 code-review.md                 │
│   📄 bug-fix.md                     │
│   📄 feature-impl.md                │
│   📁 shared/                        │
│     📄 standards.md                 │
│     📄 security-rules.md            │
│     📄 error-handling.md            │
└─────────────────────────────────────┘
```

### Step 7: Project Config (`.evoflux/config.yml`)

```yaml
# .evoflux/config.yml
project:
  name: My Project
  description: Project description

knowledge_base:
  id: kb-xxx                    # Link to Evolux KB
  auto_sync: true               # Auto-sync on git pull
  exclude_patterns:             # Additional excludes
    - "*.test.*"
    - "__tests__"

defaults:
  usecase: code-review          # Default usecase
  max_iterations: 20
  provider: prov-xxx            # Default provider
```

## Error Handling

| Error | Handling |
|---|---|
| `.evoflux/` not found | Return error: "No .evoflux folder in project. Create one with usecases." |
| Usecase file not found | Return error: "Usecase 'xxx' not found in .evoflux/usecases/" |
| Invalid YAML frontmatter | Return error with line number and description |
| @include file not found | Return error: "Included file 'xxx' not found" |
| Circular @include | Return error: "Circular include detected: a → b → a" |
| @include depth > 5 | Return error: "Include depth exceeded (max 5)" |
| Empty kb_queries | Return warning: "No KB queries defined, using input only" |
| KB not found | Return error: "Knowledge base 'xxx' not found" |
| KB has no documents | Return warning: "KB is empty, results will be limited" |

## File Changes Summary

| File | Action | Description |
|---|---|---|
| `src/engine/usecase/parser.ts` | **New** | Parse .evoflux/usecases/*.md with @include resolution |
| `src/engine/usecase/executor.ts` | **New** | Execute usecase: KB queries + context formatting |
| `src/engine/nodes/knowledge-retrieval.ts` | Modify | Add `usecase` mode |
| `electron/ipc/knowledge-base.ts` | Modify | Add usecase IPC handlers |
| `electron/preload.ts` | Modify | Add usecase methods |
| `electron-env.d.ts` | Modify | Add usecase types |
| `src/components/workflow/node-configs/NodeConfigForms.tsx` | Modify | Add usecase config form |
| `src/components/kb/KBUsecases.tsx` | **New** | Usecase browser UI |
| `src/engine/kb/file-scanner.ts` | Modify | Add .evoflux to default excludes |
| `src/engine/kb/pipeline.ts` | Modify | Skip .evoflux during indexing |

## Execution Order

| # | Task | Dependencies |
|---|---|---|
| 1 | parser.ts with @include resolution | — |
| 2 | executor.ts (KB queries + formatting) | 1 |
| 3 | KB node: add usecase mode + project_path | 2 |
| 4 | IPC handlers + preload + types | 2 |
| 5 | Config form: usecase selector + folder picker | 4 |
| 6 | UI: usecase browser in KB detail | 4 |
| 7 | Exclude .evoflux from KB indexing | — |
| 8 | Build + test | all |
