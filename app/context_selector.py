"""
Module for intelligently selecting relevant context from the dialogue history.

Instead of sending the entire dialogue history, only relevant messages are selected
based on the current query, saving 40-60% of tokens in long dialogues.
"""
import re
from typing import List, Dict, Tuple, Set
from collections import Counter

# --- Configuration Constants ---
MIN_RELEVANCE_SCORE = 0.3  # Minimum score for message inclusion
ALWAYS_KEEP_RECENT = 5  # Always keep the last N messages
MIN_KEYWORD_LENGTH = 3  # Minimum keyword length
MAX_KEYWORDS = 20  # Maximum keywords for analysis

# --- Stop words (extended list) ---
STOP_WORDS = {
    # English
    'the', 'is', 'at', 'which', 'on', 'a', 'an', 'as', 'are', 'was', 'were',
    'been', 'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
    'should', 'could', 'may', 'might', 'must', 'can', 'to', 'of', 'in', 'for',
    'with', 'by', 'from', 'up', 'about', 'into', 'through', 'during', 'before',
    'after', 'above', 'below', 'between', 'under', 'again', 'further', 'then',
    'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'both',
    'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not',
    'only', 'own', 'same', 'so', 'than', 'too', 'very', 'just', 'but', 'and',
    'or', 'if', 'because', 'until', 'while', 'this', 'that', 'these', 'those',
    'what', 'who', 'whom', 'whose', 'which', 'it', 'its', 'itself', 'they',
    'them', 'their', 'theirs', 'themselves', 'he', 'him', 'his', 'himself',
    'she', 'her', 'hers', 'herself', 'we', 'us', 'our', 'ours', 'ourselves',
    'you', 'your', 'yours', 'yourself', 'yourselves', 'i', 'me', 'my', 'mine',
    'myself',
    
    # Russian
    'и', 'в', 'во', 'не', 'что', 'он', 'на', 'я', 'с', 'со', 'как', 'а', 'то',
    'все', 'она', 'так', 'его', 'но', 'да', 'ты', 'к', 'у', 'же', 'вы', 'за',
    'бы', 'по', 'только', 'ее', 'мне', 'было', 'вот', 'от', 'меня', 'еще',
    'нет', 'о', 'из', 'ему', 'теперь', 'когда', 'даже', 'ну', 'вдруг', 'ли',
    'если', 'уже', 'или', 'ни', 'быть', 'был', 'него', 'до', 'вас', 'нибудь',
    'опять', 'уж', 'вам', 'сказал', 'ведь', 'там', 'потом', 'себя', 'ничего',
    'ей', 'может', 'они', 'тут', 'где', 'есть', 'надо', 'ней', 'для', 'мы',
    'тебя', 'их', 'чем', 'была', 'сам', 'чтоб', 'без', 'будто', 'человек',
    'чего', 'раз', 'тоже', 'себе', 'под', 'жизнь', 'будет', 'ж', 'тогда',
    'кто', 'этот', 'того', 'потому', 'этого', 'какой', 'совсем', 'ним',
    'здесь', 'этом', 'один', 'почти', 'мой', 'тем', 'чтобы', 'нее', 'кажется',
    'сейчас', 'были', 'куда', 'зачем', 'сказать', 'всех', 'никогда', 'сегодня',
    'можно', 'при', 'наконец', 'два', 'об', 'другой', 'хоть', 'после', 'над',
    'больше', 'тот', 'через', 'эти', 'нас', 'про', 'всего', 'них', 'какая',
    'много', 'разве', 'сказала', 'три', 'эту', 'моя', 'впрочем', 'хорошо',
    'свою', 'этой', 'перед', 'иногда', 'лучше', 'чуть', 'том', 'нельзя',
    'такой', 'им', 'более', 'всегда', 'конечно', 'всю', 'между'
}

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
    Умный выбор релевантных сообщений из истории.
    
    Алгоритм:
    1. Всегда берем system prompt (первое сообщение)
    2. Всегда берем последние keep_recent сообщений
    3. Из оставшихся выбираем по relevance score
    4. Сортируем по времени (сохраняем хронологию)
    
    Args:
        messages: Список всех сообщений
        current_query: Текущий запрос пользователя
        max_tokens: Максимальный лимит токенов
        keep_recent: Сколько последних сообщений всегда сохранять
        min_relevance: Минимальный relevance score
        
    Returns:
        Отфильтрованный список сообщений
    """
    from app.utils import estimate_token_count
    
    # Если сообщений мало, возвращаем все
    if len(messages) <= keep_recent + 1:
        return messages
    
    # Проверяем, нужна ли фильтрация вообще
    total_tokens = estimate_token_count(messages)
    if total_tokens <= max_tokens * 0.8:  # Если занимаем < 80% лимита
        return messages
    
    # 1. Извлекаем ключевые слова из текущего запроса
    keywords = extract_keywords(current_query)
    
    if not keywords:
        # Если не смогли извлечь ключевые слова, используем простое усечение
        return messages[:1] + messages[-keep_recent:]
    
    # 2. Всегда сохраняем первое сообщение (system prompt)
    result = [messages[0]]
    
    # 3. Последние сообщения тоже всегда сохраняем
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
        from app.utils import log, estimate_token_count

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
