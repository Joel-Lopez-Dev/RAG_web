from django.urls import path
from . import views

app_name = 'chat'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('conversation/create/', views.create_conversation, name='create_conversation'),
    path('conversation/<int:conversation_id>/', views.conversation_detail, name='conversation_detail'),
    path('conversation/<int:conversation_id>/messages/', views.get_conversation_messages, name='conversation_messages'),
    path('conversation/<int:conversation_id>/delete/', views.delete_conversation, name='delete_conversation'),
    path('message/send/', views.send_message, name='send_message'),
    path('history/', views.conversation_history, name='history'),
    path('status/', views.platform_status, name='platform_status'),
]
