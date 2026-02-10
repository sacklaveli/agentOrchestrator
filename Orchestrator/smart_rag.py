import os
import shutil
from pathlib import Path
from typing import List, Dict

# LangChain Imports
from langchain_text_splitters import RecursiveCharacterTextSplitter, Language
from langchain_community.embeddings import OllamaEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings
from .config import logger, OLLAMA_URL, EMBEDDING_MODEL, CHROMA_DB_DIR, CHUNK_SIZE, CHUNK_OVERLAP

class SmartRAG:
    def __init__(self, project_dir: str, reset_db: bool = False):
        self.project_dir = Path(project_dir)
        self.persist_dir = Path(CHROMA_DB_DIR)

        # 1. Setup Embeddings (Connects to your local Ollama)
        self.embedding_fn = OllamaEmbeddings(
            base_url=OLLAMA_URL,
            model=EMBEDDING_MODEL,
            temperature=0  # Embeddings must be deterministic
        )

        # 2. Reset DB if requested (Force Re-index)
        if reset_db and self.persist_dir.exists():
            logger.warning("🗑️  Clearing Vector Database...")
            shutil.rmtree(self.persist_dir)

        # 3. Initialize ChromaDB (Local Vector Store)
        self.vector_store = Chroma(
            persist_directory=str(self.persist_dir),
            embedding_function=self.embedding_fn,
            collection_name="project_codebase"
        )

    def index_project(self):
        """
        Walks the project, smart-chunks C# code, and saves to Vector DB.
        """
        logger.info("🧠 SMART RAG: Indexing Codebase...")
        
        documents = []
        
        # 1. Find all Code Files
        # You can expand this list (e.g., .py, .js, .md)
        files = list(self.project_dir.rglob("*.cs")) + list(self.project_dir.rglob("*.md"))
        
        for file_path in files:
            # Skip ignored dirs
            if any(part.startswith(".") or part in ["bin", "obj", "node_modules"] for part in file_path.parts):
                continue
                
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                if not content.strip(): continue

                # 2. Choose Splitter based on extension
                if file_path.suffix == ".cs":
                    splitter = RecursiveCharacterTextSplitter.from_language(
                        language=Language.CSHARP,
                        chunk_size=CHUNK_SIZE,
                        chunk_overlap=CHUNK_OVERLAP
                    )
                else:
                    splitter = RecursiveCharacterTextSplitter(
                        chunk_size=CHUNK_SIZE,
                        chunk_overlap=CHUNK_OVERLAP
                    )

                # 3. Create Chunks
                chunks = splitter.create_documents([content])
                
                # 4. Add Metadata (Critical for retrieval)
                for chunk in chunks:
                    chunk.metadata = {
                        "source": str(file_path.relative_to(self.project_dir)),
                        "filename": file_path.name
                    }
                    documents.append(chunk)
                    
            except Exception as e:
                logger.warning(f"⚠️  Failed to process {file_path.name}: {e}")

        if documents:
            # 5. Batch Upsert to Chroma
            logger.info(f"💾 Storing {len(documents)} code chunks in Vector DB...")
            # Chroma handles batching automatically
            self.vector_store.add_documents(documents)
            logger.info("✅ Indexing Complete.")
        else:
            logger.warning("⚠️  No documents found to index.")

    def search(self, query: str, limit: int = 5) -> List[str]:
        """
        Semantic Search that returns formatted context strings.
        """
        logger.info(f"🔍 Searching Memory for: '{query}'")
        
        results = self.vector_store.similarity_search_with_score(query, k=limit)
        
        formatted_results = []
        for doc, score in results:
            # Chroma returns distance (lower is better). We filter bad matches.
            # Arbitrary threshold: 0.0 is exact match, > 1.0 is unrelated.
            if score < 1.2: 
                source = doc.metadata.get("source", "unknown")
                content = doc.page_content
                formatted_results.append(f"--- SOURCE: {source} ---\n{content}\n")
        
        return formatted_results