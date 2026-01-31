import json
from .config import MEMORY_FILE_NAME

def get_memory_file_path(project_root):
    return project_root / MEMORY_FILE_NAME

def load_memory(project_root):
    mem_file = get_memory_file_path(project_root)
    if mem_file.exists():
        try: return json.loads(mem_file.read_text(encoding='utf-8'))
        except: pass
    return {"project_knowledge": {}, "steps": {}}

def save_memory(project_root, mem):
    try: 
        get_memory_file_path(project_root).write_text(json.dumps(mem, indent=2), encoding='utf-8')
    except: pass