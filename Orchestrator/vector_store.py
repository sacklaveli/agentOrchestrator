import psycopg2
from pgvector.psycopg2 import register_vector
from .config import logger, DB_HOST, DB_NAME, DB_PASS, DB_PORT, DB_USER, EMBEDDING_DIM

class VectorStore:
    def __init__(self):
        self.conn = None
        self.connect()

    def connect(self):
        try:
            self.conn = psycopg2.connect(
                host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS, dbname=DB_NAME
            )
            self.conn.autocommit = True
            cur = self.conn.cursor()
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            self.conn.autocommit = False
            
            register_vector(self.conn)
            self.init_schema()
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            self.conn = None

    def _get_cursor(self):
        if self.conn is None or self.conn.closed:
            self.connect()
        if self.conn:
            return self.conn.cursor()
        return None

    def init_schema(self):
        if not self.conn: return
        try:
            cur = self.conn.cursor()
            
            # 1. File Registry
            cur.execute("""
                CREATE TABLE IF NOT EXISTS file_registry (
                    file_path TEXT PRIMARY KEY,
                    file_hash TEXT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 2. Code Chunks
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS code_chunks (
                    id SERIAL PRIMARY KEY,
                    file_path TEXT REFERENCES file_registry(file_path) ON DELETE CASCADE,
                    chunk_index INT,
                    content TEXT,
                    embedding vector({EMBEDDING_DIM}) 
                )
            """)
            
            # 3. Journal
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS solution_journal (
                    id SERIAL PRIMARY KEY,
                    error_signature TEXT,
                    fix_diff TEXT,
                    embedding vector({EMBEDDING_DIM}),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Indexes
            if EMBEDDING_DIM <= 2000:
                cur.execute("CREATE INDEX IF NOT EXISTS code_idx ON code_chunks USING hnsw (embedding vector_cosine_ops)")
                cur.execute("CREATE INDEX IF NOT EXISTS journal_idx ON solution_journal USING hnsw (embedding vector_cosine_ops)")
            
            self.conn.commit()
            
        except Exception as e:
            logger.error(f"Schema Init Failed: {e}")
            if self.conn: self.conn.rollback()

    # --- JOURNAL METHODS ---
    def save_journal(self, error_msg, fix_diff, embedding):
        cur = self._get_cursor()
        if not cur: return
        try:
            # Note: We cast the embedding to ::vector explicitly for safety
            cur.execute("""
                INSERT INTO solution_journal (error_signature, fix_diff, embedding)
                VALUES (%s, %s, %s::vector)
            """, (error_msg, fix_diff, embedding))
            self.conn.commit()
            logger.info("🧠 Journal: Saved new fix to memory.")
        except Exception as e:
            if self.conn: self.conn.rollback()
            logger.error(f"Journal Save Failed: {e}")

    def search_journal(self, query_embedding, limit=1):
        cur = self._get_cursor()
        if not cur: return []
        try:
            # FIX: Added ::vector cast
            cur.execute("""
                SELECT error_signature, fix_diff, 1 - (embedding <=> %s::vector) AS similarity
                FROM solution_journal
                WHERE 1 - (embedding <=> %s::vector) > 0.85 
                ORDER BY similarity DESC
                LIMIT %s
            """, (query_embedding, query_embedding, limit))
            return cur.fetchall()
        except Exception as e:
            if self.conn: self.conn.rollback()
            logger.error(f"Journal Search Failed: {e}")
            return []

    # --- FILE METHODS ---
    def get_file_hash(self, file_path):
        cur = self._get_cursor()
        if not cur: return None
        try:
            cur.execute("SELECT file_hash FROM file_registry WHERE file_path = %s", (file_path,))
            res = cur.fetchone()
            return res[0] if res else None
        except:
            if self.conn: self.conn.rollback()
            return None

    def update_file(self, file_path, file_hash, chunks, embeddings):
        cur = self._get_cursor()
        if not cur: return
        try:
            cur.execute("""
                INSERT INTO file_registry (file_path, file_hash) VALUES (%s, %s)
                ON CONFLICT (file_path) DO UPDATE SET file_hash = EXCLUDED.file_hash, last_updated = NOW()
            """, (file_path, file_hash))
            cur.execute("DELETE FROM code_chunks WHERE file_path = %s", (file_path,))
            for i, (chunk, vec) in enumerate(zip(chunks, embeddings)):
                cur.execute(f"""
                    INSERT INTO code_chunks (file_path, chunk_index, content, embedding)
                    VALUES (%s, %s, %s, %s::vector)
                """, (file_path, i, chunk, vec))
            self.conn.commit()
            logger.info(f"💾 Indexed: {file_path} ({len(chunks)} chunks)")
        except Exception as e:
            if self.conn: self.conn.rollback()
            logger.error(f"Failed to update {file_path}: {e}")

    # --- SEARCH ---
    def search(self, query_embedding, limit=5, path_filter=None):
        cur = self._get_cursor()
        if not cur: return []

        try:
            if path_filter:
                # FIX: Added ::vector cast
                cur.execute("""
                    SELECT file_path, content, 1 - (embedding <=> %s::vector) AS cosine_similarity
                    FROM code_chunks
                    WHERE file_path LIKE %s
                    ORDER BY cosine_similarity DESC
                    LIMIT %s
                """, (query_embedding, path_filter, limit))
            else:
                # FIX: Added ::vector cast
                cur.execute("""
                    SELECT file_path, content, 1 - (embedding <=> %s::vector) AS cosine_similarity
                    FROM code_chunks
                    ORDER BY cosine_similarity DESC
                    LIMIT %s
                """, (query_embedding, limit))
                
            return cur.fetchall()
        except Exception as e:
            if self.conn: self.conn.rollback()
            logger.error(f"Search failed: {e}")
            return []