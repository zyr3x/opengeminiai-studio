import re
import os
from app.utils.core import logging

def apply_patches(response_text: str) -> tuple[str, list[str]]:
    """
    Parses the response text for patches in the format:
    <<<<<<< SEARCH
    ...
    =======
    ...
    >>>>>>> REPLACE
    
    Applies them to the corresponding files found in the context or specified in the patch (if we add file path support later, 
    but for now it relies on unique search blocks or we can parse file paths if needed. 
    Actually, the prompt should probably specify the file path if multiple files are involved, 
    but let's start with a robust search/replace that tries to find the unique match).

    Wait, to be safe and precise, the patch should ideally specify the file. 
    However, the user request said "system itself applied patches".
    Let's define a format that includes the file path or rely on the context.
    
    Given the `code_path=` context, we might know which files are loaded.
    Let's support a format like:
    
    File: `path/to/file`
    <<<<<<< SEARCH
    ...
    =======
    ...
    >>>>>>> REPLACE
    
    Or just search globally in loaded files if the search block is unique.
    For now, let's implement a robust search-and-replace that looks for the block in the provided text.
    
    But wait, we need to write to the actual files on disk.
    
    Returns:
        tuple: (cleaned_response_text, list_of_applied_changes_descriptions)
    """
    
    # Regex to find patch blocks
    # We look for the standard conflict marker style, but used for search/replace
    patch_pattern = re.compile(
        r'<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE',
        re.DOTALL
    )
    
    patches = list(patch_pattern.finditer(response_text))
    
    if not patches:
        return response_text, []

    applied_changes = []
    
    # We need to know WHICH file to apply to. 
    # If the response text mentions "File: `...`" before the patch, we can use that.
    # Or we can scan all files loaded in the context (which we might not have easy access to here without passing it in).
    # Let's assume the prompt instructs the model to output the file path immediately before the patch.
    
    # Actually, a better approach for the "editing mode" is to pass the list of loaded files to this function,
    # or have this function search through the loaded files to find where the SEARCH block fits.
    # Since we don't have the loaded files list passed in yet, let's update the signature to accept loaded_file_paths if possible,
    # or just try to find the file path in the text preceding the patch.
    
    # Let's try to find the file path in the text.
    
    cleaned_text = response_text
    
    # We will process patches in reverse order to maintain indices if we were modifying the response text,
    # but here we are modifying files on disk and stripping the patches from the response.
    
    # To avoid messing up the text while iterating, let's build the result text.
    # Actually, we want to return "only the answer". 
    # If the model outputs: "Here is the fix:\nFile: foo.py\n<<<<...>>>", we probably want to remove the patch block.
    
    for match in patches:
        search_block = match.group(1)
        replace_block = match.group(2)
        full_match = match.group(0)
        
        # Find the file path associated with this patch
        # Look backwards from the patch start for something like "File: `path`" or "File: path"
        preceding_text = response_text[:match.start()]
        file_path_match = re.search(r'(?:File|file):\s*`?([^`\n]+)`?\s*$', preceding_text.strip().split('\n')[-1])
        
        target_file = None
        if file_path_match:
            target_file = file_path_match.group(1).strip()
            # Resolve absolute path if possible, or assume it's relative to project root
            # We need to be careful about security here, but `code_path` logic already validates paths.
            # We should probably verify this file exists.
            if not os.path.exists(target_file):
                # Try to resolve relative to cwd
                if os.path.exists(os.path.abspath(target_file)):
                    target_file = os.path.abspath(target_file)
                else:
                    target_file = None
        
        if not target_file:
            # Fallback: Try to find the search block in any of the files we might know about?
            # Without explicit file context, this is dangerous.
            # Let's log a warning and skip if we can't find the file.
            logging.log(f"⚠️ Could not identify target file for patch starting at index {match.start()}")
            continue
            
        try:
            with open(target_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
            if search_block in content:
                new_content = content.replace(search_block, replace_block)
                with open(target_file, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                applied_changes.append(f"Applied patch to {target_file}")
                
                # Remove the patch from the response text to clean it up
                cleaned_text = cleaned_text.replace(full_match, f"[Patch applied to {os.path.basename(target_file)}]")
            else:
                logging.log(f"⚠️ Search block not found in {target_file}")
                # We might want to leave the patch in the text so the user sees it failed?
                # Or replace with an error message.
                cleaned_text = cleaned_text.replace(full_match, f"[FAILED to apply patch to {os.path.basename(target_file)}: Search block not found]")
                
        except Exception as e:
            logging.log(f"❌ Error applying patch to {target_file}: {e}")
            cleaned_text = cleaned_text.replace(full_match, f"[Error applying patch to {os.path.basename(target_file)}: {e}]")

    return cleaned_text, applied_changes
