# Usar PostgreSQL en contenedor (en lugar de SQLite)

Si, se puede usar PostgreSQL con Docker y es recomendable cuando quieres un entorno mas estable y cercano a produccion.

Este proyecto ya tiene soporte en Django para cambiar entre SQLite y PostgreSQL mediante variables de entorno.

## 1) Levantar contenedores de datos

El archivo de servicios esta en src/docker-compose.yml y ahora incluye:
- postgres (base de datos relacional)
- neo4j (grafo para RAG)

Ejecuta desde la raiz del proyecto:

docker compose -f src/docker-compose.yml up -d postgres neo4j

Para verificar:

docker ps

## 2) Configurar .env para PostgreSQL

En tu archivo .env (raiz del proyecto), usa estas variables:

USE_SQLITE=False
DB_NAME=rag_platform_db
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=127.0.0.1
DB_PORT=5433

Nota: si Django corre dentro de otro contenedor del mismo compose, DB_HOST deberia ser postgres.

## 3) Ejecutar migraciones

Con tu entorno virtual activo:

python manage.py migrate

Crear usuario admin:

python manage.py createsuperuser

## 4) Ejecutar servidor

python manage.py runserver

## 5) Migrar datos desde SQLite (opcional)

Si ya tienes datos en SQLite y quieres moverlos a PostgreSQL:

1. Cambia temporalmente USE_SQLITE=True.
2. Exporta datos:

python manage.py dumpdata --natural-foreign --natural-primary -e contenttypes -e auth.Permission > data.json

3. Cambia a PostgreSQL (USE_SQLITE=False y variables DB_*).
4. Ejecuta migraciones en PostgreSQL:

python manage.py migrate

5. Importa datos:

python manage.py loaddata data.json

## 6) Volumen de datos

PostgreSQL guarda datos en el volumen Docker:
- postgres_data

Neo4j guarda datos en:
- neo4j_data

## 7) Volver a SQLite

Solo cambia:

USE_SQLITE=True

Y reinicia Django.

## Recomendacion

Para pruebas reales de usuarios, sesiones y concurrencia, PostgreSQL es mejor opcion que SQLite.
