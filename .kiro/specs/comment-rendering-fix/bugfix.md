# Bugfix Requirements Document

## Introduction

AI-generated comments contain formatting artifacts that make them look non-human when posted to Reddit. The pipeline has no programmatic text sanitization between LLM output and database storage — only a single `.strip()` call on the editor output. When the LLM produces em-dashes, smart quotes, zero-width characters, multiple newlines, or markdown artifacts, they pass through unchanged to the clipboard and ultimately to Reddit. This makes comments visually distinguishable from genuine human-typed text, undermining the core product value.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN the LLM generates a comment containing em-dashes (—) THEN the system stores and displays the em-dash characters unchanged in `ai_draft`

1.2 WHEN the LLM generates a comment containing smart/curly quotes (" " ' ') THEN the system stores and displays the smart quote characters unchanged in `ai_draft`

1.3 WHEN the LLM generates a comment containing zero-width or invisible Unicode characters (zero-width spaces, zero-width joiners, soft hyphens, BOM markers) THEN the system stores and displays these invisible characters unchanged in `ai_draft`

1.4 WHEN the LLM generates a comment containing multiple consecutive newlines or excessive whitespace THEN the system stores and displays the extra whitespace unchanged in `ai_draft`

1.5 WHEN the LLM generates a comment containing markdown formatting artifacts (asterisks for bold/italic, backticks, hash headers, bullet markers) THEN the system stores and displays the markdown artifacts unchanged in `ai_draft`

1.6 WHEN the editor LLM produces a cleaned comment that still contains any of the above artifacts THEN the system stores the editor output with only `.strip()` applied, preserving internal artifacts

1.7 WHEN the LLM generates a comment containing trailing whitespace on lines THEN the system stores and displays the trailing whitespace unchanged in `ai_draft`

### Expected Behavior (Correct)

2.1 WHEN the LLM generates a comment containing em-dashes (—) THEN the system SHALL replace em-dashes with appropriate plain alternatives (comma, hyphen, or parenthetical) before storing in `ai_draft`

2.2 WHEN the LLM generates a comment containing smart/curly quotes (" " ' ') THEN the system SHALL normalize them to straight ASCII quotes (" ') before storing in `ai_draft`

2.3 WHEN the LLM generates a comment containing zero-width or invisible Unicode characters THEN the system SHALL strip all zero-width and invisible characters before storing in `ai_draft`

2.4 WHEN the LLM generates a comment containing multiple consecutive newlines THEN the system SHALL collapse them to a single newline before storing in `ai_draft`

2.5 WHEN the LLM generates a comment containing markdown formatting artifacts THEN the system SHALL remove markdown syntax (asterisks, backticks, hash headers, bullet markers) before storing in `ai_draft`

2.6 WHEN the editor LLM returns a cleaned comment THEN the system SHALL apply the same text normalization pipeline to the editor output before storing in `ai_draft`

2.7 WHEN the LLM generates a comment containing trailing whitespace on lines THEN the system SHALL strip trailing whitespace from each line before storing in `ai_draft`

### Unchanged Behavior (Regression Prevention)

3.1 WHEN the LLM generates a comment containing only plain ASCII text with normal spacing THEN the system SHALL CONTINUE TO store the comment text unchanged (aside from outer whitespace trimming)

3.2 WHEN the LLM generates a comment containing legitimate single newlines separating short thoughts THEN the system SHALL CONTINUE TO preserve single newlines as-is

3.3 WHEN the LLM generates a comment containing standard ASCII hyphens (-) THEN the system SHALL CONTINUE TO preserve regular hyphens unchanged

3.4 WHEN the LLM generates a comment containing straight ASCII quotes (" ') THEN the system SHALL CONTINUE TO preserve straight quotes unchanged

3.5 WHEN the LLM generates a comment containing proper nouns, acronyms, or URLs THEN the system SHALL CONTINUE TO preserve their original casing and characters unchanged

3.6 WHEN the LLM generates a comment containing parentheses, commas, and standard punctuation THEN the system SHALL CONTINUE TO preserve standard punctuation unchanged

3.7 WHEN the comment generation or editing fails THEN the system SHALL CONTINUE TO handle errors gracefully and return original text as fallback
