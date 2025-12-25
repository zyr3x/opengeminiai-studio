"""
Enhanced Auxiliary Model Module

Provides intelligent summarization, analysis, and decision support
using a lightweight auxiliary model for agent operations.
"""

import json
from typing import Dict, List, Optional, Tuple
from app.config import config
from app.utils.core.logging import log
from app.utils.core.optimization_utils import estimate_tokens


class AuxModelStrategy:
    """Defines different strategies for using the aux model"""
    
    STRATEGIES = {
        'summarize': {
            'temperature': 0.2,
            'max_output': 1024,
            'prompt_template': (
                "Summarize this tool output concisely while keeping ALL critical "
                "information: file paths, function names, errors, key results.\n\n"
                "Tool: {tool_name}\n\nOutput:\n{content}"
            )
        },
        'extract_key_info': {
            'temperature': 0.1,
            'max_output': 512,
            'prompt_template': (
                "Extract ONLY the most critical information from this tool output:\n"
                "- File paths and line numbers\n"
                "- Function/class names\n"
                "- Error messages\n"
                "- Key findings\n\n"
                "Tool: {tool_name}\n\nOutput:\n{content}"
            )
        },
        'structure': {
            'temperature': 0.1,
            'max_output': 768,
            'prompt_template': (
                "Convert this tool output into a structured, easy-to-parse format:\n"
                "- Use bullet points\n"
                "- Group related items\n"
                "- Highlight critical info with ⚠️ or ✓\n\n"
                "Tool: {tool_name}\n\nOutput:\n{content}"
            )
        },
        'analyze': {
            'temperature': 0.3,
            'max_output': 1024,
            'prompt_template': (
                "Analyze this tool output and provide:\n"
                "1. Key findings\n"
                "2. Potential issues or concerns\n"
                "3. Recommended next actions\n\n"
                "Tool: {tool_name}\n\nOutput:\n{content}"
            )
        },
        'filter_relevant': {
            'temperature': 0.1,
            'max_output': 1024,
            'prompt_template': (
                "From this tool output, extract ONLY information relevant to: {context}\n"
                "Remove noise, keep signal.\n\n"
                "Tool: {tool_name}\n\nOutput:\n{content}"
            )
        }
    }
    
    @classmethod
    def choose_strategy(cls, tool_name: str, content: str, task_context: str = None) -> str:
        """Intelligently choose the best strategy based on tool and content"""
        
        # Tool-specific strategies
        if tool_name in ['list_files', 'search_codebase', 'find_references']:
            # These produce lists - structure them
            return 'structure'
        
        elif tool_name in ['get_file_content', 'git_diff', 'git_show']:
            # Large code blocks - extract key info
            return 'extract_key_info'
        
        elif tool_name in ['analyze_project_structure', 'analyze_file_structure']:
            # Analysis output - summarize findings
            return 'summarize'
        
        elif tool_name in ['run_tests', 'execute_command']:
            # Command output - analyze for issues
            return 'analyze'
        
        elif task_context:
            # User has specific context - filter for relevance
            return 'filter_relevant'
        
        # Default strategy
        return 'summarize'


class AuxModelCache:
    """Cache aux model results to avoid redundant calls"""
    
    def __init__(self, max_size: int = 100):
        self.cache: Dict[str, str] = {}
        self.max_size = max_size
        self.hits = 0
        self.misses = 0
    
    def _make_key(self, tool_name: str, content: str, strategy: str) -> str:
        """Create cache key"""
        import hashlib
        content_hash = hashlib.md5(content.encode()).hexdigest()[:16]
        return f"{tool_name}:{strategy}:{content_hash}"
    
    def get(self, tool_name: str, content: str, strategy: str) -> Optional[str]:
        """Get cached result"""
        key = self._make_key(tool_name, content, strategy)
        result = self.cache.get(key)
        
        if result:
            self.hits += 1
            log(f"✓ Aux model cache HIT ({self.hits}/{self.hits + self.misses})")
        else:
            self.misses += 1
        
        return result
    
    def set(self, tool_name: str, content: str, strategy: str, result: str):
        """Cache result"""
        key = self._make_key(tool_name, content, strategy)
        
        # Implement simple LRU by removing oldest if full
        if len(self.cache) >= self.max_size:
            # Remove first item (oldest)
            first_key = next(iter(self.cache))
            del self.cache[first_key]
        
        self.cache[key] = result
    
    def clear(self):
        """Clear cache"""
        self.cache.clear()
        self.hits = 0
        self.misses = 0


class AuxModelEnhanced:
    """Enhanced auxiliary model with intelligent processing"""
    
    def __init__(self):
        self.cache = AuxModelCache(max_size=config.AUX_MODEL_CACHE_SIZE)
        self.total_calls = 0
        self.total_tokens_saved = 0

    def should_use_aux(self, tool_name: str, content: str) -> bool:
        """Decide if aux model should be used"""
        if not config.AGENT_AUX_MODEL_ENABLED:
            return False

        tokens = estimate_tokens(content)

        # Don't use for very short content
        if tokens < config.AUX_MODEL_MIN_TOKENS:
            return False

        # Use for content exceeding threshold
        if tokens > config.AUX_MODEL_MAX_TOKENS:
            return True

        # For specific tools, always use even if not too long
        always_process = ['analyze_project_structure', 'run_tests', 'git_log']
        if tool_name in always_process and tokens > config.AUX_MODEL_MIN_TOKENS * 2:
            return True
        
        return False
    
    def process_with_aux(
        self, 
        tool_name: str, 
        content: str,
        strategy: str = None,
        task_context: str = None
    ) -> Tuple[str, Dict]:
        """
        Process content with auxiliary model
        
        Returns: (processed_content, metadata)
        """
        if not self.should_use_aux(tool_name, content):
            return content, {'used_aux': False, 'reason': 'not_needed'}
        
        # Choose strategy
        if not strategy:
            strategy = AuxModelStrategy.choose_strategy(tool_name, content, task_context)
        
        if not strategy or strategy not in AuxModelStrategy.STRATEGIES:
            strategy = 'summarize'
        
        # Check cache first
        cached = self.cache.get(tool_name, content, strategy)
        if cached:
            return cached, {
                'used_aux': True,
                'strategy': strategy,
                'from_cache': True,
                'tokens_before': estimate_tokens(content),
                'tokens_after': estimate_tokens(cached)
            }
        
        # Call aux model
        log(f"🤖 Processing with aux model: {tool_name} (strategy: {strategy})")
        
        strategy_config = AuxModelStrategy.STRATEGIES[strategy]
        prompt_template = strategy_config['prompt_template']
        
        # Format prompt
        prompt = prompt_template.format(
            tool_name=tool_name,
            content=content,
            context=task_context or "general development task"
        )
        
        try:
            result = self._call_aux_model(prompt, strategy_config)
            
            # Cache result
            self.cache.set(tool_name, content, strategy, result)
            
            # Track metrics
            self.total_calls += 1
            tokens_before = estimate_tokens(content)
            tokens_after = estimate_tokens(result)
            tokens_saved = tokens_before - tokens_after
            self.total_tokens_saved += tokens_saved
            
            metadata = {
                'used_aux': True,
                'strategy': strategy,
                'from_cache': False,
                'tokens_before': tokens_before,
                'tokens_after': tokens_after,
                'tokens_saved': tokens_saved,
                'total_calls': self.total_calls,
                'total_saved': self.total_tokens_saved
            }
            
            log(f"✓ Aux model: {tokens_before} → {tokens_after} tokens (saved {tokens_saved})")
            
            return result, metadata
            
        except Exception as e:
            log(f"❌ Aux model error: {e}")
            return content, {'used_aux': False, 'reason': 'error', 'error': str(e)}
    
    def _call_aux_model(self, prompt: str, strategy_config: Dict) -> str:
        """Make actual API call to aux model"""
        from app.utils.core.tools import make_request_with_retry, get_provider_for_model
        import requests

        provider = get_provider_for_model(config.AGENT_AUX_MODEL_NAME)

        if provider == 'openai':
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f"Bearer {config.OPENAI_API_KEY}"
            }
            request_data = {
                "model": config.OPENAI_MODEL_NAME,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": strategy_config['temperature'],
                "max_tokens": strategy_config['max_output']
            }
            try:
                response = requests.post(
                    f"{config.OPENAI_BASE_URL}/chat/completions",
                    headers=headers,
                    json=request_data,
                    timeout=120
                )
                response.raise_for_status()
                data = response.json()
                return data['choices'][0]['message']['content']
            except Exception as e:
                raise ValueError(f"OpenAI API Error: {e}")
        
        GEMINI_URL = f"{config.UPSTREAM_URL}/v1beta/models/{config.AGENT_AUX_MODEL_NAME}:generateContent"
        
        headers = {
            'Content-Type': 'application/json',
            'X-goog-api-key': config.API_KEY
        }
        
        request_data = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": strategy_config['temperature'],
                "maxOutputTokens": strategy_config['max_output']
            }
        }
        
        response = make_request_with_retry(
            url=GEMINI_URL,
            headers=headers,
            json_data=request_data,
            stream=False,
            timeout=120
        )
        
        response_data = response.json()

        # Check for explicit API errors in the response body
        if 'error' in response_data:
            error_details = response_data['error']
            raise ValueError(f"Google API Error: {error_details.get('message', 'Unknown error')}")

        try:
            # Safely navigate the response structure with defensive checks
            if 'candidates' not in response_data or not response_data['candidates']:
                # Check for prompt feedback blocks
                if response_data.get('promptFeedback', {}).get('blockReason'):
                    reason = response_data['promptFeedback']['blockReason']
                    raise ValueError(f"Request blocked by Google API. Reason: {reason}")
                raise ValueError(f"No candidates in API response. Response: {json.dumps(response_data, indent=2)}")

            candidate = response_data['candidates'][0]

            # The model can return a candidate but no content, e.g. due to safety filters.
            if 'content' not in candidate or not candidate.get('content') or not candidate['content'].get('parts'):
                finish_reason = candidate.get('finishReason', 'UNKNOWN')
                if finish_reason == 'SAFETY':
                    safety_ratings = candidate.get('safetyRatings')
                    raise ValueError(f"Content blocked by Google API due to safety filters. Ratings: {safety_ratings}")

                if response_data.get('promptFeedback', {}).get('blockReason'):
                    reason = response_data['promptFeedback']['blockReason']
                    raise ValueError(f"Request blocked by Google API. Reason: {reason}")

                raise ValueError(f"No valid content in API response. Finish reason: {finish_reason}")

            parts = candidate['content'].get('parts', [])
            if not parts or 'text' not in parts[0]:
                raise ValueError(f"No text in response parts. Parts: {parts}")

            return parts[0]['text']

        except (KeyError, IndexError) as e:
            log(f"🔍 Aux model response parsing failed. Error: {e}. Full response: {json.dumps(response_data, indent=2)}")
            raise ValueError(f"Invalid response structure from aux model, couldn't parse. Details: {e}")

    def process_multiple(
        self,
        tool_outputs: List[Tuple[str, str]],
        task_context: str = None
    ) -> List[Tuple[str, Dict]]:
        """
        Process multiple tool outputs in batch
        
        Args:
            tool_outputs: List of (tool_name, content) tuples
            task_context: Overall task context
            
        Returns:
            List of (processed_content, metadata) tuples
        """
        results = []
        
        for tool_name, content in tool_outputs:
            processed, metadata = self.process_with_aux(tool_name, content, task_context=task_context)
            results.append((processed, metadata))
        
        return results
    
    def get_stats(self) -> Dict:
        """Get usage statistics"""
        return {
            'total_calls': self.total_calls,
            'total_tokens_saved': self.total_tokens_saved,
            'cache_hits': self.cache.hits,
            'cache_misses': self.cache.misses,
            'cache_hit_rate': self.cache.hits / (self.cache.hits + self.cache.misses) if (self.cache.hits + self.cache.misses) > 0 else 0
        }
    
    def reset_stats(self):
        """Reset statistics"""
        self.total_calls = 0
        self.total_tokens_saved = 0
        self.cache.clear()


# Global instance
_aux_model_instance: Optional[AuxModelEnhanced] = None

def get_aux_model() -> AuxModelEnhanced:
    """Get or create global aux model instance"""
    global _aux_model_instance
    if _aux_model_instance is None:
        _aux_model_instance = AuxModelEnhanced()
    return _aux_model_instance


def process_tool_output_with_aux(
    tool_name: str,
    content: str,
    task_context: str = None
) -> Tuple[str, Dict]:
    """
    Convenience function to process tool output
    
    Usage:
        result, metadata = process_tool_output_with_aux('list_files', large_output)
    """
    aux = get_aux_model()
    return aux.process_with_aux(tool_name, content, task_context=task_context)
