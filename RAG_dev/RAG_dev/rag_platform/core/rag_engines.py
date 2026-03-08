"""
RAG Engines - Motores de recuperación basados en FAISS y Neo4j
Adaptado del código base RAG_dev con integración Django
Soporta múltiples proveedores LLM: OpenAI, Google Gemini, o modo sin IA
"""
import os
import pickle
import numpy as np
from typing import List, Dict, Optional
from abc import ABC, abstractmethod

from langchain_core.documents import Document
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate

from neo4j import GraphDatabase, Driver
from sklearn.metrics.pairwise import cosine_similarity

from django.conf import settings


class BaseRAGEngine(ABC):
    """
    Clase base abstracta para los motores RAG.
    Soporta selección dinámica de proveedor LLM (openai/gemini/none).
    """
    
    def __init__(self, llm_provider: str = None):
        """
        Args:
            llm_provider: Proveedor LLM a usar ('openai', 'gemini', 'none').
                         Si es None, usa el valor de settings.LLM_PROVIDER.
        """
        self.embedder = self._init_embedder()
        self.llm_provider = llm_provider  # Guardamos para referencia
        self.llm = self._init_llm(llm_provider)
        self.memory = []
    
    def _init_embedder(self):
        """Inicializa el modelo de embeddings"""
        try:
            return HuggingFaceEmbeddings(
                model_name=getattr(settings, 'EMBEDDING_MODEL', 
                                 'sentence-transformers/all-MiniLM-L6-v2'),
                model_kwargs={
                    'device': 'cpu',
                    'trust_remote_code': False
                },
                encode_kwargs={
                    'normalize_embeddings': True,
                    'batch_size': 32
                }
            )
        except Exception as e:
            print(f"Error inicializando embedder: {e}")
            raise
    
    def _init_llm(self, override_provider: str = None):
        """
        Inicializa el LLM según la configuración.
        
        Args:
            override_provider: Si se especifica, usa este proveedor en lugar del global.
                              Valores: 'openai', 'gemini', 'none'
        
        Returns:
            Instancia del LLM o None si el proveedor es 'none' o falta la API key.
        """
        # Determinar el proveedor a usar
        provider = (override_provider or getattr(settings, 'LLM_PROVIDER', 'none')).lower()
        temperature = getattr(settings, 'TEMPERATURE', 0.1)
        
        # Modo sin LLM: solo retrieval
        if provider == 'none':
            print("ℹ️  LLM_PROVIDER=none -> Modo sin modelo de lenguaje (solo búsqueda semántica)")
            return None
        
        # Google Gemini
        if provider == 'gemini':
            google_key = getattr(settings, 'GOOGLE_API_KEY', None)
            if not google_key:
                print("⚠️  LLM_PROVIDER=gemini pero GOOGLE_API_KEY no configurada -> Modo sin LLM")
                return None
            
            model_name = getattr(settings, 'GEMINI_MODEL', 'gemini-2.0-flash-exp')
            print(f"✓ Usando Google Gemini: {model_name}")
            return ChatGoogleGenerativeAI(
                model=model_name,
                google_api_key=google_key,
                temperature=temperature,
                max_tokens=2048,
            )
        
        # OpenAI
        if provider == 'openai':
            api_key = getattr(settings, 'OPENAI_API_KEY', None)
            if not api_key:
                print("⚠️  LLM_PROVIDER=openai pero OPENAI_API_KEY no configurada -> Modo sin LLM")
                return None
            
            model_name = getattr(settings, 'OPENAI_MODEL', 'gpt-4o-mini')
            print(f"✓ Usando OpenAI: {model_name}")
            return ChatOpenAI(
                model=model_name,
                api_key=api_key,
                temperature=temperature,
                max_tokens=2048,
            )
        
        print(f"⚠️  LLM_PROVIDER desconocido: '{provider}' -> Modo sin LLM")
        return None
    
    def get_llm_status(self) -> Dict:
        """Devuelve información sobre el estado del LLM configurado"""
        provider = getattr(settings, 'LLM_PROVIDER', 'none').lower()
        return {
            'provider': provider,
            'llm_active': self.llm is not None,
            'openai_configured': bool(getattr(settings, 'OPENAI_API_KEY', None)),
            'gemini_configured': bool(getattr(settings, 'GOOGLE_API_KEY', None)),
        }
    
    @abstractmethod
    def retrieve(self, query: str, k: int = None) -> List[Document]:
        """Recupera documentos relevantes"""
        pass
    
    @abstractmethod
    def generate_response(self, query: str, conversation_history: List[Dict] = None) -> Dict:
        """Genera respuesta usando el LLM"""
        pass


class FaissEngine(BaseRAGEngine):
    """
    Motor RAG basado en FAISS para búsqueda vectorial semántica
    """
    
    def __init__(self, document_id: int = None, llm_provider: str = None):
        super().__init__(llm_provider=llm_provider)
        # Aceptar document_id como str o int (viene del frontend como string). Normalizar a int cuando sea posible.
        if document_id is not None:
            try:
                document_id = int(document_id)
            except (TypeError, ValueError):
                # dejar tal cual si no se puede convertir
                pass
        self.document_id = document_id
        self.documents = []
        self.embeddings = None
        
        # Cargar índice si existe
        if document_id:
            self._load_index(document_id)
        
        self.prompt = PromptTemplate(
            input_variables=["context", "question", "history"],
            template=(
                "Eres un asistente experto en análisis de documentos científicos con búsqueda semántica.\n\n"
                "Tu especialidad es encontrar información relevante basándote en similitud semántica del contenido.\n\n"
                "Contexto recuperado (fragmentos más similares semánticamente):\n"
                "{context}\n\n"
                "Historial de conversación:\n"
                "{history}\n\n"
                "Pregunta del usuario:\n"
                "{question}\n\n"
                "Reglas estrictas:\n"
                "- Solo responde con información del contexto proporcionado\n"
                "- Si la respuesta NO está en el contexto, di: 'No encontrado en el documento.'\n"
                "- Incluye:\n"
                "   * Respuesta directa y clara\n"
                "   * 1-2 citas textuales EXACTAS del contexto\n"
                "   * Número de página de donde proviene\n"
                "- No inventes información que no esté explícita\n"
                "- Responde en español\n"
            )
        )
    
    def _load_index(self, document_id: int):
        """Carga el índice FAISS para un documento específico"""
        from rag_platform.documents.models import DocumentChunk
        
        # Cargar chunks del documento
        chunks = DocumentChunk.objects.filter(document_id=document_id).order_by('chunk_index')
        
        if not chunks.exists():
            return
        
        # Cargar embeddings desde archivo
        index_path = os.path.join(
            settings.FAISS_INDEX_DIR,
            f"document_{document_id}_faiss.pkl"
        )
        
        if os.path.exists(index_path):
            with open(index_path, 'rb') as f:
                data = pickle.load(f)
                self.documents = data['documents']
                self.embeddings = np.array(data['embeddings'], dtype=np.float32)
        else:
            # Reconstruir desde chunks
            self._rebuild_index(chunks)
    
    def _rebuild_index(self, chunks):
        """Reconstruye el índice desde los chunks"""
        self.documents = []
        texts = []
        
        for chunk in chunks:
            doc = Document(
                page_content=chunk.text,
                metadata={
                    'chunk_id': chunk.chunk_id,
                    'page_number': chunk.page_number,
                    'section': chunk.section,
                    'document_id': chunk.document_id,
                }
            )
            self.documents.append(doc)
            texts.append(chunk.text)
        
        # Generar embeddings
        if texts:
            self.embeddings = np.array(
                self.embedder.embed_documents(texts),
                dtype=np.float32
            )
    
    def save_index(self, document_id: int):
        """Guarda el índice FAISS"""
        index_path = os.path.join(
            settings.FAISS_INDEX_DIR,
            f"document_{document_id}_faiss.pkl"
        )
        
        os.makedirs(settings.FAISS_INDEX_DIR, exist_ok=True)
        
        with open(index_path, 'wb') as f:
            pickle.dump({
                'documents': self.documents,
                'embeddings': self.embeddings.tolist(),
            }, f)
    
    def index_documents(self, chunks_data: List[Dict]):
        """Indexa nuevos documentos"""
        self.documents = []
        texts = []
        
        for chunk in chunks_data:
            doc = Document(
                page_content=chunk['text'],
                metadata=chunk['metadata']
            )
            self.documents.append(doc)
            texts.append(chunk['text'])
        
        # Generar embeddings
        self.embeddings = np.array(
            self.embedder.embed_documents(texts),
            dtype=np.float32
        )
    
    def retrieve(self, query: str, k: int = None) -> List[Document]:
        """Recupera los k documentos más similares"""
        if not self.documents or self.embeddings is None:
            return []
        
        k = k or getattr(settings, 'NUM_RETRIEVED_DOCS', 12)
        k = min(k, len(self.documents))
        
        # Embedding de la query
        query_vec = np.array(
            self.embedder.embed_query(query),
            dtype=np.float32
        ).reshape(1, -1)
        
        # Similitud coseno
        similarities = cosine_similarity(query_vec, self.embeddings).flatten()
        
        # Top-k índices
        top_indices = similarities.argsort()[::-1][:k]
        
        # Retornar documentos con scores
        results = []
        for idx in top_indices:
            doc = self.documents[idx]
            doc.metadata['similarity_score'] = float(similarities[idx])
            results.append(doc)
        
        return results
    
    def generate_response(self, query: str, conversation_history: List[Dict] = None) -> Dict:
        """Genera respuesta usando el LLM configurado o devuelve chunks si no hay LLM"""
        import time
        
        # Siempre recuperamos los documentos primero
        start_retrieval = time.time()
        retrieved_docs = self.retrieve(query)
        retrieval_time = time.time() - start_retrieval
        
        # Si no hay documentos, devolver mensaje informativo
        if not retrieved_docs:
            return {
                'response': '📭 No se encontraron documentos indexados. Por favor, sube y procesa un documento primero.',
                'retrieved_chunks': 0,
                'retrieval_time': retrieval_time,
                'generation_time': 0,
                'engine': 'faiss',
                'llm_used': None
            }
        
        # Construir contexto de los chunks recuperados
        context = ""
        for doc in retrieved_docs:
            page = doc.metadata.get("page_number", "?")
            score = doc.metadata.get("similarity_score", 0)
            context += f"[Página {page} - Similitud: {score:.3f}]\n{doc.page_content}\n\n"
        
        # MODO SIN LLM: Devolver solo los chunks encontrados
        if self.llm is None:
            chunks_text = "📚 **MODO BÚSQUEDA SEMÁNTICA** (sin modelo de IA)\n\n"
            chunks_text += f"Se encontraron {len(retrieved_docs)} fragmentos relevantes:\n\n"
            
            for i, doc in enumerate(retrieved_docs[:5]):
                page = doc.metadata.get("page_number", "?")
                score = doc.metadata.get("similarity_score", 0)
                chunks_text += f"**Fragmento {i+1}** (Pág. {page}, similitud: {score:.2%})\n"
                chunks_text += f"{doc.page_content.strip()}\n\n"
            
            return {
                'response': chunks_text,
                'retrieved_chunks': len(retrieved_docs),
                'retrieval_time': retrieval_time,
                'generation_time': 0,
                'engine': 'faiss',
                'llm_used': None,
                'chunks_info': [
                    {
                        'page': doc.metadata.get('page_number'),
                        'score': doc.metadata.get('similarity_score'),
                        'text_preview': doc.page_content[:100]
                    }
                    for doc in retrieved_docs[:5]
                ]
            }
        
        # CON LLM: Generar respuesta
        try:
            # Historial
            history_text = ""
            if conversation_history:
                for msg in conversation_history[-6:]:
                    role = "Usuario" if msg['role'] == 'user' else "Asistente"
                    history_text += f"{role}: {msg['content']}\n"
            
            # Prompt
            formatted_prompt = self.prompt.format(
                context=context,
                question=query,
                history=history_text if history_text else "Sin historial previo"
            )
            
            # Llamada al LLM
            start_generation = time.time()
            messages = [{"role": "user", "content": formatted_prompt}]
            response = self.llm.invoke(messages)
            generation_time = time.time() - start_generation
            
            # Determinar qué LLM se usó
            llm_name = type(self.llm).__name__
            if 'Google' in llm_name:
                llm_used = 'gemini'
            elif 'OpenAI' in llm_name:
                llm_used = 'openai'
            else:
                llm_used = 'unknown'
            
            return {
                'response': response.content,
                'retrieved_chunks': len(retrieved_docs),
                'retrieval_time': retrieval_time,
                'generation_time': generation_time,
                'engine': 'faiss',
                'llm_used': llm_used,
                'chunks_info': [
                    {
                        'page': doc.metadata.get('page_number'),
                        'score': doc.metadata.get('similarity_score'),
                        'text_preview': doc.page_content[:100]
                    }
                    for doc in retrieved_docs[:3]
                ]
            }
            
        except Exception as e:
            # Error de API: devolver chunks como fallback
            error_msg = str(e)
            fallback_response = f"⚠️ **Error al conectar con el modelo de IA:**\n`{error_msg[:200]}`\n\n"
            fallback_response += "---\n📚 **Información encontrada en los documentos:**\n\n"
            
            for i, doc in enumerate(retrieved_docs[:3]):
                page = doc.metadata.get("page_number", "?")
                fallback_response += f"**Fragmento {i+1}** (Pág. {page})\n{doc.page_content.strip()}\n\n"
            
            return {
                'response': fallback_response,
                'retrieved_chunks': len(retrieved_docs),
                'retrieval_time': retrieval_time,
                'generation_time': 0,
                'engine': 'faiss',
                'llm_used': 'error',
                'error': error_msg
            }


class Neo4jUnavailableError(Exception):
    """Se lanza cuando Neo4j no está disponible."""
    pass


class Neo4jEngine(BaseRAGEngine):
    """
    Motor RAG basado en Neo4j GraphRAG
    Usa índices vectoriales + expansión por grafo para recuperación contextual
    """
    
    def __init__(self, document_id: int = None, llm_provider: str = None):
        super().__init__(llm_provider=llm_provider)
        # Aceptar document_id como str o int (viene del frontend como string). Normalizar a int cuando sea posible.
        if document_id is not None:
            try:
                document_id = int(document_id)
            except (TypeError, ValueError):
                pass
        self.document_id = document_id
        
        # Conexión a Neo4j
        uri = settings.NEO4J_URI
        user = settings.NEO4J_USER
        password = settings.NEO4J_PASSWORD
        
        try:
            self.driver: Driver = GraphDatabase.driver(uri, auth=(user, password))
            self._check_connection()
        except Exception as e:
            raise Neo4jUnavailableError(
                f"Neo4j no está disponible en {uri}. "
                f"Asegúrate de que Neo4j esté corriendo (docker-compose up -d) o usa el motor FAISS. "
                f"Error: {e}"
            )
        
        self.prompt = PromptTemplate(
            input_variables=["context", "question", "history"],
            template=(
                "Eres un asistente experto en Graph RAG y análisis relacional de documentos.\n\n"
                "Tu especialidad es entender relaciones entre conceptos y navegar por grafos de conocimiento.\n\n"
                "Contexto recuperado (nodos relacionados en el grafo de conocimiento):\n"
                "{context}\n\n"
                "Historial de conversación:\n"
                "{history}\n\n"
                "Pregunta del usuario:\n"
                "{question}\n\n"
                "Reglas estrictas:\n"
                "- Solo responde con información del contexto proporcionado\n"
                "- Si la respuesta NO está en el contexto, di: 'No encontrado en el documento.'\n"
                "- Aprovecha las relaciones entre conceptos del grafo\n"
                "- Incluye:\n"
                "   * Respuesta directa considerando relaciones conceptuales\n"
                "   * 1-2 citas textuales EXACTAS\n"
                "   * Número de página y contexto relacional\n"
                "- No inventes relaciones que no estén en el grafo\n"
                "- Responde en español\n"
            )
        )
    
    def _check_connection(self):
        """Verifica la conexión a Neo4j"""
        try:
            self.driver.verify_connectivity()
            print("✓ Conexión a Neo4j exitosa")
        except Exception as e:
            print(f"✗ Error de conexión a Neo4j: {e}")
            raise
    
    def index_document(self, chunks_data: List[Dict], document_id: int):
        """Indexa un documento en Neo4j"""
        from .neo4j_indexer import Neo4jGraphIndexer
        
        indexer = Neo4jGraphIndexer(self.driver, self.embedder)
        indexer.index_chunks(chunks_data, document_id)
    
    def retrieve(self, query: str, k: int = None, hops: int = 1) -> List[Document]:
        """Recupera documentos usando el índice vectorial de Neo4j"""
        k = k or getattr(settings, 'NUM_RETRIEVED_DOCS', 12)
        
        # Embedding de la query
        query_vec = self.embedder.embed_query(query)
        
        # Búsqueda vectorial en Neo4j
        initial_k = max(k * 3, 20)

        # Si no se especifica document_id (None), buscar en todos los documentos
        where_clause = "WHERE retrievedNode.document_id = $document_id" if self.document_id is not None else ""

        cypher_query = f"""
        CALL db.index.vector.queryNodes(
            'chunk_embeddings',
            {initial_k},
            $embedding
        ) YIELD node AS retrievedNode, score AS vectorScore
        {where_clause}
        RETURN retrievedNode AS node, vectorScore
        ORDER BY vectorScore DESC
        LIMIT {initial_k}
        """

        try:
            with self.driver.session() as session:
                params = {'embedding': query_vec}
                if self.document_id is not None:
                    params['document_id'] = self.document_id

                records = session.run(cypher_query, **params).data()
        except Exception as e:
            print(f"Error en consulta Neo4j: {e}")
            return []
        
        # Reranking local
        reranked = []
        for rec in records:
            node = rec["node"]
            metadata = dict(node)
            text = metadata.pop("text", "")
            emb = np.array(metadata.pop("embedding", []), dtype="float32")
            
            # Similitud coseno
            score = float(
                np.dot(query_vec, emb) / 
                (np.linalg.norm(query_vec) * np.linalg.norm(emb) + 1e-8)
            )
            
            reranked.append((score, text, metadata))
        
        # Ordenar y filtrar
        reranked.sort(key=lambda x: x[0], reverse=True)
        reranked = reranked[:k]
        
        # Convertir a documentos
        results = []
        for score, text, metadata in reranked:
            metadata["similarity_score"] = score
            results.append(Document(page_content=text, metadata=metadata))
        
        return results
    
    def generate_response(self, query: str, conversation_history: List[Dict] = None) -> Dict:
        """Genera respuesta usando GPT-4o con contexto de grafo"""
        import time
        
        # Timing
        start_retrieval = time.time()
        retrieved_docs = self.retrieve(query)
        retrieval_time = time.time() - start_retrieval
        
        if not retrieved_docs:
            return {
                'response': 'No encontrado en el documento.',
                'retrieved_chunks': 0,
                'retrieval_time': retrieval_time,
                'generation_time': 0,
                'engine': 'neo4j',
                'llm_used': None
            }
        
        # Construir contexto
        context = ""
        for doc in retrieved_docs:
            page = doc.metadata.get("page_number", "?")
            score = doc.metadata.get("similarity_score", 0)
            context += f"[Página {page} - Score: {score:.3f}]\n{doc.page_content}\n\n"
        
        # MODO SIN LLM: Devolver solo los chunks del grafo
        if self.llm is None:
            chunks_text = "🕸️ **MODO BÚSQUEDA EN GRAFO** (sin modelo de IA)\n\n"
            chunks_text += f"Se encontraron {len(retrieved_docs)} nodos relevantes en el grafo:\n\n"
            
            for i, doc in enumerate(retrieved_docs[:5]):
                page = doc.metadata.get("page_number", "?")
                score = doc.metadata.get("similarity_score", 0)
                chunks_text += f"**Nodo {i+1}** (Pág. {page}, similitud: {score:.2%})\n"
                chunks_text += f"{doc.page_content.strip()}\n\n"
            
            return {
                'response': chunks_text,
                'retrieved_chunks': len(retrieved_docs),
                'retrieval_time': retrieval_time,
                'generation_time': 0,
                'engine': 'neo4j',
                'llm_used': None,
                'chunks_info': [
                    {
                        'page': doc.metadata.get('page_number'),
                        'score': doc.metadata.get('similarity_score'),
                        'text_preview': doc.page_content[:100]
                    }
                    for doc in retrieved_docs[:5]
                ]
            }
        
        # Historial
        history_text = ""
        if conversation_history:
            for msg in conversation_history[-6:]:
                role = "Usuario" if msg['role'] == 'user' else "Asistente"
                history_text += f"{role}: {msg['content']}\n"
        
        # Prompt
        formatted_prompt = self.prompt.format(
            context=context,
            question=query,
            history=history_text if history_text else "Sin historial previo"
        )
        
        # Llamada al LLM
        try:
            start_generation = time.time()
            messages = [{"role": "user", "content": formatted_prompt}]
            response = self.llm.invoke(messages)
            generation_time = time.time() - start_generation
            
            # Determinar qué LLM se usó
            llm_name = type(self.llm).__name__
            if 'Google' in llm_name:
                llm_used = 'gemini'
            elif 'OpenAI' in llm_name:
                llm_used = 'openai'
            else:
                llm_used = 'unknown'
            
            return {
                'response': response.content,
                'retrieved_chunks': len(retrieved_docs),
                'retrieval_time': retrieval_time,
                'generation_time': generation_time,
                'engine': 'neo4j',
                'llm_used': llm_used,
                'chunks_info': [
                    {
                        'page': doc.metadata.get('page_number'),
                        'score': doc.metadata.get('similarity_score'),
                        'text_preview': doc.page_content[:100]
                    }
                    for doc in retrieved_docs[:3]
                ]
            }
        except Exception as e:
            # Error de API: devolver chunks como fallback
            error_msg = str(e)
            fallback_response = f"⚠️ **Error al conectar con el modelo de IA:**\n`{error_msg[:200]}`\n\n"
            fallback_response += "---\n🕸️ **Información encontrada en el grafo:**\n\n"
            
            for i, doc in enumerate(retrieved_docs[:3]):
                page = doc.metadata.get("page_number", "?")
                fallback_response += f"**Nodo {i+1}** (Pág. {page})\n{doc.page_content.strip()}\n\n"
            
            return {
                'response': fallback_response,
                'retrieved_chunks': len(retrieved_docs),
                'retrieval_time': retrieval_time,
                'generation_time': 0,
                'engine': 'neo4j',
                'llm_used': 'error',
                'error': error_msg
            }
    
    def close(self):
        """Cierra la conexión a Neo4j"""
        if self.driver:
            self.driver.close()
