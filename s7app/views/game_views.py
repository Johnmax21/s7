"""
s7app/views/game_views.py — Live game view (mp_game) and result view (mp_result).

Design contract
---------------
This view is intentionally a thin HTTP adapter:
  1. Parse request / authenticate participant
  2. Load state from cache (get_game_state)
  3. Call game_engine functions for any mutations
  4. Persist state (save_game_state)
  5. Send WebSocket notification (_notify)
  6. Render or redirect

All game-rules math lives in game_engine.py.
"""

import time as _time

from django.contrib.auth.decorators import login_required
from django.core.cache import cache as django_cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .. import game_engine
from ..game_cache import delete_game_state, get_game_state, save_game_state
from ..models import DeckCard, GameRoom, PlayerCard, SupportCard, UserDeck
from .room_views import _get_player, _my_role, _notify, _opponent_role

BOOST_WINDOW_SECONDS = game_engine.BOOST_WINDOW_SECONDS


# ─── helpers ────────────────────────────────────────────────────────────────

def _build_context(state, room, my_role, opp_role, opponent_name, opponent_deck_cards):
    """
    Build the full template context for mp_game.html and its partials.
    Reads all values from *state* — never from the outer request scope.
    """
    _innings       = state.get('innings', 1)
    _round_number  = state.get('round_number', 1)
    _batting_first = state.get('batting_first', 'player1')

    _batting_team = _batting_first if _innings == 1 else (
        'player2' if _batting_first == 'player1' else 'player1'
    )

    _my_used       = state.get(f'used_by_{my_role}', [])
    _my_played_key = f'{my_role}_played_round_{_innings}_{_round_number}'
    _opp_played_key = f'{opp_role}_played_round_{_innings}_{_round_number}'
    _i_played      = state.get(_my_played_key) is not None
    _opp_played    = state.get(_opp_played_key) is not None
    _waiting       = _i_played and not _opp_played

    # Available cards for this player
    active_user = room.player1 if my_role == 'player1' else room.player2
    active_deck = UserDeck.objects.filter(user=active_user, is_active=True).first()
    if active_deck:
        deck_card_ids = DeckCard.objects.filter(
            deck=active_deck
        ).values_list('player_card_id', flat=True)
        _available_cards = PlayerCard.objects.filter(
            id__in=deck_card_ids
        ).exclude(id__in=_my_used)
    else:
        _available_cards = PlayerCard.objects.exclude(id__in=_my_used)

    _last_wicket = any(
        state.get(f'wicket_in_round_{_innings}_{r}')
        for r in [_round_number - 1, _round_number - 2] if r >= 1
    )
    _recent_runs = sum(
        state.get(f'runs_in_round_{_innings}_{r}', 0)
        for r in [_round_number - 1, _round_number - 2] if r >= 1
    )
    _opponent_team  = 'player2' if my_role == 'player1' else 'player1'
    _opponent_score = state.get('scores', {}).get(_opponent_team, 0)

    _support_cards  = SupportCard.objects.all()
    _active_support = state.get(f'{my_role}_support')
    if _active_support and _round_number >= _active_support.get('until_round', 0):
        _active_support = None

    _bowling_first = 'player2' if _batting_first == 'player1' else 'player1'

    # ── Build match timeline (one DB query for all cards) ────────────────────
    _all_card_ids = set()
    _i1_pairs, _i2_pairs = [], []

    for r in range(1, _round_number if _innings == 1 else 8):
        batter_id = state.get(f'{_batting_first}_played_round_1_{r}')
        bowler_id = state.get(f'{_bowling_first}_played_round_1_{r}')
        if batter_id and bowler_id:
            _i1_pairs.append((r, batter_id, bowler_id))
            _all_card_ids.update([batter_id, bowler_id])

    if _innings == 2:
        _batting_second = _bowling_first
        _bowling_second = _batting_first
        for r in range(1, _round_number):
            batter_id = state.get(f'{_batting_second}_played_round_2_{r}')
            bowler_id = state.get(f'{_bowling_second}_played_round_2_{r}')
            if batter_id and bowler_id:
                _i2_pairs.append((r, batter_id, bowler_id))
                _all_card_ids.update([batter_id, bowler_id])

    _card_map = {
        c.id: c
        for c in PlayerCard.objects.filter(id__in=_all_card_ids)
    } if _all_card_ids else {}

    def _build_timeline(pairs, inn):
        rows = []
        for r, batter_id, bowler_id in pairs:
            bc  = _card_map.get(batter_id)
            bwc = _card_map.get(bowler_id)
            if bc and bwc:
                rows.append({
                    'round':        r,
                    'batter':       bc.name,
                    'batter_image': bc.image.url if bc.image else None,
                    'bowler':       bwc.name,
                    'bowler_image': bwc.image.url if bwc.image else None,
                    'runs':         state.get(f'runs_in_round_{inn}_{r}', 0),
                    'wicket':       state.get(f'wicket_in_round_{inn}_{r}', False),
                })
        return rows

    _innings1_timeline = _build_timeline(_i1_pairs, 1)
    _innings2_timeline = _build_timeline(_i2_pairs, 2)

    # ── Post-round boost window info ─────────────────────────────────────────
    _boost_round          = _round_number - 1
    _boost_window_open    = state.get(f'boost_window_open_{_innings}_{_boost_round}', False)
    _boost_window_started = state.get(f'boost_window_started_{_innings}_{_boost_round}', 0)
    _boost_elapsed        = _time.time() - _boost_window_started if _boost_window_started else 999
    _boost_window_active  = _boost_window_open and _boost_elapsed <= BOOST_WINDOW_SECONDS
    _boost_seconds_left   = max(0, BOOST_WINDOW_SECONDS - _boost_elapsed) if _boost_window_active else 0

    _my_post_boost_used = state.get(f'{my_role}_post_boost_used', False)
    _boost_clicks       = state.get(f'round_boost_clicks_{_innings}_{_boost_round}', [])
    _i_already_clicked  = my_role in _boost_clicks

    _snap = state.get(f'round_snapshot_{_innings}_{_boost_round}', {})
    _my_ability_triggered_last_round = (
        (_snap.get('batter_ability_triggered') and _snap.get('batter_role') == my_role)
        or (_snap.get('bowler_ability_triggered') and _snap.get('bowler_role') == my_role)
    )
    _can_use_post_boost = (
        _boost_window_active
        and not _my_post_boost_used
        and not _i_already_clicked
        and not _my_ability_triggered_last_round
    )

    opp_post_boost_used  = state.get(f'{opp_role}_post_boost_used', False)
    opp_already_clicked  = opp_role in _boost_clicks
    opp_ability_triggered = (
        (_snap.get('batter_ability_triggered') and _snap.get('batter_role') == opp_role)
        or (_snap.get('bowler_ability_triggered') and _snap.get('bowler_role') == opp_role)
    )
    opp_can_use_post_boost = (
        _boost_window_active
        and not opp_post_boost_used
        and not opp_already_clicked
        and not opp_ability_triggered
    )

    transition_wait = (
        (state.get("innings_transition") or state.get("game_over_pending"))
        and _boost_window_active
        and (_can_use_post_boost or opp_can_use_post_boost)
    )

    # ── Per-player innings-2 / result viewing flags ──────────────────────────
    _my_viewing_innings2       = state.get(f'{my_role}_viewing_innings2', False)
    _shared_innings            = state.get('innings', 1)
    _show_transition_to_me     = (_shared_innings == 2 and not _my_viewing_innings2)
    _my_transition_target      = state.get('target') if _show_transition_to_me else None

    _my_viewing_result         = state.get(f'{my_role}_viewing_result', False)
    _shared_game_over          = state.get('game_over', False)
    _shared_game_over_pending  = state.get('game_over_pending', False)
    _show_result_screen_to_me  = (
        (_shared_game_over or _shared_game_over_pending) and not _my_viewing_result
    )

    ctx = {
        'room':                 room,
        'innings':              _innings,
        'round_number':         _round_number,
        'batting_team':         _batting_team,
        'my_role':              my_role,
        'opponent_name':        opponent_name,
        'available_cards':      _available_cards,
        'waiting_for_opponent': _waiting,
        'message':              state.get('message', ''),
        'p1_runs':              state.get('scores', {}).get('player1', 0),
        'p2_runs':              state.get('scores', {}).get('player2', 0),
        'p1_wickets':           state.get('wickets', {}).get('player1', 0),
        'p2_wickets':           state.get('wickets', {}).get('player2', 0),
        'last_batter':          state.get('last_batter'),
        'last_bowler':          state.get('last_bowler'),
        'support_cards':        _support_cards,
        'active_support':       _active_support,
        'support_used':         state.get(f'{my_role}_support_used', False),
        'innings_transition':   (
            {'target': _my_transition_target} if _show_transition_to_me
            else state.get('innings_transition')
        ),
        'game_over_pending':          _show_result_screen_to_me,
        'boost_used':                 state.get(f'{my_role}_boost_used', False),
        'boost_active':               state.get(f'{my_role}_boost_active', False),
        'last_wicket_in_round':       _last_wicket,
        'recent_runs_high':           _recent_runs >= 30,
        'opponent_score_high':        _opponent_score >= 60,
        'opponent_deck_cards':        opponent_deck_cards,
        'innings1_timeline':          _innings1_timeline,
        'innings2_timeline':          _innings2_timeline,
        'boost_window_active':        _boost_window_active,
        'boost_seconds_left':         int(_boost_seconds_left),
        'can_use_post_boost':         _can_use_post_boost,
        'my_post_boost_used':         _my_post_boost_used,
        'boost_round_for_form':       _boost_round,
        'opponent_can_use_post_boost': opp_can_use_post_boost,
        'must_wait_for_boost':        transition_wait,
    }

    if _innings == 2:
        chasing_runs          = state.get('scores', {}).get(_batting_team, 0)
        target_val            = state.get('target', 0)
        ctx['target']         = target_val
        ctx['runs_needed']    = max(0, target_val - chasing_runs)
        ctx['rounds_remaining'] = max(0, 8 - _round_number)

    return ctx


# ─── mp_game ────────────────────────────────────────────────────────────────

@login_required
def mp_game(request, code):
    room = get_object_or_404(GameRoom, code=code)
    if room.status in ('waiting', None):
        room.status = 'live'
        room.save()

    my_role = _my_role(request, room)
    if my_role is None:
        return redirect('lobby')

    opp_role      = _opponent_role(my_role)
    opponent_name = _get_player(room, opp_role).username

    state = get_game_state(code)

    if state.get('game_over') and state.get(f'{my_role}_viewing_result', False):
        return redirect('mp_result', code=code)

    innings       = state.get('innings', 1)
    round_number  = state.get('round_number', 1)
    batting_first = state.get('batting_first', 'player1')
    batting_team  = batting_first if innings == 1 else (
        'player2' if batting_first == 'player1' else 'player1'
    )

    i_played   = state.get(f'{my_role}_played_round_{innings}_{round_number}') is not None

    # Opponent deck for display purposes
    opp_user = room.player2 if my_role == 'player1' else room.player1
    opp_deck = UserDeck.objects.filter(user=opp_user, is_active=True).first()
    opponent_deck_cards = []
    if opp_deck:
        opp_deck_ids = DeckCard.objects.filter(deck=opp_deck).values_list('player_card_id', flat=True)
        opponent_deck_cards = list(PlayerCard.objects.filter(id__in=opp_deck_ids))

    # ══════════════════════════════════════════════════════════════
    # POST handlers
    # ══════════════════════════════════════════════════════════════
    if request.method == 'POST':
        action = request.POST.get('action')

        # ── cancel_boost ─────────────────────────────────────────
        if action == 'cancel_boost':
            if state.get(f'{my_role}_boost_active') and not i_played:
                state[f'{my_role}_boost_active'] = False
                state[f'{my_role}_boost_used']   = False
                save_game_state(code, state, save_to_db=False)
            if request.headers.get('HX-Request'):
                return render(request, 'partials/status_bar.html',
                              _build_context(get_game_state(code), room, my_role, opp_role,
                                             opponent_name, opponent_deck_cards))
            return redirect('mp_game', code=code)

        # ── cancel_support ───────────────────────────────────────
        if action == 'cancel_support':
            if state.get(f'{my_role}_support_used') and not i_played:
                state[f'{my_role}_support_used'] = False
                state[f'{my_role}_support']      = None
                save_game_state(code, state, save_to_db=False)
            if request.headers.get('HX-Request'):
                return render(request, 'partials/status_bar.html',
                              _build_context(get_game_state(code), room, my_role, opp_role,
                                             opponent_name, opponent_deck_cards))
            return redirect('mp_game', code=code)

        # ── use_boost ────────────────────────────────────────────
        if action == 'use_boost':
            if not state.get(f'{my_role}_boost_used'):
                state[f'{my_role}_boost_used']  = True
                state[f'{my_role}_boost_active'] = True
                save_game_state(code, state, save_to_db=False)
            if request.headers.get('HX-Request'):
                return render(request, 'partials/status_bar.html',
                              _build_context(get_game_state(code), room, my_role, opp_role,
                                             opponent_name, opponent_deck_cards))
            return redirect('mp_game', code=code)

        # ── use_support ──────────────────────────────────────────
        if action == 'use_support':
            if not state.get(f'{my_role}_support_used'):
                support_type = request.POST.get('support_type')
                state[f'{my_role}_support'] = {
                    'type':        support_type,
                    'from_round':  round_number,
                    'until_round': round_number + 3,
                }
                state[f'{my_role}_support_used'] = True
                save_game_state(code, state, save_to_db=False)
            if request.headers.get('HX-Request'):
                return render(request, 'partials/status_bar.html',
                              _build_context(get_game_state(code), room, my_role, opp_role,
                                             opponent_name, opponent_deck_cards))
            return redirect('mp_game', code=code)

        # ── continue_innings ─────────────────────────────────────
        if action == 'continue_innings':
            lock_key = f'lock:{code}:transition'
            if not django_cache.add(lock_key, 1, timeout=3):
                if request.headers.get('HX-Request'):
                    return render(request, 'partials/game_panel.html',
                                  _build_context(get_game_state(code), room, my_role, opp_role,
                                                 opponent_name, opponent_deck_cards))
                return redirect('mp_game', code=code)
            try:
                fresh_state = get_game_state(code)
                fresh_state[f'{my_role}_viewing_innings2'] = True

                if fresh_state.get('innings', 1) == 1:
                    transition = fresh_state.get('innings_transition')
                    if transition:
                        fresh_state.update({
                            'target':           transition['target'],
                            'innings':          2,
                            'round_number':     1,
                            'used_by_player1':  [],
                            'used_by_player2':  [],
                            'player1_support':  None,
                            'player2_support':  None,
                            'last_batter':      None,
                            'last_bowler':      None,
                            'message':          '',
                        })
                        fresh_state.pop('innings_transition', None)

                save_game_state(code, fresh_state, save_to_db=True)
                result_state = get_game_state(code)
            finally:
                django_cache.delete(lock_key)

            if request.headers.get('HX-Request'):
                return render(request, 'partials/game_panel.html',
                              _build_context(result_state, room, my_role, opp_role,
                                             opponent_name, opponent_deck_cards))
            return redirect('mp_game', code=code)

        # ── continue_result ──────────────────────────────────────
        if action == 'continue_result':
            lock_key = f'lock:{code}:transition'
            if not django_cache.add(lock_key, 1, timeout=3):
                if request.headers.get('HX-Request'):
                    return render(request, 'partials/game_panel.html',
                                  _build_context(get_game_state(code), room, my_role, opp_role,
                                                 opponent_name, opponent_deck_cards))
                return redirect('mp_game', code=code)
            try:
                fresh_state = get_game_state(code)
                fresh_state[f'{my_role}_viewing_result'] = True
                if fresh_state.get('game_over_pending'):
                    fresh_state['game_over'] = True
                    fresh_state.pop('game_over_pending', None)
                save_game_state(code, fresh_state, save_to_db=True)
            finally:
                django_cache.delete(lock_key)
            return redirect('mp_result', code=code)

        # ── use_post_round_boost ─────────────────────────────────
        if action == 'use_post_round_boost':
            target_innings = int(request.POST.get('boost_innings', innings))
            target_round   = int(request.POST.get('boost_round', round_number - 1))
            lock_key       = f'lock:{code}:boost_{target_innings}_{target_round}'

            if not django_cache.add(lock_key, 1, timeout=3):
                if request.headers.get('HX-Request'):
                    return render(request, 'partials/_boost_response.html',
                                  _build_context(get_game_state(code), room, my_role, opp_role,
                                                 opponent_name, opponent_deck_cards))
                return redirect('mp_game', code=code)

            try:
                fresh_state    = get_game_state(code)
                window_open    = fresh_state.get(f'boost_window_open_{target_innings}_{target_round}', False)
                window_started = fresh_state.get(f'boost_window_started_{target_innings}_{target_round}', 0)
                elapsed        = _time.time() - window_started
                already_used   = fresh_state.get(f'{my_role}_post_boost_used', False)

                snap = fresh_state.get(f'round_snapshot_{target_innings}_{target_round}', {})
                my_own_ability_triggered = (
                    (snap.get('batter_ability_triggered') and snap.get('batter_role') == my_role)
                    or (snap.get('bowler_ability_triggered') and snap.get('bowler_role') == my_role)
                )

                can_use = (
                    window_open and elapsed <= BOOST_WINDOW_SECONDS
                    and not already_used
                    and not my_own_ability_triggered
                )

                print(f"=== BOOST CLICK by {my_role} ===")
                print(f"target_innings={target_innings}, target_round={target_round}")
                print(f"window_open={window_open}, elapsed={elapsed:.2f}, already_used={already_used}")
                print(f"can_use={can_use}")
                print("==============================")

                if can_use:
                    clicks = fresh_state.get(f'round_boost_clicks_{target_innings}_{target_round}', [])
                    if my_role not in clicks:
                        bonus = 10 if len(clicks) == 0 else 5
                        clicks.append(my_role)
                        fresh_state[f'round_boost_clicks_{target_innings}_{target_round}'] = clicks
                        fresh_state[f'{my_role}_post_boost_used'] = True
                        save_game_state(code, fresh_state, save_to_db=False)

                        print(f"✅ Applying recalculation: role={my_role}, bonus={bonus}")
                        fresh_state = game_engine.recalculate_round_with_boost(
                            fresh_state, target_innings, target_round, my_role, bonus
                        )
                        save_game_state(code, fresh_state, save_to_db=bool(
                            fresh_state.get('game_over') or
                            fresh_state.get('game_over_pending') or
                            fresh_state.get('innings_transition')
                        ))
                        print(f"✅ After recalc: scores={fresh_state.get('scores')}")

                        _notify(code, {
                            "type":    "boost_applied",
                            "round":   target_round,
                            "message": fresh_state.get('message', ''),
                            "action":  "reload",
                        })

                result_state = get_game_state(code)
            finally:
                django_cache.delete(lock_key)

            if request.headers.get('HX-Request'):
                return render(request, 'partials/_boost_response.html',
                              _build_context(result_state, room, my_role, opp_role,
                                             opponent_name, opponent_deck_cards))
            return redirect('mp_game', code=code)

        # ── play_card ────────────────────────────────────────────
        if action == 'play_card':
            lock_key = f'lock:{code}:play_round'
            if not django_cache.add(lock_key, 1, timeout=3):
                if request.headers.get('HX-Request'):
                    return render(request, 'partials/game_panel.html',
                                  _build_context(get_game_state(code), room, my_role, opp_role,
                                                 opponent_name, opponent_deck_cards))
                return redirect('mp_game', code=code)

            try:
                fresh_state   = get_game_state(code)
                fresh_innings = fresh_state.get('innings', 1)
                fresh_round   = fresh_state.get('round_number', 1)
                fresh_key     = f'{my_role}_played_round_{fresh_innings}_{fresh_round}'

                # Idempotency guard — already played this round
                if fresh_state.get(fresh_key) is not None:
                    if request.headers.get('HX-Request'):
                        return render(request, 'partials/game_panel.html',
                                      _build_context(fresh_state, room, my_role, opp_role,
                                                     opponent_name, opponent_deck_cards))
                    return redirect('mp_game', code=code)

                selected_id = int(request.POST.get('selected_card_id'))
                fresh_state[fresh_key] = selected_id
                my_used_list = fresh_state.get(f'used_by_{my_role}', [])
                if selected_id not in my_used_list:
                    my_used_list.append(selected_id)
                fresh_state[f'used_by_{my_role}'] = my_used_list
                save_game_state(code, fresh_state, save_to_db=False)

                _notify(code, {"type": "card_played", "by_role": my_role, "action": "reload_if_waiting"})

                # Check if opponent already played — if so, resolve the round
                after_save    = get_game_state(code)
                opp_fresh_key = f'{opp_role}_played_round_{fresh_innings}_{fresh_round}'

                if after_save.get(opp_fresh_key) is not None:
                    # Load both cards and delegate to engine
                    fresh_batting_first = after_save.get('batting_first', 'player1')
                    fresh_batting_team  = fresh_batting_first if fresh_innings == 1 else (
                        'player2' if fresh_batting_first == 'player1' else 'player1'
                    )
                    fresh_bowling_team  = 'player2' if fresh_batting_team == 'player1' else 'player1'

                    batter_card_id = after_save.get(
                        f'{fresh_batting_team}_played_round_{fresh_innings}_{fresh_round}'
                    )
                    bowler_card_id = after_save.get(
                        f'{fresh_bowling_team}_played_round_{fresh_innings}_{fresh_round}'
                    )
                    batter_card = PlayerCard.objects.get(id=batter_card_id)
                    bowler_card = PlayerCard.objects.get(id=bowler_card_id)

                    updated_state = game_engine.resolve_round(
                        after_save, fresh_innings, fresh_round,
                        fresh_batting_team, fresh_batting_first,
                        batter_card, bowler_card
                    )

                    is_game_over        = updated_state.get('game_over', False)
                    is_game_over_pending = updated_state.get('game_over_pending', False)
                    is_innings_transition = bool(updated_state.get('innings_transition'))
                    should_save_db = is_game_over or is_game_over_pending or is_innings_transition

                    save_game_state(code, updated_state, save_to_db=should_save_db)

                    # WebSocket notification
                    if is_game_over:
                        _notify(code, {"type": "game_over", "action": "redirect_result"})
                    elif is_innings_transition or is_game_over_pending:
                        _notify(code, {"type": "innings_over", "action": "reload"})
                    else:
                        _notify(code, {
                            "type":    "round_result",
                            "round":   fresh_round,
                            "message": updated_state.get('message', ''),
                            "action":  "reload",
                        })

                    if is_game_over:
                        return redirect('mp_result', code=code)

                if request.headers.get('HX-Request'):
                    return render(request, 'partials/game_panel.html',
                                  _build_context(get_game_state(code), room, my_role, opp_role,
                                                 opponent_name, opponent_deck_cards))
                return redirect('mp_game', code=code)

            finally:
                django_cache.delete(lock_key)

    # ══════════════════════════════════════════════════════════════
    # GET handlers
    # ══════════════════════════════════════════════════════════════
    state   = get_game_state(code)
    context = _build_context(state, room, my_role, opp_role, opponent_name, opponent_deck_cards)

    partial = request.GET.get('partial')

    if partial == 'round_check':
        fresh_state = get_game_state(code)
        my_viewing_innings2 = fresh_state.get(f'{my_role}_viewing_innings2', False)
        my_viewing_result   = fresh_state.get(f'{my_role}_viewing_result', False)
        shared_innings      = fresh_state.get('innings', 1)
        shared_game_over    = fresh_state.get('game_over', False)
        shared_pending      = fresh_state.get('game_over_pending', False)

        return JsonResponse({
            'round_number':     fresh_state.get('round_number', 1),
            'innings':          shared_innings,
            'game_over':        bool(shared_game_over and my_viewing_result),
            'boost_counter':    fresh_state.get('boost_update_counter', 0),
            'needs_transition': (
                (shared_innings == 2 and not my_viewing_innings2)
                or ((shared_game_over or shared_pending) and not my_viewing_result)
            ),
        })

    if partial == 'scoreboard':
        return render(request, 'partials/scoreboard.html', context)
    if partial == 'game_panel':
        return render(request, 'partials/game_panel.html', context)
    if partial == 'last_round':
        return render(request, 'partials/last_round_result.html', context)
    if partial == 'status_bar':
        return render(request, 'partials/status_bar.html', context)
    if partial == 'timeline':
        return render(request, 'partials/timeline_content.html', context)

    return render(request, 'mp_game.html', context)


# ─── mp_result ───────────────────────────────────────────────────────────────

def mp_result(request, code):
    room = get_object_or_404(GameRoom, code=code)

    state = get_game_state(code)
    loaded_from_db = False
    if not state or 'winner' not in state:
        state = room.state or {}
        loaded_from_db = True

    # ── NEW: if there's genuinely no result yet, this isn't a real finished match ──
    if 'winner' not in state:
        return redirect('mp_game', code=code)

    my_role = _my_role(request, room)
    if my_role is None:
        return redirect('lobby')

    if not loaded_from_db:
        room.state  = state
        room.status = 'completed'
        room.save()
    else:
        room.status = 'completed'
        room.save(update_fields=['status'])

    scores        = state.get('scores',  {'player1': 0, 'player2': 0})
    wickets       = state.get('wickets', {'player1': 0, 'player2': 0})
    batting_first = state.get('batting_first', 'player1')
    chasing_team  = 'player2' if batting_first == 'player1' else 'player1'

    p1_runs    = scores.get('player1', 0)
    p2_runs    = scores.get('player2', 0)
    p1_wickets = wickets.get('player1', 0)
    p2_wickets = wickets.get('player2', 0)
    target     = state.get('target', 0)

    winner_role = state.get('winner')
    if not winner_role:
        chasing_score = scores.get(chasing_team, 0)
        first_score   = scores.get(batting_first, 0)
        if chasing_score >= target:
            winner_role = chasing_team
        elif chasing_score == first_score:
            winner_role = 'Tie'
        else:
            winner_role = batting_first

    i_won = (winner_role == my_role)
    i_drew = (winner_role == 'Tie')

    if winner_role == 'Tie':
        winner_name = 'Draw'
    elif winner_role == 'player1':
        winner_name = room.player1.username
    elif winner_role == 'player2':
        winner_name = room.player2.username if room.player2 else 'Unknown'
    else:
        winner_name = 'Unknown'

    batting_first_name = (
        room.player1.username if batting_first == 'player1'
        else (room.player2.username if room.player2 else 'Player 2')
    )
    chasing_name = (
        room.player1.username if chasing_team == 'player1'
        else (room.player2.username if room.player2 else 'Player 2')
    )

    delete_game_state(code)

    return render(request, 'mp_result.html', {
        'room':               room,
        'winner':             winner_name,
        'winner_role':        winner_role,
        'i_won':              i_won,
        'i_drew':             i_drew,
        'p1_name':            room.player1.username,
        'p2_name':            room.player2.username if room.player2 else 'Player 2',
        'batting_first_name': batting_first_name,
        'chasing_name':       chasing_name,
        'first_score':        scores.get(batting_first, 0),
        'second_score':       scores.get(chasing_team, 0),
        'first_wickets':      wickets.get(batting_first, 0),
        'second_wickets':     wickets.get(chasing_team, 0),
        'target':             target,
        'batting_first':      batting_first,
        'chasing_team':       chasing_team,
        'exit_by':            state.get('exit_by'),
        'p1_runs':            p1_runs,
        'p2_runs':            p2_runs,
        'p1_wickets':         p1_wickets,
        'p2_wickets':         p2_wickets,
    })
