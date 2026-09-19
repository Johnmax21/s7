"""
s7app/views/__init__.py

Re-exports all view functions so that the existing urls.py pattern:

    from .import views
    views.lobby, views.mp_game, etc.

continues to work without any changes to urls.py.
"""
from .auth_views import register, login, logout_view, landing  # noqa: F401
from .deck_views import (                                        # noqa: F401
    my_decks, create_deck, build_deck, swap_card, set_active_deck,
)
from .room_views import (                                        # noqa: F401
    lobby, create_room, join_room, waiting_room,
    exit_match, watch_matches, watch_match_detail,
)
from .toss_views import mp_toss, mp_toss_result                  # noqa: F401
from .game_views import mp_game, mp_result                       # noqa: F401
from .stats_views import profile, leaderboard                    # noqa: F401
