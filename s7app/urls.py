from django.urls import path,include
from .import views

from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from s7app import views as game_views

urlpatterns = [
    path('landing/', views.landing, name='landing'),
    path('register/', views.register, name='register'),
    path('login/', views.login, name='login'),
    path('', views.toss_view, name='toss_view'),
    path('game/', views.game_start, name='game_start'),
    path('logout/', views.logout_view, name='logout'),
    
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

path('decks/',                      views.my_decks,       name='my_decks'),
path('decks/create/',               views.create_deck,    name='create_deck'),
path('decks/<int:deck_id>/build/',  views.build_deck,     name='build_deck'),
path('decks/<int:deck_id>/swap/',   views.swap_card,      name='swap_card'),
path('decks/<int:deck_id>/activate/', views.set_active_deck, name='set_active_deck'),
path('room/<str:code>/exit/', views.exit_match, name='exit_match'),
path('watch/', views.watch_matches, name='watch_matches'),
path('watch/<str:code>/', views.watch_match_detail, name='watch_match_detail'),
path('profile/', views.profile, name='profile'),
path("leaderboard/", views.leaderboard, name="leaderboard"),
]
