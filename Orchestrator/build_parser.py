import re

def parse_build_errors(build_output):
    if not build_output: return {"compile_errors": [], "warnings": []}
    errors = {"compile_errors": [], "warnings": []}
    for line in build_output.splitlines():
        l = line.strip()
        if not l: continue
        lower = l.lower()
        if "error cs" in lower or ": error" in lower:
            errors["compile_errors"].append(l)
    return errors

def extract_files_from_errors(errors_list):
    files = set()
    for err in errors_list:
        m = re.search(r'([a-zA-Z]:[^:]+\.cs)\(\d+', err)
        if m: files.add(m.group(1))
        m2 = re.search(r'([^\s(]+\.cs)\(\d+', err)
        if m2: files.add(m2.group(1))
    return list(files)