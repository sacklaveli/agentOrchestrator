import os
import re
from pathlib import Path

def find_project_root(start_path):
    """
    Traverse up to find the root directory containing .git or .sln
    """
    current = start_path.resolve()
    while current != current.parent:
        if (current / ".git").exists() or list(current.glob("*.sln")):
            return current
        current = current.parent
    return start_path

def get_file_tree(start_path, max_depth=2, ignore_dirs=None):
    """
    Generates a visual string representation of the file structure.
    Used by recon_agent to understand project layout.
    """
    if ignore_dirs is None:
        ignore_dirs = ['.git', 'bin', 'obj', 'node_modules', '.vs', '.idea']
        
    tree_str = ""
    start_path = Path(start_path)
    
    for root, dirs, files in os.walk(start_path):
        # Filter directories in-place
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        
        level = str(root).replace(str(start_path), '').count(os.sep)
        if level > max_depth:
            continue
            
        indent = ' ' * 4 * level
        tree_str += f"{indent}{os.path.basename(root)}/\n"
        
        subindent = ' ' * 4 * (level + 1)
        # Limit visible files per folder to keep token count low
        for f in files[:10]: 
             tree_str += f"{subindent}{f}\n"
        if len(files) > 10:
            tree_str += f"{subindent}... ({len(files)-10} more)\n"
            
    return tree_str

def fuzzy_find_file(project_root, filename, ignore_dirs=None):
    """
    Locates a file by name within the project, skipping ignored directories.
    """
    if ignore_dirs is None:
        ignore_dirs = ['.git', 'bin', 'obj', 'node_modules', '.vs', '.idea']
        
    target_name = filename.lower()
    
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        
        for file in files:
            if file.lower() == target_name:
                return Path(root) / file
    return None

def sanitize_file_path(project_root, user_path):
    """
    Ensures a path from the LLM is valid and absolute.
    """
    clean_path = str(user_path).strip().strip("'").strip('"')
    
    # Handle simple filenames by finding them
    if not (os.sep in clean_path or '/' in clean_path):
        found = fuzzy_find_file(project_root, clean_path)
        if found:
            return str(found)

    # Handle relative paths
    try:
        full_path = (project_root / clean_path).resolve()
    except Exception:
        return None
    
    # Security check: ensure we didn't escape project root
    if str(project_root) not in str(full_path):
        return None
        
    if full_path.exists():
        return str(full_path)
        
    return None

def find_related_files(project_dir, file_path_str):
    """
    Returns a list of related files based on naming conventions.
    Example: Input 'UserService.cs' -> Returns ['IUserService.cs', 'UserServiceTests.cs']
    """
    try:
        path = Path(file_path_str)
        filename = path.name
        stem = path.stem # e.g. "UserService"
        ext = path.suffix # e.g. ".cs"
        
        related = []
        
        # Define patterns based on the file stem
        # 1. Interface (IUserService.cs)
        patterns = [f"I{stem}{ext}"]
        
        # 2. Tests (UserServiceTests.cs, UserService.Tests.cs)
        patterns.append(f"{stem}Tests{ext}")
        patterns.append(f"{stem}.Tests{ext}")
        
        # 3. Inverse: If we are IUserService, look for UserService
        if stem.startswith("I") and len(stem) > 1 and stem[1].isupper():
            impl_name = stem[1:] # Remove 'I'
            patterns.append(f"{impl_name}{ext}")
            
        # 4. Inverse: If we are UserServiceTests, look for UserService
        if stem.endswith("Tests"):
            impl_name = stem.replace("Tests", "")
            patterns.append(f"{impl_name}{ext}")

        # Search the project for these patterns
        if not patterns:
            return []

        for root, dirs, files in os.walk(project_dir):
            dirs[:] = [d for d in dirs if d not in ['.git', 'bin', 'obj', 'node_modules', '.vs', '.idea']]
                
            for p in patterns:
                if p in files:
                    full_path = Path(root) / p
                    try:
                        related.append(str(full_path.relative_to(project_dir)))
                    except:
                        pass
                        
        return list(set(related))
    except Exception:
        return []