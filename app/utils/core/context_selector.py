import re
import os
import json
from typing import List, Tuple
from collections import Counter
from app.utils.core.logging import log
from app.utils.core.config_loader import load_json_file
from app.utils.core.optimization_utils import estimate_token_count

MIN_RELEVANCE_SCORE = 0.3
ALWAYS_KEEP_RECENT = 5
MIN_KEYWORD_LENGTH = 3
MAX_KEYWORDS = 20

CONTEXT_SELECTOR_STOPWORDS_PATH = 'etc/context/selector/stop_words.json'
def load_stop_words() -> list:
    return load_json_file(CONTEXT_SELECTOR_STOPWORDS_PATH, default=[])
STOP_WORDS = load_stop_words()
def extract_keywords(text: str) -> List[str]:
    if not text:
        return []
    text_lower = text.lower()
    tokens = re.findall(r'\b[a-zа-яё_][a-zа-яё0-9_]*\b', text_lower)
    filtered_tokens = [
        token for token in tokens
        if len(token) >= MIN_KEYWORD_LENGTH
        and token not in STOP_WORDS
        and not token.isdigit()
    ]

    if not filtered_tokens:
        return []
    word_freq = Counter(filtered_tokens)
    top_keywords = [word for word, _ in word_freq.most_common(MAX_KEYWORDS)]
    return top_keywords
def calculate_relevance(message: dict, keywords: List[str]) -> float:
    if not keywords:
        return 0.0
    parts = message.get('parts', [])
    text_parts = []
    for part in parts:
        if 'text' in part:
            text_parts.append(part['text'])
        elif 'functionCall' in part:
            func_call = part['functionCall']
            text_parts.append(func_call.get('name', ''))
        elif 'functionResponse' in part:
            func_resp = part['functionResponse']
            text_parts.append(func_resp.get('name', ''))

    if not text_parts:
        return 0.0
    full_text = ' '.join(text_parts).lower()
    if not full_text:
        return 0.0
    matches = 0
    total_keyword_occurrences = 0
    for keyword in keywords:
        pattern = r'\b' + re.escape(keyword) + r'\b'
        occurrences = len(re.findall(pattern, full_text))
        if occurrences > 0:
            matches += 1
            total_keyword_occurrences += occurrences

    if matches == 0:
        return 0.0
    keyword_coverage = matches / len(keywords)
    density = min(total_keyword_occurrences / 5.0, 1.0)
    relevance_score = (keyword_coverage * 0.7) + (density * 0.3)
    return min(relevance_score, 1.0)
def select_relevant_messages(
    messages: List[dict],
    current_query: str,
    max_tokens: int,
    keep_recent: int = ALWAYS_KEEP_RECENT,
    min_relevance: float = MIN_RELEVANCE_SCORE
) -> List[dict]:
    if len(messages) <= keep_recent + 1:
        return messages
    total_tokens = estimate_token_count(messages)
    if total_tokens <= max_tokens * 0.8:
        return messages

    keywords = extract_keywords(current_query)

    if not keywords:
        return messages[:1] + messages[-keep_recent:]
    result = [messages[0]]
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
    selected = select_relevant_messages(
        messages=messages,
        current_query=current_query,
        max_tokens=max_tokens,
        keep_recent=ALWAYS_KEEP_RECENT,
        min_relevance=MIN_RELEVANCE_SCORE
    )

    original_count = len(messages)
    selected_count = len(selected)

    if selected_count < original_count:
        original_tokens = estimate_token_count(messages)
        selected_tokens = estimate_token_count(selected)
        saved_tokens = original_tokens - selected_tokens
        saved_percentage = (saved_tokens / original_tokens * 100) if original_tokens > 0 else 0

        log(f"✓ Selective Context: {original_count} → {selected_count} messages")
        log(f"  Tokens: {original_tokens} → {selected_tokens} (saved {saved_tokens}, -{saved_percentage:.1f}%)")

    return selected


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