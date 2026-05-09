# Bugfix Requirements Document

## Introduction

AI-generated comments render differently on Reddit than they appear in the review UI, making them look suspicious and risking account suspension. The root cause is a mismatch between how the review UI displays text (raw, with `whitespace-pre-wrap`) and how Reddit interprets it (as Markdown). The LLM output may contain Markdown-significant characters (`*`, `_`, `~`, `>`, `` ` ``, `#`) and non-standard Unicode (smart quotes, en-dashes, special whitespace) that Reddit's parser transforms into visible formatting — bold, italic, code blocks, blockquotes — none of which a real human typing on their phone would produce.

The editor prompt partially addresses this (banning em-dashes, blank lines) but does not sanitize the actual text output for Reddit Markdown safety or Unicode normalization.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN the LLM outputs text containing asterisks (e.g., `*word*` or `**word**`) THEN the system stores it as-is and Reddit renders it as italic or bold formatting, making the comment look non-human

1.2 WHEN the LLM outputs text containing underscores within words or phrases (e.g., `_emphasis_`) THEN the system stores it as-is and Reddit renders it as italic formatting

1.3 WHEN the LLM outputs text containing backticks (e.g., `` `code` ``) THEN the system stores it as-is and Reddit renders it as inline code with monospace font, which looks suspicious for casual comments

1.4 WHEN the LLM outputs text containing lines starting with `>` THEN the system stores it as-is and Reddit renders it as a blockquote, creating unexpected visual formatting

1.5 WHEN the LLM outputs text containing lines starting with `#` THEN the system stores it as-is and Reddit renders it as a heading, creating large bold text

1.6 WHEN the LLM outputs Unicode smart quotes (`"` `"` `'` `'`), en-dashes (`–`), or other non-ASCII punctuation THEN the system stores it as-is and these characters appear visually distinct from standard ASCII on Reddit, flagging the text as AI-generated

1.7 WHEN the LLM outputs text containing strikethrough markup (`~~text~~`) THEN the system stores it as-is and Reddit renders it with strikethrough formatting

1.8 WHEN the LLM outputs text containing numbered lists (lines starting with `1.`, `2.`) or bullet lists (lines starting with `- ` or `* `) THEN the system stores it as-is and Reddit renders it as formatted lists, which look overly structured for casual comments

1.9 WHEN the LLM outputs text containing link syntax (`[text](url)`) or bare URLs with surrounding parentheses THEN the system stores it as-is and Reddit renders it as a hyperlink, which may look suspicious in context

1.10 WHEN the LLM outputs text containing non-standard whitespace characters (non-breaking spaces, zero-width spaces, thin spaces) THEN the system stores it as-is and these invisible characters may cause unexpected word wrapping or spacing on Reddit

### Expected Behavior (Correct)

2.1 WHEN the LLM outputs text containing asterisks THEN the system SHALL escape or remove them so Reddit renders the text as plain characters without bold/italic formatting

2.2 WHEN the LLM outputs text containing underscores within words or phrases THEN the system SHALL escape or remove them so Reddit renders the text without italic formatting

2.3 WHEN the LLM outputs text containing backticks THEN the system SHALL remove them so Reddit renders the text as plain text without code formatting

2.4 WHEN the LLM outputs text containing lines starting with `>` THEN the system SHALL remove the leading `>` so Reddit does not render blockquotes

2.5 WHEN the LLM outputs text containing lines starting with `#` THEN the system SHALL remove the leading `#` characters so Reddit does not render headings

2.6 WHEN the LLM outputs Unicode smart quotes, en-dashes, or other non-ASCII punctuation THEN the system SHALL normalize them to their ASCII equivalents (`"`, `'`, `-`)

2.7 WHEN the LLM outputs text containing strikethrough markup (`~~text~~`) THEN the system SHALL remove the tildes so Reddit renders plain text

2.8 WHEN the LLM outputs text containing numbered or bullet list formatting THEN the system SHALL remove the list markers so the text reads as natural prose

2.9 WHEN the LLM outputs text containing Markdown link syntax THEN the system SHALL extract only the display text, removing the URL and brackets

2.10 WHEN the LLM outputs text containing non-standard whitespace characters THEN the system SHALL normalize them to standard ASCII spaces

### Unchanged Behavior (Regression Prevention)

3.1 WHEN the LLM outputs plain text without any Markdown-significant characters or non-standard Unicode THEN the system SHALL CONTINUE TO store and display the text unchanged

3.2 WHEN the editor prompt successfully removes em-dashes and blank lines THEN the system SHALL CONTINUE TO apply the editor pass before the sanitizer runs

3.3 WHEN the comment contains standard ASCII punctuation (periods, commas, question marks, exclamation marks, hyphens, parentheses) THEN the system SHALL CONTINUE TO preserve them as-is

3.4 WHEN the comment contains legitimate use of apostrophes in contractions (e.g., "you're", "it's", "don't") THEN the system SHALL CONTINUE TO preserve them unchanged

3.5 WHEN the comment contains standard line breaks (single newline for paragraph flow) THEN the system SHALL CONTINUE TO preserve them as-is

3.6 WHEN the comment is displayed in the review UI THEN the system SHALL CONTINUE TO show the final sanitized text that will render identically on Reddit
