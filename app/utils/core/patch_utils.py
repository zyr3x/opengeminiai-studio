import re
import os
from app.utils.core import logging
from thefuzz import fuzz

MIN_FUZZY_MATCH_SCORE = 80

def apply_patches(response_text: str) -> tuple[str, list[str]]:
    """
    Parses the response text for patches and applies them using fuzzy matching.
    
    The expected format is:
    File: `path/to/file`
    <<<<<<< SEARCH
    ...
    =======
    ...
    >>>>>>> REPLACE
    
    It first attempts an exact match. If that fails, it uses fuzzy string matching
    to find the most likely location for the patch to be applied.
    
    Returns:
        tuple: (cleaned_response_text, list_of_applied_changes_descriptions)
    """
    
    patch_pattern = re.compile(
        r'(?:File|file):\s*`?([^`\n]+)`?\s*\n<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE',
        re.DOTALL
    )
    
    patches = list(patch_pattern.finditer(response_text))
    
    if not patches:
        return response_text, []

    applied_changes = []
    cleaned_text = response_text
    
    for match in reversed(list(patches)): # Reverse to handle indices correctly
        full_match_text = match.group(0)
        target_file = match.group(1).strip()
        search_block = match.group(2)
        replace_block = match.group(3)

        # Always remove the patch block from the chat response
        cleaned_text = cleaned_text.replace(full_match_text, "")

        if not os.path.exists(target_file):
            logging.log(f"⚠️ Patch skipped: Target file does not exist at {target_file}")
            continue

        try:
            with open(target_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # 1. Try for a direct, exact match first (fast path)
            if search_block in content:
                new_content = content.replace(search_block, replace_block, 1)
                with open(target_file, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                logging.log(f"✅ Applied exact patch to {target_file}")
                applied_changes.append(f"Applied exact patch to {target_file}")
                continue

            # 2. If exact match fails, use fuzzy matching (slower path)
            search_lines = search_block.splitlines()
            content_lines = content.splitlines()
            
            best_score = 0
            best_match_start_index = -1

            # Sliding window approach
            for i in range(len(content_lines) - len(search_lines) + 1):
                window_lines = content_lines[i : i + len(search_lines)]
                window_text = '\n'.join(window_lines)
                
                # Using token_set_ratio is good for ignoring word order and minor changes
                score = fuzz.token_set_ratio(search_block, window_text)
                
                if score > best_score:
                    best_score = score
                    best_match_start_index = i

            if best_score >= MIN_FUZZY_MATCH_SCORE:
                # Found a good enough fuzzy match, replace it
                start = best_match_start_index
                end = start + len(search_lines)
                
                # Reconstruct the file content
                new_content_lines = content_lines[:start]
                new_content_lines.extend(replace_block.splitlines())
                new_content_lines.extend(content_lines[end:])
                
                new_content = '\n'.join(new_content_lines)
                
                with open(target_file, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                logging.log(f"✅ Applied fuzzy patch to {target_file} (score: {best_score}%)")
                applied_changes.append(f"Applied fuzzy patch to {target_file} (score: {best_score}%)")
            else:
                logging.log(f"⚠️ Skipped patch for {target_file}: No match found (best score: {best_score}%)")

        except Exception as e:
            logging.log(f"❌ Error applying patch to {target_file}: {e}")

    # Clean up any leftover empty lines from removing the patch blocks
    cleaned_text = '\n'.join(line for line in cleaned_text.split('\n') if line.strip() or line)

    return cleaned_text, applied_changes
