# Base de Datos - Estructura de la Aplicacion

Este documento describe la estructura actual de la base de datos del proyecto y los tipos de usuario disponibles.

## Motor de base de datos

La aplicacion soporta dos modos:
- SQLite para desarrollo rapido (archivo local).
- PostgreSQL para entorno mas robusto, usando contenedor Docker.

En configuracion actual, Django decide el motor con la variable de entorno USE_SQLITE.

## Tipos de usuario

La aplicacion usa un modelo personalizado de usuario: accounts.User, que extiende AbstractUser.

Hay dos perfiles funcionales principales:
- Usuario normal:
  - is_staff=False
  - is_superuser=False
  - Puede registrarse, iniciar sesion, subir documentos y crear conversaciones.
- Usuario administrador:
  - is_staff=True
  - Opcionalmente is_superuser=True
  - Puede acceder al panel /admin y gestionar usuarios, documentos y conversaciones.

Campos personalizados del usuario:
- bio: texto corto de perfil.
- avatar: imagen de perfil opcional.
- preferred_engine: preferencia de motor RAG (faiss o neo4j).
- created_at, updated_at: trazabilidad.

## Entidades principales

### 1) accounts_user

Tabla de autenticacion personalizada (modelo User).

Incluye todos los campos base de Django (username, email, password, is_active, is_staff, is_superuser, etc.) mas:
- bio
- avatar
- preferred_engine
- created_at
- updated_at

### 2) documents_document

Representa archivos cargados por usuario (PDF/TXT) y su estado de procesamiento.

Relacion:
- user -> FK a accounts_user (1 usuario puede tener muchos documentos).

Campos relevantes:
- title, file, file_type, file_size
- status (pending, processing, completed, failed)
- metadata extraida (author, year, doi, abstract, keywords)
- indexacion (indexed_in_faiss, indexed_in_neo4j, faiss_index_path)
- auditoria (created_at, updated_at, processed_at, error_message)

### 3) documents_documentchunk

Chunks de texto derivados de cada documento.

Relacion:
- document -> FK a documents_document (1 documento tiene muchos chunks).

Campos relevantes:
- chunk_id (unico)
- text, chunk_index
- page_number, section
- embedding_preview
- similarity_score
- created_at

### 4) chat_conversation

Conversaciones de chat persistentes por usuario.

Relacion:
- user -> FK a accounts_user (1 usuario puede tener muchas conversaciones).

Campos relevantes:
- title
- engine_used (faiss o neo4j)
- is_active
- created_at, updated_at

### 5) chat_message

Mensajes dentro de una conversacion.

Relacion:
- conversation -> FK a chat_conversation (1 conversacion tiene muchos mensajes).

Campos relevantes:
- role (user, assistant, system)
- content
- metricas (tokens_used, retrieval_time, generation_time)
- retrieved_chunks_count
- created_at

## Relaciones clave (resumen)

- User 1:N Document
- User 1:N Conversation
- Document 1:N DocumentChunk
- Conversation 1:N Message

## Diagrama conceptual rapido

User
  -> Document
      -> DocumentChunk
  -> Conversation
      -> Message

## Administracion

El admin de Django usa el modelo personalizado User y permite filtrar por:
- preferred_engine
- is_staff
- is_active
- created_at

Para crear un administrador:
- python manage.py createsuperuser

Luego entrar a:
- http://127.0.0.1:8000/admin

## Notas de buenas practicas

- Para desarrollo local rapido: SQLite.
- Para pruebas multiusuario o entornos mas cercanos a produccion: PostgreSQL.
- Mantener migraciones al dia y evitar cambios manuales directos en la base de datos.
