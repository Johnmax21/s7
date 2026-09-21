"""
views.py — Backward-compatibility shim.
All view logic has been split into s7app/views/ package:
  auth_views.py   — register, login, logout_view, landing
  deck_views.py   — my_decks, create_deck, build_deck, swap_card, set_active_deck
  room_views.py   — lobby, create_room, join_room, waiting_room, exit_match, watch_*
  toss_views.py   — mp_toss, mp_toss_result
  game_views.py   — mp_game, mp_result
  stats_views.py  — profile, leaderboard
All game-rules logic (scoring math, abilities, boost recalculation) lives in:
  game_engine.py  — pure Python, zero Django imports, fully unit-testable
This file exists only so that urls.py (which does `from .import views; views.X`)
continues to work without modification.
"""
from django.shortcuts import render

# Re-export everything from the views package
from s7app.views.auth_views import register, login, logout_view, landing,how_to_play  # noqa: F401
from s7app.views.deck_views import (                                        # noqa: F401
    my_decks, create_deck, build_deck, swap_card, set_active_deck,
)
from s7app.views.room_views import (                                        # noqa: F401
    lobby, create_room, join_room, waiting_room,
    exit_match, watch_matches, watch_match_detail,
)
from s7app.views.toss_views import mp_toss, mp_toss_result                  # noqa: F401
from s7app.views.game_views import mp_game, mp_result                       # noqa: F401
from s7app.views.stats_views import profile, leaderboard       
def how_to_play(request):
    return render(request, 'how_to_play.html')
             # noqa: F401
