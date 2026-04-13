"""
Django settings for RAG Platform.
Configuración profesional con PostgreSQL, seguridad y deployment en Gunicorn.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Cargar variables de entorno
load_dotenv(os.path.join(BASE_DIR, '.env'))


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = (
    os.getenv('DJANGO_SECRET_KEY')
    or os.getenv('SECRET_KEY')
    or 'django-insecure-change-this-in-production'
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env_bool('DEBUG', False)

ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if h.strip()]

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Local apps
    'rag_platform.accounts',
    'rag_platform.chat',
    'rag_platform.documents',
    'rag_platform.manuscript',
    'rag_platform.core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'rag_platform.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'rag_platform/templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.media',
            ],
        },
    },
]

WSGI_APPLICATION = 'rag_platform.wsgi.application'

# Database - SQLite para desarrollo, PostgreSQL para producción
USE_SQLITE = os.getenv('USE_SQLITE', 'True') == 'True'

if USE_SQLITE:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('DB_NAME', 'rag_platform_db'),
            'USER': os.getenv('DB_USER', 'postgres'),
            'PASSWORD': os.getenv('DB_PASSWORD', 'postgres'),
            'HOST': os.getenv('DB_HOST', 'localhost'),
            'PORT': os.getenv('DB_PORT', '5432'),
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'es-es'
TIME_ZONE = 'America/Mexico_City'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'rag_platform/static')]

# Media files (User uploads)
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'rag_platform/media')

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom User Model
AUTH_USER_MODEL = 'accounts.User'

# Authentication
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'accounts:workspace_menu'
LOGOUT_REDIRECT_URL = 'accounts:landing'

# Security Settings (Production)
if not DEBUG:
    # Se pueden desactivar temporalmente en un servidor interno sin HTTPS.
    SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', True)
    SESSION_COOKIE_SECURE = env_bool('SESSION_COOKIE_SECURE', True)
    CSRF_COOKIE_SECURE = env_bool('CSRF_COOKIE_SECURE', True)
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'

# RAG Configuration - LLM Provider
LLM_PROVIDER = os.getenv('LLM_PROVIDER', 'none')  # 'openai' | 'gemini' | 'none'

# API Keys
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# Model names (configurables)
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash-exp')

# Neo4j
NEO4J_URI = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
NEO4J_USER = os.getenv('NEO4J_USER', 'neo4j')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD', 'neo4jpassword')

# Embedding model configuration
EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', 'sentence-transformers/all-MiniLM-L6-v2')
CHUNK_SIZE = int(os.getenv('CHUNK_SIZE', 512))
CHUNK_OVERLAP = int(os.getenv('CHUNK_OVERLAP', 50))
NUM_RETRIEVED_DOCS = int(os.getenv('NUM_RETRIEVED_DOCS', 5))
TEMPERATURE = float(os.getenv('TEMPERATURE', 0.1))

# FAISS Index path
FAISS_INDEX_DIR = os.path.join(BASE_DIR, 'rag_platform/core/faiss_indexes')
os.makedirs(FAISS_INDEX_DIR, exist_ok=True)
