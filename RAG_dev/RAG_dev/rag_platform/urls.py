"""
URL Configuration for RAG Platform
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('rag_platform.accounts.urls')),
    path('chat/', include('rag_platform.chat.urls')),
    path('manuscript/', include('rag_platform.manuscript.urls')),
    path('documents/', include('rag_platform.documents.urls')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
