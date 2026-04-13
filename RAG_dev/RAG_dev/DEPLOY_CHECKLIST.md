# DEPLOY_CHECKLIST.md

Checklist de despliegue para mover este proyecto a otra maquina (servidor principal).

## 1) Pre-Deploy (local)
- [ ] El proyecto corre sin errores en local.
- [ ] `python manage.py migrate` ejecuta correctamente.
- [ ] Las conversaciones y documentos importantes estan respaldados.
- [ ] El repo esta actualizado y con cambios confirmados.

## 2) Requisitos del servidor
- [ ] Python instalado (misma version recomendada que en desarrollo).
- [ ] Git instalado.
- [ ] Neo4j instalado y en ejecucion (si se usara GraphRAG).
- [ ] Acceso a internet para instalar dependencias.

## 3) Clonar proyecto y entorno virtual
- [ ] Clonar el repositorio en el servidor.
- [ ] Crear entorno virtual.
- [ ] Activar entorno virtual.
- [ ] Instalar dependencias con `requirements.txt`.

Comandos de referencia (Windows PowerShell):
```powershell
git clone <URL_DEL_REPO>
cd RAG_dev
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 4) Variables y configuracion sensible
- [ ] Configurar `DJANGO_SECRET_KEY` (o `SECRET_KEY` como alias).
- [ ] Forzar PostgreSQL para servidor: `USE_SQLITE=False`.
- [ ] Configurar credenciales de base de datos (si no se usa SQLite).
- [ ] Configurar API keys de proveedores LLM (`OPENAI_API_KEY` y `GOOGLE_API_KEY`; `GEMINI_API_KEY` es alias compatible).
- [ ] Configurar parametros de Neo4j (`URI`, `USER`, `PASSWORD`).
- [ ] Verificar `ALLOWED_HOSTS` y `DEBUG=False` en produccion.
- [ ] Si no hay HTTPS aun (servidor interno temporal), definir:
	- `SECURE_SSL_REDIRECT=False`
	- `SESSION_COOKIE_SECURE=False`
	- `CSRF_COOKIE_SECURE=False`

## 5) Base de datos y migraciones
- [ ] Ejecutar migraciones:
```powershell
python manage.py migrate
```
- [ ] Si necesitas usuarios iniciales:
```powershell
python manage.py createsuperuser
```

## 6) Archivos estaticos y media
- [ ] Ejecutar colecta de estaticos:
```powershell
python manage.py collectstatic --noinput
```
- [ ] Copiar carpeta `media/` si quieres conservar documentos subidos.
- [ ] Verificar permisos de lectura/escritura para `media/` y `static/`.

## 7) Datos RAG e indices
- [ ] Verificar que los documentos indexados existen en la nueva maquina.
- [ ] Si faltan, reindexar documentos.
- [ ] Validar conectividad con Neo4j desde la app.
- [ ] Probar una consulta FAISS y una GraphRAG.

## 8) Levantar en modo produccion
- [ ] No usar `runserver` como servicio final.
- [ ] Configurar servidor WSGI/ASGI (por ejemplo Gunicorn/Uvicorn) y proxy (Nginx/IIS).
- [ ] Configurar reinicio automatico del servicio.

## 9) Pruebas funcionales minimas
- [ ] Login/logout.
- [ ] Carga de documento.
- [ ] Conversacion nueva y recuperacion de historial.
- [ ] Persistencia de motor/modelo/documento por conversacion.
- [ ] Vista de historial y detalles de documentos.

## 10) Seguridad y operacion
- [ ] Confirmar que no hay secretos en el repo.
- [ ] Ejecutar `python manage.py check --deploy` y resolver advertencias relevantes.
- [ ] Habilitar logs de app y de servidor web.
- [ ] Definir politica de backup (DB + media + configuraciones).
- [ ] Probar restauracion de backup.

## 11) Rollback (si algo falla)
- [ ] Mantener snapshot/copia previa del servidor.
- [ ] Tener backup de DB y `media/` antes de cambios.
- [ ] Documentar comando rapido de rollback.

---

## Nota rapida
Si migras desde SQLite a PostgreSQL/MySQL, planifica export/import de datos y valida migraciones en entorno de prueba antes de pasar a produccion.
