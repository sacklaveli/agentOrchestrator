import tempfile
import json
import re
from pathlib import Path
from .config import logger, OLLAMA_MODEL, OLLAMA_URL, AIDER_TIMEOUT
from .process_utils import run_with_timeout
from .file_utils import sanitize_file_path, fuzzy_find_file, find_related_files
from .ai_client import ollama_query, extract_json, get_embedding
from .vector_store import VectorStore 

def run_aider(project_dir, directive, context_files, step_id):
    enforcer_footer = """
\n
TIMETABLE: IMMEDIATE
TASK: Fix the code errors listed above.
OUTPUT FORMAT:
1. Use standard SEARCH/REPLACE blocks.
2. NO comments inside the SEARCH block (must match exactly).
3. NO conversational text.
"""
    final_directive = directive + enforcer_footer

    try:
        with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(final_directive)
            msg_file = f.name
    except: return "", "", 1
    
    aider_env = {
        "AIDER_MODEL": f"ollama/{OLLAMA_MODEL}",
        "OLLAMA_API_BASE": OLLAMA_URL,
        "AIDER_EDIT_FORMAT": "diff",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "TERM": "xterm-256color"
    }
    
    cmd = (f'aider --yes-always --no-auto-commits --dirty-commits --no-pretty '
           f'--model ollama/{OLLAMA_MODEL} --message-file "{msg_file}"')
    
    # Smart Context Expansion
    expanded_context = set()
    if context_files:
        for f in context_files:
            expanded_context.add(f)
            related = find_related_files(project_dir, f)
            if related:
                for r in related:
                    if r not in expanded_context:
                        logger.info(f"  🔗 Auto-linking related file: {r}")
                        expanded_context.add(r)
    
    active_files = []
    for f in expanded_context:
        abs_path = sanitize_file_path(project_dir, f)
        if abs_path and abs_path not in cmd: 
            cmd += f' "{abs_path}"'
            active_files.append(Path(abs_path).name)
            if len(active_files) >= 15: break 

    logger.info(f"▶ AIDER (Step {step_id})")
    logger.info(f"  📂 Files: {active_files}")
    logger.info(f"  📝 Directive: {directive[:100].replace(chr(10), ' ')}...") 

    try:
        out, err, code, to = run_with_timeout(cmd, cwd=project_dir, timeout=AIDER_TIMEOUT, env=aider_env)
        
        if code != 0:
             logger.warning(f"  ⚠️ Aider exited with code {code}")
        else:
             snippet = out[-300:].replace('\n', ' ') if out else "No output"
             logger.info(f"  📄 Result: ...{snippet}")
             
             logger.info("  🧹 Running Janitor (Auto-Format)...")
             try:
                 run_with_timeout("dotnet format whitespace", cwd=project_dir, timeout=30)
             except Exception:
                 pass 
        
        return out, err, code
    finally:
        try: Path(msg_file).unlink()
        except: pass

def perform_semantic_search(query_text, limit=3, only_extensions=None):
    """
    Searches the Vector DB with SQL-side filtering.
    """
    try:
        db = VectorStore()
        
        # Determine SQL Filter
        path_filter = None
        if only_extensions:
            # Note: Postgres LIKE is simple. If you need multiple exts, 
            # this logic would need to be smarter. For now, we assume .md is the main use case.
            if '.md' in only_extensions:
                path_filter = '%.md'
        
        if len(query_text) > 10 and path_filter:
             clean_query = query_text.replace('\n', ' ')[:100]
             logger.info(f"  🔎 Doc Search: '{clean_query}...'")
        
        query_vec = get_embedding(query_text)
        if not query_vec: return []
        
        # Pass filter to DB
        results = db.search(query_vec, limit=limit, path_filter=path_filter)
        
        final_results = []
        for r in results:
            file_path = r[0]
            content = r[1]
            formatted = f"Source: {file_path}\nContent:\n{content}"
            final_results.append(formatted)
                
        return final_results
    except Exception:
        return [] 

def reflect_on_failure(memory, step_goal, errors, project_dir, lang_profile):
    knowledge = memory.get("project_knowledge", {}).get("summary", "Unknown")
    
    # 1. Smart-Fix
    extra_files = []
    for err in errors:
        matches = re.findall(r"\b([A-Z][a-zA-Z0-9_]+)\b", err)
        for m in matches:
            exts = [".cs"] if lang_profile['name'] == "C#" else [".js", ".ts", ".rb"]
            for ext in exts:
                found = fuzzy_find_file(project_dir, f"{m}{ext}", lang_profile['ignore_dirs'])
                if found:
                    extra_files.append(str(found.relative_to(project_dir)))

    # 2. Semantic Search
    semantic_context = []
    if errors:
        semantic_context = perform_semantic_search(errors[0])

    prompt = f"""
You are a Lead {lang_profile['name']} Developer.
CONTEXT: {knowledge}
GOAL: {step_goal}
FAILURES: {json.dumps(errors[:10], indent=2)}

RELEVANT FILES LOCATED: {list(set(extra_files))}

RELEVANT CODE/DOCS (FROM VECTOR DB):
{json.dumps(semantic_context, indent=2)}

TASK: Provide a COMMAND to fix the code.
Return JSON: {{ "root_cause": "...", "fix_directive": "...", "relevant_files": ["file1"] }}
"""
    try: 
        reflection = json.loads(extract_json(ollama_query(prompt)))
        if "relevant_files" in reflection:
            reflection["relevant_files"].extend(extra_files)
            for item in semantic_context:
                match = re.search(r"Source: (.+)", item)
                if match:
                    reflection["relevant_files"].append(match.group(1))
                    
        return reflection
    except: return None