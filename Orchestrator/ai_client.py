import requests
import json
import re
import ast
from .config import OLLAMA_URL, OLLAMA_MODEL, EMBEDDING_MODEL, logger

import requests
import json
import re
import ast
from .config import OLLAMA_URL, PLANNER_MODEL, EMBEDDING_MODEL, logger

def get_embedding(text):
    try:
        url = f"{OLLAMA_URL}/api/embeddings"
        payload = {"model": EMBEDDING_MODEL, "prompt": text}
        response = requests.post(url, json=payload, timeout=120)
        if response.status_code == 200:
            return response.json().get("embedding")
    except Exception as e:
        logger.error(f"Failed to get embedding: {e}")
    return None

def ollama_query(prompt, model=PLANNER_MODEL):
    """
    Sends a request to Ollama.
    Allows switching between PLANNER_MODEL and CODER_MODEL dynamically.
    """
    try:
        url = f"{OLLAMA_URL}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_ctx": 8192 # Increased for larger context reasoning
            }
        }
        
        response = requests.post(url, json=payload, timeout=600)
        
        if response.status_code == 200:
            return response.json().get("response", "")
        else:
            logger.error(f"Ollama query failed: {response.text}")
            return ""
    except Exception as e:
        logger.error(f"Ollama query failed: {e}")
        return ""


def extract_json(text):
    """
    Robustly extracts and repairs JSON from LLM output.
    Handles Markdown fences, single quotes, and trailing commas.
    """
    text = text.strip()
    
    # 1. Strip Markdown Code Blocks (```json ... ```)
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if match:
        text = match.group(1)
    
    # 2. Isolate the JSON array/object if there is extra chatter
    # Find the first '[' or '{'
    start_idx = -1
    for i, char in enumerate(text):
        if char in ['{', '[']:
            start_idx = i
            break
            
    # Find the last ']' or '}'
    end_idx = -1
    for i in range(len(text) - 1, -1, -1):
        if text[i] in ['}', ']']:
            end_idx = i + 1
            break
            
    if start_idx != -1 and end_idx != -1:
        text = text[start_idx:end_idx]

    # 3. Attempt to Parse & Repair
    try:
        # First try: Standard Strict JSON
        return json.dumps(json.loads(text)) 
    except:
        try:
            # Second try: Repair Trailing Commas (common error: [1, 2,])
            text_fixed = re.sub(r',\s*([\]}])', r'\1', text)
            return json.dumps(json.loads(text_fixed))
        except:
            try:
                # Third try: Python Eval (Handles single quotes: {'id': 1})
                # WARNING: Only use on trusted local LLM output
                return json.dumps(ast.literal_eval(text))
            except:
                # Give up and return original (caller will handle failure)
                return text