from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.db.models import Sum
from django.contrib import messages
from django.views.decorators.http import require_http_methods
import os

from rag_platform.documents.models import Document


@login_required
def dashboard(request):
    """
    Dashboard del flujo de analisis de manuscritos.
    Esta seccion solo comparte los PDFs del usuario.
    """
    documents_qs = Document.objects.filter(
        user=request.user,
        file_type='pdf'
    ).order_by('-created_at')

    documents = documents_qs[:50]

    selected_document = None
    requested_document_id = request.GET.get('doc')
    if requested_document_id:
        try:
            requested_document_id = int(requested_document_id)
        except (TypeError, ValueError):
            requested_document_id = None

    if requested_document_id:
        selected_document = documents.filter(id=requested_document_id).first()

    if selected_document is None and documents:
        selected_document = documents[0]

    total_size_bytes = documents_qs.aggregate(total=Sum('file_size')).get('total') or 0
    latest_document = documents_qs.first()

    context = {
        'documents': documents,
        'selected_document': selected_document,
        'total_documents': documents_qs.count(),
        'total_size_mb': round(total_size_bytes / (1024 * 1024), 2),
        'latest_document': latest_document,
    }
    return render(request, 'manuscript/dashboard.html', context)


@login_required
@require_http_methods(["GET", "POST"])
def upload_pdf(request):
    """
    Subida de PDFs para manuscrito.
    Solo almacena el archivo y metadata basica, sin procesos RAG.
    """
    if request.method == 'POST':
        uploaded_file = request.FILES.get('file')

        if not uploaded_file:
            messages.error(request, 'No se selecciono ningun archivo.')
            return redirect('manuscript:upload')

        file_ext = os.path.splitext(uploaded_file.name)[1].lower()
        if file_ext != '.pdf':
            messages.error(request, 'Solo se permiten archivos PDF en esta seccion.')
            return redirect('manuscript:upload')

        if uploaded_file.size > 50 * 1024 * 1024:
            messages.error(request, 'El archivo supera el limite de 50MB.')
            return redirect('manuscript:upload')

        Document.objects.create(
            user=request.user,
            title=os.path.splitext(uploaded_file.name)[0],
            file=uploaded_file,
            file_type='pdf',
            file_size=uploaded_file.size,
            status='completed',
            indexed_in_faiss=False,
            indexed_in_neo4j=False,
            total_chunks=0,
        )

        messages.success(request, 'PDF almacenado correctamente.')
        return redirect('manuscript:dashboard')

    return render(request, 'manuscript/upload.html')
