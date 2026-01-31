import os
import re
import json
import tempfile
import urllib.request
import urllib.error
from pathlib import Path
from .config import logger, OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_URL  # <--- Added OLLAMA_URL
from .process_utils import run_with_timeout

def extract_json(text):
    if not text: return None
    m = re.search(r'```(?:json)?\s*([\[\{].*?[\]\}])\s*```', text, re.DOTALL)
    if m: return m.group(1)
    m = re.search(r'(\{.*\})', text, re.DOTALL)
    if m: return m.group(1)
    m = re.search(r'(\[.*\])', text, re.DOTALL)
    if m: return m.group(1)
    return text

def ollama_query(prompt):
    logger.info(f"→ Querying AI...")
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(prompt)
        fname = f.name
    
    # Use 'type' on Windows, 'cat' on Unix
    cat_cmd = 'type' if os.name == 'nt' else 'cat'
    cmd = f'{cat_cmd} "{fname}" | ollama run {OLLAMA_MODEL}'
    
    try:
        out, err, code, to = run_with_timeout(cmd, timeout=OLLAMA_TIMEOUT)
        if to or code != 0: return None
        return out.strip()
    finally:
        try: Path(fname).unlink()
        except: pass

def get_embedding(text):
    """
    Generates a vector embedding using Python's standard library (Windows-Safe).
    """
    try:
        url = f"{OLLAMA_URL}/api/embeddings"
        payload = {
            "model": "qwen3-embedding", # Ensure you ran: ollama pull nomic-embed-text
            "prompt": text
        }
        
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        
        # 10s timeout for embeddings is usually enough per chunk
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get("embedding")
            
    except Exception as e:
        logger.error(f"Failed to get embedding: {e}")
        return None