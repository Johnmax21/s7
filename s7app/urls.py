from django.urls import path,include
from .import views

from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from s7app import views as game_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('register/', views.register, name='register'),
    path('login/', views.login, name='login'),
    path('', views.toss_view, name='toss_view'),
    path('game/', views.game_start, name='game_start'),
    
    # ── Multiplayer lobby ─────────────────────────────────
    path('lobby/',                         views.lobby,        name='lobby'),
    path('room/create/',             views.create_room,  name='create_room'),
    path('room/join/',               views.join_room,    name='join_room'),
    path('room/<str:code>/waiting/', views.waiting_room, name='waiting_room'),
 
    # ── Toss ──────────────────────────────────────────────
    path('room/<str:code>/toss/',        views.mp_toss,        name='mp_toss'),
    path('room/<str:code>/toss/result/', views.mp_toss_result, name='mp_toss_result'),
 
    # ── Match ─────────────────────────────────────────────
    path('room/<str:code>/game/',   views.mp_game,   name='mp_game'),
    path('room/<str:code>/result/', views.mp_result, name='mp_result'),
]
