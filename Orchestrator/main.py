import json
import time
import argparse
import sys
import subprocess
from pathlib import Path

# --- IMPORTS ---
from .config import logger, INITIAL_BACKOFF, MAX_BACKOFF, MAX_RETRIES, BUILD_TIMEOUT, LANGUAGE_PROFILES
from .process_utils import check_dependencies, run_with_timeout
from .file_utils import find_project_root, fuzzy_find_file
from .ai_client import ollama_query, extract_json, get_embedding
from .output_parser import parse_command_output, extract_files_from_output
from .memory_manager import load_memory, save_memory
from .recon_agent import perform_recursive_recon
from .execution_agent import run_aider, reflect_on_failure
# NEW: Import SmartRAG and the Architect
from .smart_rag import SmartRAG
from .planner import Architect
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

def get_git_hash(project_dir):
    """Gets current commit hash to detect changes."""
    try:
        out, _, _, _ = run_with_timeout("git rev-parse HEAD", cwd=project_dir, timeout=2)
        return out.strip() if out else None
    except: return None

def orchestrate(plan_file, language, build_cmd, test_cmd, force_recon=False, force_index=False):
    # 1. SETUP & DISCOVERY
    script_loc = Path(__file__).parent.resolve()
    project_dir = find_project_root(script_loc)
    if project_dir == script_loc: project_dir = find_project_root(Path.cwd())

    logger.info(f"📂 Project Root: {project_dir}")
    
    # Load Language Profile
    if language not in LANGUAGE_PROFILES:
        logger.critical(f"❌ Unknown language: {language}")
        return
    profile = LANGUAGE_PROFILES[language]
    active_build = build_cmd if build_cmd else profile['default_build']
    active_test = test_cmd if test_cmd else profile['default_test']
    
    check_dependencies(active_build)
    
    # 2. SMART INDEXING (LangChain/Chroma)
    try:
        # Initialize SmartRAG
        rag_system = SmartRAG(project_dir, reset_db=force_index)
        if force_index:
            rag_system.index_project()
        else:
            # We assume the DB is persistent. We could verify count here.
            pass
    except Exception as e:
        logger.warning(f"⚠️  SmartRAG Init failed: {e}")

    # 3. MEMORY & ARCHITECT INIT
    memory = load_memory(project_dir)
    # The Architect gets the profile to know about ignore_dirs
    architect = Architect(project_dir, profile)
    db = VectorStore() # Keep for error journaling if needed

    # 4. RECONNAISSANCE (Optional fallback)
    prev_conf = memory.get("project_knowledge", {}).get("confidence", 0)
    if prev_conf < 50 or force_recon:
        knowledge = perform_recursive_recon(project_dir, profile)
        memory["project_knowledge"] = knowledge
        save_memory(project_dir, memory)
    else:
        logger.info(f"✓ Using cached knowledge (Confidence: {prev_conf}%)")

    # 5. PLAN LOADING & INVESTIGATION
    plan_path = resolve_plan_path(plan_file, project_dir)
    if not plan_path:
        logger.critical(f"❌ Plan not found: {plan_file}")
        return
        
    try:
        plan_raw = plan_path.read_text(encoding='utf-8')
        
        # --- PHASE 1: THE DETECTIVE (Investigates using SmartRAG) ---
        investigation_context = architect.investigate(plan_raw)
        
        # --- PHASE 2: THE ARCHITECT (Creates steps) ---
        steps = architect.create_master_plan(plan_raw, investigation_context)
        
        if not steps:
            logger.critical(f"❌ Architect failed to generate steps.")
            return

    except Exception as e:
        logger.critical(f"Planning failed: {e}")
        return

    # 6. EXECUTION LOOP
    for i, step in enumerate(steps):
        # Handle both string/dict formats
        if isinstance(step, str):
            step_id = i + 1
            goal = step
            verification = active_test if "test" in goal.lower() else active_build
        else:
            step_id = step.get('id', i + 1)
            goal = step.get('goal', step.get('step', str(step)))
            verification = step.get('verification', active_build)
            if not verification: verification = active_build

        retries = 0
        backoff = INITIAL_BACKOFF
        
        logger.info(f"\n{'='*60}\nSTEP {step_id}: {goal}\n{'='*60}")
        
        # Intent Detection (Should we code or just verify?)
        force_execution = False
        action_verbs = ["add", "create", "implement", "write", "analyze", "refactor", "clone", "scaffold"]
        if any(v in goal.lower() for v in action_verbs):
            force_execution = True
            logger.info("🚀 Detected 'Feature' Intent: Will execute Aider before verifying.")

        previous_errors = [] 
        
        # SNAPSHOT STATE: Get Git Hash before starting the step
        hash_before = get_git_hash(project_dir)

        while retries < MAX_RETRIES:
            skip_verification = (retries == 0 and force_execution)
            is_success = False
            errors = []
            
            # Extract Verification Command
            if "Verification:" in goal:
                 parts = goal.split("Verification:")
                 current_cmd = parts[-1].strip()
            else:
                 current_cmd = verification

            if not skip_verification:
                logger.info(f"🔨 Verifying: {current_cmd}")
                out, err, code, to = run_with_timeout(current_cmd, cwd=project_dir, timeout=BUILD_TIMEOUT)
                output_combined = (out or "") + "\n" + (err or "")
                errors = parse_command_output(output_combined, profile['error_patterns'])
                is_success = (code == 0 and not errors)
                
                # --- STRICT CHANGE DETECTION ---
                # If the step was supposed to write code (force_execution=True)
                # But the Git Hash hasn't changed, it means Aider failed to save.
                if is_success and force_execution:
                    hash_now = get_git_hash(project_dir)
                    if hash_now == hash_before:
                        # Double check with diff (maybe uncommitted changes?)
                        diff = capture_git_diff(project_dir)
                        if not diff:
                            logger.warning("🛑 STRICT MODE: Build passed, but NO FILES CHANGED. Forcing retry.")
                            is_success = False
                            errors = ["Agent claimed success but no files were created or modified."]

            if is_success:
                logger.info(f"✓ Step {step_id} Complete")
                # Learning logic (optional)
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
            
            # --- PHASE 3: THE TACTICIAN (Targeting & Instruction) ---
            tactical_data = architect.create_tactical_spec(goal, step_id, investigation_context)
            
            # 1. Target Files (Pre-load for Aider)
            target_files = tactical_data.get("files", [])
            for f in target_files:
                found = fuzzy_find_file(project_dir, Path(f).name, profile['ignore_dirs'])
                if found:
                    focus_files.append(str(found))
                else:
                    # New file creation intent
                    if ".." not in f: # Safety check
                        pass # Aider handles new file paths if explicitly passed
            
            # 2. Reference Material Injection (The Clone Feature)
            reference_content = ""
            for ref in tactical_data.get("reference_files", []):
                ref_path = fuzzy_find_file(project_dir, Path(ref).name, profile['ignore_dirs'])
                if ref_path:
                    try:
                        content = ref_path.read_text(encoding='utf-8')
                        reference_content += f"\n\n--- REFERENCE SOURCE: {ref_path.name} (DO NOT EDIT) ---\n{content}\n"
                        logger.info(f"  📖 Injected Reference: {ref_path.name}")
                    except: pass
            
            # 3. Construct the Full Prompt
            tactical_instructions = tactical_data.get("instructions", "")
            full_prompt = f"# Step {step_id}\n\n{tactical_instructions}"
            
            if reference_content:
                full_prompt += f"\n\n# REFERENCE MATERIAL\nUse the code below as a template:\n{reference_content}"

            # 4. Reflection (If retrying)
            if retries > 0 and errors:
                logger.info("🤔 Reflecting on failure...")
                reflection = reflect_on_failure(memory, goal, errors, project_dir, profile)
                if reflection:
                    logger.info(f"  🧠 Analysis: {reflection.get('root_cause')}")
                    full_prompt += f"\n\nFAILURE ANALYSIS:\n{reflection.get('root_cause')}\nRECOMMENDED FIX:\n{reflection.get('fix_directive')}"
                    
                    if "relevant_files" in reflection:
                        for f in reflection["relevant_files"]:
                            found = fuzzy_find_file(project_dir, Path(f).name, profile['ignore_dirs'])
                            if found: focus_files.append(str(found))

            if errors:
                full_prompt += f"\n\nFailures:\n{json.dumps(errors[:10], indent=2)}"
            
            # 5. EXECUTE AIDER
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