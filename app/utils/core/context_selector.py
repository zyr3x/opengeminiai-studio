"""
Module for intelligently selecting relevant context from the dialogue history.

Instead of sending the entire dialogue history, only relevant messages are selected
based on the current query, saving 40-60% of tokens in long dialogues.
"""
import re
import os
import json
from typing import List, Tuple
from collections import Counter
from app.utils.core.tools import log

MIN_RELEVANCE_SCORE = 0.3
ALWAYS_KEEP_RECENT = 5
MIN_KEYWORD_LENGTH = 3
MAX_KEYWORDS = 20

CONTEXT_SELECTOR_STOPWORDS_PATH = 'etc/context/selector/stop_words.json'

def load_stop_words() -> list:
    try:
        full_path = os.path.join(CONTEXT_SELECTOR_STOPWORDS_PATH)

        if not os.path.exists(full_path):
             full_path = os.path.join(os.getcwd(), CONTEXT_SELECTOR_STOPWORDS_PATH)

        if not os.path.exists(full_path):
            log(f"Warning: Context Selector Stop words file not found at {CONTEXT_SELECTOR_STOPWORDS_PATH}. Using empty list.")
            return []

        with open(full_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    except Exception as e:
        log(f"Error loading context selector stop words from {CONTEXT_SELECTOR_STOPWORDS_PATH}: {e}")
        return []

STOP_WORDS = load_stop_words()

def extract_keywords(text: str) -> List[str]:
    """
    Extracts keywords from the text.

    Algorithm:
    1. Text normalization (lowercase)
    2. Tokenization (split by non-alphabetic characters)
    3. Filtering of stop words and short words
    4. Selection of top-N by frequency

    Args:
        text: Source text

    Returns:
        List of keywords (up to MAX_KEYWORDS)
    """
    if not text:
        return []

    # 1. Normalization
    text_lower = text.lower()

    # 2. Tokenization - split by non-alphabetic characters
    # Preserve underscores for variable names
    tokens = re.findall(r'\b[a-zа-яё_][a-zа-яё0-9_]*\b', text_lower)

    # 3. Filtering
    filtered_tokens = [
        token for token in tokens
        if len(token) >= MIN_KEYWORD_LENGTH  # Length >= 3
        and token not in STOP_WORDS          # Not a stop word
        and not token.isdigit()              # Not a number
    ]

    # 4. Frequency count and top-N selection
    if not filtered_tokens:
        return []

    word_freq = Counter(filtered_tokens)

    # Take the top-N most frequent words
    top_keywords = [word for word, _ in word_freq.most_common(MAX_KEYWORDS)]
    
    return top_keywords


def calculate_relevance(message: dict, keywords: List[str]) -> float:
    """
    Calculates the relevance of a message relative to a list of keywords.

    Algorithm:
    - Extracts text from all parts of the message.
    - Counts the number of keyword occurrences.
    - Normalizes the score by text length and keyword count.

    Args:
        message: Message in Gemini API format.
        keywords: List of keywords.

    Returns:
        Relevance score from 0.0 to 1.0
    """
    if not keywords:
        return 0.0

    # Extract text from the message
    parts = message.get('parts', [])
    text_parts = []

    for part in parts:
        if 'text' in part:
            text_parts.append(part['text'])
        elif 'functionCall' in part:
            # Account for function calls
            func_call = part['functionCall']
            text_parts.append(func_call.get('name', ''))
        elif 'functionResponse' in part:
            # Account for function responses
            func_resp = part['functionResponse']
            text_parts.append(func_resp.get('name', ''))

    if not text_parts:
        return 0.0

    full_text = ' '.join(text_parts).lower()

    if not full_text:
        return 0.0

    # Count keyword matches
    matches = 0
    total_keyword_occurrences = 0

    for keyword in keywords:
        # Search for keyword occurrences as separate words
        pattern = r'\b' + re.escape(keyword) + r'\b'
        occurrences = len(re.findall(pattern, full_text))
        if occurrences > 0:
            matches += 1
            total_keyword_occurrences += occurrences

    if matches == 0:
        return 0.0

    # Calculate score
    # Factor 1: Percentage of keywords found (0-1)
    keyword_coverage = matches / len(keywords)

    # Factor 2: Density of occurrences relative to text length (0-1)
    # Normalize such that 5+ occurrences = 1.0
    density = min(total_keyword_occurrences / 5.0, 1.0)

    # Combine factors (70% coverage, 30% density)
    relevance_score = (keyword_coverage * 0.7) + (density * 0.3)
    
    return min(relevance_score, 1.0)


def select_relevant_messages(
    messages: List[dict],
    current_query: str,
    max_tokens: int,
    keep_recent: int = ALWAYS_KEEP_RECENT,
    min_relevance: float = MIN_RELEVANCE_SCORE
) -> List[dict]:
    """
    Intelligent selection of relevant messages from history.

    Algorithm:
    1. Always include the system prompt (first message)
    2. Always include the last `keep_recent` messages
    3. Select remaining messages based on relevance score
    4. Sort by time (preserve chronology)

    Args:
        messages: List of all messages
        current_query: The user's current query
        max_tokens: Maximum token limit
        keep_recent: How many recent messages to always keep
        min_relevance: Minimum relevance score

    Returns:
        The filtered list of messages
    """
    from app.utils.core.tools import estimate_token_count
    
    # If there are few messages, return all
    if len(messages) <= keep_recent + 1:
        return messages

    # Check if filtering is even necessary
    total_tokens = estimate_token_count(messages)
    if total_tokens <= max_tokens * 0.8:  # If we occupy < 80% of the limit
        return messages

    # 1. Extract keywords from the current query
    keywords = extract_keywords(current_query)

    if not keywords:
        # If we couldn't extract keywords, use simple truncation
        return messages[:1] + messages[-keep_recent:]

    # 2. Always keep the first message (system prompt)
    result = [messages[0]]

    # 3. Always keep the last messages too
    recent_messages = messages[-keep_recent:]

    middle_messages = messages[1:-keep_recent]
    
    if not middle_messages:
        return result + recent_messages

    scored_messages: List[Tuple[float, int, dict]] = []
    
    for idx, msg in enumerate(middle_messages, start=1):
        score = calculate_relevance(msg, keywords)
        if score >= min_relevance:
            scored_messages.append((score, idx, msg))

    scored_messages.sort(reverse=True, key=lambda x: x[0])

    current_tokens = estimate_token_count(result + recent_messages)
    target_tokens = max_tokens * 0.8
    
    selected_middle = []
    
    for score, original_idx, msg in scored_messages:
        msg_tokens = estimate_token_count([msg])
        
        if current_tokens + msg_tokens <= target_tokens:
            selected_middle.append((original_idx, msg))
            current_tokens += msg_tokens
        else:
            pass

    selected_middle.sort(key=lambda x: x[0])

    result.extend([msg for _, msg in selected_middle])
    result.extend(recent_messages)
    
    return result


def smart_context_window(
    messages: List[dict],
    current_query: str,
    max_tokens: int,
    enabled: bool = True
) -> List[dict]:
    if not enabled:
        return messages
    
    if len(messages) <= 1:
        return messages
    
    # Apply selective context
    selected = select_relevant_messages(
        messages=messages,
        current_query=current_query,
        max_tokens=max_tokens,
        keep_recent=ALWAYS_KEEP_RECENT,
        min_relevance=MIN_RELEVANCE_SCORE
    )

    # Log results
    original_count = len(messages)
    selected_count = len(selected)

    if selected_count < original_count:
        from app.utils.core.tools import log, estimate_token_count

        original_tokens = estimate_token_count(messages)
        selected_tokens = estimate_token_count(selected)
        saved_tokens = original_tokens - selected_tokens
        saved_percentage = (saved_tokens / original_tokens * 100) if original_tokens > 0 else 0

        log(f"✓ Selective Context: {original_count} → {selected_count} messages")
        log(f"  Tokens: {original_tokens} → {selected_tokens} (saved {saved_tokens}, -{saved_percentage:.1f}%)")

    return selected


# --- Stats ---

_stats = {
    'total_calls': 0,
    'messages_filtered': 0,
    'tokens_saved': 0
}

def record_selective_context_stats(original_tokens: int, selected_tokens: int):
    global _stats
    _stats['total_calls'] += 1
    _stats['tokens_saved'] += (original_tokens - selected_tokens)

def get_selective_context_stats() -> dict:
    return _stats.copy()

def reset_selective_context_stats():
    global _stats
    _stats = {
        'total_calls': 0,
        'messages_filtered': 0,
        'tokens_saved': 0
    }
