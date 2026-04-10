from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.db.models import Count, Q, Avg
import json
import logging

from .models import Conversation, Message
from rag_platform.documents.models import Document
from rag_platform.core.rag_engines import FaissEngine, Neo4jEngine, Neo4jUnavailableError

logger = logging.getLogger(__name__)


def _normalize_llm_provider(value):
    if value in (None, '', 'default'):
        return None
    if value in ('openai', 'gemini', 'none'):
        return value
    return None


def _normalize_document_id(value):
    if value in (None, ''):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@login_required
def dashboard(request):
    """
    Dashboard principal del chat con historial de conversaciones
    """
    conversations = Conversation.objects.filter(
        user=request.user,
        is_active=True
    ).annotate(
        message_count=Count('messages')
    )[:20]
    
    # Estadísticas
    total_conversations = request.user.conversations.filter(is_active=True).count()
    total_messages = Message.objects.filter(conversation__user=request.user).count()
    
    # Documentos disponibles
    documents = Document.objects.filter(
        user=request.user,
        status='completed'
    )
    
    context = {
        'conversations': conversations,
        'total_conversations': total_conversations,
        'total_messages': total_messages,
        'documents': documents,
        'preferred_engine': request.user.preferred_engine,
    }
    
    return render(request, 'chat/dashboard.html', context)


@login_required
@require_http_methods(["POST"])
def create_conversation(request):
    """
    Crea una nueva conversación
    """
    title = request.POST.get('title', 'Nueva Conversación')
    engine = request.POST.get('engine', request.user.preferred_engine)
    
    conversation = Conversation.objects.create(
        user=request.user,
        title=title,
        engine_used=engine
    )
    
    return JsonResponse({
        'success': True,
        'conversation_id': conversation.id,
        'title': conversation.title
    })


@login_required
def conversation_detail(request, conversation_id):
    """
    Vista detallada de una conversación con sus mensajes
    """
    conversation = get_object_or_404(
        Conversation,
        id=conversation_id,
        user=request.user
    )
    
    messages_list = conversation.messages.all().order_by('created_at')
    
    # Documentos para el selector
    documents = Document.objects.filter(
        user=request.user,
        status='completed'
    )
    
    context = {
        'conversation': conversation,
        'messages': messages_list,
        'documents': documents,
    }
    
    return render(request, 'chat/conversation_detail.html', context)


@login_required
@require_http_methods(["POST"])
def send_message(request):
    """
    Envía un mensaje y obtiene respuesta del engine RAG.
    Soporta selección dinámica de proveedor LLM (openai/gemini/none).
    Si no hay conversation_id, crea una automáticamente.
    """
    try:
        data = json.loads(request.body)
        conversation_id = data.get('conversation_id')
        message_text = data.get('message')
        requested_engine = data.get('engine', 'faiss')  # faiss o neo4j
        requested_llm_provider = _normalize_llm_provider(data.get('llm_provider'))
        requested_document_id = _normalize_document_id(data.get('document_id'))
        
        if not message_text:
            return JsonResponse({'error': 'Mensaje vacío'}, status=400)
        
        is_new_conversation = False
        
        # Si no hay conversation_id, crear una nueva
        if not conversation_id:
            # Título basado en primeras palabras del mensaje
            words = message_text.split()[:5]
            title = ' '.join(words)
            if len(title) > 40:
                title = title[:37] + '...'
            
            conversation = Conversation.objects.create(
                user=request.user,
                title=title,
                engine_used=requested_engine,
                llm_provider=requested_llm_provider,
                selected_document_id=requested_document_id
            )
            is_new_conversation = True
        else:
            # Obtener conversación existente
            conversation = get_object_or_404(
                Conversation,
                id=conversation_id,
                user=request.user
            )

        # Validar documento para el usuario actual
        valid_document_id = conversation.selected_document_id if conversation_id else requested_document_id
        if valid_document_id:
            doc_exists = Document.objects.filter(
                id=valid_document_id,
                user=request.user,
                status='completed'
            ).exists()
            if not doc_exists:
                valid_document_id = None

        # Para conversaciones existentes, usar siempre configuración persistida.
        if conversation_id:
            engine_choice = conversation.engine_used or requested_engine
            llm_provider = conversation.llm_provider
            document_id = valid_document_id

            # Backfill para conversaciones antiguas sin llm/doc configurado.
            updates = []
            if llm_provider is None and requested_llm_provider is not None:
                conversation.llm_provider = requested_llm_provider
                llm_provider = requested_llm_provider
                updates.append('llm_provider')
            if conversation.selected_document_id is None and requested_document_id is not None:
                doc_exists = Document.objects.filter(
                    id=requested_document_id,
                    user=request.user,
                    status='completed'
                ).exists()
                if doc_exists:
                    conversation.selected_document_id = requested_document_id
                    document_id = requested_document_id
                    updates.append('selected_document_id')
            if updates:
                conversation.save(update_fields=updates)
        else:
            engine_choice = conversation.engine_used
            llm_provider = conversation.llm_provider
            document_id = valid_document_id
        
        # Guardar mensaje del usuario
        user_message = Message.objects.create(
            conversation=conversation,
            role='user',
            content=message_text,
            engine_used=engine_choice
        )
        
        # Obtener historial (últimos 10 mensajes)
        # Nota: Django no soporta indexación negativa, usamos orden descendente y luego revertimos
        recent_messages = list(conversation.messages.all().order_by('-created_at')[:10])
        recent_messages.reverse()  # Revertir para orden cronológico
        history = [
            {
                'role': msg.role,
                'content': msg.content
            }
            for msg in recent_messages
        ]
        
        # Seleccionar engine (pasando el proveedor LLM seleccionado)
        if engine_choice == 'neo4j':
            try:
                engine = Neo4jEngine(document_id=document_id, llm_provider=llm_provider)
            except Neo4jUnavailableError as e:
                return JsonResponse({
                    'success': False,
                    'error': str(e)
                }, status=503)
        else:
            engine = FaissEngine(document_id=document_id, llm_provider=llm_provider)
        
        # Generar respuesta
        response_data = engine.generate_response(
            query=message_text,
            conversation_history=history
        )
        
        # Si el proveedor no vino explícito pero el engine reporta uno efectivo,
        # persistimos ese valor para que el selector lo recuerde entre sesiones.
        if llm_provider is None:
            llm_provider = _normalize_llm_provider(response_data.get('llm_used'))

        # Guardar respuesta del asistente
        assistant_message = Message.objects.create(
            conversation=conversation,
            role='assistant',
            content=response_data['response'],
            engine_used=engine_choice,
            retrieval_time=response_data.get('retrieval_time'),
            generation_time=response_data.get('generation_time'),
            retrieved_chunks_count=response_data.get('retrieved_chunks', 0)
        )
        
        # Actualizar conversación
        conversation.engine_used = engine_choice
        conversation.llm_provider = llm_provider
        conversation.selected_document_id = document_id
        conversation.save(update_fields=['engine_used', 'llm_provider', 'selected_document_id', 'updated_at'])
        
        # Cerrar conexión Neo4j si aplica
        if engine_choice == 'neo4j':
            engine.close()
        
        return JsonResponse({
            'success': True,
            'is_new_conversation': is_new_conversation,
            'conversation_id': conversation.id,
            'conversation_title': conversation.title,
            'conversation': {
                'id': conversation.id,
                'engine': conversation.engine_used,
                'llm_provider': conversation.llm_provider,
                'document_id': conversation.selected_document_id,
            },
            'user_message': {
                'id': user_message.id,
                'content': user_message.content,
                'created_at': user_message.created_at.isoformat()
            },
            'assistant_message': {
                'id': assistant_message.id,
                'content': assistant_message.content,
                'created_at': assistant_message.created_at.isoformat(),
                'engine': engine_choice,
                'llm_used': response_data.get('llm_used'),
                'retrieval_time': response_data.get('retrieval_time'),
                'generation_time': response_data.get('generation_time'),
                'chunks_info': response_data.get('chunks_info', [])
            }
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Formato de solicitud inválido'
        }, status=400)
    except Exception as e:
        logger.exception(f'Error en send_message: {e}')
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
def platform_status(request):
    """
    Endpoint de estado de la plataforma (health check)
    Retorna info sobre Neo4j, documentos, conversaciones, etc.
    """
    from django.conf import settings as s
    
    user = request.user
    
    # Estado Neo4j
    neo4j_status = 'desconectado'
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(s.NEO4J_URI, auth=(s.NEO4J_USER, s.NEO4J_PASSWORD))
        driver.verify_connectivity()
        with driver.session() as session:
            result = session.run('MATCH (n:Chunk) RETURN count(n) AS total').data()
            neo4j_nodes = result[0]['total'] if result else 0
        driver.close()
        neo4j_status = 'conectado'
    except Exception:
        neo4j_nodes = 0
    
    # Estadísticas del usuario
    total_docs = Document.objects.filter(user=user).count()
    completed_docs = Document.objects.filter(user=user, status='completed').count()
    total_conversations = Conversation.objects.filter(user=user, is_active=True).count()
    total_messages = Message.objects.filter(conversation__user=user).count()
    
    # Tiempos promedio
    avg_times = Message.objects.filter(
        conversation__user=user,
        role='assistant'
    ).aggregate(
        avg_retrieval=Avg('retrieval_time'),
        avg_generation=Avg('generation_time')
    )
    
    return JsonResponse({
        'status': 'ok',
        'platform': {
            'llm_provider': getattr(s, 'LLM_PROVIDER', 'none'),
            'embedding_model': getattr(s, 'EMBEDDING_MODEL', 'N/A'),
            'neo4j': neo4j_status,
            'neo4j_nodes': neo4j_nodes,
        },
        'user_stats': {
            'documents': total_docs,
            'documents_completed': completed_docs,
            'conversations': total_conversations,
            'messages': total_messages,
            'avg_retrieval_time': round(avg_times['avg_retrieval'] or 0, 3),
            'avg_generation_time': round(avg_times['avg_generation'] or 0, 3),
        }
    })


@login_required
def get_conversation_messages(request, conversation_id):
    """
    Obtiene los mensajes de una conversación (para cargar vía AJAX)
    """
    conversation = get_object_or_404(
        Conversation,
        id=conversation_id,
        user=request.user
    )
    
    messages_list = conversation.messages.all().order_by('created_at')
    
    return JsonResponse({
        'success': True,
        'conversation': {
            'id': conversation.id,
            'title': conversation.title,
            'engine': conversation.engine_used,
            'llm_provider': conversation.llm_provider,
            'document_id': conversation.selected_document_id
        },
        'messages': [
            {
                'id': msg.id,
                'role': msg.role,
                'content': msg.content,
                'engine_used': msg.engine_used,
                'retrieval_time': msg.retrieval_time,
                'generation_time': msg.generation_time,
                'created_at': msg.created_at.isoformat()
            }
            for msg in messages_list
        ]
    })


@login_required
@require_http_methods(["POST"])
def delete_conversation(request, conversation_id):
    """
    Elimina (marca como inactiva) una conversación
    """
    conversation = get_object_or_404(
        Conversation,
        id=conversation_id,
        user=request.user
    )
    
    conversation.is_active = False
    conversation.save()
    
    # Devolver JSON para peticiones AJAX
    return JsonResponse({'success': True, 'message': 'Conversación eliminada'})


@login_required
def conversation_history(request):
    """
    Lista completa del historial de conversaciones con búsqueda y filtros
    """
    from django.core.paginator import Paginator
    from django.db.models import Subquery, OuterRef
    
    search_query = request.GET.get('q', '')
    engine_filter = request.GET.get('engine', '')
    active_filter = request.GET.get('active', '')
    
    # Query base
    conversations = Conversation.objects.filter(
        user=request.user
    ).annotate(
        message_count=Count('messages')
    )
    
    # Aplicar filtros
    if search_query:
        conversations = conversations.filter(
            Q(title__icontains=search_query) |
            Q(messages__content__icontains=search_query)
        ).distinct()
    
    if engine_filter:
        conversations = conversations.filter(engine_used=engine_filter)
    
    if active_filter:
        is_active = active_filter == 'true'
        conversations = conversations.filter(is_active=is_active)
    
    # Agregar último mensaje para preview
    last_messages = Message.objects.filter(
        conversation=OuterRef('pk')
    ).order_by('-created_at').values('content')[:1]
    
    conversations = conversations.annotate(
        last_message=Subquery(last_messages)
    )
    
    conversations = conversations.order_by('-updated_at')
    
    # Estadísticas
    all_conversations = Conversation.objects.filter(user=request.user)
    total_conversations = all_conversations.count()
    faiss_count = all_conversations.filter(engine_used='faiss').count()
    neo4j_count = all_conversations.filter(engine_used='neo4j').count()
    active_count = all_conversations.filter(is_active=True).count()
    
    # Paginación
    paginator = Paginator(conversations, 10)  # 10 conversaciones por página
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'total_conversations': total_conversations,
        'faiss_count': faiss_count,
        'neo4j_count': neo4j_count,
        'active_count': active_count
    }
    
    return render(request, 'chat/conversation_history.html', context)
