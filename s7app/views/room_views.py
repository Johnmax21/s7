"""
s7app/views/room_views.py — Room lifecycle: lobby, create, join, waiting,
                             exit, and spectator/watch views.
"""
import random
import string

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from ..game_cache import delete_game_state, get_game_state, save_game_state
from ..models import DeckCard, GameRoom, PlayerCard, UserDeck


# ─── helpers ────────────────────────────────────────────────────────────────

def _make_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase, k=length))


def _my_role(request, room):
    """Returns 'player1', 'player2', or None if not in this room."""
    if request.user == room.player1:
        return 'player1'
    if request.user == room.player2:
        return 'player2'
    return None


def _opponent_role(my_role):
    return 'player2' if my_role == 'player1' else 'player1'


def _get_player(room, role):
    return room.player1 if role == 'player1' else room.player2


def _notify(code, payload):
    """Send a WebSocket group message. Silently ignores failures."""
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        async_to_sync(get_channel_layer().group_send)(f"s7app_{code}", payload)
    except Exception as exc:
        print(f"WebSocket notify failed: {exc}")


# ─── lobby ──────────────────────────────────────────────────────────────────

@login_required
def lobby(request):
    active_deck = UserDeck.objects.filter(
        user=request.user, is_active=True
    ).first()

    has_enough_cards = False
    if active_deck:
        main_card_count = DeckCard.objects.filter(deck=active_deck).count()
        has_enough_cards = main_card_count >= 7

    return render(request, 'lobby.html', {
        'active_deck':      active_deck,
        'has_enough_cards': has_enough_cards,
    })


# ─── create_room ────────────────────────────────────────────────────────────

@login_required
def create_room(request):
    active_deck = UserDeck.objects.filter(
        user=request.user, is_active=True
    ).first()
    if not active_deck:
        return redirect('lobby')

    if DeckCard.objects.filter(deck=active_deck).count() < 7:
        return redirect('lobby')

    if request.method == 'POST':
        code = _make_code()
        while GameRoom.objects.filter(code=code).exists():
            code = _make_code()
        room = GameRoom.objects.create(code=code, player1=request.user, state={})
        room.player1_deck = active_deck
        room.save()
        return redirect('waiting_room', code=room.code)

    return redirect('lobby')


# ─── join_room ──────────────────────────────────────────────────────────────

@login_required
def join_room(request):
    active_deck = UserDeck.objects.filter(
        user=request.user, is_active=True
    ).first()
    if not active_deck:
        return redirect('lobby')

    if DeckCard.objects.filter(deck=active_deck).count() < 7:
        return redirect('lobby')

    if request.method == 'POST':
        code = request.POST.get('code', '').strip().upper()
        try:
            room = GameRoom.objects.get(code=code)
        except GameRoom.DoesNotExist:
            return render(request, 'lobby.html', {
                'error':            f'Room "{code}" not found.',
                'active_deck':      active_deck,
                'has_enough_cards': True,
            })

        if request.user == room.player1:
            return redirect('waiting_room', code=room.code)

        if room.player2 and room.player2 != request.user:
            return render(request, 'lobby.html', {
                'error':            'Room is already full.',
                'active_deck':      active_deck,
                'has_enough_cards': True,
            })

        if not room.player2:
            room.player2      = request.user
            room.player2_deck = active_deck
            room.save()

        _notify(code, {
            "type":     "player_joined",
            "username": request.user.username,
            "action":   "redirect_toss",
        })
        return redirect('waiting_room', code=room.code)

    return redirect('lobby')


# ─── waiting_room ───────────────────────────────────────────────────────────

@login_required
def waiting_room(request, code):
    room = get_object_or_404(GameRoom, code=code)
    if room.player2 and request.method == 'POST':
        return redirect('mp_toss', code=room.code)
    return render(request, 'waiting_room.html', {'room': room})


# ─── exit_match ─────────────────────────────────────────────────────────────

@login_required
def exit_match(request, code):
    if request.method != 'POST':
        return redirect('mp_game', code=code)

    room = get_object_or_404(GameRoom, code=code)
    my_role = _my_role(request, room)
    if my_role is None:
        return redirect('lobby')

    state = get_game_state(code)

    # ── NEW: no real match state means there's nothing to exit from ──
    if not state:
        return redirect('mp_game', code=code)

    if state.get('game_over'):
        return redirect('mp_result', code=code)

    opp_role = _opponent_role(my_role)
    state['game_over'] = True
    state['winner']    = opp_role
    state['exit_by']   = my_role

    save_game_state(room.code, state, save_to_db=True)
    delete_game_state(room.code)

    _notify(code, {
        "type":      "player_exit",
        "message":   f"{request.user.username} has exited the match.\nYou win by default! 🎉",
        "exited_by": my_role,
        "winner":    opp_role,
        "game_over": True,
    })
    return redirect('mp_result', code=code)


# ─── watch views ────────────────────────────────────────────────────────────

@login_required
def watch_matches(request):
    live_matches      = GameRoom.objects.filter(status='live')
    completed_matches = GameRoom.objects.filter(status='completed').order_by('-created_at')
    return render(request, 'watch_matches.html', {
        'live_matches':      live_matches,
        'completed_matches': completed_matches,
    })


@login_required
def watch_match_detail(request, code):
    room  = get_object_or_404(GameRoom, code=code)
    state = get_game_state(code)

    current_innings = state.get('innings', 1)
    round_number    = state.get('round_number', 1)
    batting_first   = state.get('batting_first', 'player1')

    batting_team = batting_first if current_innings == 1 else (
        'player2' if batting_first == 'player1' else 'player1'
    )
    bowling_team = 'player2' if batting_team == 'player1' else 'player1'

    # ── Build innings 1 timeline ────────────────────────────────────────────
    innings1_rounds = []
    bowling_first   = 'player2' if batting_first == 'player1' else 'player1'
    for r in range(1, 8):
        batter_id = state.get(f'{batting_first}_played_round_1_{r}')
        bowler_id = state.get(f'{bowling_first}_played_round_1_{r}')
        if batter_id and bowler_id:
            try:
                bc  = PlayerCard.objects.get(id=batter_id)
                bwc = PlayerCard.objects.get(id=bowler_id)
                innings1_rounds.append({
                    'round':        r,
                    'batter':       bc.name,
                    'batter_image': bc.image.url if bc.image else None,
                    'bowler':       bwc.name,
                    'bowler_image': bwc.image.url if bwc.image else None,
                    'runs':         state.get(f'runs_in_round_1_{r}', 0),
                    'wicket':       state.get(f'wicket_in_round_1_{r}', False),
                })
            except PlayerCard.DoesNotExist:
                pass

    # ── Build innings 2 timeline ────────────────────────────────────────────
    innings2_rounds = []
    if current_innings >= 2:
        batting_team_2 = 'player2' if batting_first == 'player1' else 'player1'
        bowling_team_2 = batting_first
        for r in range(1, 8):
            batter_id = state.get(f'{batting_team_2}_played_round_2_{r}')
            bowler_id = state.get(f'{bowling_team_2}_played_round_2_{r}')
            if batter_id and bowler_id:
                try:
                    bc  = PlayerCard.objects.get(id=batter_id)
                    bwc = PlayerCard.objects.get(id=bowler_id)
                    innings2_rounds.append({
                        'round':        r,
                        'batter':       bc.name,
                        'batter_image': bc.image.url if bc.image else None,
                        'bowler':       bwc.name,
                        'bowler_image': bwc.image.url if bwc.image else None,
                        'runs':         state.get(f'runs_in_round_2_{r}', 0),
                        'wicket':       state.get(f'wicket_in_round_2_{r}', False),
                    })
                except PlayerCard.DoesNotExist:
                    pass

    winner       = state.get('winner')
    winner_name  = None
    if winner and winner != 'Tie':
        winner_user = room.player1 if winner == 'player1' else room.player2
        winner_name = winner_user.username if winner_user else 'Unknown'

    scores  = state.get('scores',  {'player1': 0, 'player2': 0})
    wickets = state.get('wickets', {'player1': 0, 'player2': 0})

    return render(request, 'watch_match_detail.html', {
        'room':             room,
        'current_innings':  current_innings,
        'round_number':     round_number,
        'batting_first':    batting_first,
        'batting_team':     batting_team,
        'bowling_team':     bowling_team,
        'p1_runs':          scores.get('player1', 0),
        'p2_runs':          scores.get('player2', 0),
        'p1_wickets':       wickets.get('player1', 0),
        'p2_wickets':       wickets.get('player2', 0),
        'last_batter':      state.get('last_batter'),
        'last_bowler':      state.get('last_bowler'),
        'innings1_rounds':  innings1_rounds,
        'innings2_rounds':  innings2_rounds,
        'message':          state.get('message', ''),
        'game_over':        state.get('game_over', False),
        'winner':           winner,
        'winner_name':      winner_name,
        'target':           state.get('target'),
        'is_live':          room.status == 'live',
    })
