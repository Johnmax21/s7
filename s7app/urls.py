from django.urls import path,include

from s7app.views import tournament_views
from s7app.views import season_views
from .import views

from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from s7app import views as game_views

urlpatterns = [
    # ── Auth ──────────────────────────────────────────────
    path('', views.landing, name='landing'),
    path('register/', views.register, name='register'),
    path('login/', views.login, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # ── Multiplayer lobby ─────────────────────────────────
    path('lobby/',                         views.lobby,        name='lobby'),
    path('room/create/',             views.create_room,  name='create_room'),
    path('room/join/',views.join_room,name='join_room'),
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
path('tournaments/', tournament_views.tournament_hub, name='tournament_hub'),
path('base/', tournament_views.base, name='tournament_base'),
    path('tournaments/create/', tournament_views.create_tournament, name='create_tournament'),
    path('tournaments/<int:tournament_id>/', tournament_views.tournament_detail, name='tournament_detail'),
    path('tournaments/<int:tournament_id>/join/', tournament_views.join_tournament, name='join_tournament'),
    path('tournaments/<int:tournament_id>/seed/', tournament_views.set_seeds, name='set_seeds'),
    path('tournaments/<int:tournament_id>/start/', tournament_views.start_tournament, name='start_tournament'),
     path('seasons/', season_views.season_list, name='season_list'),
    path('seasons/create/', season_views.create_season, name='create_season'),
]
