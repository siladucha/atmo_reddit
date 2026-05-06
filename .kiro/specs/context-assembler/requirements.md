# Requirements Document

## Introduction

The ContextAssembler is a centralized service (`app/services/context_assembler.py`) that becomes the single source of truth for assembling LLM call context. Currently, context is assembled ad-hoc in `build_scoring_messages()` (scoring.py) and `generate_comment()` (generation.py), leading to three critical problems: no client data isolation guarantee, subreddit rules/culture not bound to LLM calls, and no single definition of "what does avatar know about client X in subreddit Y." The ContextAssembler enforces strict client isolation boundaries, mandatory subreddit rule inclusion, scoped avatar memory, and correct persona voice application — making the platform safe for multi-client operation.

## Glossary

- **Context_Assembler**: The service responsible for constructing complete, isolated LLM context payloads for any AI operation (scoring, generation, editing)
- **Isolation_Boundary**: A data access constraint ensuring that context assembled for one client never contains data belonging to another client
- **Context_Payload**: The structured output of the Context_Assembler containing all messages, metadata, and provenance information for a single LLM call
- **Memory_Scope**: The set of historical interactions (previous comments, engagement patterns) scoped to a specific avatar within a specific subreddit
- **Subreddit_Rules**: The moderation rules, cultural norms, and posting guidelines for a specific subreddit that must be included in every LLM call targeting that subreddit
- **Persona_Voice**: The per-client voice profile (tone, vocabulary, constraints) applied to an avatar when generating content for a specific client
- **Context_Operation**: The type of LLM call being assembled: scoring, persona_selection, generation, or editing
- **Rules_Priority**: The precedence order for conflicting instructions: subreddit rules override persona voice settings
- **Client**: A tenant in the platform with their own brand, keywords, and competitive landscape
- **Avatar**: A Reddit account used for engagement, potentially shared across multiple clients
- **Subreddit**: A Reddit community with its own rules and culture

## Requirements

### Requirement 1: Client Data Isolation

**User Story:** As a platform operator, I want the context assembler to enforce strict client isolation, so that one client's proprietary data (brand info, keywords, competitive landscape) never leaks into another client's LLM calls.

#### Acceptance Criteria

1. WHEN assembling context for a given client_id, THE Context_Assembler SHALL include only data belonging to that client_id
2. WHEN an avatar serves multiple clients, THE Context_Assembler SHALL use only the requesting client's brand profile, keywords, and competitive landscape in the Context_Payload
3. IF a context assembly request references a client_id that does not exist, THEN THE Context_Assembler SHALL raise a validation error and refuse to produce a Context_Payload
4. THE Context_Assembler SHALL never query or include Client model fields (brand_name, company_profile, company_worldview, company_problem, competitive_landscape, keywords, brand_voice, case_studies, icp_profiles) from any client other than the one specified in the assembly request
5. FOR ALL Context_Payloads produced by the Context_Assembler, the payload SHALL contain a client_id field that matches the requesting client and no references to other client identifiers

### Requirement 2: Mandatory Subreddit Rules Inclusion

**User Story:** As a platform operator, I want subreddit rules and cultural context always included in LLM calls, so that generated content respects community norms and avoids bans for rule violations.

#### Acceptance Criteria

1. WHEN assembling context for any Context_Operation targeting a subreddit, THE Context_Assembler SHALL include the subreddit's rules in the Context_Payload
2. WHEN subreddit rules conflict with persona voice settings, THE Context_Assembler SHALL apply Rules_Priority (subreddit rules override persona voice)
3. IF a subreddit has no rules loaded (empty or null), THEN THE Context_Assembler SHALL log a warning and proceed with an explicit "no rules available" marker in the Context_Payload
4. THE Context_Assembler SHALL place subreddit rules in the system prompt before persona voice instructions to enforce precedence via prompt ordering

### Requirement 3: Scoped Avatar Memory

**User Story:** As a platform operator, I want avatar memory (previous comments, engagement history) scoped to a specific subreddit, so that the LLM generates contextually appropriate content without cross-subreddit contamination.

#### Acceptance Criteria

1. WHEN assembling context for comment generation, THE Context_Assembler SHALL include only the avatar's previous comments from the target subreddit
2. WHEN assembling context for comment generation, THE Context_Assembler SHALL limit memory to a configurable maximum number of recent comments (default: 20)
3. THE Context_Assembler SHALL order memory entries by recency (most recent first)
4. IF an avatar has no previous comments in the target subreddit, THEN THE Context_Assembler SHALL include an empty memory section and proceed without error

### Requirement 4: Persona Voice Application

**User Story:** As a platform operator, I want the correct persona voice applied per client per avatar, so that each client's brand voice is consistently represented regardless of which avatar is used.

#### Acceptance Criteria

1. WHEN assembling context for generation or editing operations, THE Context_Assembler SHALL include the avatar's voice_profile_md, tone_principles, speech_patterns, and constraints
2. WHEN a client has a dedicated Persona record for the avatar, THE Context_Assembler SHALL merge the Persona voice settings with the avatar's base voice profile
3. WHILE subreddit rules are present in the Context_Payload, THE Context_Assembler SHALL annotate persona voice instructions as lower priority than subreddit rules

### Requirement 5: Unified Context Assembly Interface

**User Story:** As a developer, I want a single entry point for all LLM context assembly, so that I can replace ad-hoc context building in scoring.py and generation.py with a consistent, testable service.

#### Acceptance Criteria

1. THE Context_Assembler SHALL expose a method `assemble(operation, client_id, subreddit_id, avatar_id, thread_id, **kwargs)` that returns a Context_Payload
2. WHEN operation is "scoring", THE Context_Assembler SHALL produce a Context_Payload equivalent to the current `build_scoring_messages()` output plus subreddit rules
3. WHEN operation is "generation", THE Context_Assembler SHALL produce a Context_Payload equivalent to the current `generate_comment()` prompt construction plus subreddit rules and scoped memory
4. WHEN operation is "persona_selection", THE Context_Assembler SHALL produce a Context_Payload equivalent to the current `select_persona()` prompt construction plus subreddit rules
5. WHEN operation is "editing", THE Context_Assembler SHALL produce a Context_Payload equivalent to the current `edit_comment()` prompt construction
6. THE Context_Assembler SHALL return a Context_Payload as a structured dataclass or Pydantic model containing: messages (list of role/content dicts), metadata (client_id, subreddit_id, avatar_id, operation), and provenance (which data sources were included)

### Requirement 6: Context Payload Provenance

**User Story:** As a platform operator, I want each context payload to include provenance metadata, so that I can audit what data went into any LLM call for debugging and compliance.

#### Acceptance Criteria

1. THE Context_Assembler SHALL include in every Context_Payload a provenance section listing: client_id, subreddit_id, avatar_id, operation type, whether subreddit rules were included, memory entry count, and timestamp of assembly
2. WHEN a Context_Payload is used for an LLM call, THE Context_Assembler SHALL make the provenance available for logging without including it in the LLM messages themselves
3. IF any expected data source is missing during assembly (rules not loaded, persona not found), THEN THE Context_Assembler SHALL record the gap in the provenance section

### Requirement 7: Context Payload Serialization

**User Story:** As a developer, I want to serialize and deserialize Context_Payloads, so that I can cache them, log them, and use them in tests.

#### Acceptance Criteria

1. THE Context_Assembler SHALL provide a method to serialize a Context_Payload to a JSON-compatible dictionary
2. THE Context_Assembler SHALL provide a method to deserialize a JSON-compatible dictionary back into a Context_Payload
3. FOR ALL valid Context_Payloads, serializing then deserializing SHALL produce an equivalent Context_Payload (round-trip property)

### Requirement 8: Backward Compatibility

**User Story:** As a developer, I want the context assembler to be adoptable incrementally, so that existing scoring and generation services can migrate without a big-bang rewrite.

#### Acceptance Criteria

1. THE Context_Assembler SHALL produce message lists compatible with the existing `call_llm()` and `call_llm_json()` interfaces (list of dicts with "role" and "content" keys)
2. WHEN the Context_Assembler is used for scoring, THE Context_Payload messages SHALL produce equivalent LLM behavior to the current `build_scoring_messages()` output
3. THE Context_Assembler SHALL not require changes to the `app/services/ai.py` call interface
