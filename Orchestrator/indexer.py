import hashlib
import os
import re
import time
from pathlib import Path
from .config import logger
from .ai_client import get_embedding
from .vector_store import VectorStore

class CodeIndexer:
    def __init__(self, project_root):
        self.root = Path(project_root)
        self.db = VectorStore()
        
    def calculate_hash(self, text):
        return hashlib.md5(text.encode('utf-8')).hexdigest()

    def chunk_markdown(self, text):
        chunks = []
        lines = text.splitlines()
        current_chunk = []
        current_header = ""
        header_pattern = re.compile(r'^(#{1,6})\s+(.*)')

        for line in lines:
            match = header_pattern.match(line)
            if match:
                if current_chunk:
                    full_text = "\n".join(current_chunk)
                    if current_header and current_header not in full_text:
                        full_text = f"{current_header}\n{full_text}"
                    chunks.append(full_text)
                    current_chunk = []
                current_header = line
                current_chunk.append(line)
            else:
                current_chunk.append(line)
        
        if current_chunk:
            full_text = "\n".join(current_chunk)
            if current_header and current_header not in full_text:
                full_text = f"{current_header}\n{full_text}"
            chunks.append(full_text)
        return chunks

    def chunk_code_structure_aware(self, text, file_ext):
        if file_ext not in ['.cs', '.js', '.ts', '.java', '.py']:
            return self.chunk_code_simple(text)

        lines = text.splitlines()
        chunks = []
        current_chunk = []
        current_size = 0
        MAX_CHUNK_SIZE = 50 

        boundary_pattern = re.compile(r'^\s*(public|private|protected|internal|class|interface|struct|func|def|async)\s+')

        for line in lines:
            if current_size > 10 and boundary_pattern.match(line):
                if current_size + len(current_chunk) > MAX_CHUNK_SIZE:
                    chunks.append("\n".join(current_chunk))
                    current_chunk = [] 
                    current_size = 0

            current_chunk.append(line)
            current_size += 1

            if current_size >= MAX_CHUNK_SIZE:
                chunks.append("\n".join(current_chunk))
                current_chunk = current_chunk[-5:] 
                current_size = 5

        if current_chunk:
            chunks.append("\n".join(current_chunk))
        return chunks

    def chunk_code_simple(self, text, chunk_size=30, overlap=5):
        lines = text.splitlines()
        chunks = []
        for i in range(0, len(lines), chunk_size - overlap):
            chunk = "\n".join(lines[i:i + chunk_size])
            if chunk.strip():
                chunks.append(chunk)
        return chunks

    def index_project(self, force=False):
        logger.info("🔍 Starting Semantic Indexing...")
        
        # Extended Ignore List to catch frontend build artifacts
        ignore_list = ['.git', 'bin', 'obj', 'node_modules', '.vs', '.idea', 'dist', 'build', 'assets', 'coverage']

        for root, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in ignore_list]
            
            for file in files:
                if file.startswith(".aider"): continue 
                
                # Check for minified files explicitly
                if '.min.' in file: continue

                if not file.endswith(('.cs', '.js', '.ts', '.py', '.md', '.sql', '.xml', '.json')):
                    continue
                    
                path = Path(root) / file
                rel_path = str(path.relative_to(self.root))
                file_ext = path.suffix.lower()
                
                try:
                    content = path.read_text(encoding='utf-8', errors='ignore')
                    current_hash = self.calculate_hash(content)
                    
                    if not force:
                        stored_hash = self.db.get_file_hash(rel_path)
                        if current_hash == stored_hash:
                            continue
                        
                    if file_ext == '.md':
                        chunks = self.chunk_markdown(content)
                        prefix = "Documentation"
                    else:
                        chunks = self.chunk_code_structure_aware(content, file_ext)
                        prefix = "File"

                    embeddings = []
                    
                    for chunk in chunks:
                        contextualized_text = f"{prefix}: {rel_path}\nContent:\n{chunk}"
                        time.sleep(1.0) # Breather
                        vec = get_embedding(contextualized_text)
                        
                        if vec:
                            embeddings.append(vec)
                        else:
                            logger.warning(f"Failed to embed chunk in {rel_path}")
                            break
                            
                    if len(embeddings) == len(chunks) and len(chunks) > 0:
                        self.db.update_file(rel_path, current_hash, chunks, embeddings)
                        
                except Exception as e:
                    logger.warning(f"Could not index {rel_path}: {e}")