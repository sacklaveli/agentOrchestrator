import json
import time
import argparse
import sys
import subprocess
from pathlib import Path
from .config import logger, INITIAL_BACKOFF, MAX_BACKOFF, MAX_RETRIES, BUILD_TIMEOUT, LANGUAGE_PROFILES
from .process_utils import check_dependencies, run_with_timeout
from .file_utils import find_project_root, fuzzy_find_file
from .ai_client import ollama_query, extract_json, get_embedding
from .output_parser import parse_command_output, extract_files_from_output
from .memory_manager import load_memory, save_memory
from .recon_agent import perform_recursive_recon
# Import perform_semantic_search
from .execution_agent import run_aider, reflect_on_failure, perform_semantic_search
from .indexer import CodeIndexer
from .vector_store import VectorStore

def resolve_plan_path(user_input, project_dir):
    p = Path(user_input).resolve()
    if p.exists(): return p
    p = project_dir / user_input
    if p.exists(): return p
    return None

def capture_git_diff(project_dir):
    try:
        out, _, _, _ = run_with_timeout("git diff HEAD", cwd=project_dir, timeout=5)
        return out
    except: return None

def orchestrate(plan_file, language, build_cmd, test_cmd, force_recon=False, force_index=False):
    # 1. SETUP
    script_loc = Path(__file__).parent.resolve()
    project_dir = find_project_root(script_loc)
    if project_dir == script_loc: project_dir = find_project_root(Path.cwd())

    logger.info(f"📂 Project Root: {project_dir}")
    
    # 2. PROFILE
    if language not in LANGUAGE_PROFILES:
        logger.critical(f"❌ Unknown language: {language}")
        return
    profile = LANGUAGE_PROFILES[language]
    active_build = build_cmd if build_cmd else profile['default_build']
    active_test = test_cmd if test_cmd else profile['default_test']
    
    check_dependencies(active_build)
    
    # 3. INDEXING
    try:
        logger.info("🧠 Checking code index...")
        indexer = CodeIndexer(project_dir)
        indexer.index_project(force=force_index)
    except Exception as e:
        logger.warning(f"⚠️  Indexing failed: {e}")

    memory = load_memory(project_dir)

    # 4. RECON
    prev_conf = memory.get("project_knowledge", {}).get("confidence", 0)
    if prev_conf < 50 or force_recon:
        knowledge = perform_recursive_recon(project_dir, profile)
        memory["project_knowledge"] = knowledge
        save_memory(project_dir, memory)
    else:
        logger.info(f"✓ Using cached knowledge (Confidence: {prev_conf}%)")

    # 5. PLAN
    plan_path = resolve_plan_path(plan_file, project_dir)
    if not plan_path:
        logger.critical(f"❌ Plan not found: {plan_file}")
        return
        
    try:
        plan_raw = plan_path.read_text(encoding='utf-8')
        
        # --- NEW: GLOBAL DOC SEARCH (Context for Understanding) ---
        logger.info("📚 Searching documentation for global context...")
        # We explicitly ask for .md files relevant to the *entire plan*
        global_docs = perform_semantic_search(plan_raw, limit=3, only_extensions=['.md'])
        
        doc_context_str = ""
        if global_docs:
            logger.info(f"  found {len(global_docs)} global doc chunks:")
            for d in global_docs:
                # Log just the filename/header for clarity
                title = d.split('\n')[0] 
                logger.info(f"    - {title}")
                doc_context_str += f"\n{d}\n"
        else:
            logger.info("  No specific documentation found for this plan.")
        # ----------------------------------------------------------
        
        prompt = f"""
        Read the following development plan.
        
        CONTEXT FROM DOCUMENTATION:
        {doc_context_str}
        
        TASK:
        1. Ignore the 'Goal', 'Context', and 'Constraints' sections.
        2. Extract ONLY the numbered steps (1., 2., 3., etc.).
        3. Do NOT summarize. Copy the step text exactly.
        
        PLAN CONTENT:
        {plan_raw}
        
        RETURN JSON ARRAY: 
        [
          {{ "id": 1, "goal": "Verify baseline..." }},
          {{ "id": 2, "goal": "Analyze ChunkingService..." }}
        ]
        """
        raw_response = extract_json(ollama_query(prompt))
        parsed_data = json.loads(raw_response)

        steps = []
        if isinstance(parsed_data, list):
            steps = parsed_data
        elif isinstance(parsed_data, dict):
            for key, val in parsed_data.items():
                if isinstance(val, list):
                    steps = val
                    break
        
        if not steps:
            logger.critical(f"❌ Could not find a list of steps.")
            return

    except Exception as e:
        logger.critical(f"Failed to parse steps: {e}")
        return

    # 6. EXECUTE
    db = VectorStore() 

    for i, step in enumerate(steps):
        if isinstance(step, str):
            step_id = i + 1
            goal = step
        else:
            step_id = step.get('id', i + 1)
            goal = step.get('goal', step.get('step', str(step)))

        retries = 0
        backoff = INITIAL_BACKOFF
        
        logger.info(f"\n{'='*60}\nSTEP {step_id}: {goal}\n{'='*60}")
        
        # Intent Detection
        force_execution = False
        action_verbs = ["add", "create", "implement", "write", "analyze", "refactor"]
        if any(v in goal.lower() for v in action_verbs):
            force_execution = True
            logger.info("🚀 Detected 'Feature' Intent: Will execute Aider before verifying.")

        previous_errors = [] 

        while retries < MAX_RETRIES:
            skip_verification = (retries == 0 and force_execution)
            is_success = False
            errors = []

            if "Verification:" in goal:
                parts = goal.split("Verification:")
                current_cmd = parts[-1].strip()
            else:
                current_cmd = active_test if "test" in goal.lower() else active_build

            if not skip_verification:
                logger.info(f"🔨 Verifying: {current_cmd}")
                out, err, code, to = run_with_timeout(current_cmd, cwd=project_dir, timeout=BUILD_TIMEOUT)
                output_combined = (out or "") + "\n" + (err or "")
                errors = parse_command_output(output_combined, profile['error_patterns'])
                is_success = (code == 0 and not errors)

            if is_success:
                logger.info(f"✓ Step {step_id} Complete")
                if previous_errors:
                    logger.info("🧠 Learning from success...")
                    diff = capture_git_diff(project_dir)
                    if diff and len(diff) < 10000: 
                        err_vec = get_embedding(previous_errors[0])
                        if err_vec:
                            db.save_journal(previous_errors[0], diff, err_vec)
                break

            if errors and (not previous_errors or errors[0] != previous_errors[0]):
                previous_errors = errors

            focus_files = extract_files_from_output(errors)
            directive = goal
            
            # --- NEW: STEP SPECIFIC DOC SEARCH (Action Context) ---
            # Before we ask Aider to do anything, we find relevant rules for THIS step
            logger.info(f"  🔍 Looking for documentation relevant to this step...")
            step_docs = perform_semantic_search(goal, limit=2, only_extensions=['.md'])
            
            if step_docs:
                 logger.info(f"  📖 Found {len(step_docs)} relevant documentation chunks:")
                 doc_context = ""
                 for d in step_docs:
                     title = d.split('\n')[0]
                     logger.info(f"    - {title}")
                     doc_context += f"\n{d}\n"
                 
                 # Inject into directive
                 directive += f"\n\nRELEVANT DOCUMENTATION & PATTERNS:\n{doc_context}"
            # ------------------------------------------------------

            if retries > 0 and errors:
                logger.info("🤔 Reflecting...")
                reflection = reflect_on_failure(memory, goal, errors, project_dir, profile)
                if reflection:
                    logger.info(f"  🧠 Analysis: {reflection.get('root_cause')}")
                    directive = f"FAILURE.\nANALYSIS: {reflection.get('root_cause')}\nACTION: {reflection.get('fix_directive')}"
                    if "relevant_files" in reflection:
                        for f in reflection["relevant_files"]:
                            found = fuzzy_find_file(project_dir, Path(f).name, profile['ignore_dirs'])
                            if found: focus_files.append(str(found))

            full_prompt = f"# Step {step_id}\n\n{directive}"
            if errors:
                full_prompt += f"\n\nFailures:\n{json.dumps(errors[:10], indent=2)}"
            
            run_aider(project_dir, full_prompt, focus_files, step_id)
            
            retries += 1
            if retries < MAX_RETRIES:
                time.sleep(backoff)
                backoff = min(backoff * 1.5, MAX_BACKOFF)
            else:
                logger.error("❌ Failed")
                return

    logger.info("🎉 Done")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('plan_file')
    parser.add_argument('--language', default='csharp', help='csharp, node, rails')
    parser.add_argument('--build-cmd', help='Override build command')
    parser.add_argument('--test-cmd', help='Override test command')
    parser.add_argument('--force-recon', action='store_true')
    parser.add_argument('--reindex', action='store_true')
    args = parser.parse_args()
    
    orchestrate(args.plan_file, args.language, args.build_cmd, args.test_cmd, args.force_recon, args.reindex)