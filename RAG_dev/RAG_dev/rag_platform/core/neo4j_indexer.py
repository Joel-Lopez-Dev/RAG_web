"""
Indexador de Neo4j para GraphRAG
Crea nodos, relaciones y índices vectoriales
"""
import os
import logging
import numpy as np
from typing import List, Dict, Any
from sklearn.metrics.pairwise import cosine_similarity
from django.conf import settings


class Neo4jGraphIndexer:
    """
    Indexador que guarda chunks y sus embeddings en Neo4j
    Crea relaciones de similitud entre chunks
    """
    
    def __init__(self, driver, embedder=None):
        self.driver = driver
        self.embedder = embedder
        self._setup_constraints()
        if self.embedder is not None:
            self._setup_vector_index()
    
    def _setup_constraints(self):
        """Crea restricción de unicidad para chunk_id"""
        query = """
        CREATE CONSTRAINT chunk_id_constraint IF NOT EXISTS
        FOR (c:Chunk)
        REQUIRE c.chunk_id IS UNIQUE
        """
        with self.driver.session() as session:
            try:
                session.run(query)
            except Exception as e:
                logging.info(f"Constraint ya existe o no soportado: {e}")
    
    def _setup_vector_index(self):
        """Crea índice vectorial para búsquedas por embedding"""
        if self.embedder is None:
            logging.warning("No se proporcionó embedder, no se crea índice vectorial.")
            return
        sample_embedding = self.embedder.embed_query("test")
        vector_dim = len(sample_embedding)
        query = f"""
        CREATE VECTOR INDEX chunk_embeddings IF NOT EXISTS
        FOR (c:Chunk) ON (c.embedding)
        OPTIONS {{
            indexConfig: {{
                `vector.dimensions`: {vector_dim},
                `vector.similarity_function`: 'cosine'
            }}
        }}
        """
        with self.driver.session() as session:
            try:
                session.run(query)
            except Exception as e:
                logging.info(f"Vector index ya existe o no soportado: {e}")
    
    def index_chunks(self, chunks_data: List[Dict], document_id: int, threshold: float = 0.75, top_k: int = 5):
        """Indexa chunks en Neo4j con relaciones de similitud"""
        if not chunks_data:
            logging.warning("No hay chunks para indexar")
            return

        logging.info(f"Indexando {len(chunks_data)} chunks en Neo4j...")

        # Preparar nodos
        chunks_to_add = []
        embeddings_list = []

        for i, chunk in enumerate(chunks_data):
            chunk_id = f"doc_{document_id}::chunk_{i}"
            node_data = {
                "chunk_id": chunk_id,
                "text": chunk['text'],
                "embedding": chunk['embedding'],
                "document_id": document_id,
                "chunk_index": i,
                "page_number": chunk['metadata'].get('page_number'),
                "section": chunk['metadata'].get('section', ''),
            }
            chunks_to_add.append(node_data)
            embeddings_list.append(chunk['embedding'])

        # Crear nodos
        self._create_chunk_nodes(chunks_to_add)

        # Crear relaciones de similitud
        self._create_similarity_relationships(
            chunks_to_add,
            embeddings_list,
            threshold=threshold,
            top_k=top_k
        )

        logging.info(f"✓ Indexación completada: {len(chunks_to_add)} nodos")
    
    def _create_chunk_nodes(self, chunks: List[Dict]):
        """Crea nodos :Chunk en Neo4j"""
        query = """
        UNWIND $chunks AS chunk
        MERGE (c:Chunk {chunk_id: chunk.chunk_id})
        SET c += chunk
        """
        with self.driver.session() as session:
            session.run(query, chunks=chunks)
    
    def _create_similarity_relationships(
        self,
        chunks: List[Dict],
        embeddings: List,
        threshold: float = 0.75,
        top_k: int = 5
    ):
        """Crea relaciones :SIMILAR_TO entre chunks similares"""
        if not embeddings or len(embeddings) < 2:
            logging.info("No hay suficientes embeddings para crear relaciones de similitud.")
            return
        vecs = np.array(embeddings, dtype="float32")
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vecs = vecs / norms
        sim_matrix = cosine_similarity(vecs)
        n = sim_matrix.shape[0]
        relationships = []
        for i in range(n):
            sorted_indices = np.argsort(-sim_matrix[i])
            count = 0
            for j in sorted_indices[1:]:
                score = float(sim_matrix[i, j])
                if score < threshold:
                    continue
                relationships.append({
                    "chunk_id_1": chunks[i]["chunk_id"],
                    "chunk_id_2": chunks[j]["chunk_id"],
                    "score": score
                })
                count += 1
                if count >= top_k:
                    break
        if relationships:
            rel_query = """
            UNWIND $rels AS rel
            MATCH (c1:Chunk {chunk_id: rel.chunk_id_1})
            MATCH (c2:Chunk {chunk_id: rel.chunk_id_2})
            MERGE (c1)-[r:SIMILAR_TO]->(c2)
            SET r.score = rel.score
            """
            with self.driver.session() as session:
                session.run(rel_query, rels=relationships)
            logging.info(f"✓ {len(relationships)} relaciones de similitud creadas")
    
    def delete_document_chunks(self, document_id: int):
        """Elimina todos los chunks de un documento"""
        query = """
        MATCH (c:Chunk {document_id: $document_id})
        DETACH DELETE c
        """
        with self.driver.session() as session:
            session.run(query, document_id=document_id)
        logging.info(f"✓ Chunks del documento {document_id} eliminados")
