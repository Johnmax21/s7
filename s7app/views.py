import code
import csv
from urllib import request
from urllib import request
from django.shortcuts import render, redirect
import random
from .models import DeckCard, GameRoom, PlayerCard, UserDeck, UserPrizeCard
import os
from datetime import datetime
from collections import defaultdict

from s7app import models

# ML code moved to ai_model.py and imported lazily inside game_start
# Load strategies from CSV
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATEGIES_FILE = os.path.join(BASE_DIR, 's7app', 'strategies.csv')
HISTORY_FILE = os.path.join(BASE_DIR, 's7app', 'game_history.csv')
MODEL_FILE = os.path.join(BASE_DIR, 's7app', 'card_model.joblib')
OPTIMAL_COUNTERS = {
    'high_bowling': lambda cards: max(cards, key=lambda x: x.batting + x.runs),
    'high_batting': lambda cards: max(cards, key=lambda x: x.bowling),
    'balanced': lambda cards: max(cards, key=lambda x: (x.bowling + x.batting + x.runs) / 3),
}
strategies = {}
if os.path.exists(STRATEGIES_FILE):
    with open(STRATEGIES_FILE, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            strategies[row['player_profile']] = row['best_counter']
else:
    # default strategies file creation
    with open(STRATEGIES_FILE, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=['player_profile', 'best_counter'])
        writer.writeheader()
        writer.writerow({'player_profile': 'high_batting', 'best_counter': 'high_bowling'})
        writer.writerow({'player_profile': 'high_bowling', 'best_counter': 'high_batting'})
        writer.writerow({'player_profile': 'balanced', 'best_counter': 'balanced'})
    strategies = {'high_batting': 'high_bowling', 'high_bowling': 'high_batting', 'balanced': 'balanced'}

# Initialize game_history.csv with full headers if it doesn't exist
if not os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=[
            'round_number', 'player_card_id', 'player_name', 'computer_card_id', 'computer_name',
            'outcome', 'score', 'wickets', 'batting_team', 'innings', 'round_timestamp'
        ])
        writer.writeheader()

def ensure_history_headers():
    """Ensure HISTORY_FILE has the expected headers. If headers mismatch attempt to remap common variants and rewrite file."""
    desired = ['round_number', 'player_card_id', 'player_name', 'computer_card_id', 'computer_name',
               'outcome', 'score', 'wickets', 'batting_team', 'innings', 'round_timestamp']
    if not os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=desired)
            writer.writeheader()
        return

    # Read existing file
    try:
        with open(HISTORY_FILE, newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        rows = []

    if not rows:
        with open(HISTORY_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=desired)
            writer.writeheader()
        return

    existing_header = rows[0]
    # if desired header is already present (subset), nothing to do
    if set(desired).issubset(set(existing_header)):
        return

    # Try to read with DictReader and remap known timestamp variants
    try:
        with open(HISTORY_FILE, newline='', encoding='utf-8') as f:
            old_rows = list(csv.DictReader(f))
    except Exception:
        old_rows = []

    new_rows = []
    for r in old_rows:
        new_r = {k: '' for k in desired}
        # copy values for keys that exist
        for k in desired:
            if k in r:
                new_r[k] = r.get(k, '')
        # common mappings: 'timestamp' or 'timestamp1' => 'round_timestamp'
        if not new_r.get('round_timestamp'):
            if 'timestamp' in r:
                new_r['round_timestamp'] = r.get('timestamp', '')
            elif 'timestamp1' in r:
                new_r['round_timestamp'] = r.get('timestamp1', '')
        # best-effort: if batting_team or innings missing, leave blank/default
        new_rows.append(new_r)

    # rewrite file with desired header and remapped rows
    try:
        with open(HISTORY_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=desired)
            writer.writeheader()
            for nr in new_rows:
                writer.writerow(nr)
    except Exception:
        # last-resort: overwrite with just header to avoid future ValueError
        with open(HISTORY_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=desired)
            writer.writeheader()

def analyze_history_and_update_strategy():
    win_counts = defaultdict(lambda: defaultdict(int))
    loss_counts = defaultdict(lambda: defaultdict(int))
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                player_profile = 'high_batting' if int(row['player_card_id']) % 2 == 0 else 'balanced'
                computer_strategy = row['computer_name'] or 'N/A'
                if row['outcome'] == 'win':
                    win_counts[player_profile][computer_strategy] += 1
                else:
                    loss_counts[player_profile][computer_strategy] += 1

    new_strategies = {}
    for profile in strategies:
        current_counter = strategies[profile]
        wins = win_counts[profile][current_counter]
        losses = loss_counts[profile][current_counter]
        if losses > wins and losses > 2:
            alt_strategies = [s for s in OPTIMAL_COUNTERS.keys() if s != current_counter]
            best_alt = min(alt_strategies, key=lambda s: loss_counts[profile].get(s, 0), default=current_counter)
            new_strategies[profile] = best_alt
        else:
            new_strategies[profile] = current_counter

    with open(STRATEGIES_FILE, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=['player_profile', 'best_counter'])
        writer.writeheader()
        for profile, counter in new_strategies.items():
            writer.writerow({'player_profile': profile, 'best_counter': counter})
    # update in-memory strategies
    strategies.update(new_strategies)

# keep ML-heavy helpers in ai_model; do lazy import inside view to avoid ModuleNotFoundError at import time

def toss_view(request):
    if request.method == "POST":
        player_choice = request.POST.get("toss_choice")
        if not player_choice:
            return render(request, "toss.html", {"error": "Please select head or tails."})
        toss_result = random.choice(["head", "tails"])
        if player_choice == toss_result:
            request.session['won_toss'] = True
            request.session['toss_result'] = toss_result
            request.session['player_choice'] = player_choice
            batting_first = None
            return render(request, "toss_result.html", {"won_toss": True, "toss_result": toss_result, "player_choice": player_choice, "batting_first": batting_first})
        else:
            batting_first = random.choice(["player", "computer"])
            request.session['won_toss'] = False
            request.session['toss_result'] = toss_result
            request.session['player_choice'] = player_choice
            request.session['batting_first'] = batting_first
            return render(request, "toss_result.html", {"won_toss": False, "toss_result": toss_result, "player_choice": player_choice, "batting_first": batting_first})
    return render(request, "toss.html")

def game_start(request):
    analyze_history_and_update_strategy()

    # Lazy import ai_model here so module import doesn't fail if ai_model.py missing
    try:
        from .ai_model import predict_best_card, load_model
        model_module_available = True
    except Exception:
        predict_best_card = None
        load_model = None
        model_module_available = False

    # Initialize / reset session
    if 'innings' not in request.session or request.method == "POST" and 'batting_first' in request.POST:
        request.session.flush()
        if request.method == "POST" and 'batting_first' in request.POST:
            batting_first = request.POST['batting_first']
            request.session['batting_first'] = batting_first
            request.session['innings'] = 1
            request.session['used_by_player'] = []
            request.session['used_by_computer'] = []
            request.session['scores'] = {'player': 0, 'computer': 0}
            request.session['wickets'] = {'player': 0, 'computer': 0}
            request.session['round_number'] = 1
            request.session['message'] = ""

    if request.method == "POST" and 'selected_card_id' in request.POST:
        innings = request.session['innings']
        round_number = request.session['round_number']
        batting_first = request.session['batting_first']
        batting_team = batting_first if innings == 1 else 'computer' if batting_first == 'player' else 'player'
        used_by_player = request.session['used_by_player']
        used_by_computer = request.session['used_by_computer']
        available_for_player = PlayerCard.objects.exclude(id__in=used_by_player)
        selected_id = int(request.POST['selected_card_id'])
        player_card = PlayerCard.objects.get(id=selected_id)
        if player_card.id in used_by_player:
            pass
        used_by_player.append(player_card.id)
        request.session['used_by_player'] = used_by_player

        available_for_computer = PlayerCard.objects.exclude(id__in=used_by_computer)

        # compute player profile and counter strategy for fallback
        player_batting_weight = player_card.batting / (player_card.batting + player_card.bowling + 1)
        player_profile = 'high_batting' if player_batting_weight > 0.6 else 'high_bowling' if player_card.bowling > player_card.batting else 'balanced'
        counter_strategy = strategies.get(player_profile, 'balanced')

        model_ready = False
        if model_module_available:
            try:
                model_ready = load_model() is not None
            except Exception:
                model_ready = False

        computer_card = None
        if not available_for_computer:
            computer_card = None
        elif batting_team == 'computer':
            computer_card = max(available_for_computer, key=lambda x: x.batting + x.runs)
        elif model_ready and predict_best_card is not None:
            candidate_ids = [c.id for c in available_for_computer]
            try:
                best_id, prob = predict_best_card(player_card.id, candidate_ids, innings=innings, round_number=round_number, wickets=request.session['wickets'].get(batting_team, 0))
                if best_id:
                    computer_card = PlayerCard.objects.get(id=best_id)
            except Exception:
                computer_card = None

        if computer_card is None:
            # fallback heuristic
            try:
                computer_card = OPTIMAL_COUNTERS[counter_strategy](available_for_computer)
            except Exception:
                computer_card = random.choice(list(available_for_computer)) if available_for_computer else None

        if computer_card:
            used_by_computer.append(computer_card.id)
            request.session['used_by_computer'] = used_by_computer
        else:
            message = "Error: Insufficient cards available!"
            request.session['message'] = message

        if computer_card and player_card:
            if batting_team == 'player':
                batter = player_card
                bowler = computer_card
            else:
                batter = computer_card
                bowler = player_card

            if batter.batting > bowler.bowling:
                request.session['scores'][batting_team] += batter.runs
                message = f"Runs added: {batter.runs}"
                round_outcome = 'win'
            else:
                request.session['wickets'][batting_team] += 1
                message = "Wicket!"
                round_outcome = 'loss'
            request.session['message'] = message

            ensure_history_headers()   # <-- add this before appending a new row
            with open(HISTORY_FILE, 'a', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=[
                    'round_number', 'player_card_id', 'player_name', 'computer_card_id', 'computer_name',
                    'outcome', 'score', 'wickets', 'batting_team', 'innings', 'round_timestamp'
                ])
                writer.writerow({
                    'round_number': round_number,
                    'player_card_id': player_card.id,
                    'player_name': player_card.name,
                    'computer_card_id': computer_card.id if computer_card else None,
                    'computer_name': computer_card.name if computer_card else 'N/A',
                    'outcome': round_outcome,
                    'score': request.session['scores'][batting_team],
                    'wickets': request.session['wickets'][batting_team],
                    'batting_team': batting_team,
                    'innings': request.session.get('innings', 1),
                    'round_timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })

            request.session['last_batter'] = {
                'name': batter.name,
                'batting': batter.batting,
                'bowling': bowler.bowing,
                'runs': batter.runs,
                'image': batter.image.url if batter.image else None
            }
            request.session['last_bowler'] = {
                'name': bowler.name,
                'batting': bowler.batting,
                'bowling': bowler.bowing,
                'runs': bowler.runs,
                'image': bowler.image.url if bowler.image else None
            }

        request.session['round_number'] += 1
        if request.session['round_number'] > 7:
            if innings == 1:
                first_score = request.session['scores'][batting_first]
                request.session['target'] = first_score + 1
                request.session['innings'] = 2
                request.session['used_by_player'] = []
                request.session['used_by_computer'] = []
                request.session['round_number'] = 1
                request.session['message'] = "First innings over. Second innings starts!"
                request.session.pop('last_batter', None)
                request.session.pop('last_bowler', None)
            else:
                second_team = 'computer' if batting_first == 'player' else 'player'
                second_score = request.session['scores'][second_team]
                first_score = request.session['scores'][batting_first]
                first_wickets = request.session['wickets'][batting_first]
                second_wickets = request.session['wickets'][second_team]
                if second_score > first_score:
                    winner = second_team
                elif second_score == first_score:
                    winner = "Tie"
                else:
                    winner = batting_first
                return render(request, "game_result.html", {
                    "winner": winner,
                    "first_team": batting_first,
                    "second_team": second_team,
                    "first_score": first_score,
                    "second_score": second_score,
                    "first_wickets": first_wickets,
                    "second_wickets": second_wickets,
                })

    innings = request.session.get('innings', 1)
    round_number = request.session.get('round_number', 1)
    batting_first = request.session.get('batting_first')
    batting_team = batting_first if innings == 1 else 'computer' if batting_first == 'player' else 'player'
    used_by_player = request.session.get('used_by_player', [])
    available_cards = PlayerCard.objects.exclude(id__in=used_by_player)
    label = "Select your batter" if batting_team == 'player' else "Select your bowler"
    message = request.session.get('message', "")
    current_runs = request.session['scores'][batting_team]
    current_wickets = request.session['wickets'][batting_team]
    context = {
        "innings": innings,
        "round_number": round_number,
        "batting_team": batting_team,
        "available_cards": available_cards,
        "label": label,
        "message": message,
        "current_runs": current_runs,
        "current_wickets": current_wickets,
    }
    if innings == 2:
        context["target"] = request.session['target']
    if innings > 1:
        first_team = batting_first
        context["first_runs"] = request.session['scores'][first_team]
        context["first_wickets"] = request.session['wickets'][first_team]
    if 'last_batter' in request.session:
        context['last_batter'] = request.session['last_batter']
        context['last_bowler'] = request.session['last_bowler']
    game_history = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            game_history = list(reader)[-10:]
    context['game_history'] = game_history
    return render(request, "game.html", context)





# game/views.py (new views)
import random, string
from django.contrib.auth.decorators import login_required


def create_room(request):
    code = ''.join(random.choices(string.ascii_uppercase, k=6))
    room = GameRoom.objects.create(code=code, player1=request.user)
    return redirect('room_lobby', code=code)

def join_room(request, code):
    room = GameRoom.objects.get(code=code)
    room.player2 = request.user
    room.save()
    return redirect('game_room', code=code)


from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login as auth_login, logout as auth_logout, authenticate
from django.shortcuts import render, redirect
from django.contrib import messages

def register(request):
    if request.user.is_authenticated:
        return redirect('lobby')

    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            return redirect('lobby')
    else:
        form = UserCreationForm()

    return render(request, 'register.html', {'form': form})


def login(request):
    if request.user.is_authenticated:
        return redirect('lobby')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user:
            auth_login(request, user)   # ← was login(request, user) — calling itself!
            return redirect(request.POST.get('next') or 'lobby')
        else:
            messages.error(request, 'Invalid username or password.')

    return render(request, 'login.html')


def logout_view(request):
    auth_logout(request)   # ← use auth_logout not logout
    return redirect('login')


import random
import string
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from .models import GameRoom, PlayerCard


# ─── helpers ────────────────────────────────────────────────────────────────

def _make_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase, k=length))


def _my_role(request, room):
    """Returns 'player1' or 'player2' based on who is logged in."""
    if request.user == room.player1:
        return 'player1'
    return 'player2'


def _opponent_role(my_role):
    return 'player2' if my_role == 'player1' else 'player1'


def _get_player(room, role):
    return room.player1 if role == 'player1' else room.player2


# ─── lobby ──────────────────────────────────────────────────────────────────

@login_required
def lobby(request):
    """Landing page — create or join a room."""
    return render(request, 'lobby.html')


# ─── create room ────────────────────────────────────────────────────────────

@login_required
def create_room(request):
    if request.method == 'POST':
        code = _make_code()
        # Avoid rare duplicate codes
        while GameRoom.objects.filter(code=code).exists():
            code = _make_code()

        room = GameRoom.objects.create(
            code=code,
            player1=request.user,
            state={}
        )
        return redirect('waiting_room', code=room.code)

    return redirect('lobby')


# ─── join room ──────────────────────────────────────────────────────────────

@login_required
def join_room(request):
    if request.method == 'POST':
        code = request.POST.get('code', '').strip().upper()
        try:
            room = GameRoom.objects.get(code=code)
        except GameRoom.DoesNotExist:
            return render(request, 'lobby.html', {'error': f'Room "{code}" not found.'})

        # Already player1 — just go to waiting room
        if request.user == room.player1:
            return redirect('waiting_room', code=room.code)

        # Room already full with a different player2
        if room.player2 and room.player2 != request.user:
            return render(request, 'lobby.html', {'error': 'Room is already full.'})

        # Join as player2
        if not room.player2:
            room.player2 = request.user
            room.save()

        return redirect('waiting_room', code=room.code)

    return redirect('lobby')


# ─── waiting room ────────────────────────────────────────────────────────────

@login_required
def waiting_room(request, code):
    room = get_object_or_404(GameRoom, code=code)

    # Once both players are in, player1 can click Start
    if room.player2 and request.method == 'POST':
        return redirect('mp_toss', code=room.code)

    return render(request, 'waiting_room.html', {'room': room})


# ─── toss ────────────────────────────────────────────────────────────────────

@login_required
def mp_toss(request, code):
    room = get_object_or_404(GameRoom, code=code)
    state = room.state or {}

    my_role = _my_role(request, room)
    # player1 always calls the toss
    is_toss_caller = (my_role == 'player1')

    if request.method == 'POST' and request.POST.get('action') == 'call_toss':
        if not is_toss_caller:
            return redirect('mp_toss', code=code)

        choice = request.POST.get('toss_choice', 'heads')
        result = random.choice(['heads', 'tails'])
        toss_winner = 'player1' if choice == result else 'player2'

        state['toss_result'] = result
        state['toss_winner'] = toss_winner
        state['toss_done'] = True
        room.state = state
        room.save()
        return redirect('mp_toss_result', code=code)

    # If toss already done, redirect to result
    if state.get('toss_done'):
        return redirect('mp_toss_result', code=code)

    return render(request, 'mp_toss.html', {
        'room': room,
        'is_toss_caller': is_toss_caller,
    })


# ─── toss result ─────────────────────────────────────────────────────────────

@login_required
def mp_toss_result(request, code):
    room = get_object_or_404(GameRoom, code=code)
    state = room.state or {}

    # Wait if toss not done yet
    if not state.get('toss_done'):
        return redirect('mp_toss', code=code)

    my_role = _my_role(request, room)
    toss_winner = state.get('toss_winner')       # 'player1' or 'player2'
    i_won_toss = (my_role == toss_winner)
    toss_winner_name = _get_player(room, toss_winner).username

    if request.method == 'POST' and request.POST.get('action') == 'choose_innings':
        if not i_won_toss:
            return redirect('mp_toss_result', code=code)

        batting_first = request.POST.get('batting_first')  # 'player1' or 'player2'
        state['batting_first'] = batting_first
        state['innings'] = 1
        state['round_number'] = 1
        state['scores'] = {'player1': 0, 'player2': 0}
        state['wickets'] = {'player1': 0, 'player2': 0}
        state['used_by_player1'] = []
        state['used_by_player2'] = []
        state['message'] = ''
        state['innings_chosen'] = True
        room.state = state
        room.save()
        return redirect('mp_game', code=code)

    # Loser checks if innings has been chosen yet
    if state.get('innings_chosen'):
        return redirect('mp_game', code=code)

    return render(request, 'mp_toss_result.html', {
        'room': room,
        'toss_result': state.get('toss_result'),
        'i_won_toss': i_won_toss,
        'toss_winner_name': toss_winner_name,
        'my_role': my_role,
        'opponent_role': _opponent_role(my_role),
    })


# ─── multiplayer game ────────────────────────────────────────────────────────
"""
Replace _resolve_round and mp_game in your views.py with these fixed versions.
Fixes:
  1. Game ends immediately when target is chased (no waiting for 7 rounds)
  2. Both players redirected to result at the same time
  3. 10 wickets also ends the game early
"""
def _resolve_round(room, innings, round_number, batting_team, batting_first):
    state = room.state

    p1_card_id = state.get(f'player1_played_round_{innings}_{round_number}')
    p2_card_id = state.get(f'player2_played_round_{innings}_{round_number}')

    p1_card = PlayerCard.objects.get(id=p1_card_id)
    p2_card = PlayerCard.objects.get(id=p2_card_id)

    if batting_team == 'player1':
        batter_card, bowler_card = p1_card, p2_card
    else:
        batter_card, bowler_card = p2_card, p1_card

    # Apply all abilities + support cards
   # After _apply_abilities returns, before scoring:
    eff_batting, eff_bowling, eff_runs, runs_cutter_active, ability_log = _apply_abilities(
        batter_card, bowler_card, round_number, state, batting_team
    )

    # Calculate individual bonuses for display
    batter_ability_bonus  = eff_batting - batter_card.batting
    bowler_ability_bonus  = eff_bowling - bowler_card.bowling

    # Check support bonuses separately
    batter_role = batting_team
    bowler_role = 'player2' if batting_team == 'player1' else 'player1'
    batter_support = state.get(f'{batter_role}_support')
    bowler_support = state.get(f'{bowler_role}_support')

    batter_support_bonus = 0
    batter_support_type  = None
    if batter_support and batter_support.get('from_round', 0) <= round_number <= batter_support.get('until_round', 0):
        if batter_support.get('type') == 'batting_support':
            batter_support_bonus = 2
            batter_support_type  = 'Batting Support'

    bowler_support_bonus = 0
    bowler_support_type  = None
    if bowler_support and bowler_support.get('from_round', 0) <= round_number <= bowler_support.get('until_round', 0):
        st = bowler_support.get('type')
        if st == 'pace_support' and not bowler_card.is_spinner:
            bowler_support_bonus = 2
            bowler_support_type  = 'Pace Support'
        elif st == 'spin_support' and bowler_card.is_spinner:
            bowler_support_bonus = 2
            bowler_support_type  = 'Spin Support'

    # Save to state
    state['last_batter'] = {
        'name':              batter_card.name,
        'image':             batter_card.image.url if batter_card.image else None,
        'ability':           batter_card.ability,
        'batting':           batter_card.batting,
        'runs':              batter_card.runs,
        'ability_bonus':     batter_ability_bonus - batter_support_bonus,   # ability portion only
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
        'ability_bonus':     bowler_ability_bonus - bowler_support_bonus,   # ability portion only
        'support_bonus':     bowler_support_bonus,
        'support_type':      bowler_support_type,
        'effective_bowling': eff_bowling,
    }
    state['round_number'] = round_number + 1

    current_score   = state['scores'][batting_team]
    current_wickets = state['wickets'][batting_team]
    target          = state.get('target')

    # Early end: target chased
    if innings == 2 and target is not None and current_score >= target:
        state['game_over'] = True
        state['winner']    = batting_team
        room.state = state
        room.save()
        return

    # Early end: all out or 7 rounds done
    innings_over = (current_wickets >= 10) or (state['round_number'] > 7)

    if innings_over:
        if innings == 1:
            first_score = state['scores'][batting_first]
            state['target']          = first_score + 1
            state['innings']         = 2
            state['round_number']    = 1
            state['used_by_player1'] = []
            state['used_by_player2'] = []
            # Reset support cards for innings 2
            state['player1_support'] = None
            state['player2_support'] = None
            state['message']         = f"First innings over! Target: {first_score + 1}"
            state['last_batter']     = None
            state['last_bowler']     = None
        else:
            second_batting = batting_team
            first_score    = state['scores'][batting_first]
            second_score   = state['scores'][second_batting]

            if second_score > first_score:
                winner = second_batting
            elif second_score == first_score:
                winner = 'Tie'
            else:
                winner = batting_first

            state['game_over'] = True
            state['winner']    = winner

    room.state = state
    room.save()
@login_required
@login_required
def mp_game(request, code):
    room = get_object_or_404(GameRoom, code=code)
    state = room.state or {}
    my_role  = _my_role(request, room)
    opp_role = _opponent_role(my_role)
    opponent_name = _get_player(room, opp_role).username

    if state.get('game_over'):
        return redirect('mp_result', code=code)

    innings       = state.get('innings', 1)
    round_number  = state.get('round_number', 1)
    batting_first = state.get('batting_first', 'player1')

    if innings == 1:
        batting_team = batting_first
    else:
        batting_team = 'player2' if batting_first == 'player1' else 'player1'

    my_used  = state.get(f'used_by_{my_role}', [])
    opp_used = state.get(f'used_by_{opp_role}', [])

    my_played_key  = f'{my_role}_played_round_{innings}_{round_number}'
    opp_played_key = f'{opp_role}_played_round_{innings}_{round_number}'
    i_played   = state.get(my_played_key) is not None
    opp_played = state.get(opp_played_key) is not None

    if request.method == 'POST':

        # ── Support card ──────────────────────────────────────────
        if request.POST.get('action') == 'use_support':
            if not state.get(f'{my_role}_support_used'):
                support_type = request.POST.get('support_type')
                state[f'{my_role}_support'] = {
                    'type':        support_type,
                    'from_round':  round_number,
                    'until_round': round_number + 3,
                }
                state[f'{my_role}_support_used'] = True
                room.state = state
                room.save()
            return redirect('mp_game', code=code)

        # ── Play card ─────────────────────────────────────────────
        if request.POST.get('action') == 'play_card':
            if i_played:
                return redirect('mp_game', code=code)

            selected_id = int(request.POST.get('selected_card_id'))
            state[my_played_key] = selected_id
            my_used.append(selected_id)
            state[f'used_by_{my_role}'] = my_used
            room.state = state
            room.save()

            room.refresh_from_db()
            state = room.state
            opp_played_now = state.get(opp_played_key) is not None

            if opp_played_now:
                _resolve_round(room, innings, round_number, batting_team, batting_first)
                room.refresh_from_db()
                state = room.state
                if state.get('game_over'):
                    return redirect('mp_result', code=code)

            return redirect('mp_game', code=code)

    # ── GET ───────────────────────────────────────────────────────

    # ── ONLY THIS BLOCK CHANGED — active deck cards ───────────────
    if my_role == 'player1':
        active_user = room.player1
    else:
        active_user = room.player2

    active_deck = UserDeck.objects.filter(
        user=active_user, is_active=True
    ).first()

    if active_deck:
    # Get ALL cards in active deck — main cards AND prize cards
        deck_card_ids = DeckCard.objects.filter(
            deck=active_deck
        ).values_list('player_card_id', flat=True)

        available_cards = PlayerCard.objects.filter(
            id__in=deck_card_ids
        ).exclude(id__in=my_used)
    else:
        available_cards = PlayerCard.objects.exclude(id__in=my_used)
    
 

    waiting_for_opponent = i_played and not opp_played

    from .models import SupportCard
    support_cards  = SupportCard.objects.all()
    active_support = state.get(f'{my_role}_support')
    if active_support and round_number >= active_support.get('until_round', 0):
        active_support = None

    context = {
        'room':                 room,
        'innings':              innings,
        'round_number':         round_number,
        'batting_team':         batting_team,
        'my_role':              my_role,
        'opponent_name':        opponent_name,
        'available_cards':      available_cards,
        'waiting_for_opponent': waiting_for_opponent,
        'message':              state.get('message', ''),
        'p1_runs':              state['scores']['player1'],
        'p2_runs':              state['scores']['player2'],
        'p1_wickets':           state['wickets']['player1'],
        'p2_wickets':           state['wickets']['player2'],
        'last_batter':          state.get('last_batter'),
        'last_bowler':          state.get('last_bowler'),
        'support_cards':        support_cards,
        'active_support':       active_support,
        'support_used':         state.get(f'{my_role}_support_used', False),
    }
    if innings == 2:
        context['target'] = state.get('target')

    return render(request, 'mp_game.html', context)
def _apply_abilities(batter_card, bowler_card, round_number, state, batting_team):
    batting = batter_card.batting
    bowling = bowler_card.bowling
    runs    = batter_card.runs
    log     = []

    scores  = state.get('scores', {})
    wickets = state.get('wickets', {})

    # ── BATTING ABILITIES (independent if blocks) ────────────────
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

    # ── BOWLING ABILITIES (independent if blocks) ────────────────
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
    # ── SUPPORT CARD EFFECTS ─────────────────────────────────────
    # Determine who is batting and who is bowling by role
    if batting_team == 'player1':
        batter_role = 'player1'
        bowler_role = 'player2'
    else:
        batter_role = 'player2'
        bowler_role = 'player1'

    # Batter's support card
    batter_support = state.get(f'{batter_role}_support')
    if batter_support:
        s_from  = batter_support.get('from_round', 0)
        s_until = batter_support.get('until_round', 0)
        s_type  = batter_support.get('type')
        if s_from <= round_number <= s_until:      # ← was < s_until, now <= so last round included
            if s_type == 'batting_support':
                batting += 2
                log.append("🟢 Batting Support: +2 batting!")

    # Bowler's support card
    bowler_support = state.get(f'{bowler_role}_support')
    if bowler_support:
        s_from  = bowler_support.get('from_round', 0)
        s_until = bowler_support.get('until_round', 0)
        s_type  = bowler_support.get('type')
        if s_from <= round_number <= s_until:      # ← same fix
            if s_type == 'pace_support' and not bowler_card.is_spinner:
                bowling += 2
                log.append("⚡ Pace Support: +2 bowling!")
            elif s_type == 'spin_support' and bowler_card.is_spinner:
                bowling += 2
                log.append("🌀 Spin Support: +2 bowling!")

    return batting, bowling, runs, runs_cutter_active, log

# ─── result ──────────────────────────────────────────────────────────────────

@login_required
def mp_result(request, code):
    room = get_object_or_404(GameRoom, code=code)
    state = room.state or {}

    if not state.get('game_over'):
        return redirect('mp_game', code=code)

    batting_first = state.get('batting_first', 'player1')
    second_batting = 'player2' if batting_first == 'player1' else 'player1'
    winner_role = state.get('winner')

    my_role = _my_role(request, room)
    i_won = (winner_role == my_role)

    winner_name = 'Tie' if winner_role == 'Tie' else _get_player(room, winner_role).username

    return render(request, 'mp_result.html', {
        'room': room,
        'winner': winner_name,
        'i_won': i_won,
        'p1_name': room.player1.username,
        'p2_name': room.player2.username if room.player2 else 'Player 2',
        'first_score': state['scores'][batting_first],
        'second_score': state['scores'][second_batting],
        'first_wickets': state['wickets'][batting_first],
        'second_wickets': state['wickets'][second_batting],

        
    })
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction
from .models import UserDeck, DeckCard, PlayerCard, Team


# ── My Decks page ─────────────────────────────────────────────────────────

@login_required
def my_decks(request):
    decks = UserDeck.objects.filter(
        user=request.user
    ).prefetch_related('deckcard_set__player_card')

    # All PlayerCards assigned as prize cards to this user
    prize_card_objects = PlayerCard.objects.filter(
        userprizecard__user=request.user
    )

    if request.method == 'POST':
        pass  # set_active_deck handles this via its own URL

    return render(request, 'my_decks.html', {
        'decks':             decks,
        'prize_card_objects': prize_card_objects,
    })

# ── Create a new deck (pick a team) ───────────────────────────────────────

@login_required
def create_deck(request):
    user_deck_count = UserDeck.objects.filter(user=request.user).count()
    if user_deck_count >= 2:
        return render(request, 's7app/create_deck.html', {
            'error': 'You can only have 2 decks. Delete one to create another.',
            'teams': Team.objects.all(),
        })

    if request.method == 'POST':
        team_id   = request.POST.get('team_id')
        deck_name = request.POST.get('deck_name', '').strip()
        team      = get_object_or_404(Team, id=team_id)

        deck = UserDeck.objects.create(
            user=request.user,
            team=team,
            name=deck_name or f"{team.name} Deck",
        )
        return redirect('build_deck', deck_id=deck.id)

    teams = Team.objects.all()
    return render(request, 'create_deck.html', {'teams': teams})


# ── Build / edit deck (add cards, stay under weightage 32) ────────────────
from django.contrib.auth import logout as auth_logout
from django.shortcuts import redirect
from django.db.models import Q
from .models import UserPrizeCard
def logout_view(request):
    auth_logout(request)
    return redirect('login')
# @login_required
# def swap_card(request, deck_id):
#     deck = get_object_or_404(UserDeck, id=deck_id, user=request.user)

#     main_cards = DeckCard.objects.filter(
#         deck=deck
#     ).select_related('player_card').exclude(
#         player_card__id__in=UserPrizeCard.objects.filter(
#             user=request.user
#         ).values_list('player_card_id', flat=True)
#     )

#     user_prize_cards = UserPrizeCard.objects.filter(
#         user=request.user
#     ).filter(
#         Q(deck=None) | Q(deck=deck)
#     ).select_related('player_card')

#     if request.method == 'POST':
#         main_dc_id   = int(request.POST.get('main_card_id'))
#         prize_upc_id = int(request.POST.get('prize_card_id'))

#         main_dc   = get_object_or_404(DeckCard,       id=main_dc_id,   deck=deck)
#         prize_upc = get_object_or_404(UserPrizeCard,  id=prize_upc_id, user=request.user)

#         # Block if prize already in another deck
#         if prize_upc.deck and prize_upc.deck != deck:
#             return render(request, 's7app/swap_card.html', {
#                 'deck':             deck,
#                 'main_cards':       main_cards,
#                 'user_prize_cards': user_prize_cards,
#                 'error':            f'{prize_upc.player_card.name} is already used in another deck.',
#             })

#         # Weightage check
#         new_total = (
#             deck.total_weightage()
#             - main_dc.player_card.weightage
#             + prize_upc.player_card.weightage
#         )
#         if new_total > 32:
#             return render(request, 's7app/swap_card.html', {
#                 'deck':             deck,
#                 'main_cards':       main_cards,
#                 'user_prize_cards': user_prize_cards,
#                 'error':            f'Swap exceeds weightage limit of 32! (would be {new_total})',
#             })

#         with transaction.atomic():
#             # Remove main card from deck
#             main_dc.delete()

#             # Add prize card only if not already in deck (fix integrity error)
#             DeckCard.objects.get_or_create(
#                 deck=deck,
#                 player_card=prize_upc.player_card
#             )

#             # Mark prize card as slotted into this deck
#             prize_upc.deck = deck
#             prize_upc.save()

#         return redirect('build_deck', deck_id=deck.id)

#     return render(request, 'swap_card.html', {
#         'deck':             deck,
#         'main_cards':       main_cards,
#         'user_prize_cards': user_prize_cards,
#         'total_w':          deck.total_weightage(),
#     })
# @login_required
# def build_deck(request, deck_id):
#     deck = get_object_or_404(UserDeck, id=deck_id, user=request.user)

#     team_cards = PlayerCard.objects.filter(team=deck.team)

#     user_prize_cards = UserPrizeCard.objects.filter(
#         user=request.user
#     ).filter(
#         Q(deck=None) | Q(deck=deck)
#     ).select_related('player_card')

#     prize_card_ids = list(
#         UserPrizeCard.objects.filter(
#             user=request.user
#         ).values_list('player_card_id', flat=True)
#     )

#     current_cards = DeckCard.objects.filter(deck=deck).select_related('player_card')
#     current_ids   = list([dc.player_card.id for dc in current_cards])

#     main_in_deck  = [dc for dc in current_cards if dc.player_card.id not in prize_card_ids]
#     prize_in_deck = [dc for dc in current_cards if dc.player_card.id in prize_card_ids]

#     total_w = deck.total_weightage()
#     error   = None

#     if request.method == 'POST':
#         action  = request.POST.get('action')
#         card_id = int(request.POST.get('card_id'))
#         card    = get_object_or_404(PlayerCard, id=card_id)
#         is_prize = card.id in prize_card_ids

#         if action == 'add':
#             if card.id in current_ids:
#                 error = 'Card already in deck!'
#             elif not is_prize and len(main_in_deck) >= 9:
#                 error = 'Max 9 main cards allowed!'
#             elif total_w + card.weightage > 32:
#                 error = f'Adding {card.name} exceeds weightage limit of 32!'
#             else:
#                 DeckCard.objects.get_or_create(deck=deck, player_card=card)
#                 if is_prize:
#                     upc = UserPrizeCard.objects.filter(
#                         user=request.user, player_card=card
#                     ).first()
#                     if upc:
#                         upc.deck = deck
#                         upc.save()
#                 return redirect('build_deck', deck_id=deck.id)

#         elif action == 'remove':
#             DeckCard.objects.filter(deck=deck, player_card=card).delete()
#             if card.id in prize_card_ids:
#                 upc = UserPrizeCard.objects.filter(
#                     user=request.user, player_card=card
#                 ).first()
#                 if upc:
#                     upc.deck = None   # free prize card
#                     upc.save()
#             return redirect('build_deck', deck_id=deck.id)

#     context = {
#         'deck':             deck,
#         'team_cards':       team_cards,       # ALL team cards, HTML decides add/remove
#         'user_prize_cards': user_prize_cards,
#         'current_cards':    current_cards,
#         'main_in_deck':     main_in_deck,
#         'prize_in_deck':    prize_in_deck,
#         'prize_card_ids':   prize_card_ids,
#         'current_ids':      current_ids,
#         'total_w':          total_w,
#         'remaining_w':      32 - total_w,
#         'error':            error,
#     }
#     return render(request, 'build_deck.html', context)
@login_required
def set_active_deck(request, deck_id):
    deck = get_object_or_404(UserDeck, id=deck_id, user=request.user)

    # Deactivate all other decks for this user
    UserDeck.objects.filter(user=request.user).update(is_active=False)
    deck.is_active = True
    deck.save()

    return redirect('my_decks')
@login_required
def build_deck(request, deck_id):
    deck = get_object_or_404(UserDeck, id=deck_id, user=request.user)

    current_cards = DeckCard.objects.filter(deck=deck).select_related('player_card')
    current_ids   = list(current_cards.values_list('player_card_id', flat=True))

    # Prize card ids assigned to this user (all, regardless of deck)
    prize_card_ids = list(
        UserPrizeCard.objects.filter(
            user=request.user
        ).values_list('player_card_id', flat=True)
    )

    main_in_deck  = [dc for dc in current_cards if dc.player_card.id not in prize_card_ids]
    prize_in_deck = [dc for dc in current_cards if dc.player_card.id in prize_card_ids]

    # Available main cards = team cards not currently in deck
    available_main_cards = PlayerCard.objects.filter(
        team=deck.team
    ).exclude(id__in=current_ids)

    # Available prize cards = assigned to user, either unused (deck=None) OR in THIS deck
    available_prize_cards = UserPrizeCard.objects.filter(
        user=request.user
    ).filter(
        Q(deck=None) | Q(deck=deck)   # ← key fix: show both unused AND already-in-this-deck
    ).select_related('player_card')

    total_w = deck.total_weightage()
    error   = None

    if request.method == 'POST':
        action  = request.POST.get('action')
        card_id = int(request.POST.get('card_id'))
        card    = get_object_or_404(PlayerCard, id=card_id)
        is_prize = card.id in prize_card_ids

        if action == 'add':
            if card.id in current_ids:
                error = 'Card already in deck!'
            elif not is_prize and len(main_in_deck) >= 9:
                error = 'Max 9 main cards allowed!'
            elif total_w + card.weightage > 32:
                error = f'Adding {card.name} exceeds weightage limit of 32!'
            else:
                DeckCard.objects.get_or_create(deck=deck, player_card=card)
                if is_prize:
                    UserPrizeCard.objects.filter(
                        user=request.user, player_card=card
                    ).update(deck=deck)
                return redirect('build_deck', deck_id=deck.id)

        elif action == 'remove':
            DeckCard.objects.filter(deck=deck, player_card=card).delete()
            if is_prize:
                UserPrizeCard.objects.filter(
                    user=request.user, player_card=card
                ).update(deck=None)
            return redirect('build_deck', deck_id=deck.id)

    context = {
        'deck':                  deck,
        'current_cards':         current_cards,
        'main_in_deck':          main_in_deck,
        'prize_in_deck':         prize_in_deck,
        'prize_card_ids':        prize_card_ids,
        'current_ids':           current_ids,
        'available_main_cards':  available_main_cards,
        'available_prize_cards': available_prize_cards,
        'total_w':               total_w,
        'remaining_w':           32 - total_w,
        'error':                 error,
    }
    return render(request, 'build_deck.html', context)

@login_required
def swap_card(request, deck_id):
    deck = get_object_or_404(UserDeck, id=deck_id, user=request.user)

    # All cards currently in deck (to pick which to swap OUT)
    main_cards = DeckCard.objects.filter(deck=deck).select_related('player_card')

    # ALL prize cards assigned to this user — no deck filter
    available_prize_cards = UserPrizeCard.objects.filter(
        user=request.user
    ).select_related('player_card')

    if request.method == 'POST':
        main_dc_id   = int(request.POST.get('main_card_id'))
        prize_upc_id = int(request.POST.get('prize_card_id'))

        main_dc   = get_object_or_404(DeckCard,      id=main_dc_id,  deck=deck)
        prize_upc = get_object_or_404(UserPrizeCard, id=prize_upc_id, user=request.user)

        # Block if prize already locked in the OTHER deck
        other_deck = UserDeck.objects.filter(
            user=request.user
        ).exclude(id=deck.id).first()

        if prize_upc.deck and prize_upc.deck != deck:
            return render(request, 's7app/swap_card.html', {
                'deck':                  deck,
                'main_cards':            main_cards,
                'available_prize_cards': available_prize_cards,
                'error': f'{prize_upc.player_card.name} is already used in your other deck.',
            })

        # Weightage check
        new_total = (
            deck.total_weightage()
            - main_dc.player_card.weightage
            + prize_upc.player_card.weightage
        )
        if new_total > 32:
            return render(request, 's7app/swap_card.html', {
                'deck':                  deck,
                'main_cards':            main_cards,
                'available_prize_cards': available_prize_cards,
                'error': f'Swap exceeds weightage limit of 32! (would be {new_total})',
            })

        with transaction.atomic():
            # Remove chosen deck card
            main_dc.delete()
            # Add prize card into deck
            DeckCard.objects.get_or_create(deck=deck, player_card=prize_upc.player_card)
            # Lock prize card to this deck
            prize_upc.deck = deck
            prize_upc.save()

        return redirect('build_deck', deck_id=deck.id)

    return render(request, 'swap_card.html', {
        'deck':                  deck,
        'main_cards':            main_cards,
        'available_prize_cards': available_prize_cards,
        'total_w':               deck.total_weightage(),
    })