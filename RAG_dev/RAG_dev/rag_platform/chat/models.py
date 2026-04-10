from django.db import models
from django.conf import settings


class Conversation(models.Model):
    """
    Conversación de chat con historial persistente
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='conversations',
        verbose_name='Usuario'
    )
    title = models.CharField(max_length=255, verbose_name='Título')
    engine_used = models.CharField(
        max_length=10,
        choices=[('faiss', 'FAISS'), ('neo4j', 'Neo4j')],
        default='faiss',
        verbose_name='Motor utilizado'
    )
    llm_provider = models.CharField(
        max_length=20,
        choices=[('openai', 'OpenAI'), ('gemini', 'Gemini'), ('none', 'Sin IA')],
        null=True,
        blank=True,
        verbose_name='Proveedor LLM'
    )
    selected_document_id = models.IntegerField(
        null=True,
        blank=True,
        verbose_name='ID del documento seleccionado'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de creación')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Última actualización')
    is_active = models.BooleanField(default=True, verbose_name='Activa')
    
    class Meta:
        verbose_name = 'Conversación'
        verbose_name_plural = 'Conversaciones'
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['-updated_at']),
            models.Index(fields=['user', '-updated_at']),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.user.username}"
    
    def get_messages_count(self):
        return self.messages.count()


class Message(models.Model):
    """
    Mensaje individual dentro de una conversación
    """
    ROLE_CHOICES = [
        ('user', 'Usuario'),
        ('assistant', 'Asistente'),
        ('system', 'Sistema'),
    ]
    
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='messages',
        verbose_name='Conversación'
    )
    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
        verbose_name='Rol'
    )
    content = models.TextField(verbose_name='Contenido')
    engine_used = models.CharField(
        max_length=10,
        choices=[('faiss', 'FAISS'), ('neo4j', 'Neo4j')],
        null=True,
        blank=True,
        verbose_name='Motor utilizado'
    )
    tokens_used = models.IntegerField(null=True, blank=True, verbose_name='Tokens usados')
    retrieval_time = models.FloatField(null=True, blank=True, verbose_name='Tiempo de recuperación (s)')
    generation_time = models.FloatField(null=True, blank=True, verbose_name='Tiempo de generación (s)')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de creación')
    
    # Metadata de recuperación
    retrieved_chunks_count = models.IntegerField(
        null=True,
        blank=True,
        verbose_name='Cantidad de chunks recuperados'
    )
    
    class Meta:
        verbose_name = 'Mensaje'
        verbose_name_plural = 'Mensajes'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.role}: {self.content[:50]}..."
