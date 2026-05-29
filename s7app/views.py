import csv
from django.shortcuts import render, redirect
import random
from .models import GameRoom, PlayerCard
import os
from datetime import datetime
from collections import defaultdict

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
            return render(request, 's7app/lobby.html', {'error': f'Room "{code}" not found.'})

        # Already player1 — just go to waiting room
        if request.user == room.player1:
            return redirect('waiting_room', code=room.code)

        # Room already full with a different player2
        if room.player2 and room.player2 != request.user:
            return render(request, 's7app/lobby.html', {'error': 'Room is already full.'})

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

    # Apply all abilities
    eff_batting, eff_bowling, eff_runs, runs_cutter_active, ability_log = _apply_abilities(
        batter_card, bowler_card, round_number, state, batting_team
    )

    import math

    # Score the round
    if eff_batting > eff_bowling:
        if runs_cutter_active:
            eff_runs = max(0, eff_runs - 10)
            ability_log.append("✂️ Runs Cutter: -10 runs!")

        state['scores'][batting_team] += eff_runs
        state[f'runs_in_round_{innings}_{round_number}'] = eff_runs
        state[f'wicket_in_round_{innings}_{round_number}'] = False

        ability_str = "  |  " + "  ".join(ability_log) if ability_log else ""
        state['message'] = f"Runs added: {eff_runs}!{ability_str}"

    elif eff_batting == eff_bowling:
        partial = eff_runs / 3
        awarded = math.floor(partial + 0.5)

        if runs_cutter_active:
            awarded = max(0, awarded - 10)
            ability_log.append("✂️ Runs Cutter: -10 runs!")

        state['scores'][batting_team] += awarded
        state[f'runs_in_round_{innings}_{round_number}'] = awarded
        state[f'wicket_in_round_{innings}_{round_number}'] = False

        ability_str = "  |  " + "  ".join(ability_log) if ability_log else ""
        state['message'] = f"Tie! Partial runs: {awarded}!{ability_str}"

    else:
        state['wickets'][batting_team] += 1
        state[f'runs_in_round_{innings}_{round_number}'] = 0
        state[f'wicket_in_round_{innings}_{round_number}'] = True

        ability_str = "  |  " + "  ".join(ability_log) if ability_log else ""
        state['message'] = f"Wicket! 🎯{ability_str}"

    # Save last played cards for display
    state['last_batter'] = {
        'name':    batter_card.name,
        'image':   batter_card.image.url if batter_card.image else None,
        'ability': batter_card.ability,
    }
    state['last_bowler'] = {
        'name':    bowler_card.name,
        'image':   bowler_card.image.url if bowler_card.image else None,
        'ability': bowler_card.ability,
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
def mp_game(request, code):
    room = get_object_or_404(GameRoom, code=code)
    state = room.state or {}
    my_role  = _my_role(request, room)
    opp_role = _opponent_role(my_role)
    opponent_name = _get_player(room, opp_role).username

    # ── Redirect both players to result as soon as game_over is set ──
    if state.get('game_over'):
        return redirect('mp_result', code=code)

    innings      = state.get('innings', 1)
    round_number = state.get('round_number', 1)
    batting_first = state.get('batting_first', 'player1')

    # Who is batting this innings?
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

    if request.method == 'POST' and request.POST.get('action') == 'play_card':
        if i_played:
            return redirect('mp_game', code=code)

        selected_id = int(request.POST.get('selected_card_id'))

        # Save this player's card
        state[my_played_key] = selected_id
        my_used.append(selected_id)
        state[f'used_by_{my_role}'] = my_used
        room.state = state
        room.save()

        # Check if opponent already played this round
        room.refresh_from_db()
        state = room.state
        opp_played_now = state.get(opp_played_key) is not None

        if opp_played_now:
            # Both played — resolve round (handles game_over internally)
            _resolve_round(room, innings, round_number, batting_team, batting_first)
            room.refresh_from_db()
            state = room.state

            # Redirect both players if game is over
            if state.get('game_over'):
                return redirect('mp_result', code=code)

        return redirect('mp_game', code=code)

    # ── GET: render game page ──
    available_cards = PlayerCard.objects.exclude(id__in=my_used)

    # Player already submitted this round — waiting for opponent
    waiting_for_opponent = i_played and not opp_played

    last_batter = state.get('last_batter')
    last_bowler = state.get('last_bowler')

    context = {
        'room': room,
        'innings': innings,
        'round_number': round_number,
        'batting_team': batting_team,
        'my_role': my_role,
        'opponent_name': opponent_name,
        'available_cards': available_cards,
        'waiting_for_opponent': waiting_for_opponent,
        'message': state.get('message', ''),
        'p1_runs':    state['scores']['player1'],
        'p2_runs':    state['scores']['player2'],
        'p1_wickets': state['wickets']['player1'],
        'p2_wickets': state['wickets']['player2'],
        'last_batter': last_batter,
        'last_bowler': last_bowler,
    }
    if innings == 2:
        context['target'] = state.get('target')

    return render(request, 'mp_game.html', context)
def _apply_abilities(batter_card, bowler_card, round_number, state, batting_team):
    """
    Returns (effective_batting, effective_bowling, effective_runs, ability_log)
    ability_log is a list of strings describing what fired, shown to players.
    """
    batting  = batter_card.batting
    bowling  = bowler_card.bowling
    runs     = batter_card.runs
    log      = []

    scores  = state.get('scores', {})
    wickets = state.get('wickets', {})

    # ── BATTING ABILITIES ────────────────────────────────────────────────────

    # Opener: +10 batting in rounds 1-2
    if batter_card.ability == 'opener' and round_number <= 2:
        batting += 10
        log.append("⚡ Opener ability: +10 batting!")

    # Finisher: +10 batting in rounds 6-7
    elif batter_card.ability == 'finisher' and round_number >= 6:
        batting += 10
        log.append("💥 Finisher ability: +10 batting!")

    # Mid Over Hitter: +10 batting in rounds 3-5
    elif batter_card.ability == 'mid_over_hitter' and 3 <= round_number <= 5:
        batting += 10
        log.append("🏏 Mid Over Hitter ability: +10 batting!")

    # Spin Basher: +10 batting if bowler is a spinner
    elif batter_card.ability == 'spin_basher' and bowler_card.is_spinner:
        batting += 10
        log.append("🌀 Spin Basher ability: +10 batting vs spinner!")

    # Saviour: +10 batting if a wicket fell in either of the last 2 rounds
    elif batter_card.ability == 'saviour':
        # Check wickets recorded in round-1 and round-2 (previous 2 rounds)
        prev_rounds = [round_number - 1, round_number - 2]
        innings = state.get('innings', 1)
        wicket_fell = any(
            state.get(f'wicket_in_round_{innings}_{r}') for r in prev_rounds if r >= 1
        )
        if wicket_fell:
            batting += 10
            log.append("🛡️ Saviour ability: +10 batting after recent wicket!")

    # ── BOWLING ABILITIES ────────────────────────────────────────────────────

    # Powerplay Specialist: +10 bowling in rounds 1-2
    if bowler_card.ability == 'powerplay_specialist' and round_number <= 2:
        bowling += 10
        log.append("🔥 Powerplay Specialist: +10 bowling!")

    # Death Specialist: +10 bowling in rounds 6-7
    elif bowler_card.ability == 'death_specialist' and round_number >= 6:
        bowling += 10
        log.append("💀 Death Specialist: +10 bowling!")

    # Mid Over Specialist: +10 bowling in rounds 3-5
    elif bowler_card.ability == 'mid_over_specialist' and 3 <= round_number <= 5:
        bowling += 10
        log.append("🎯 Mid Over Specialist: +10 bowling!")

    # Golden Arm: +10 bowling if 30+ runs scored collectively in last 2 rounds
    elif bowler_card.ability == 'golden_arm':
        innings = state.get('innings', 1)
        prev_runs = sum(
            state.get(f'runs_in_round_{innings}_{r}', 0)
            for r in [round_number - 1, round_number - 2] if r >= 1
        )
        if prev_runs >= 30:
            bowling += 10
            log.append(f"💛 Golden Arm: +10 bowling ({prev_runs} runs in last 2 rounds)!")

    # Breakthrough: +10 bowling if opponent crossed 60 runs
    elif bowler_card.ability == 'breakthrough':
        opponent_score = scores.get(batting_team, 0)
        if opponent_score >= 60:
            bowling += 10
            log.append(f"🚨 Breakthrough: +10 bowling (opponent at {opponent_score} runs)!")

    # Runs Cutter: -10 runs if batter wins BUT batter is NOT spin_basher
    # (handled after comparison — returned as a flag)
    runs_cutter_active = (
        bowler_card.ability == 'runs_cutter'
        and batter_card.ability != 'spin_basher'
    )

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