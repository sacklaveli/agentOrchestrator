import re

def parse_command_output(output, error_patterns):
    """
    Scans output for specific regex patterns defined in the language profile.
    """
    if not output: return []
    
    detected_errors = []
    
    for line in output.splitlines():
        clean_line = line.strip()
        if not clean_line: continue
        
        for pattern in error_patterns:
            if re.search(pattern, clean_line):
                detected_errors.append(clean_line)
                break
                
    return detected_errors

def extract_files_from_output(output_lines):
    """
    Extracts file paths from error messages (C#, JS stack traces, etc).
    """
    files = set()
    for line in output_lines:
        # Win/Unix C# style: File.cs(10,20)
        m1 = re.search(r'([a-zA-Z0-9_\-\.\\]+\.(cs|js|ts|rb|py))\(\d+', line)
        if m1: files.add(m1.group(1))
        
        # JS/Stack trace style: at ... (src/file.js:10:20)
        m2 = re.search(r'\(([^)]+\.(cs|js|ts|rb|py)):\d+', line)
        if m2: files.add(m2.group(1))
        
        # Simple file match at start of line
        m3 = re.search(r'^([a-zA-Z0-9_\-\.\\]+\.(cs|js|ts|rb|py))', line)
        if m3: files.add(m3.group(1))

    return list(files)