"""
Fuzzy string replacement utility for ThreeJS MCP modify_script tool.

Ported and adapted from OpenCode's edit.ts Replacer chain:
https://github.com/opencode-ai/opencode/blob/main/packages/opencode/src/tool/edit.ts

Implements 9 replacement strategies (aligned with OpenCode) in priority order:
  1. SimpleReplacer         - exact match
  2. LineTrimmedReplacer    - per-line trim match
  3. BlockAnchorReplacer    - first/last line anchor + Levenshtein similarity
  4. WhitespaceNormalizedReplacer - collapse all whitespace
  5. IndentationFlexibleReplacer  - remove common indentation
  6. EscapeNormalizedReplacer     - unescape \\n, \\t, quotes, etc. then match
  7. TrimmedBoundaryReplacer      - trim entire block boundary
  8. ContextAwareReplacer          - first/last line anchor + 50% middle lines match
  9. MultiOccurrenceReplacer      - detect multiple matches and raise error
"""
import re
import logging
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Similarity thresholds for BlockAnchorReplacer
SINGLE_CANDIDATE_THRESHOLD = 0.0    # accept any middle similarity when only one candidate
MULTIPLE_CANDIDATES_THRESHOLD = 0.3  # require 30%+ similarity when multiple candidates


# ---------------------------------------------------------------------------
# Core algorithm: Levenshtein distance
# ---------------------------------------------------------------------------

def levenshtein(a: str, b: str) -> int:
    """Compute edit distance between two strings."""
    if not a:
        return len(b)
    if not b:
        return len(a)
    m, n = len(a), len(b)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, n + 1):
            temp = dp[j]
            if a[i - 1] == b[j - 1]:
                dp[j] = prev
            else:
                dp[j] = 1 + min(prev, dp[j], dp[j - 1])
            prev = temp
    return dp[n]


def _lines_to_span(content_lines: List[str], start_line: int, end_line: int) -> Tuple[int, int]:
    """Convert line range [start_line, end_line] (0-based inclusive) to char span."""
    start = sum(len(content_lines[k]) + 1 for k in range(start_line))
    end = start
    for k in range(start_line, end_line + 1):
        end += len(content_lines[k])
        if k < end_line:
            end += 1  # newline between lines
    return (start, end)


# ---------------------------------------------------------------------------
# Strategy 1: SimpleReplacer — exact substring match
# ---------------------------------------------------------------------------

def _simple_replace(content: str, old: str, new: str, replace_all: bool) -> Optional[str]:
    if old not in content:
        return None
    count = content.count(old)
    if replace_all:
        return content.replace(old, new)
    if count > 1:
        # Let MultiOccurrenceReplacer handle the error
        return None
    return content.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Strategy 2: LineTrimmedReplacer — match after per-line trim
# ---------------------------------------------------------------------------

def _line_trimmed_replace(content: str, old: str, new: str, replace_all: bool) -> Optional[str]:
    content_lines = content.split('\n')
    old_lines = old.split('\n')
    # Remove trailing empty line from search pattern
    if old_lines and old_lines[-1] == '':
        old_lines = old_lines[:-1]
    if not old_lines:
        return None

    found_spans = []
    for i in range(len(content_lines) - len(old_lines) + 1):
        if all(content_lines[i + j].strip() == old_lines[j].strip()
               for j in range(len(old_lines))):
            span = _lines_to_span(content_lines, i, i + len(old_lines) - 1)
            found_spans.append(span)

    if not found_spans:
        return None
    if len(found_spans) > 1 and not replace_all:
        return None  # ambiguous, let MultiOccurrence handle

    result = content
    # Replace from end to preserve offsets
    for start, end in reversed(found_spans):
        result = result[:start] + new + result[end:]
        if not replace_all:
            break
    return result


# ---------------------------------------------------------------------------
# Strategy 3: BlockAnchorReplacer — anchor on first/last line + Levenshtein
# ---------------------------------------------------------------------------

def _block_anchor_replace(content: str, old: str, new: str, replace_all: bool) -> Optional[str]:
    old_lines = old.split('\n')
    if old_lines and old_lines[-1] == '':
        old_lines = old_lines[:-1]
    if len(old_lines) < 3:
        return None

    content_lines = content.split('\n')
    first_search = old_lines[0].strip()
    last_search = old_lines[-1].strip()

    # Find all candidate positions where first and last lines match.
    # Do NOT break on the first matching end line — collect ALL possible
    # (start, end) pairs so the similarity scorer can pick the best one.
    # Breaking early causes wrong selection when the last-line pattern
    # (e.g. "}") appears multiple times in the block.
    candidates = []
    for i, line in enumerate(content_lines):
        if line.strip() != first_search:
            continue
        for j in range(i + 2, len(content_lines)):
            if content_lines[j].strip() == last_search:
                candidates.append((i, j))

    if not candidates:
        return None

    def _similarity(start: int, end: int) -> float:
        actual_middle = content_lines[start + 1:end]
        search_middle = old_lines[1:-1]
        lines_to_check = min(len(search_middle), len(actual_middle))
        if lines_to_check == 0:
            return 1.0
        total = 0.0
        for k in range(lines_to_check):
            orig = actual_middle[k].strip()
            srch = search_middle[k].strip()
            max_len = max(len(orig), len(srch))
            if max_len == 0:
                continue
            dist = levenshtein(orig, srch)
            total += 1.0 - dist / max_len
        return total / lines_to_check

    if len(candidates) == 1:
        start, end = candidates[0]
        sim = _similarity(start, end)
        if sim < SINGLE_CANDIDATE_THRESHOLD:
            return None
        char_start, char_end = _lines_to_span(content_lines, start, end)
        return content[:char_start] + new + content[char_end:]

    # Multiple candidates: pick the most similar
    best = max(candidates, key=lambda c: _similarity(c[0], c[1]))
    best_sim = _similarity(best[0], best[1])
    if best_sim < MULTIPLE_CANDIDATES_THRESHOLD:
        return None
    char_start, char_end = _lines_to_span(content_lines, best[0], best[1])
    return content[:char_start] + new + content[char_end:]


# ---------------------------------------------------------------------------
# Strategy 4: WhitespaceNormalizedReplacer — collapse all whitespace
# ---------------------------------------------------------------------------

def _whitespace_normalized_replace(content: str, old: str, new: str, replace_all: bool) -> Optional[str]:
    def normalize(text: str) -> str:
        return re.sub(r'\s+', ' ', text).strip()

    norm_old = normalize(old)
    old_lines = old.split('\n')
    content_lines = content.split('\n')

    found_spans = []

    # Single-line match
    for i, line in enumerate(content_lines):
        if normalize(line) == norm_old:
            span = _lines_to_span(content_lines, i, i)
            found_spans.append(span)

    # Multi-line match
    if len(old_lines) > 1:
        for i in range(len(content_lines) - len(old_lines) + 1):
            block = '\n'.join(content_lines[i:i + len(old_lines)])
            if normalize(block) == norm_old:
                span = _lines_to_span(content_lines, i, i + len(old_lines) - 1)
                if span not in found_spans:
                    found_spans.append(span)

    if not found_spans:
        return None
    if len(found_spans) > 1 and not replace_all:
        return None

    result = content
    for start, end in reversed(found_spans):
        result = result[:start] + new + result[end:]
        if not replace_all:
            break
    return result


# ---------------------------------------------------------------------------
# Strategy 5: IndentationFlexibleReplacer — remove common indentation
# ---------------------------------------------------------------------------

def _indentation_flexible_replace(content: str, old: str, new: str, replace_all: bool) -> Optional[str]:
    def remove_indent(text: str) -> str:
        lines = text.split('\n')
        non_empty = [l for l in lines if l.strip()]
        if not non_empty:
            return text
        min_indent = min(len(l) - len(l.lstrip()) for l in non_empty)
        return '\n'.join(l[min_indent:] if l.strip() else l for l in lines)

    norm_old = remove_indent(old)
    old_line_count = len(old.split('\n'))
    content_lines = content.split('\n')

    found_spans = []
    for i in range(len(content_lines) - old_line_count + 1):
        block = '\n'.join(content_lines[i:i + old_line_count])
        if remove_indent(block) == norm_old:
            span = _lines_to_span(content_lines, i, i + old_line_count - 1)
            found_spans.append(span)

    if not found_spans:
        return None
    if len(found_spans) > 1 and not replace_all:
        return None

    result = content
    for start, end in reversed(found_spans):
        result = result[:start] + new + result[end:]
        if not replace_all:
            break
    return result


# ---------------------------------------------------------------------------
# Strategy 6: EscapeNormalizedReplacer — unescape \n, \t, quotes, etc. then match
# ---------------------------------------------------------------------------

def _unescape_string(s: str) -> str:
    """Unescape common escape sequences: \\n, \\t, \\r, \\', \\\", \\`, \\\\, \\$, backslash-newline."""
    def repl(match: re.Match) -> str:
        c = match.group(1)
        if c == 'n':
            return '\n'
        if c == 't':
            return '\t'
        if c == 'r':
            return '\r'
        if c == "'":
            return "'"
        if c == '"':
            return '"'
        if c == '`':
            return '`'
        if c == '\\':
            return '\\'
        if c == '$':
            return '$'
        if c == '\n':  # backslash followed by newline
            return '\n'
        return match.group(0)

    return re.sub(r'\\(.)', repl, s)


def _escape_normalized_replace(content: str, old: str, new: str, replace_all: bool) -> Optional[str]:
    unescaped_old = _unescape_string(old)

    # Direct match: content contains the unescaped form
    if unescaped_old in content:
        count = content.count(unescaped_old)
        if replace_all:
            return content.replace(unescaped_old, new)
        if count > 1:
            return None
        return content.replace(unescaped_old, new, 1)

    # Multi-line: find blocks in content that unescape to unescaped_old
    content_lines = content.split('\n')
    find_lines = unescaped_old.split('\n')
    if find_lines and find_lines[-1] == '':
        find_lines = find_lines[:-1]
    n_lines = len(find_lines)
    if n_lines == 0:
        return None

    found_spans = []
    for i in range(len(content_lines) - n_lines + 1):
        block = '\n'.join(content_lines[i:i + n_lines])
        if _unescape_string(block) == unescaped_old:
            span = _lines_to_span(content_lines, i, i + n_lines - 1)
            found_spans.append(span)

    if not found_spans:
        return None
    if len(found_spans) > 1 and not replace_all:
        return None

    result = content
    for start, end in reversed(found_spans):
        result = result[:start] + new + result[end:]
        if not replace_all:
            break
    return result


# ---------------------------------------------------------------------------
# Strategy 7: TrimmedBoundaryReplacer — trim entire old block
# ---------------------------------------------------------------------------

def _trimmed_boundary_replace(content: str, old: str, new: str, replace_all: bool) -> Optional[str]:
    trimmed_old = old.strip()
    if trimmed_old == old:
        return None  # already trimmed, no point trying

    if trimmed_old in content:
        count = content.count(trimmed_old)
        if replace_all:
            return content.replace(trimmed_old, new)
        if count > 1:
            return None
        return content.replace(trimmed_old, new, 1)

    # Multi-line block trim
    old_lines = old.split('\n')
    content_lines = content.split('\n')
    found_spans = []
    for i in range(len(content_lines) - len(old_lines) + 1):
        block = '\n'.join(content_lines[i:i + len(old_lines)])
        if block.strip() == trimmed_old:
            span = _lines_to_span(content_lines, i, i + len(old_lines) - 1)
            found_spans.append(span)

    if not found_spans:
        return None
    if len(found_spans) > 1 and not replace_all:
        return None

    result = content
    for start, end in reversed(found_spans):
        result = result[:start] + new + result[end:]
        if not replace_all:
            break
    return result


    return result


# ---------------------------------------------------------------------------
# Strategy 8: ContextAwareReplacer — first/last line anchor + 50% middle lines match
# ---------------------------------------------------------------------------

def _context_aware_replace(content: str, old: str, new: str, replace_all: bool) -> Optional[str]:
    """Match block by first/last line anchors; require same line count and >= 50% middle lines match (trimmed)."""
    old_lines = old.split('\n')
    if old_lines and old_lines[-1] == '':
        old_lines = old_lines[:-1]
    if len(old_lines) < 3:
        return None

    content_lines = content.split('\n')
    first_line = old_lines[0].strip()
    last_line = old_lines[-1].strip()

    for i in range(len(content_lines)):
        if content_lines[i].strip() != first_line:
            continue
        for j in range(i + 2, len(content_lines)):
            if content_lines[j].strip() != last_line:
                continue
            block_lines = content_lines[i:j + 1]
            if len(block_lines) != len(old_lines):
                break
            # At least 50% of non-empty middle lines must match (trimmed)
            matching_lines = 0
            total_non_empty = 0
            for k in range(1, len(block_lines) - 1):
                bl = block_lines[k].strip()
                ol = old_lines[k].strip()
                if len(bl) > 0 or len(ol) > 0:
                    total_non_empty += 1
                    if bl == ol:
                        matching_lines += 1
            if total_non_empty == 0 or (matching_lines / total_non_empty >= 0.5):
                char_start, char_end = _lines_to_span(content_lines, i, j)
                return content[:char_start] + new + content[char_end:]
            break  # only first matching last line per start
    return None


# ---------------------------------------------------------------------------
# Strategy 9: MultiOccurrenceReplacer — report ambiguous matches clearly
# ---------------------------------------------------------------------------

def _multi_occurrence_check(content: str, old: str) -> Optional[str]:
    """Return error message if old appears multiple times, else None."""
    count = content.count(old)
    if count > 1:
        return (
            f"old_code appears {count} times in the file. "
            "Provide more surrounding lines in old_code to uniquely identify the target location."
        )
    return None


# ---------------------------------------------------------------------------
# Public API: fuzzy_replace
# ---------------------------------------------------------------------------

class FuzzyReplaceError(Exception):
    """Raised when no strategy can find a match."""
    pass


class FuzzyReplaceAmbiguousError(Exception):
    """Raised when old_code matches multiple locations."""
    pass


def fuzzy_replace(content: str, old_str: str, new_str: str, replace_all: bool = False) -> Tuple[str, str]:
    """
    Try multiple replacement strategies in priority order.

    Returns:
        (new_content, strategy_name) on success

    Raises:
        FuzzyReplaceAmbiguousError: if old_str matches multiple locations
        FuzzyReplaceError: if no strategy finds a match
    """
    if old_str == new_str:
        raise FuzzyReplaceError("old_str and new_str are identical — nothing to replace.")

    strategies: List[Tuple[str, Callable]] = [
        ("exact",                 _simple_replace),
        ("line_trimmed",          _line_trimmed_replace),
        ("block_anchor",          _block_anchor_replace),
        ("whitespace_normalized",  _whitespace_normalized_replace),
        ("indentation_flexible",   _indentation_flexible_replace),
        ("escape_normalized",      _escape_normalized_replace),
        ("trimmed_boundary",       _trimmed_boundary_replace),
        ("context_aware",          _context_aware_replace),
    ]

    for strategy_name, strategy_fn in strategies:
        try:
            result = strategy_fn(content, old_str, new_str, replace_all)
            if result is not None:
                logger.info(f"fuzzy_replace: matched using strategy '{strategy_name}'")
                return result, strategy_name
        except Exception as e:
            logger.warning(f"fuzzy_replace: strategy '{strategy_name}' raised {e}")
            continue

    # All strategies failed — check for multi-occurrence before giving up
    ambiguous_msg = _multi_occurrence_check(content, old_str)
    if ambiguous_msg:
        raise FuzzyReplaceAmbiguousError(ambiguous_msg)

    raise FuzzyReplaceError(
        "old_code not found in the file after trying all matching strategies. "
        "Please use read_script to verify the exact content and try again."
    )
