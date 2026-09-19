"""
game_engine.py — Pure game-rules logic for Super-7.

Zero Django / HTTP awareness. All functions take explicit state dicts
and return values. No request, no render, no DB calls inside the core math.
The views layer is responsible for:
  1. Loading state (via game_cache.get_game_state)
  2. Loading PlayerCard objects from the DB
  3. Calling the appropriate engine function
  4. Persisting the returned state (via game_cache.save_game_state)
  5. Sending WebSocket notifications

─── STATE KEY SCHEMA ──────────────────────────────────────────────────────────
Every key that may appear in the game-state dict is listed here.
A typo in an f-string key fails *silently* (returns None), so treat this
schema as the authoritative reference. If you add a new key, add it here.

  scores                               dict  {'player1': int, 'player2': int}
  wickets                              dict  {'player1': int, 'player2': int}
  innings                              int   1 or 2
  round_number                         int   1-8  (8 means "all rounds done")
  batting_first                        str   'player1' | 'player2'
  target                               int   runs needed by chasing team in innings 2
  winner                               str   'player1' | 'player2' | 'Tie'
  game_over                            bool  match fully concluded
  game_over_pending                    bool  target chased; boost window still open
  innings_transition                   dict  {'target': int, 'first_score': int}
  used_by_player1                      list  [card_id, ...]
  used_by_player2                      list  [card_id, ...]
  message                              str   human-readable round result
  last_batter                          dict  {name, image, batting, runs, ability,
                                              ability_bonus, boost_bonus,
                                              support_bonus, support_type,
                                              effective_batting}
  last_bowler                          dict  {name, image, bowling, runs, ability,
                                              ability_bonus, boost_bonus,
                                              support_bonus, support_type,
                                              effective_bowling, runs_cut}
  {role}_played_round_{inn}_{rnd}      int   card_id chosen by role for that round
  {role}_boost_used                    bool  once-per-match pre-round boost consumed
  {role}_boost_active                  bool  boost is active for the current round
  {role}_post_boost_used               bool  post-round boost consumed for current rnd
  {role}_support                       dict|None  {type, from_round, until_round}
  {role}_support_used                  bool  once-per-innings support card consumed
  {role}_viewing_innings2              bool  this player clicked Continue on transition
  {role}_viewing_result                bool  this player clicked See Result
  runs_in_round_{inn}_{rnd}            int   runs awarded that round (0 on wicket)
  wicket_in_round_{inn}_{rnd}          bool  True if a wicket fell
  round_snapshot_{inn}_{rnd}           dict  frozen state needed for boost recalc
  boost_window_open_{inn}_{rnd}        bool  post-round boost window still open
  boost_window_started_{inn}_{rnd}     float unix timestamp when window opened
  round_boost_clicks_{inn}_{rnd}       list  [role, ...]  who has clicked boost
  boost_update_counter                 int   incremented each recalc for WS polling
  exit_by                              str   'player1' | 'player2'
  toss_result                          str   'heads' | 'tails'
  toss_winner                          str   'player1' | 'player2'
  toss_done                            bool
  innings_chosen                       bool

role is always 'player1' or 'player2'.
{inn} is 1 or 2; {rnd} is 1-7.
───────────────────────────────────────────────────────────────────────────────
"""

import math
import time as _time

# Seconds the post-round boost window stays open
BOOST_WINDOW_SECONDS = 7


# ─── Ability application ─────────────────────────────────────────────────────

def apply_abilities(batter_card, bowler_card, round_number, state, batting_team):
    """
    Apply all ability bonuses, boost, and support effects for one round.

    Returns
    -------
    (eff_batting, eff_bowling, eff_runs, runs_cutter_active, ability_log)
      eff_batting        int  -- batter's effective batting stat after bonuses
      eff_bowling        int  -- bowler's effective bowling stat after bonuses
      eff_runs           int  -- batter's runs value (unchanged here)
      runs_cutter_active bool -- True if Runs Cutter ability should deduct runs
      ability_log        list[str] -- human-readable ability trigger messages
    """
    batting = batter_card.batting
    bowling = bowler_card.bowling
    runs    = batter_card.runs
    log     = []

    scores = state.get('scores', {})

    # ── Determine roles ──────────────────────────────────────────────────────
    if batting_team == 'player1':
        batter_role = 'player1'
        bowler_role = 'player2'
    else:
        batter_role = 'player2'
        bowler_role = 'player1'

    # Will spin_basher trigger? Decide now so we can skip boost if it does.
    spin_basher_will_trigger = (
        batter_card.ability == 'spin_basher'
        and bowler_card.is_spinner
    )

    # ── BATTING ABILITIES ────────────────────────────────────────────────────
    if batter_card.ability == 'opener' and round_number <= 2:
        batting += 10
        log.append("⚡ Opener: +10 batting!")

    if batter_card.ability == 'finisher' and round_number >= 6:
        batting += 10
        log.append("💥 Finisher: +10 batting!")

    if batter_card.ability == 'mid_over_hitter' and 3 <= round_number <= 5:
        batting += 10
        log.append("🏏 Mid Over Hitter: +10 batting!")

    if batter_card.ability == 'spin_basher' and bowler_card.is_spinner:
        batting += 10
        log.append("🌀 Spin Basher: +10 batting vs spinner!")

    if batter_card.ability == 'saviour':
        innings = state.get('innings', 1)
        wicket_fell = any(
            state.get(f'wicket_in_round_{innings}_{r}')
            for r in [round_number - 1, round_number - 2] if r >= 1
        )
        if wicket_fell:
            batting += 10
            log.append("🛡️ Saviour: +10 batting after recent wicket!")

    # ── BOWLING ABILITIES ────────────────────────────────────────────────────
    if bowler_card.ability == 'powerplay_specialist' and round_number <= 2:
        bowling += 10
        log.append("🔥 Powerplay Specialist: +10 bowling!")

    if bowler_card.ability == 'death_specialist' and round_number >= 6:
        bowling += 10
        log.append("💀 Death Specialist: +10 bowling!")

    if bowler_card.ability == 'mid_over_specialist' and 3 <= round_number <= 5:
        bowling += 10
        log.append("🎯 Mid Over Specialist: +10 bowling!")

    if bowler_card.ability == 'golden_arm':
        innings = state.get('innings', 1)
        prev_runs = sum(
            state.get(f'runs_in_round_{innings}_{r}', 0)
            for r in [round_number - 1, round_number - 2] if r >= 1
        )
        if prev_runs >= 30:
            bowling += 10
            log.append(f"💛 Golden Arm: +10 bowling ({prev_runs} runs in last 2 rounds)!")

    if bowler_card.ability == 'breakthrough':
        opponent_score = scores.get(batting_team, 0)
        if opponent_score >= 60:
            bowling += 10
            log.append(f"🚨 Breakthrough: +10 bowling (opponent at {opponent_score} runs)!")

    runs_cutter_active = (
        bowler_card.ability == 'runs_cutter'
        and batter_card.ability != 'spin_basher'
    )

    # ── BOOST EFFECT (skipped if spin_basher triggers) ───────────────────────
    if state.get(f'{batter_role}_boost_active'):
        if not spin_basher_will_trigger:
            batting += 10
            log.append("🚀 Boost: +10 batting!")
        # Always consume the boost token, even if skipped by spin_basher
        state[f'{batter_role}_boost_active'] = False

    if state.get(f'{bowler_role}_boost_active'):
        bowling += 10
        log.append("🚀 Boost: +10 bowling!")
        state[f'{bowler_role}_boost_active'] = False

    # ── SUPPORT CARD EFFECTS ─────────────────────────────────────────────────
    batter_support = state.get(f'{batter_role}_support')
    if batter_support:
        s_from  = batter_support.get('from_round', 0)
        s_until = batter_support.get('until_round', 0)
        if s_from <= round_number <= s_until:
            if batter_support.get('type') == 'batting_support':
                batting += 2
                log.append("🟢 Batting Support: +2 batting!")

    bowler_support = state.get(f'{bowler_role}_support')
    if bowler_support:
        s_from  = bowler_support.get('from_round', 0)
        s_until = bowler_support.get('until_round', 0)
        if s_from <= round_number <= s_until:
            s_type = bowler_support.get('type')
            if s_type == 'pace_support' and not bowler_card.is_spinner:
                bowling += 2
                log.append("⚡ Pace Support: +2 bowling!")
            elif s_type == 'spin_support' and bowler_card.is_spinner:
                bowling += 2
                log.append("🌀 Spin Support: +2 bowling!")

    return batting, bowling, runs, runs_cutter_active, log


# ─── Round resolution ────────────────────────────────────────────────────────

def resolve_round(state, innings, round_number, batting_team, batting_first,
                  batter_card, bowler_card):
    """
    Resolve a single round of play, updating *state* in-place and returning it.

    The caller is responsible for persisting *state* via save_game_state().

    Parameters
    ----------
    state         dict   -- full game state (mutated and returned)
    innings       int    -- 1 or 2
    round_number  int    -- current round (1-7)
    batting_team  str    -- 'player1' or 'player2'
    batting_first str    -- which team batted in innings 1
    batter_card   obj    -- PlayerCard ORM object for the batting team
    bowler_card   obj    -- PlayerCard ORM object for the bowling team

    Returns
    -------
    state  dict  -- updated state
    """
    state.setdefault('scores',  {'player1': 0, 'player2': 0})
    state.setdefault('wickets', {'player1': 0, 'player2': 0})

    batter_role = batting_team
    bowler_role = 'player2' if batting_team == 'player1' else 'player1'

    # ── 0. Will spin_basher trigger? ─────────────────────────────────────────
    spin_basher_will_trigger = (
        batter_card.ability == 'spin_basher'
        and bowler_card.is_spinner
    )

    # ── 1. Read boost flags BEFORE apply_abilities consumes them ─────────────
    batter_boost_was_active = state.get(f'{batter_role}_boost_active', False)
    bowler_boost_was_active = state.get(f'{bowler_role}_boost_active', False)

    batter_boost_bonus = 10 if (batter_boost_was_active and not spin_basher_will_trigger) else 0
    bowler_boost_bonus = 10 if bowler_boost_was_active else 0

    # ── 2. Apply abilities (also consumes boost_active flags) ────────────────
    eff_batting, eff_bowling, eff_runs, runs_cutter_active, ability_log = apply_abilities(
        batter_card, bowler_card, round_number, state, batting_team
    )

    # ── 2.5. Restore boost if spin_basher fired instead ──────────────────────
    if spin_basher_will_trigger and batter_boost_was_active:
        state[f'{batter_role}_boost_active'] = False
        state[f'{batter_role}_boost_used']   = False
        log_entry = "♻️ Boost restored: Spin Basher used instead!"
        if log_entry not in ability_log:
            ability_log.append(log_entry)

    # ── 3. Calculate display bonuses ─────────────────────────────────────────
    batter_support_bonus, batter_support_type = _calc_support_bonus(
        state, batter_role, round_number, batter_card, is_batter=True
    )
    bowler_support_bonus, bowler_support_type = _calc_support_bonus(
        state, bowler_role, round_number, bowler_card, is_batter=False
    )

    batter_actual_ability_bonus = eff_batting - batter_card.batting - batter_support_bonus - batter_boost_bonus
    bowler_actual_ability_bonus = eff_bowling - bowler_card.bowling - bowler_support_bonus - bowler_boost_bonus

    # ── 4. Score the round ───────────────────────────────────────────────────
    runs_cut_amount = 0

    if eff_batting > eff_bowling:
        if runs_cutter_active:
            runs_cut_amount = min(10, eff_runs)
            eff_runs = max(0, eff_runs - 10)
            ability_log.append("✂️ Runs Cutter: -10 runs!")

        state['scores'][batting_team] += eff_runs
        state[f'runs_in_round_{innings}_{round_number}']   = eff_runs
        state[f'wicket_in_round_{innings}_{round_number}'] = False
        ability_str = "  |  " + "  ".join(ability_log) if ability_log else ""
        state['message'] = f"Runs added: {eff_runs}!{ability_str}"

    elif eff_batting == eff_bowling:
        awarded = math.floor(eff_runs / 3 + 0.5)
        state['scores'][batting_team] += awarded
        state[f'runs_in_round_{innings}_{round_number}']   = awarded
        state[f'wicket_in_round_{innings}_{round_number}'] = False
        ability_str = "  |  " + "  ".join(ability_log) if ability_log else ""
        state['message'] = f"Tie! Partial runs: {awarded}!{ability_str}"

    else:
        state['wickets'][batting_team] += 1
        state[f'runs_in_round_{innings}_{round_number}']   = 0
        state[f'wicket_in_round_{innings}_{round_number}'] = True
        ability_str = "  |  " + "  ".join(ability_log) if ability_log else ""
        state['message'] = f"Wicket! 🎯{ability_str}"

    # ── 5. Save last-played card data for display ────────────────────────────
    state['last_batter'] = {
        'name':              batter_card.name,
        'image':             batter_card.image.url if batter_card.image else None,
        'ability':           batter_card.ability,
        'batting':           batter_card.batting,
        'runs':              batter_card.runs,
        'ability_bonus':     batter_actual_ability_bonus,
        'boost_bonus':       batter_boost_bonus,
        'support_bonus':     batter_support_bonus,
        'support_type':      batter_support_type,
        'effective_batting': eff_batting,
    }
    state['last_bowler'] = {
        'name':              bowler_card.name,
        'image':             bowler_card.image.url if bowler_card.image else None,
        'ability':           bowler_card.ability,
        'bowling':           bowler_card.bowling,
        'runs':              bowler_card.runs,
        'ability_bonus':     bowler_actual_ability_bonus,
        'boost_bonus':       bowler_boost_bonus,
        'support_bonus':     bowler_support_bonus,
        'support_type':      bowler_support_type,
        'effective_bowling': eff_bowling,
        'runs_cut':          runs_cut_amount,
    }

    state['round_number'] = round_number + 1

    # ── 6. Open post-round boost window + save snapshot ──────────────────────
    _batter_triggered = batter_actual_ability_bonus > 0
    _bowler_triggered = (
        bowler_actual_ability_bonus > 0
        or (bowler_card.ability == 'runs_cutter' and runs_cutter_active)
    )

    state[f'round_snapshot_{innings}_{round_number}'] = {
        'batting_team':             batting_team,
        'batter_card_id':           batter_card.id,
        'bowler_card_id':           bowler_card.id,
        'eff_batting':              eff_batting,
        'eff_bowling':              eff_bowling,
        'eff_runs':                 batter_card.runs,
        'runs_cutter_active':       runs_cutter_active,
        'batter_ability_triggered': _batter_triggered,
        'bowler_ability_triggered': _bowler_triggered,
        'batter_role':              batter_role,
        'bowler_role':              bowler_role,
    }
    state[f'boost_window_open_{innings}_{round_number}']    = not (_batter_triggered and _bowler_triggered)
    state[f'boost_window_started_{innings}_{round_number}'] = _time.time()
    state[f'round_boost_clicks_{innings}_{round_number}']   = []

    # ── 7. Check end-of-innings / game conditions ────────────────────────────
    state = _check_end_conditions(state, innings, round_number, batting_team, batting_first)

    return state


def _calc_support_bonus(state, role, round_number, card, is_batter):
    """Return (bonus_int, bonus_type_str|None) for display purposes only."""
    support = state.get(f'{role}_support')
    if not support:
        return 0, None
    s_from  = support.get('from_round', 0)
    s_until = support.get('until_round', 0)
    s_type  = support.get('type')
    if not (s_from <= round_number <= s_until):
        return 0, None
    if is_batter and s_type == 'batting_support':
        return 2, 'Batting Support'
    if not is_batter and s_type == 'pace_support' and not card.is_spinner:
        return 2, 'Pace Support'
    if not is_batter and s_type == 'spin_support' and card.is_spinner:
        return 2, 'Spin Support'
    return 0, None


def _check_end_conditions(state, innings, round_number, batting_team, batting_first):
    """
    Check whether the innings or match has ended after a resolved round,
    and update state accordingly. Returns updated state.
    """
    current_score   = state['scores'][batting_team]
    current_wickets = state['wickets'][batting_team]
    target          = state.get('target')

    # Target chased in innings 2 — game ends (pending boost window)
    if innings == 2 and target is not None and current_score >= target:
        chasing_team = 'player2' if batting_first == 'player1' else 'player1'
        state['game_over_pending'] = True
        state['winner'] = chasing_team
        return state

    # All out (10 wickets) OR all 7 rounds played
    innings_over = (current_wickets >= 10) or (state['round_number'] > 7)

    if innings_over:
        if innings == 1:
            first_score = state['scores'][batting_first]
            state['innings_transition'] = {
                'target':      first_score + 1,
                'first_score': first_score,
            }
            state['message'] = f"First innings over! Target: {first_score + 1}"
        else:
            # Innings 2 ended without chasing team reaching target
            chasing_team    = 'player2' if batting_first == 'player1' else 'player1'
            chasing_score   = state['scores'][chasing_team]
            defending_score = state['scores'][batting_first]
            target_val      = state.get('target', 0)

            if chasing_score == defending_score:
                state['winner'] = 'Tie'
            elif chasing_score >= target_val:
                state['winner'] = chasing_team
            else:
                state['winner'] = batting_first

            state['game_over'] = True

    return state


# ─── Post-round boost recalculation ──────────────────────────────────────────

def recalculate_round_with_boost(state, innings, round_number, clicking_role, bonus_amount):
    """
    Re-run the round outcome using the stored snapshot, applying bonus_amount
    to whichever side clicking_role played (batter or bowler).

    Updates scores / wickets / last_batter / last_bowler in state and
    re-checks innings/game-over conditions.

    Returns the updated state dict.
    """
    snap = state.get(f'round_snapshot_{innings}_{round_number}')
    if not snap:
        return state  # nothing to recalculate

    batting_team       = snap['batting_team']
    eff_batting        = snap['eff_batting']
    eff_bowling        = snap['eff_bowling']
    eff_runs           = snap['eff_runs']
    runs_cutter_active = snap['runs_cutter_active']
    batting_first      = state.get('batting_first', 'player1')

    # Apply bonus to the clicking player's side
    if clicking_role == snap['batter_role']:
        eff_batting += bonus_amount
    elif clicking_role == snap['bowler_role']:
        eff_bowling += bonus_amount

    # Persist boosted values so a second click builds on THIS result
    snap['eff_batting'] = eff_batting
    snap['eff_bowling'] = eff_bowling
    state[f'round_snapshot_{innings}_{round_number}'] = snap

    # Undo the previous round's contribution before reapplying
    prev_runs   = state.get(f'runs_in_round_{innings}_{round_number}', 0)
    prev_wicket = state.get(f'wicket_in_round_{innings}_{round_number}', False)

    if prev_wicket:
        state['wickets'][batting_team] = max(0, state['wickets'][batting_team] - 1)
    else:
        state['scores'][batting_team] = max(0, state['scores'][batting_team] - prev_runs)

    # Recompute outcome
    runs_cut_amount = 0

    if eff_batting > eff_bowling:
        new_runs = eff_runs
        if runs_cutter_active:
            runs_cut_amount = min(10, new_runs)
            new_runs = max(0, new_runs - 10)
        state['scores'][batting_team] += new_runs
        state[f'runs_in_round_{innings}_{round_number}']   = new_runs
        state[f'wicket_in_round_{innings}_{round_number}'] = False
        state['message'] = f"Runs added: {new_runs}! (Boost applied)"

    elif eff_batting == eff_bowling:
        awarded = math.floor(eff_runs / 3 + 0.5)
        state['scores'][batting_team] += awarded
        state[f'runs_in_round_{innings}_{round_number}']   = awarded
        state[f'wicket_in_round_{innings}_{round_number}'] = False
        state['message'] = f"Tie! Partial runs: {awarded}! (Boost applied)"

    else:
        state['wickets'][batting_team] += 1
        state[f'runs_in_round_{innings}_{round_number}']   = 0
        state[f'wicket_in_round_{innings}_{round_number}'] = True
        state['message'] = "Wicket! 🎯 (Boost applied)"

    # Update display dicts
    last_batter = state.get('last_batter') or {}
    last_bowler = state.get('last_bowler') or {}

    if clicking_role == snap['batter_role']:
        last_batter['boost_bonus']       = last_batter.get('boost_bonus', 0) + bonus_amount
        last_batter['effective_batting'] = eff_batting
    elif clicking_role == snap['bowler_role']:
        last_bowler['boost_bonus']       = last_bowler.get('boost_bonus', 0) + bonus_amount
        last_bowler['effective_bowling'] = eff_bowling

    last_batter['runs_cut'] = runs_cut_amount
    state['last_batter'] = last_batter
    state['last_bowler'] = last_bowler

    # Record click and mark boost used
    state[f'{clicking_role}_post_boost_used'] = True
    boost_clicks = state.get(f'round_boost_clicks_{innings}_{round_number}', [])
    if clicking_role not in boost_clicks:
        boost_clicks.append(clicking_role)
    state[f'round_boost_clicks_{innings}_{round_number}'] = boost_clicks

    # Close window if neither player can boost anymore
    batter_role = snap.get('batter_role')
    bowler_role = snap.get('bowler_role')

    other_role = bowler_role if clicking_role == batter_role else batter_role
    other_ability_triggered = (
        (snap.get('batter_role') == other_role and snap.get('batter_ability_triggered'))
        or
        (snap.get('bowler_role') == other_role and snap.get('bowler_ability_triggered'))
    )
    other_can_still_boost = (
        not state.get(f'{other_role}_post_boost_used', False)
        and other_role not in boost_clicks
        and not other_ability_triggered
    )
    if not other_can_still_boost:
        state[f'boost_window_open_{innings}_{round_number}'] = False

    # Re-check innings/game-over since outcome may have flipped.
    # Clear stale end-condition flags before re-evaluating.
    state.pop('innings_transition', None)
    state.pop('game_over_pending', None)
    state.pop('game_over', None)
    state.pop('winner', None)

    state = _check_end_conditions(
        state, innings, round_number, batting_team, batting_first
    )

    state['boost_update_counter'] = state.get('boost_update_counter', 0) + 1
    return state
