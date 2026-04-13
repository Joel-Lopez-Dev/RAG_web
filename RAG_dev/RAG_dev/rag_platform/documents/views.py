from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
import os
from datetime import datetime

from .models import Document, DocumentChunk
from rag_platform.core.processor import DocumentProcessor
from rag_platform.core.rag_engines import FaissEngine

from django.conf import settings


@login_required
def document_list(request):
    """
    Lista documentos por flujo (chat/manuscript) del usuario
    """
    scope = request.GET.get('scope', 'chat')

    documents = Document.objects.filter(user=request.user)

    if scope == 'manuscript':
        # Flujo de manuscrito: solo biblioteca de PDFs del usuario.
        documents = documents.filter(file_type='pdf')
        list_title = 'Mis PDFs'
        list_subtitle = 'Biblioteca del módulo Analiza tu manuscrito.'
        template_name = 'documents/document_list.html'
    else:
        # Flujo de chat/RAG: excluir PDFs de manuscrito sin procesamiento RAG.
        documents = documents.filter(
            Q(total_chunks__gt=0)
            | Q(indexed_in_faiss=True)
            | Q(indexed_in_neo4j=True)
            | Q(file_type='txt')
            | Q(status__in=['processing', 'failed'])
        )
        list_title = 'Mis Documentos'
        list_subtitle = 'Documentos disponibles para el flujo de conversación con RAG.'
        template_name = 'documents/document_list_chat.html'

    documents = documents.order_by('-created_at')
    
    # Filtros
    status_filter = request.GET.get('status')
    if status_filter:
        documents = documents.filter(status=status_filter)
    
    # Paginación
    paginator = Paginator(documents, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'scope': scope,
        'list_title': list_title,
        'list_subtitle': list_subtitle,
    }
    
    return render(request, template_name, context)


@login_required
@require_http_methods(["GET", "POST"])
def document_upload(request):
    """
    Subida de documentos PDF/TXT
    """
    scope = request.GET.get('scope', request.POST.get('scope', 'manuscript'))

    if request.method == 'POST':
        if 'file' not in request.FILES:
            messages.error(request, 'No se seleccionó ningún archivo.')
            return redirect(f'{request.path}?scope={scope}')
        
        uploaded_file = request.FILES['file']
        index_in_faiss = request.POST.get('index_faiss') == 'on'
        index_in_neo4j = request.POST.get('index_neo4j') == 'on'
        
        # Validar tipo de archivo
        file_ext = os.path.splitext(uploaded_file.name)[1].lower()
        if file_ext not in ['.pdf', '.txt']:
            messages.error(request, 'Solo se permiten archivos PDF o TXT.')
            return redirect(f'{request.path}?scope={scope}')
        
        # Validar tamaño (50MB máximo)
        if uploaded_file.size > 50 * 1024 * 1024:
            messages.error(request, 'El archivo es demasiado grande (máximo 50MB).')
            return redirect(f'{request.path}?scope={scope}')
        
        # Crear documento
        document = Document.objects.create(
            user=request.user,
            title=os.path.splitext(uploaded_file.name)[0],
            file=uploaded_file,
            file_type=file_ext[1:],  # sin el punto
            file_size=uploaded_file.size,
            status='pending'
        )
        
        # Procesar en background (en producción usar Celery)
        try:
            process_document_task(
                document.id,
                index_in_faiss,
                index_in_neo4j
            )
            messages.success(request, f'Documento "{document.title}" subido y procesado correctamente.')
        except Exception as e:
            document.status = 'failed'
            document.error_message = str(e)
            document.save()
            messages.error(request, f'Error al procesar el documento: {str(e)}')
        
        return redirect(f"{reverse('documents:detail', args=[document.id])}?scope={scope}")
    
    return render(request, 'documents/document_upload.html', {'scope': scope})


def process_document_task(document_id: int, index_faiss: bool, index_neo4j: bool):
    """
    Procesa un documento: extrae chunks, metadata e indexa
    """
    document = Document.objects.get(id=document_id)
    document.status = 'processing'
    document.save()
    
    try:
        # Procesar documento
        processor = DocumentProcessor()
        file_path = document.file.path
        
        result = processor.process_document(file_path)
        
        if not result.get('success'):
            raise Exception(result.get('error', 'Error desconocido'))
        
        # Actualizar metadata del documento
        metadata = result['metadata']
        document.author = metadata.get('author_real') or ''
        document.year = metadata.get('year')
        document.doi = metadata.get('doi') or ''
        document.abstract = metadata.get('abstract') or ''
        document.keywords = ', '.join(metadata.get('tags') or [])
        document.total_pages = metadata.get('total_pages', 0)
        document.total_chunks = metadata.get('total_chunks', 0)
        
        # Guardar chunks en la base de datos
        with transaction.atomic():
            # Eliminar chunks antiguos si existen
            DocumentChunk.objects.filter(document=document).delete()
            
            # Crear nuevos chunks
            chunks_to_create = []
            for chunk_data in result['chunks']:
                chunk = DocumentChunk(
                    document=document,
                    chunk_id=f"doc_{document_id}_chunk_{chunk_data['index']}",
                    text=chunk_data['text'],
                    chunk_index=chunk_data['index'],
                    page_number=chunk_data['metadata'].get('page_number'),
                    section=chunk_data['metadata'].get('section', ''),
                    embedding_preview=chunk_data.get('embedding_preview', '')
                )
                chunks_to_create.append(chunk)
            
            DocumentChunk.objects.bulk_create(chunks_to_create)
        
        # Indexar en FAISS
        if index_faiss:
            faiss_engine = FaissEngine()
            faiss_engine.index_documents(result['chunks'])
            faiss_engine.save_index(document_id)
            document.indexed_in_faiss = True
            document.faiss_index_path = os.path.join(
                settings.FAISS_INDEX_DIR,
                f"document_{document_id}_faiss.pkl"
            )
        
        # Indexar en Neo4j (opcional)
        if index_neo4j:
            try:
                from neo4j import GraphDatabase
                from rag_platform.core.neo4j_indexer import Neo4jGraphIndexer
                driver = GraphDatabase.driver(
                    settings.NEO4J_URI,
                    auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
                )
                embedder = processor.get_embedder()
                indexer = Neo4jGraphIndexer(driver, embedder)
                indexer.index_chunks(result['chunks'], document_id)
                driver.close()
                document.indexed_in_neo4j = True
            except Exception as e:
                print(f"⚠️ Neo4j no disponible, se omite indexación en grafo: {e}")
                document.error_message = (document.error_message or '') + f"\nNeo4j no disponible: {str(e)}"
        
        # Marcar como completado
        document.status = 'completed'
        document.processed_at = datetime.now()
        document.save()
        
    except Exception as e:
        document.status = 'failed'
        document.error_message = str(e)
        document.save()
        raise


@login_required
def document_detail(request, document_id):
    """
    Vista detallada de un documento
    """
    document = get_object_or_404(
        Document,
        id=document_id,
        user=request.user
    )

    scope = request.GET.get('scope', 'manuscript')
    
    context = {
        'document': document,
        'scope': scope,
    }
    
    return render(request, 'documents/document_detail.html', context)


@login_required
def document_chunks(request, document_id):
    """
    Inspección de chunks de un documento
    """
    document = get_object_or_404(
        Document,
        id=document_id,
        user=request.user
    )

    scope = request.GET.get('scope', 'manuscript')
    
    chunks = document.chunks.all().order_by('chunk_index')
    
    # Filtros
    section_filter = request.GET.get('section')
    if section_filter:
        chunks = chunks.filter(section=section_filter)
    
    # Paginación
    paginator = Paginator(chunks, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Secciones disponibles
    sections = document.chunks.values_list('section', flat=True).distinct()
    
    context = {
        'document': document,
        'page_obj': page_obj,
        'sections': sections,
        'section_filter': section_filter,
        'scope': scope,
    }
    
    return render(request, 'documents/document_chunks.html', context)


@login_required
@require_http_methods(["POST"])
def document_delete(request, document_id):
    """
    Elimina un documento y sus chunks
    """
    document = get_object_or_404(
        Document,
        id=document_id,
        user=request.user
    )

    scope = request.GET.get('scope', request.POST.get('scope', 'manuscript'))
    
    document_title = document.title
    
    # Eliminar archivo físico
    if document.file and os.path.exists(document.file.path):
        os.remove(document.file.path)
    
    # Eliminar índice FAISS
    if document.faiss_index_path and os.path.exists(document.faiss_index_path):
        os.remove(document.faiss_index_path)
    
    # Eliminar de Neo4j
    if document.indexed_in_neo4j:
        try:
            driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
            )
            indexer = Neo4jGraphIndexer(driver, None)
            indexer.delete_document_chunks(document_id)
            driver.close()
        except Exception as e:
            print(f"Error al eliminar de Neo4j: {e}")
    
    # Eliminar documento
    document.delete()
    
    messages.success(request, f'Documento "{document_title}" eliminado correctamente.')
    return redirect(f"{reverse('documents:list')}?scope={scope}")


@login_required
@require_http_methods(["POST"])
def reindex_document(request, document_id):
    """
    Re-indexa un documento en FAISS y/o Neo4j
    """
    document = get_object_or_404(
        Document,
        id=document_id,
        user=request.user
    )
    
    index_faiss = request.POST.get('index_faiss') == 'on'
    index_neo4j = request.POST.get('index_neo4j') == 'on'
    
    try:
        # Obtener chunks existentes
        chunks = document.chunks.all().order_by('chunk_index')
        
        if not chunks.exists():
            messages.error(request, 'El documento no tiene chunks para indexar.')
            return redirect(f"{reverse('documents:detail', args=[document_id])}?scope={request.POST.get('scope', 'manuscript')}")
        
        # Preparar datos
        processor = DocumentProcessor()
        embedder = processor.get_embedder()
        
        chunks_data = []
        texts = [chunk.text for chunk in chunks]
        embeddings = embedder.embed_documents(texts)
        
        for chunk, embedding in zip(chunks, embeddings):
            chunks_data.append({
                'text': chunk.text,
                'embedding': embedding,
                'metadata': {
                    'chunk_id': chunk.chunk_id,
                    'page_number': chunk.page_number,
                    'section': chunk.section,
                }
            })
        
        # Re-indexar FAISS
        if index_faiss:
            faiss_engine = FaissEngine()
            faiss_engine.index_documents(chunks_data)
            faiss_engine.save_index(document_id)
            document.indexed_in_faiss = True
        
        # Re-indexar Neo4j
        if index_neo4j:
            driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
            )
            indexer = Neo4jGraphIndexer(driver, embedder)
            # Eliminar chunks antiguos
            indexer.delete_document_chunks(document_id)
            # Indexar nuevos
            indexer.index_chunks(chunks_data, document_id)
            driver.close()
            document.indexed_in_neo4j = True
        
        document.save()
        messages.success(request, 'Documento re-indexado correctamente.')
        
    except Exception as e:
        messages.error(request, f'Error al re-indexar: {str(e)}')
    
    return redirect(f"{reverse('documents:detail', args=[document_id])}?scope={request.POST.get('scope', 'manuscript')}")
