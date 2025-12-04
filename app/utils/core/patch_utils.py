import re
import os
from app.utils.core import logging

def apply_patches(response_text: str) -> tuple[str, list[str]]:
    """
    Parses the response text for patches, applies them to files,
    and removes the technical patch blocks from the returned text.

    Returns:
        tuple: (cleaned_text_for_user, list_of_applied_changes_descriptions)
    """

    # Regex to find patch blocks
    patch_pattern = re.compile(
        r'<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE',
        re.DOTALL
    )

    patches = list(patch_pattern.finditer(response_text))

    if not patches:
        return response_text, []

    applied_changes = []
    cleaned_text = response_text

    for match in reversed(patches):
        search_block = match.group(1)
        replace_block = match.group(2)

        removal_start = match.start()
        removal_end = match.end()

        preceding_text = response_text[:match.start()]
        lines = preceding_text.splitlines(keepends=True)

        target_file_raw = None
        target_file_abs = None

        lines_to_check = 5
        chars_scanned_from_end = 0

        for line in reversed(lines):
            if lines_to_check <= 0:
                break
            lines_to_check -= 1

            file_match = re.search(r'(?i)(?:^|\n)\s*(?:\**)?(?:File|Path|Target)(?:\**)?\s*:?\s*[`\'"]?([^`\'"\n\r]+)[`\'"]?', line)

            if file_match:
                candidate = file_match.group(1).strip()
                is_path_like = '.' in candidate or '/' in candidate or '\\' in candidate

                if candidate and (os.path.exists(candidate) or os.path.exists(os.path.abspath(candidate)) or is_path_like):
                    target_file_raw = candidate
                    line_length = len(line)
                    line_start_index = match.start() - chars_scanned_from_end - line_length
                    removal_start = line_start_index
                    break

            chars_scanned_from_end += len(line)

        status_message = ""

        if not target_file_raw:
            logging.log(f"⚠️ Could not identify target file for patch starting at index {match.start()}")
            status_message = f"\n> ⚠️ *Failed to apply patch: Could not identify target file*\n"
        else:
            # Определяем полный абсолютный путь
            if os.path.isabs(target_file_raw):
                target_file_abs = target_file_raw
            else:
                # Превращаем относительный путь в абсолютный
                target_file_abs = os.path.abspath(target_file_raw)

            try:
                if not os.path.exists(target_file_abs):
                    # Fallback: пробуем найти, если путь был указан относительно текущей папки
                    if os.path.exists(os.path.abspath(target_file_raw)):
                         target_file_abs = os.path.abspath(target_file_raw)
                    else:
                         logging.log(f"Target file does not exist: {target_file_abs}")
                         status_message = f"\n> ⚠️ *Failed: File `{target_file_raw}` not found*\n"
                         target_file_abs = None

                if target_file_abs:
                    with open(target_file_abs, 'r', encoding='utf-8') as f:
                        content = f.read()

                    content_normalized = content.replace('\r\n', '\n')
                    search_block_normalized = search_block.replace('\r\n', '\n')

                    if search_block_normalized in content_normalized:
                        new_content = content_normalized.replace(search_block_normalized, replace_block)
                        with open(target_file_abs, 'w', encoding='utf-8') as f:
                            f.write(new_content)

                        # !!! ИЗМЕНЕНИЕ ЗДЕСЬ: Используем target_file_abs вместо target_file_raw !!!
                        applied_changes.append(target_file_abs)
                        logging.log(f"Applied patch to {target_file_abs}")

                        # Выводим полный путь пользователю
                        status_message = f"\n> 📝 *Applied patch to `{target_file_abs}`*\n"
                    else:
                        logging.log(f"⚠️ Search block not found in {target_file_abs}")
                        status_message = f"\n> ⚠️ *Failed to apply patch to `{target_file_raw}`: Search block match failed*\n"

            except Exception as e:
                logging.log(f"❌ Error applying patch to {target_file_abs}: {e}")
                status_message = f"\n> ❌ *Error applying patch: {str(e)}*\n"

        cleaned_text = cleaned_text[:removal_start] + status_message + cleaned_text[removal_end:]

    return cleaned_text, applied_changes