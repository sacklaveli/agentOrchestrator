import subprocess
import shutil
import os
import sys
from .config import logger

def check_dependencies(build_cmd):
    """
    Verifies tools are available.
    Accepts 'build_cmd' (e.g., 'npm install', 'dotnet build') to check for the specific language tool.
    """
    # Extract just the executable (e.g., 'npm' from 'npm install')
    tool = build_cmd.split()[0] if build_cmd else "dotnet"
    
    missing = []
    if not shutil.which("aider"): missing.append("aider")
    if not shutil.which(tool): missing.append(tool)
    
    if missing:
        logger.warning(f"⚠️  Missing tools in PATH: {', '.join(missing)}. Orchestration may fail.")
    else:
        logger.info(f"✅ Tools found: aider, {tool}")

def run_with_timeout(cmd, cwd=None, timeout=None, input_text=None, env=None):
    logger.debug(f"EXEC: {cmd}")
    try:
        process_env = os.environ.copy()
        # Force UTF-8 for Windows Console compatibility
        process_env["PYTHONIOENCODING"] = "utf-8"
        process_env["PYTHONUTF8"] = "1"
        
        if env:
            process_env.update(env)

        # shell=True required for Windows internal commands, strict args for Mac/Linux
        use_shell = True if os.name == 'nt' else True 

        proc = subprocess.Popen(
            cmd, shell=use_shell, cwd=cwd,
            stdin=subprocess.PIPE if input_text else None,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace",
            env=process_env
        )
        try:
            out, err = proc.communicate(input_text, timeout=timeout)
            return out, err, proc.returncode, False
        except subprocess.TimeoutExpired:
            logger.error(f"⏰ TIMEOUT ({timeout}s) on command: {cmd[:50]}...")
            proc.kill()
            out, err = proc.communicate()
            return out, err, -1, True
    except Exception as e:
        logger.error(f"Process failed: {e}")
        return "", str(e), 1, False