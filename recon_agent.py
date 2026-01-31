import json
from pathlib import Path
from .config import logger
from .ai_client import ollama_query, extract_json
from .file_utils import get_file_tree, fuzzy_find_file

def perform_recursive_recon(project_dir, lang_profile):
    logger.info("="*60)
    logger.info("🧠 RECURSIVE KNOWLEDGE ACQUISITION LOOP")
    logger.info("="*60)
    
    tree = get_file_tree(project_dir, ignore_dirs=lang_profile['ignore_dirs'])
    current_knowledge = "None. Just started."
    known_files = set()
    confidence = 0
    iteration = 0
    MAX_ITERATIONS = 4 
    
    while confidence < 85 and iteration < MAX_ITERATIONS:
        iteration += 1
        logger.info(f"\n🔄 Iteration {iteration}/{MAX_ITERATIONS} (Confidence: {confidence}%)")
        
        prompt_investigate = f"""
You are investigating a {lang_profile['name']} codebase.
FILE TREE:
{tree}

CURRENT KNOWLEDGE:
{current_knowledge}

TASK:
Identify 3-5 files to read next to understand the architecture, build system, and testing setup.
Look for files like: {lang_profile['critical_files']}
Return JSON list: ["path/to/file"]
"""
        resp = ollama_query(prompt_investigate)
        target_files = []
        try: target_files = json.loads(extract_json(resp))
        except: pass

        if not isinstance(target_files, list): target_files = []
        new_files = [f for f in target_files if f not in known_files]
        
        if not new_files:
            logger.info("No new files requested.")
            break
            
        logger.info(f"→ Investigating: {new_files}")
        
        file_contents = {}
        for rel_path in new_files:
            clean_name = Path(rel_path).name 
            found_path = fuzzy_find_file(project_dir, clean_name, lang_profile['ignore_dirs'])
            
            if found_path:
                try:
                    text = found_path.read_text(encoding='utf-8', errors='ignore')
                    key = str(found_path.relative_to(project_dir))
                    file_contents[key] = "\n".join(text.splitlines()[:300])
                    known_files.add(rel_path)
                    logger.info(f"  ✓ Found: {key}")
                except: pass
        
        if not file_contents: continue 

        prompt_synthesize = f"""
Update our Mental Map.
PREVIOUS: {current_knowledge}
NEW FILES: {json.dumps(file_contents, indent=2)}

TASK:
1. Summarize architecture.
2. Rate confidence (0-100).

Return JSON: {{ "updated_knowledge": "...", "missing_info": "...", "confidence_score": 85 }}
"""
        resp_map = ollama_query(prompt_synthesize)
        try:
            data = json.loads(extract_json(resp_map))
            current_knowledge = data.get("updated_knowledge", current_knowledge)
            confidence = int(data.get("confidence_score", 0))
            logger.info(f"→ Knowledge updated.")
        except: pass

    logger.info(f"✅ Reconnaissance Complete (Final: {confidence}%)")
    return {
        "summary": current_knowledge,
        "confidence": confidence,
        "checked_files": list(known_files)
    }