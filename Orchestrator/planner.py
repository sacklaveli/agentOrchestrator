import json
from .config import logger, PLANNER_MODEL
from .ai_client import ollama_query, extract_json
from .file_utils import fuzzy_find_file
# NEW: Import SmartRAG for intelligent retrieval
from .smart_rag import SmartRAG

class Architect:
    def __init__(self, project_dir, profile):
        self.project_dir = project_dir
        self.profile = profile
        # Initialize the Smart Eyes (ChromaDB)
        self.rag = SmartRAG(project_dir)

    def investigate(self, user_goal, max_turns=2):
        """
        🕵️ PHASE 1: THE DETECTIVE
        Iteratively asks for information (Search/Read) to understand the problem.
        """
        # Fallback safety
        active_model = PLANNER_MODEL if PLANNER_MODEL else "qwen2.5:32b"
        
        logger.info(f"🕵️ Investigation Phase (Model: {active_model})...")
        context_gathered = ""
        
        for turn in range(max_turns):
            prompt = f"""
            You are a Senior Lead Developer analyzing a task.
            GOAL: {user_goal}
            
            CURRENT KNOWLEDGE:
            {context_gathered if context_gathered else "(None)"}
            
            TASK: Identify information needed to execute the GOAL.
            - Ask to search documentation or read files.
            - If you have enough info, output "ENOUGH".
            
            RETURN JSON ARRAY of strings (Examples):
            ["search: <concept_keywords>", "read: <file_path>"]
            """
            
            response = extract_json(ollama_query(prompt, model=active_model))
            requests = json.loads(response)
            
            if not requests or "ENOUGH" in requests:
                logger.info("  ✓ Detective is satisfied.")
                break
                
            new_info = ""
            for req in requests:
                if req.startswith("search:"):
                    query = req.replace("search:", "").strip()
                    # USE SMART RAG HERE
                    results = self.rag.search(query, limit=3)
                    if results:
                        new_info += f"\n--- Search: {query} ---\n" + "\n".join(results) + "\n"
                        logger.info(f"  🔍 Searched: {query}")
                
                elif req.startswith("read:"):
                    fname = req.replace("read:", "").strip()
                    path = fuzzy_find_file(self.project_dir, fname)
                    if path:
                        try:
                            # Reduced read limit to prevent context overflow
                            content = path.read_text(encoding='utf-8')[:3000] 
                            new_info += f"\n--- File: {fname} ---\n{content}\n"
                            logger.info(f"  📄 Read: {fname}")
                        except: pass
            
            context_gathered += new_info
            
        return context_gathered

    def create_master_plan(self, user_goal, context):
        """
        👷 PHASE 2: THE ARCHITECT
        Creates the high-level roadmap, enforcing granularity for tests.
        """
        active_model = PLANNER_MODEL if PLANNER_MODEL else "qwen2.5:32b"
        logger.info(f"👷 Creating Master Plan (Model: {active_model})...")
        
        prompt = f"""
        You are a Technical Architect.
        
        CONTEXT FROM INVESTIGATION:
        {context}
        
        GOAL: {user_goal}
        
        TASK: Create a detailed implementation plan.
        
        CRITICAL RULES FOR BREAKING DOWN TASKS:
        1. **TESTING:** If the goal is "Add Tests", you MUST create a separate step for EACH test case.
           - ❌ BAD: "Add tests for ChunkingService"
           - ✅ GOOD: 
             1. "Add test: SplitText_EmptyInput_ReturnsEmpty"
             2. "Add test: SplitText_NullInput_ThrowsException"
        
        2. **CLONING:** If scaffolding a service, do it file-by-file (e.g., "Create .csproj", then "Create Program.cs").
        3. **VERIFICATION:** Every single step must have a verification command (usually `dotnet test` or `dotnet build`).
        
        RETURN JSON ARRAY:
        [ {{ "id": 1, "goal": "Add test for Method A", "verification": "dotnet test ..." }} ]
        """
        return json.loads(extract_json(ollama_query(prompt, model=active_model)))

    def create_tactical_spec(self, step_goal, step_id, master_context):
        """
        ⚔️ PHASE 3: THE TACTICIAN
        Creates a micro-plan AND identifies target/reference files.
        """
        active_model = PLANNER_MODEL if PLANNER_MODEL else "qwen2.5:32b"
        logger.info(f"⚔️ Generating Tactical Spec (Model: {active_model})...")
        
        prompt = f"""
        You are a Team Lead instructing a Junior Dev.
        
        PROJECT CONTEXT:
        {master_context}
        
        CURRENT STEP: {step_goal}
        
        TASK:
        1. Identify the **files** that need to be edited or created.
        2. Identify **reference files** (existing code to use as a template/source).
        3. Write precise **instructions** for the coding agent.
           - Describe the specific function/class to change.
           - Provide the logic or pseudo-code.
           - **DO NOT** put the filename inside the "instructions" text.
        
        RETURN JSON:
        {{
            "files": ["src/MyService/Worker.cs"],
            "reference_files": ["src/OldService/Worker.cs"],
            "instructions": "Create Worker.cs by adapting OldService/Worker.cs. Change namespace..."
        }}
        """
        return json.loads(extract_json(ollama_query(prompt, model=active_model)))