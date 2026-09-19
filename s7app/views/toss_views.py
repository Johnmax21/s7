"""
s7app/views/toss_views.py — Toss and innings-choice views.
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
import random

from ..game_cache import get_game_state, save_game_state
from ..models import DeckCard, GameRoom, PlayerCard, UserDeck
from .room_views import _my_role, _opponent_role, _get_player, _notify


# ─── toss ────────────────────────────────────────────────────────────────────

@login_required
def mp_toss(request, code):
    room    = get_object_or_404(GameRoom, code=code)
    state   = get_game_state(code)
    my_role = _my_role(request, room)
    if my_role is None:
        return redirect('lobby')

    is_toss_caller = (my_role == 'player1')

    if request.method == 'POST' and request.POST.get('action') == 'call_toss':
        if not is_toss_caller:
            return redirect('mp_toss', code=code)

        choice = request.POST.get('toss_choice', 'heads')
        result = random.choice(['heads', 'tails'])
        toss_winner = 'player1' if choice == result else 'player2'

        state['toss_result'] = result
        state['toss_winner'] = toss_winner
        state['toss_done']   = True
        save_game_state(room.code, state, save_to_db=False)

        _notify(code, {"type": "toss_result", "action": "reload"})
        return redirect('mp_toss_result', code=code)

    if state.get('toss_done'):
        return redirect('mp_toss_result', code=code)

    # Load deck card previews for both players
    p1_deck = UserDeck.objects.filter(user=room.player1, is_active=True).first()
    p2_deck = UserDeck.objects.filter(
        user=room.player2, is_active=True
    ).first() if room.player2 else None

    p1_cards, p2_cards = [], []
    if p1_deck:
        p1_ids   = DeckCard.objects.filter(deck=p1_deck).values_list('player_card_id', flat=True)
        p1_cards = list(PlayerCard.objects.filter(id__in=p1_ids))
    if p2_deck:
        p2_ids   = DeckCard.objects.filter(deck=p2_deck).values_list('player_card_id', flat=True)
        p2_cards = list(PlayerCard.objects.filter(id__in=p2_ids))

    return render(request, 'mp_toss.html', {
        'room':           room,
        'is_toss_caller': is_toss_caller,
        'p1_cards':       p1_cards,
        'p2_cards':       p2_cards,
        'p1_deck':        p1_deck,
        'p2_deck':        p2_deck,
    })


# ─── toss result ─────────────────────────────────────────────────────────────

@login_required
def mp_toss_result(request, code):
    room  = get_object_or_404(GameRoom, code=code)
    state = get_game_state(code)

    if not state.get('toss_done'):
        return redirect('mp_toss', code=code)

    my_role     = _my_role(request, room)
    if my_role is None:
        return redirect('lobby')

    toss_winner      = state.get('toss_winner')
    i_won_toss       = (my_role == toss_winner)
    toss_winner_name = _get_player(room, toss_winner).username

    if request.method == 'POST' and request.POST.get('action') == 'choose_innings':
        if not i_won_toss:
            return redirect('mp_toss_result', code=code)

        batting_first = request.POST.get('batting_first')
        state.update({
            'batting_first':   batting_first,
            'innings':         1,
            'round_number':    1,
            'scores':          {'player1': 0, 'player2': 0},
            'wickets':         {'player1': 0, 'player2': 0},
            'used_by_player1': [],
            'used_by_player2': [],
            'message':         '',
            'innings_chosen':  True,
        })
        save_game_state(room.code, state, save_to_db=False)

        _notify(code, {"type": "innings_chosen", "action": "redirect_game"})
        return redirect('mp_game', code=code)

    if state.get('innings_chosen'):
        return redirect('mp_game', code=code)

    return render(request, 'mp_toss_result.html', {
        'room':           room,
        'toss_result':    state.get('toss_result'),
        'i_won_toss':     i_won_toss,
        'toss_winner_name': toss_winner_name,
        'my_role':        my_role,
        'opponent_role':  _opponent_role(my_role),
    })
