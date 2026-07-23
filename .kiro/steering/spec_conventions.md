# Spec Workflow Conventions

## Purpose

Standardizes the format and behavior of spec documents (requirements.md, design.md, tasks.md) for consistency across all features.

## File Structure

All specs live in `.kiro/specs/{feature-name}/`:
- `requirements.md` — EARS-format requirements with user stories + acceptance criteria
- `design.md` — Architecture, components, data models, correctness properties, testing strategy
- `tasks.md` — Implementation plan with dependency graph
- `.config.kiro` — Spec metadata (specType, workflowType)

Feature names are kebab-case (e.g., `sales-faq-page`, `browser-extension`).

## Tasks Document Format

### Task Hierarchy

```markdown
- [ ] 1. Top-level task (group)
  - [ ] 1.1 Sub-task (implementable unit)
    - Bullet: implementation detail
    - _Requirements: X.Y, Z.W_
  - [ ] 1.2 Sub-task
  - [ ]* 1.3 Optional sub-task (asterisk = skippable)
```

- Top-level tasks = logical groups
- Sub-tasks = atomic implementable units (what a subagent executes)
- Bullets under sub-tasks = implementation guidance
- `*` after checkbox = optional task (can be skipped for faster MVP)
- `_Requirements: ..._` = traceability link to requirements

### Checkpoints

Checkpoint tasks verify progress between phases:
```markdown
- [ ] 3. Checkpoint - Verify X renders correctly
  - Description of what to verify. Ask the user if questions arise.
```

Checkpoints are sequential by definition and NOT included in the dependency graph.

### Dependency Graph

Always included at the end of tasks.md. Defines parallel execution order.

**Format:**
```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.2"] },
    { "id": 2, "tasks": ["2.1", "2.3"] }
  ]
}
```

**Rules:**
- Wave N+1 starts only after ALL tasks in wave N complete
- Tasks within the same wave are independent and execute in parallel
- Task IDs reference sub-task numbers (e.g., "1.1", "2.3")
- Checkpoints are excluded from the graph (they're sequential gates)
- Optional tasks (`*`) may be included in later waves

**How to build the graph:**
1. After writing all tasks, analyze dependencies: "what must exist before this task can start?"
2. Group independent tasks into the same wave
3. Tasks that produce artifacts consumed by others → earlier wave
4. Tests always come after the code they test
5. SEO/docs/cleanup → last waves

### Notes Section

Optional section after tasks, before dependency graph:
- Explains conventions used in this specific plan
- Documents assumptions
- Lists what doesn't exist yet and needs to be created

## Design Document Format

### Required Sections

1. **Overview** — What this design does (2-3 sentences)
2. **Architecture** — Mermaid diagram + key decisions
3. **Components and Interfaces** — Each component with code examples
4. **Data Models** — DB models or data structures
5. **Correctness Properties** — Formal properties that must hold true (for PBT)
6. **Error Handling** — Failure scenarios and responses
7. **Testing Strategy** — What to test, how, which properties to verify

### Correctness Properties Format

```markdown
### Property N: Title

*For any* [domain element], [property statement].

**Validates: Requirements X.Y, Z.W**
```

## Requirements Document Format

### Required Sections

1. **Introduction** — One paragraph context
2. **Glossary** — Domain terms used in requirements
3. **Requirements** — Numbered, each with user story + acceptance criteria

### Requirement Format

```markdown
### Requirement N: Title

**User Story:** As a [role], I want [feature], so that [benefit]

#### Acceptance Criteria

1. WHEN/WHERE/WHILE/IF [trigger], THE [component] SHALL [behavior]
2. ...
```

Uses EARS pattern (Easy Approach to Requirements Syntax):
- **WHEN** — event-driven (something happens)
- **WHERE** — state-driven (system is in state X)
- **WHILE** — ongoing condition
- **IF/THEN** — conditional
- **THE [X] SHALL** — unconditional (always true)

## Notion Deprecation

Notion is NO LONGER the primary store for anything. PostgreSQL `bug_reports` table is the source of truth for QA. Notion MCP is available for reading historical archive only. Never write to Notion.
