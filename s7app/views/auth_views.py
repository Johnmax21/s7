"""
s7app/views/auth_views.py — Registration, login, logout, landing page.
"""
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import (
    login as auth_login,
    logout as auth_logout,
    authenticate,
)
from django.shortcuts import render, redirect
from django.contrib import messages


def register(request):
    if request.user.is_authenticated:
        return redirect('my_decks')

    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            return redirect('my_decks')
    else:
        form = UserCreationForm()

    return render(request, 'register.html', {'form': form})


def login(request):
    if request.user.is_authenticated:
        return redirect('my_decks')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user:
            auth_login(request, user)
            return redirect(request.POST.get('next') or 'my_decks')
        else:
            messages.error(request, 'Invalid username or password.')

    return render(request, 'login.html')


def logout_view(request):
    auth_logout(request)
    return redirect('landing')


def landing(request):
    return render(request, 'landing.html')

def how_to_play(request):
    return render(request, 'how_to_play.html')
