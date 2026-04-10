from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from .models import User


def landing(request):
    """
    Landing page principal con información del sistema RAG
    """
    if request.user.is_authenticated:
        return redirect('chat:dashboard')
    return render(request, 'accounts/landing.html')


@require_http_methods(["GET", "POST"])
def login_view(request):
    """
    Vista de login con validación
    """
    if request.user.is_authenticated:
        return redirect('chat:dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            messages.success(request, f'¡Bienvenido de nuevo, {user.username}!')
            return redirect('chat:dashboard')
        else:
            messages.error(request, 'Usuario o contraseña incorrectos.')
    
    return render(request, 'accounts/login.html')


@require_http_methods(["GET", "POST"])
def register_view(request):
    """
    Vista de registro de nuevos usuarios
    """
    if request.user.is_authenticated:
        return redirect('chat:dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')
        
        # Validaciones
        if User.objects.filter(username=username).exists():
            messages.error(request, 'El nombre de usuario ya existe.')
            return render(request, 'accounts/register.html')
        
        if User.objects.filter(email=email).exists():
            messages.error(request, 'El email ya está registrado.')
            return render(request, 'accounts/register.html')
        
        if password != password_confirm:
            messages.error(request, 'Las contraseñas no coinciden.')
            return render(request, 'accounts/register.html')
        
        if len(password) < 8:
            messages.error(request, 'La contraseña debe tener al menos 8 caracteres.')
            return render(request, 'accounts/register.html')
        
        # Crear usuario
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )
        
        login(request, user)
        messages.success(request, f'¡Cuenta creada exitosamente! Bienvenido, {username}.')
        return redirect('chat:dashboard')
    
    return render(request, 'accounts/register.html')


@login_required
def logout_view(request):
    """
    Cerrar sesión
    """
    logout(request)
    return redirect('accounts:landing')


@login_required
def profile_view(request):
    """
    Perfil de usuario con configuraciones
    """
    if request.method == 'POST':
        user = request.user
        
        # Actualizar datos
        user.first_name = request.POST.get('first_name', user.first_name)
        user.last_name = request.POST.get('last_name', user.last_name)
        user.email = request.POST.get('email', user.email)
        user.bio = request.POST.get('bio', user.bio)
        user.preferred_engine = request.POST.get('preferred_engine', user.preferred_engine)
        
        # Avatar
        if 'avatar' in request.FILES:
            user.avatar = request.FILES['avatar']
        
        user.save()
        messages.success(request, 'Perfil actualizado exitosamente.')
        return redirect('accounts:profile')
    
    return render(request, 'accounts/profile.html')
