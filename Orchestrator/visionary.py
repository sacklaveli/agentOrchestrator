import os
import sys
import json
import time
import argparse
from pathlib import Path

# --- IMPORTS ---
from .config import logger, PLANNER_MODEL
from .ai_client import ollama_query, extract_json
from .supervisor import Supervisor
# Import the Architect from planner (which uses SmartRAG internally)
from .planner import Architect as TacticianArchitect 
from .file_utils import find_project_root

# Configure a specific logger for Visionary to keep things clean
v_logger = logger.getChild("visionary")

class Visionary:
    def __init__(self, big_plan_file, project_dir, cli_args):
        self.project_dir = Path(project_dir)
        self.big_plan_file = Path(big_plan_file)
        self.cli_args = cli_args
        self.memory_file = self.project_dir / "orchestrator_vision.json"
        
        # Profile for ignoring junk dirs during research
        self.profile = {"ignore_dirs": [".git", "bin", "obj", "node_modules", ".vs", ".idea"]} 
        
        # The Visionary uses the Architect tool to "Research & Draft" plans
        self.architect_tool = TacticianArchitect(self.project_dir, self.profile)

    def load_history(self):
        if self.memory_file.exists():
            try:
                return json.loads(self.memory_file.read_text(encoding='utf-8'))
            except:
                v_logger.warning("⚠️  Corrupt memory file. Starting fresh.")
        return {"completed_milestones": [], "failed_attempts": []}

    def save_history(self, history):
        self.memory_file.write_text(json.dumps(history, indent=2), encoding='utf-8')

    def run(self):
        print("\n" + "="*60)
        v_logger.info(f"🚀 VISIONARY STARTED")
        v_logger.info(f"📂 Target Project: {self.project_dir}")
        v_logger.info(f"📜 Grand Strategy: {self.big_plan_file.name}")
        print("="*60 + "\n")
        
        # Read the Grand Strategy
        try:
            goal_text = self.big_plan_file.read_text(encoding='utf-8')
        except Exception as e:
            v_logger.critical(f"❌ Could not read strategy file: {e}")
            return

        history = self.load_history()

        while True:
            # --- STATUS REPORT ---
            completed = len(history['completed_milestones'])
            failed = len(history['failed_attempts'])
            v_logger.info(f"📊 STATUS: {completed} Milestones Complete | {failed} Failures Detected")

            # 1. STRATEGY PHASE (The CEO decides what to do)
            v_logger.info("🧠 STRATEGIST: Analyzing project state...")
            next_move = self.strategize(goal_text, history)
            
            if next_move.get("status") == "COMPLETE":
                v_logger.info("🏆 VISIONARY: The Grand Strategy is Complete!")
                print("\n" + "="*60)
                print("      MISSION ACCOMPLISHED      ")
                print("="*60 + "\n")
                break
            
            # Sanity check directive
            directive = next_move.get("directive")
            if not directive:
                v_logger.error("❌ STRATEGIST: Produced an empty directive. Retrying in 10s...")
                time.sleep(10)
                continue

            v_logger.info(f"👉 NEXT MOVE: {directive}")
            
            # Check if we are looping on a failure
            if directive in history['failed_attempts']:
                v_logger.warning(f"⚠️  RETRYING FAILED OBJECTIVE: {directive}")
                # We let it proceed, hoping the Strategist generated a "Fix" directive this time

            # 2. ARCHITECT PHASE (The Manager researches and writes the plan)
            plan_filename = f"visionary_plan_{int(time.time())}.md"
            plan_path = self.project_dir / plan_filename
            
            success = self.create_execution_plan(directive, plan_path)
            
            if not success:
                v_logger.error("❌ ARCHITECT: Failed to generate a valid plan file. Skipping turn.")
                continue

            # 3. SUPERVISOR PHASE (The Foreman executes the plan)
            v_logger.info(f"👮 DELEGATING: Handing '{plan_filename}' to Supervisor")
            
            # Initialize Supervisor with the specific plan file
            supervisor = Supervisor([str(plan_filename)], self.cli_args)
            
            start_time = time.time()
            try:
                # Run the Supervisor (It handles retries, loops, and crashes internally)
                supervisor.run()
                # If supervisor.run() returns (doesn't exit), it means success
                result = "SUCCESS"
            except SystemExit as e:
                # Supervisor calls sys.exit(1) on failure
                result = "FAILURE" if e.code != 0 else "SUCCESS"
            except Exception as e:
                v_logger.error(f"💥 SUPERVISOR CRASHED: {e}")
                result = "FAILURE"
            
            duration = round(time.time() - start_time, 1)

            # 4. REFLECTION PHASE (Update History)
            if result == "SUCCESS":
                v_logger.info(f"✅ MILESTONE COMPLETE ({duration}s): {directive}")
                history["completed_milestones"].append(directive)
                # Cleanup the temp plan file to keep dir clean
                try: plan_path.unlink() 
                except: pass
            else:
                v_logger.error(f"🚫 MILESTONE FAILED ({duration}s): {directive}")
                history["failed_attempts"].append(directive)
            
            self.save_history(history)
            
            v_logger.info("💤 Resting for 5 seconds before next strategic review...")
            time.sleep(5)

    def strategize(self, big_goal, history):
        """
        The Visionary looks at the Big Goal + History and decides the next chunk.
        """
        prompt = f"""
        You are the CIO/Visionary of a software project.
        
        BIG GOAL:
        {big_goal}
        
        HISTORY:
        Completed: {json.dumps(history['completed_milestones'], indent=2)}
        Failures: {json.dumps(history['failed_attempts'], indent=2)}
        
        TASK: Decide the IMMEDIATE NEXT MILESTONE.
        - If the project is done, return "COMPLETE".
        - The milestone must be small enough to execute in 10-20 minutes.
        - **CRITICAL:** If the Big Goal mentions a "Reference" or "Clone Source", you MUST explicitly mention that source file/folder in your directive.
          - ❌ Bad: "Scaffold the service."
          - ✅ Good: "Scaffold the service by cloning infrastructure from services/FormFieldAnalysis."
        
        - If a milestone failed previously, you MUST propose a DIFFERENT approach or a "Fix" step.
        - **DO NOT** repeat a failed milestone identically.
        
        RETURN JSON:
        {{
            "status": "IN_PROGRESS",  // or "COMPLETE"
            "directive": "Create the initial folder structure for the Auth Service"
        }}
        """
        try:
            return json.loads(extract_json(ollama_query(prompt, model=PLANNER_MODEL)))
        except:
            v_logger.error("❌ STRATEGIST: LLM JSON Malformed")
            return {"status": "ERROR"}

    def create_execution_plan(self, directive, output_path):
        """
        The Architect takes the Directive, Research, and writes a high-quality .md file.
        """
        v_logger.info("🏗️  ARCHITECT: Researching codebase for context...")
        
        # 1. Reuse the Detective (from planner.py) to find context
        # This will use SmartRAG to search the vector DB if needed
        context = self.architect_tool.investigate(directive, max_turns=3)
        v_logger.info(f"    found {len(context)} chars of context.")

        # 2. Ask LLM to write the Plan File
        v_logger.info("🏗️  ARCHITECT: Drafting execution plan...")
        prompt = f"""
        You are a Senior Solutions Architect.
        
        DIRECTIVE: {directive}
        
        CONTEXT FROM REPO:
        {context}
        
        TASK: Write a robust, detailed Markdown Plan for the AI Developer.
        - The format MUST exactly match the example below.
        - Use the Context to reference real file paths (reference files, source files).
        - Break it down into clear steps.
        - Include verification commands.
        
        EXAMPLE FORMAT:
        # Goal: <Directive Name>
        
        ## Context
        <Summary of what we know>
        
        ## Steps
        1. Create file `src/X.cs`...
           - Verification: `dotnet build...`
        """
        
        try:
            plan_content = ollama_query(prompt, model=PLANNER_MODEL)
            # Remove any Markdown code blocks if the LLM wraps the whole file
            if plan_content.startswith("```markdown"):
                plan_content = plan_content.replace("```markdown", "").replace("```", "")
            
            output_path.write_text(plan_content, encoding='utf-8')
            v_logger.info(f"📝 PLAN WRITTEN: {output_path.name}")
            return True
        except Exception as e:
            v_logger.error(f"❌ ARCHITECT FAILURE: {e}")
            return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Visionary: Autonomous Project Manager")
    parser.add_argument('big_plan', help='Markdown file containing the Grand Goal')
    
    # Pass-through args for the lower layers
    parser.add_argument('--language', default='csharp')
    parser.add_argument('--reindex', action='store_true', help='Force RAG re-indexing')
    parser.add_argument('--force-recon', action='store_true', help='Force file tree recon')
    
    args, unknown = parser.parse_known_args()
    
    pass_through_args = []
    if args.language: pass_through_args.extend(['--language', args.language])
    if args.reindex: pass_through_args.append('--reindex')
    if args.force_recon: pass_through_args.append('--force-recon')
    pass_through_args.extend(unknown)

    # Find project root
    script_loc = Path(__file__).parent.resolve()
    project_root = find_project_root(script_loc)
    if project_root == script_loc: project_root = find_project_root(Path.cwd())

    visionary = Visionary(args.big_plan, project_root, pass_through_args)
    visionary.run()