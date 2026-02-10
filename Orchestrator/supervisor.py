import sys
import subprocess
import time
import argparse
import logging
import os
from collections import deque

# --- FIX WINDOWS EMOJI CRASH (AGGRESSIVE) ---
# Force Python to utilize UTF-8 for all IO operations
if sys.platform == "win32":
    # This magic command forces Windows console to accept UTF-8
    os.system('chcp 65001 >NUL')
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | 👮 SUPERVISOR | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("supervisor")

class Supervisor:
    def __init__(self, plans, cli_args):
        self.plans = plans
        self.cli_args = cli_args
        self.max_retries = 3
        self.log_window = deque(maxlen=20)

    def run(self):
        logger.info(f"📋 Job Queue: {self.plans}")
        
        for plan in self.plans:
            success = self.execute_plan_with_retries(plan)
            if not success:
                logger.error(f"❌ Aborting Queue. Plan '{plan}' failed permanently.")
                sys.exit(1)
                
        logger.info("🎉 All plans executed successfully!")

    def execute_plan_with_retries(self, plan_file):
        retries = 0
        
        # Pass current environment + force UTF-8 on child process
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        while retries < self.max_retries:
            logger.info(f"▶️ Starting Plan: {plan_file} (Attempt {retries + 1}/{self.max_retries})")
            
            cmd = [sys.executable, "-m", "orchestrator.main", plan_file] + self.cli_args
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding='utf-8', 
                errors='replace', # Replace bad chars with ? instead of crashing
                env=env
            )

            state = self.monitor_process(process)
            
            if state == "SUCCESS":
                return True
            elif state == "FATAL_ERROR":
                logger.error("🛑 Fatal Error detected. NOT Retrying.")
                return False
            elif state == "LOOP_DETECTED":
                logger.warning("🔄 Logic Loop Detected! Killing process and retrying...")
                try: process.kill()
                except: pass
            elif state == "CRASH":
                logger.warning("💥 Agent Crashed! Retrying...")
            
            retries += 1
            time.sleep(5) 
            
        return False

    def safe_print(self, text):
        """
        Tries to print text. If it fails (due to encoding), 
        prints a sanitized ASCII version instead.
        """
        try:
            print(text, end='', flush=True)
        except Exception:
            try:
                # Fallback: Replace emojis/special chars with '?'
                clean_text = text.encode('ascii', 'replace').decode('ascii')
                print(clean_text, end='', flush=True)
            except:
                pass # Give up, don't crash

    def monitor_process(self, process):
        self.log_window.clear()

        while True:
            try:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                
                if line:
                    # USE SAFE PRINT
                    self.safe_print(line)
                    
                    clean_line = line.strip()
                    if not clean_line: continue

                    # --- FATAL ERRORS (Do Not Retry) ---
                    if "Plan not found" in clean_line:
                        return "FATAL_ERROR"
                    if "Unknown language" in clean_line:
                        return "FATAL_ERROR"

                    # --- LOOP DETECTION ---
                    if "STEP" in clean_line and "Complete" not in clean_line:
                        self.log_window.append(clean_line)
                        if self.log_window.count(clean_line) >= 3:
                            return "LOOP_DETECTED"

                    # --- CRASH DETECTION (Retry) ---
                    if "Traceback" in clean_line:
                         return "CRASH"
                    if "Ollama query failed" in clean_line:
                         return "CRASH"

            except Exception as e:
                logger.error(f"Supervisor Monitor Error: {e}")
                break
        
        if process.returncode == 0:
            return "SUCCESS"
        else:
            return "FAILURE"

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('plans', nargs='+', help='List of plan files')
    parser.add_argument('--language', default='csharp')
    parser.add_argument('--reindex', action='store_true')
    parser.add_argument('--force-recon', action='store_true')
    
    args, unknown = parser.parse_known_args()
    
    pass_through_args = []
    if args.language: pass_through_args.extend(['--language', args.language])
    if args.reindex: pass_through_args.append('--reindex')
    if args.force_recon: pass_through_args.append('--force-recon')
    pass_through_args.extend(unknown)

    supervisor = Supervisor(args.plans, pass_through_args)
    supervisor.run()