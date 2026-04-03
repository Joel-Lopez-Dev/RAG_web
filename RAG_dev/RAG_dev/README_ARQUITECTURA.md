# RAG Platform - Guia de Arquitectura

Este documento explica como esta armado el proyecto para que una persona nueva pueda entender:

1. Que hace cada modulo.
2. Como fluye la data de extremo a extremo.
3. Que servicios externos usa.
4. Como correrlo local y que revisar al depurar.

## 1. Vision General

RAG Platform es una aplicacion web en Django para:

1. Subir documentos PDF/TXT.
2. Procesarlos en chunks con embeddings.
3. Indexarlos en dos motores:
   1. FAISS (busqueda semantica).
   2. Neo4j (busqueda relacional/grafo).
4. Chatear sobre el contenido con OpenAI, Gemini o modo sin LLM.

## 2. Stack Tecnologico

1. Backend web: Django.
2. Persistencia principal: SQLite o PostgreSQL (segun .env).
3. Embeddings: sentence-transformers via LangChain.
4. Vector search: FAISS (indices en archivos .pkl).
5. Graph search: Neo4j.
6. LLMs soportados:
   1. OpenAI.
   2. Gemini.
   3. none (solo retrieval).
7. Frontend server-rendered: Django templates + Tailwind por CDN.

## 3. Estructura del Proyecto

Ruta base de la app Django: RAG_dev/RAG_dev/

### 3.1 Apps Django

1. rag_platform/accounts
   1. Login, registro, perfil.
   2. Modelo User custom con preferred_engine.

2. rag_platform/documents
   1. Upload y procesamiento de documentos.
   2. Modelos Document y DocumentChunk.
   3. Reindexacion FAISS/Neo4j.

3. rag_platform/chat
   1. Dashboard de chat.
   2. Conversaciones y mensajes persistentes.
   3. Endpoint AJAX para enviar mensaje y recibir respuesta RAG.

4. rag_platform/core
   1. processor.py: parseo, metadata, chunking, embeddings.
   2. rag_engines.py: FaissEngine y Neo4jEngine.
   3. neo4j_indexer.py: indexacion en grafo.

### 3.2 Configuracion

1. rag_platform/settings.py: DB, static/media, llm provider, neo4j, chunking, seguridad.
2. rag_platform/urls.py: rutas principales (accounts, chat, documents).
3. manage.py: entrada CLI de Django.

### 3.3 Frontend

1. rag_platform/templates/base.html: layout global (navbar, mensajes, footer).
2. rag_platform/templates/accounts/*: landing, login, register, profile.
3. rag_platform/templates/chat/*: dashboard, historial, detalle de conversacion.
4. rag_platform/templates/documents/*: upload, lista, detalle, chunks.
5. rag_platform/static/images/: branding (logos CUAED/UNAM y fondo).

### 3.4 Codigo Base Heredado

src/ conserva scripts del RAG original (indexing/retrieval/generation) y docker-compose.yml para Neo4j.

## 4. Modelo de Datos (Resumen)

1. accounts.User
   1. Extiende AbstractUser.
   2. Campos clave: preferred_engine, avatar, bio.

2. documents.Document
   1. Estado: pending, processing, completed, failed.
   2. Metadata: autor, year, doi, abstract, keywords.
   3. Flags de indexacion: indexed_in_faiss, indexed_in_neo4j.

3. documents.DocumentChunk
   1. Texto chunkificado por documento.
   2. Referencia de pagina y seccion.

4. chat.Conversation
   1. Conversacion por usuario.
   2. Motor usado: faiss o neo4j.

5. chat.Message
   1. Roles: user, assistant, system.
   2. Guarda telemetria: retrieval/generation time y chunks recuperados.

## 5. Flujo End-to-End

### 5.1 Flujo de Upload e Indexacion

1. Usuario sube archivo en documents:upload.
2. Se crea Document en estado pending.
3. process_document_task() cambia a processing.
4. DocumentProcessor:
   1. Extrae texto y metadata.
   2. Divide en chunks.
   3. Genera embeddings.
5. Se guardan DocumentChunk.
6. Si aplica:
   1. Indexa en FAISS y guarda document_<id>_faiss.pkl.
   2. Indexa en Neo4j.
7. Documento queda completed o failed.

### 5.2 Flujo de Chat RAG

1. Frontend envia POST a chat:send_message (AJAX).
2. Backend crea o reutiliza conversacion.
3. Guarda mensaje del usuario.
4. Instancia motor segun selector:
   1. FaissEngine.
   2. Neo4jEngine.
5. Motor hace retrieval de chunks relevantes.
6. Si hay LLM activo:
   1. Construye prompt con contexto + historial.
   2. Genera respuesta.
7. Si LLM_PROVIDER=none, devuelve solo resultado de retrieval.
8. Guarda mensaje assistant y retorna JSON al dashboard.

## 6. Configuracion por Entorno (.env)

Variables clave:

1. DEBUG, ALLOWED_HOSTS, DJANGO_SECRET_KEY.
2. USE_SQLITE o credenciales PostgreSQL (DB_*).
3. LLM_PROVIDER = openai | gemini | none.
4. OPENAI_API_KEY y/o GOOGLE_API_KEY.
5. NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD.
6. EMBEDDING_MODEL, CHUNK_SIZE, CHUNK_OVERLAP, NUM_RETRIEVED_DOCS, TEMPERATURE.

## 7. Dependencias Criticas

Si faltan, el pipeline RAG no responde bien:

1. sentence-transformers (embeddings).
2. faiss-cpu (vector search).
3. langchain-community, langchain-openai, langchain-google-genai.
4. neo4j (si se usa Graph).

## 8. Comandos de Desarrollo

Desde RAG_dev/RAG_dev/:

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows PowerShell

pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Neo4j local (si aplica):

```bash
cd src
docker compose up -d
```

## 9. Endpoints/URLs Principales

1. / -> accounts (landing/login/register).
2. /chat/ -> dashboard de chat.
3. /chat/send/ -> envio de mensajes (AJAX).
4. /documents/ -> lista de documentos.
5. /documents/upload/ -> subida y procesamiento.
6. /admin/ -> admin Django.

## 10. Troubleshooting Rapido

1. Error Could not import sentence_transformers
   1. Instalar: pip install sentence-transformers.

2. Neo4j no conecta
   1. Revisar contenedor y NEO4J_* en .env.

3. Chat no responde con LLM
   1. Revisar LLM_PROVIDER y API key correspondiente.

4. No aparecen docs en selector
   1. El documento debe estar en estado completed.

## 11. Convenciones para Nuevos Colaboradores

1. No subir db.sqlite3 en commits normales.
2. Mantener cambios de UI en templates + static.
3. Validar siempre con:

```bash
python manage.py check
```

4. Si tocas chat/documents/core, probar un flujo real:
   1. Upload de documento.
   2. Indexado.
   3. Pregunta en dashboard.
