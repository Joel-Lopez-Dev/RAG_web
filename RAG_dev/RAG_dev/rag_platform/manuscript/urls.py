from django.urls import path
from . import views

app_name = 'manuscript'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('upload/', views.upload_pdf, name='upload'),
]
