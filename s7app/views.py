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
from .game_cache import get_game_state, save_game_state, delete_game_state
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
    # In create_room view, when room is created
    active_deck = UserDeck.objects.filter(user=request.user, is_active=True).first()
    room.player1_deck = active_deck
    room.save()


    return redirect('room_lobby', code=code)

def join_room(request, code):
    room = GameRoom.objects.get(code=code)
    room.player2 = request.user
        # In join_room view, when player2 joins
    active_deck = UserDeck.objects.filter(user=request.user, is_active=True).first()
    room.player2_deck = active_deck
    room.save()
    return redirect('game_room', code=code)


from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login as auth_login, logout as auth_logout, authenticate
from django.shortcuts import render, redirect
from django.contrib import messages

def register(request):
    if request.user.is_authenticated:
        return redirect('my_decks')

    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            return redirect('my_decks')
    else:
        form = UserCreationForm()

    return render(request, 'register.html', {'form': form})


def login(request):
    if request.user.is_authenticated:
        return redirect('my_decks')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user:
            auth_login(request, user)   # ← was login(request, user) — calling itself!
            return redirect(request.POST.get('my_decks') or 'my_decks')
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
    # Check if user has an active deck
    active_deck = UserDeck.objects.filter(
        user=request.user, is_active=True
    ).first()

    has_enough_cards = False
    if active_deck:
        main_card_count = DeckCard.objects.filter(deck=active_deck).count()
        has_enough_cards = main_card_count >= 7   # minimum 7 to play 7 rounds

    return render(request, 'lobby.html', {
        'active_deck':      active_deck,
        'has_enough_cards': has_enough_cards,
    })


@login_required
def create_room(request):
    # Block if no active deck with enough cards
    active_deck = UserDeck.objects.filter(
        user=request.user, is_active=True
    ).first()
    if not active_deck:
        return redirect('lobby')

    main_card_count = DeckCard.objects.filter(deck=active_deck).count()
    if main_card_count < 7:
        return redirect('lobby')

    if request.method == 'POST':
        code = _make_code()
        while GameRoom.objects.filter(code=code).exists():
            code = _make_code()
        room = GameRoom.objects.create(
            code=code, player1=request.user, state={}
        )
        # In create_room view, when room is created
        active_deck = UserDeck.objects.filter(user=request.user, is_active=True).first()
        room.player1_deck = active_deck
        room.save()

# In join_room view, when player2 joins

        return redirect('waiting_room', code=room.code)

    return redirect('lobby')


@login_required
def join_room(request):
    # Block if no active deck with enough cards
    active_deck = UserDeck.objects.filter(
        user=request.user, is_active=True
    ).first()
    if not active_deck:
        return redirect('lobby')

    main_card_count = DeckCard.objects.filter(deck=active_deck).count()
    if main_card_count < 7:
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
            room.player2 = request.user
            active_deck = UserDeck.objects.filter(user=request.user, is_active=True).first()
            room.player2_deck = active_deck
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
    state = get_game_state(code)
    my_role = _my_role(request, room)
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
        save_game_state(room.code, state, save_to_db=False)
        return redirect('mp_toss_result', code=code)

    if state.get('toss_done'):
        return redirect('mp_toss_result', code=code)

    # ── Get both decks ──────────────────────────────
    p1_deck = UserDeck.objects.filter(user=room.player1, is_active=True).first()
    p2_deck = UserDeck.objects.filter(
        user=room.player2, is_active=True
    ).first() if room.player2 else None

    p1_cards = []
    p2_cards = []

    if p1_deck:
        p1_ids = DeckCard.objects.filter(deck=p1_deck).values_list('player_card_id', flat=True)
        p1_cards = list(PlayerCard.objects.filter(id__in=p1_ids))

    if p2_deck:
        p2_ids = DeckCard.objects.filter(deck=p2_deck).values_list('player_card_id', flat=True)
        p2_cards = list(PlayerCard.objects.filter(id__in=p2_ids))

    return render(request, 'mp_toss.html', {
        'room': room,
        'is_toss_caller': is_toss_caller,
        'p1_cards': p1_cards,
        'p2_cards': p2_cards,
        'p1_deck': p1_deck,
        'p2_deck': p2_deck,
    })

# ─── toss result ─────────────────────────────────────────────────────────────

@login_required
def mp_toss_result(request, code):
    room = get_object_or_404(GameRoom, code=code)
    state = get_game_state(code)

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
        save_game_state(room.code, state, save_to_db=False)
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
    state = get_game_state(room.code)

    p1_card_id = state.get(f'player1_played_round_{innings}_{round_number}')
    p2_card_id = state.get(f'player2_played_round_{innings}_{round_number}')

    p1_card = PlayerCard.objects.get(id=p1_card_id)
    p2_card = PlayerCard.objects.get(id=p2_card_id)

    if batting_team == 'player1':
        batter_card, bowler_card = p1_card, p2_card
    else:
        batter_card, bowler_card = p2_card, p1_card

    batter_role = batting_team
    bowler_role = 'player2' if batting_team == 'player1' else 'player1'

    # ── 0. Check if spin_basher will trigger ──────────────
    spin_basher_will_trigger = (
        batter_card.ability == 'spin_basher' 
        and bowler_card.is_spinner
    )

    # ── 1. Read boost BEFORE _apply_abilities clears it ──
    batter_boost_was_active = state.get(f'{batter_role}_boost_active', False)
    bowler_boost_was_active = state.get(f'{bowler_role}_boost_active', False)
    
    # If spin_basher triggers, boost won't be used (show 0)
    batter_boost_bonus = 10 if (batter_boost_was_active and not spin_basher_will_trigger) else 0
    bowler_boost_bonus = 10 if bowler_boost_was_active else 0

    # ── 2. Apply abilities (clears boost_active internally) ──
    eff_batting, eff_bowling, eff_runs, runs_cutter_active, ability_log = _apply_abilities(
        batter_card, bowler_card, round_number, state, batting_team
    )
    
    # ── 2.5. Auto-restore boost if spin_basher was used instead ──
    # If spin_basher triggered AND boost was active before abilities fired
    if spin_basher_will_trigger and batter_boost_was_active:
        # Restore boost for next round
        state[f'{batter_role}_boost_active'] = False   # ← Key change       
        state[f'{batter_role}_boost_used'] = False  # Allow it to be used again
        log_entry = "♻️ Boost restored: Spin Basher used instead!"
        if log_entry not in ability_log:
            ability_log.append(log_entry)

    import math

    # ── 3. Calculate individual bonuses for display ───────
    batter_ability_bonus = eff_batting - batter_card.batting
    bowler_ability_bonus = eff_bowling - bowler_card.bowling

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

    # ── 4. Score the round ────────────────────────────────
    runs_cut_amount = 0  # ← Track how many runs were cut

    if eff_batting > eff_bowling:
        if runs_cutter_active:
            runs_cut_amount = min(10, eff_runs)  # ← How much was actually cut
            eff_runs = max(0, eff_runs - 10)
            ability_log.append("✂️ Runs Cutter: -10 runs!")

        state['scores'][batting_team] += eff_runs
        print(f"✅ Runs added: {eff_runs} to {batting_team}, total: {state['scores'][batting_team]}")  # Debug

        state[f'runs_in_round_{innings}_{round_number}']   = eff_runs
        state[f'wicket_in_round_{innings}_{round_number}'] = False

        ability_str = "  |  " + "  ".join(ability_log) if ability_log else ""
        state['message'] = f"Runs added: {eff_runs}!{ability_str}"

    elif eff_batting == eff_bowling:
        partial = eff_runs / 3
        awarded = math.floor(partial + 0.5)

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

    # ── 5. Calculate actual bonuses for display ──────────
    batter_actual_ability_bonus = (
        eff_batting 
        - batter_card.batting 
        - batter_support_bonus 
        - batter_boost_bonus  
    )

    bowler_actual_ability_bonus = (
        eff_bowling 
        - bowler_card.bowling 
        - bowler_support_bonus 
        - bowler_boost_bonus  
    )

    # ── 6. Save last played cards with all bonuses ────────
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
        'runs_cut':          runs_cut_amount,  # ← Add this

    }

    state['round_number'] = round_number + 1

    current_score   = state['scores'][batting_team]
    current_wickets = state['wickets'][batting_team]
    target          = state.get('target')

    # ── 7. Early end: target chased ───────────────────────
    if innings == 2 and target is not None and current_score >= target:
        state['game_over_pending'] = True
        state['winner'] = batting_team
        save_game_state(room.code, state, save_to_db=True)
        return


    # ── 8. Early end: all out or 7 rounds done ────────────
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
            if innings == 2:
                p1_score = state['scores']['player1']
                p2_score = state['scores']['player2']
                target = state.get('target', 0)

                if p2_score >= target:                    # Chasing team (player2) wins
                    state['winner'] = 'player2'
                    state['game_over'] = True
                elif state['wickets']['player2'] >= 10 or state['round_number'] > 7:
                    # Chasing team failed to reach target
                    state['winner'] = 'player1'           # First innings team wins
                    state['game_over'] = True
                else:
                    state['winner'] = None

    is_game_over = state.get('game_over', False)
    is_game_over_pending = state.get('game_over_pending', False)
    is_innings_transition = bool(state.get('innings_transition'))

    should_save_db = is_game_over or is_game_over_pending or is_innings_transition

    # Save to Redis always, DB only at important moments
    save_game_state(room.code, state, save_to_db=should_save_db)
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"s7app_{room.code}",
            {
                "type": "round_result",
                "message": state.get('message', ''),
                "round": round_number,
                "innings": innings,
            }
        )
    except Exception as e:
        print(f"WebSocket notify failed: {e}")
@login_required
def mp_game(request, code):
    room = get_object_or_404(GameRoom, code=code)
    state = get_game_state(code)
    if room.status in ['waiting', None]:
        room.status = 'live'
        room.save()
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
    # In mp_game view, GET section
    opp_user = room.player2 if my_role == 'player1' else room.player1
    opp_deck = UserDeck.objects.filter(user=opp_user, is_active=True).first()
    opponent_deck_cards = []
    if opp_deck:
        opp_deck_ids = DeckCard.objects.filter(deck=opp_deck).values_list('player_card_id', flat=True)
        opponent_deck_cards = list(PlayerCard.objects.filter(id__in=opp_deck_ids))



    if request.method == 'POST':

        if request.POST.get('action') == 'cancel_boost':
            if state.get(f'{my_role}_boost_active') and not i_played:
                state[f'{my_role}_boost_active'] = False
                state[f'{my_role}_boost_used'] = False
                # ← Redis only (not important enough for DB)
                save_game_state(room.code, state, save_to_db=False)
            return redirect('mp_game', code=code)

        if request.POST.get('action') == 'cancel_support':
            if state.get(f'{my_role}_support_used') and not i_played:
                state[f'{my_role}_support_used'] = False
                state[f'{my_role}_support'] = None
                # ← Redis only
                save_game_state(room.code, state, save_to_db=False)
            return redirect('mp_game', code=code)

        if request.POST.get('action') == 'use_boost':
            if not state.get(f'{my_role}_boost_used'):
                state[f'{my_role}_boost_used'] = True
                state[f'{my_role}_boost_active'] = True
                # ← Redis only
                save_game_state(room.code, state, save_to_db=False)
            return redirect('mp_game', code=code)

        if request.POST.get('action') == 'use_support':
            if not state.get(f'{my_role}_support_used'):
                support_type = request.POST.get('support_type')
                state[f'{my_role}_support'] = {
                    'type': support_type,
                    'from_round': round_number,
                    'until_round': round_number + 3,
                }
                state[f'{my_role}_support_used'] = True
                # ← Redis only
                save_game_state(room.code, state, save_to_db=False)
            return redirect('mp_game', code=code)

        if request.POST.get('action') == 'continue_innings':
            transition = state.get('innings_transition')
            if transition:
                state['target'] = transition['target']
                state['innings'] = 2
                state['round_number'] = 1
                state['used_by_player1'] = []
                state['used_by_player2'] = []
                state['player1_support'] = None
                state['player2_support'] = None
                state['last_batter'] = None
                state['last_bowler'] = None
                state['message'] = ''
                del state['innings_transition']
                # ← Save to BOTH (innings change is important)
                save_game_state(code, state, save_to_db=True)
            return redirect('mp_game', code=code)

        if request.POST.get('action') == 'continue_result':
            if state.get('game_over_pending'):
                state['game_over'] = True
                del state['game_over_pending']
                save_game_state(code, state, save_to_db=True)
            return redirect('mp_result', code=code)

        if request.POST.get('action') == 'play_card':
            if state.get(my_played_key) is not None:
                return redirect('mp_game', code=code)

            selected_id = int(request.POST.get('selected_card_id'))
            
            state[my_played_key] = selected_id
            my_used = state.get(f'used_by_{my_role}', [])
            if selected_id not in my_used:
                my_used.append(selected_id)
            state[f'used_by_{my_role}'] = my_used

            # Save to Redis
            save_game_state(room.code, state, save_to_db=False)

            # Refresh state from Redis to check opponent
            state = get_game_state(code)
            opp_played_now = state.get(opp_played_key) is not None

            if opp_played_now:
                _resolve_round(room, innings, round_number, batting_team, batting_first)
                state = get_game_state(code)   # Refresh again after resolve
                if state.get('game_over'):
                    return redirect('mp_result', code=code)

            return redirect('mp_game', code=code)
    # ── GET ───────────────────────────────────────────────────────

    # ── ONLY THIS BLOCK CHANGED — active deck cards ───────────────
    state = get_game_state(code)

    my_used = state.get(f'used_by_{my_role}', [])
    opp_used = state.get(f'used_by_{opp_role}', [])

    i_played = state.get(my_played_key) is not None
    opp_played = state.get(opp_played_key) is not None

    # ── Active Deck Cards (correct filtering) ──────────────────
    active_user = room.player1 if my_role == 'player1' else room.player2
    active_deck = UserDeck.objects.filter(user=active_user, is_active=True).first()
    available_cards = PlayerCard.objects.none()

    if active_deck:
        # Correct: filter PlayerCard IDs from DeckCard
        deck_card_ids = DeckCard.objects.filter(
            deck=active_deck
        ).values_list('player_card_id', flat=True)

        available_cards = PlayerCard.objects.filter(
            id__in=deck_card_ids
        ).exclude(id__in=my_used)
    else:
        available_cards = PlayerCard.objects.exclude(id__in=my_used)

    waiting_for_opponent = i_played and not opp_played

    # ── Helper Calculations ───────────────────────────────────────
    last_wicket_in_round = any(
        state.get(f'wicket_in_round_{innings}_{r}')
        for r in [round_number - 1, round_number - 2] if r >= 1
    )

    recent_runs = sum(
        state.get(f'runs_in_round_{innings}_{r}', 0)
        for r in [round_number - 1, round_number - 2] if r >= 1
    )
    recent_runs_high = recent_runs >= 30

    opponent_team = 'player2' if my_role == 'player1' else 'player1'
    opponent_score = state.get('scores', {}).get(opponent_team, 0)
    opponent_score_high = opponent_score >= 60

    from .models import SupportCard
    support_cards = SupportCard.objects.all()
    active_support = state.get(f'{my_role}_support')
    if active_support and round_number >= active_support.get('until_round', 0):
        active_support = None

    batting_first = state.get('batting_first', 'player1')
    bowling_first = 'player2' if batting_first == 'player1' else 'player1'

    # ── Timeline (innings 1) ──────────────────────────────────────
    innings1_timeline = []
    for r in range(1, round_number if innings == 1 else 8):
        batter_id = state.get(f'{batting_first}_played_round_1_{r}')
        bowler_id = state.get(f'{bowling_first}_played_round_1_{r}')
        if batter_id and bowler_id:
            try:
                batter_card = PlayerCard.objects.get(id=batter_id)
                bowler_card = PlayerCard.objects.get(id=bowler_id)
                innings1_timeline.append({
                    'round': r,
                    'batter': batter_card.name,
                    'batter_image': batter_card.image.url if batter_card.image else None,
                    'bowler': bowler_card.name,
                    'bowler_image': bowler_card.image.url if bowler_card.image else None,
                    'runs': state.get(f'runs_in_round_1_{r}', 0),
                    'wicket': state.get(f'wicket_in_round_1_{r}', False),
                })
            except PlayerCard.DoesNotExist:
                pass

    # ── Timeline (innings 2) ──────────────────────────────────────
    innings2_timeline = []
    if innings == 2:
        batting_second = bowling_first
        bowling_second = batting_first
        for r in range(1, round_number):
            batter_id = state.get(f'{batting_second}_played_round_2_{r}')
            bowler_id = state.get(f'{bowling_second}_played_round_2_{r}')
            if batter_id and bowler_id:
                try:
                    batter_card = PlayerCard.objects.get(id=batter_id)
                    bowler_card = PlayerCard.objects.get(id=bowler_id)
                    innings2_timeline.append({
                        'round': r,
                        'batter': batter_card.name,
                        'batter_image': batter_card.image.url if batter_card.image else None,
                        'bowler': bowler_card.name,
                        'bowler_image': bowler_card.image.url if bowler_card.image else None,
                        'runs': state.get(f'runs_in_round_2_{r}', 0),
                        'wicket': state.get(f'wicket_in_round_2_{r}', False),
                    })
                except PlayerCard.DoesNotExist:
                    pass

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
        'p1_runs':              state.get('scores', {}).get('player1', 0),
        'p2_runs':              state.get('scores', {}).get('player2', 0),
        'p1_wickets':           state.get('wickets', {}).get('player1', 0),
        'p2_wickets':           state.get('wickets', {}).get('player2', 0),
        'last_batter':          state.get('last_batter'),
        'last_bowler':          state.get('last_bowler'),
        'support_cards':        support_cards,
        'active_support':       active_support,
        'support_used':         state.get(f'{my_role}_support_used', False),
        'innings_transition':   state.get('innings_transition'),
        'game_over_pending':    state.get('game_over_pending'),
        'boost_used':           state.get(f'{my_role}_boost_used', False),
        'boost_active':         state.get(f'{my_role}_boost_active', False),
        'last_wicket_in_round': last_wicket_in_round,
        'recent_runs_high':     recent_runs_high,
        'opponent_score_high':  opponent_score_high,
        'opponent_deck_cards':  opponent_deck_cards,
        'innings1_timeline':    innings1_timeline,
        'innings2_timeline':    innings2_timeline,
    }

    # ── Chasing context (innings 2) ─────────────────────────────
    if innings == 2:
        context['target'] = state.get('target')
        chasing_team = batting_team
        chasing_runs = state.get('scores', {}).get(chasing_team, 0)
        target_val = state.get('target', 0)
        context['runs_needed'] = max(0, target_val - chasing_runs)
        context['rounds_remaining'] = max(0, 8 - round_number)

    return render(request, 'mp_game.html', context)

def _apply_abilities(batter_card, bowler_card, round_number, state, batting_team):
    batting = batter_card.batting
    bowling = bowler_card.bowling
    runs    = batter_card.runs
    log     = []

    scores  = state.get('scores', {})
    wickets = state.get('wickets', {})

    # ── Determine roles ──────────────────────────────────
    if batting_team == 'player1':
        batter_role = 'player1'
        bowler_role = 'player2'
    else:
        batter_role = 'player2'
        bowler_role = 'player1'

    # ── CHECK: Will spin_basher trigger? ─────────────────
    spin_basher_will_trigger = (
        batter_card.ability == 'spin_basher' 
        and bowler_card.is_spinner
    )

    # ── BATTING ABILITIES ────────────────────────────────
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

    # ── BOWLING ABILITIES ────────────────────────────────
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

    # ── BOOST EFFECT — BUT NOT if spin_basher will trigger ──
    if state.get(f'{batter_role}_boost_active'):
        # Only add boost if spin_basher won't trigger
        if not spin_basher_will_trigger:
            batting += 10
            log.append("🚀 Boost: +10 batting!")
        # Consume boost after this round (whether used or not)
        state[f'{batter_role}_boost_active'] = False

    if state.get(f'{bowler_role}_boost_active'):
        bowling += 10
        log.append("🚀 Boost: +10 bowling!")
        state[f'{bowler_role}_boost_active'] = False

    # ── SUPPORT CARD EFFECTS ─────────────────────────────
    batter_support = state.get(f'{batter_role}_support')
    if batter_support:
        s_from  = batter_support.get('from_round', 0)
        s_until = batter_support.get('until_round', 0)
        s_type  = batter_support.get('type')
        if s_from <= round_number <= s_until:
            if s_type == 'batting_support':
                batting += 2
                log.append("🟢 Batting Support: +2 batting!")

    bowler_support = state.get(f'{bowler_role}_support')
    if bowler_support:
        s_from  = bowler_support.get('from_round', 0)
        s_until = bowler_support.get('until_round', 0)
        s_type  = bowler_support.get('type')
        if s_from <= round_number <= s_until:
            if s_type == 'pace_support' and not bowler_card.is_spinner:
                bowling += 2
                log.append("⚡ Pace Support: +2 bowling!")
            elif s_type == 'spin_support' and bowler_card.is_spinner:
                bowling += 2
                log.append("🌀 Spin Support: +2 bowling!")

    return batting, bowling, runs, runs_cutter_active, log

# ─── result ──────────────────────────────────────────────────────────────────

def mp_result(request, code):
    room = get_object_or_404(GameRoom, code=code)
    
    # Try Redis first, then fallback to DB
    state = get_game_state(code)
    
    # If Redis empty, load from DB (happens when second player loads result)
    if not state or 'winner' not in state:
        state = room.state or {}

    # Save state to DB before deleting Redis
    # This ensures second player can still get data from DB
    if state and 'winner' in state:
        room.state = state
        room.status = 'completed'
        room.save()
    else:
        room.status = 'completed'
        room.save(update_fields=['status'])

    # Safe defaults
    scores  = state.get('scores',  {'player1': 0, 'player2': 0})
    wickets = state.get('wickets', {'player1': 0, 'player2': 0})

    batting_first = state.get('batting_first', 'player1')
    chasing_team  = 'player2' if batting_first == 'player1' else 'player1'

    p1_runs    = scores.get('player1', 0)
    p2_runs    = scores.get('player2', 0)
    p1_wickets = wickets.get('player1', 0)
    p2_wickets = wickets.get('player2', 0)

    target = state.get('target', 0)

    # Use stored winner — don't recalculate
    winner_role = state.get('winner')

    # Only fallback calculate if winner not stored
    if not winner_role:
        if p1_runs == p2_runs:
            winner_role = 'Tie'
        elif p1_runs > p2_runs:
            winner_role = 'player1'
        else:
            winner_role = 'player2'

    my_role = _my_role(request, room)
    i_won = (winner_role == my_role)

    if winner_role == 'Tie':
        winner_name = 'Tie'
    else:
        winner_player = _get_player(room, winner_role)
        winner_name = winner_player.username if winner_player else 'Unknown'

    # Only delete Redis AFTER saving to DB above
    delete_game_state(code)

    context = {
        'room':           room,
        'winner':         winner_name,
        'winner_role':    winner_role,
        'i_won':          i_won,
        'p1_name':        room.player1.username,
        'p2_name':        room.player2.username if room.player2 else 'Player 2',
        'first_score':    scores.get(batting_first, 0),
        'second_score':   scores.get(chasing_team, 0),
        'first_wickets':  wickets.get(batting_first, 0),
        'second_wickets': wickets.get(chasing_team, 0),
        'target':         target,
        'batting_first':  batting_first,
        'chasing_team':   chasing_team,
        'exit_by':        state.get('exit_by'),
        'p1_runs':        p1_runs,
        'p2_runs':        p2_runs,
        'p1_wickets':     p1_wickets,
        'p2_wickets':     p2_wickets,
    }

    return render(request, 'mp_result.html', context)

    return render(request, 'mp_result.html', context)
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction
from .models import UserDeck, DeckCard, PlayerCard, Team

@login_required
def exit_match(request, code):
    if request.method == 'POST':
        room = get_object_or_404(GameRoom, code=code)
        state = get_game_state(code)
        
        if state.get('game_over'):
            return redirect('mp_result', code=code)
        
        my_role = _my_role(request, room)
        opp_role = _opponent_role(my_role)
        if 'scores' not in state:
            state['scores'] = {'player1': 0, 'player2': 0}
        if 'wickets' not in state:
            state['wickets'] = {'player1': 0, 'player2': 0}

        state['game_over'] = True
        state['winner'] = opp_role
        state['exit_by'] = my_role
        
        # ← Save to BOTH (game over)
        save_game_state(code, state, save_to_db=True)
        delete_game_state(code)

        # Notify via WebSocket
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"s7app_{code}",
            {
                "type": "player_exit",
                "message": f"{request.user.username} has exited",
                "exited_by": my_role,
                "winner": opp_role,
                "game_over": True,
            }
        )
        return redirect('mp_result', code=code)

    return redirect('mp_game', code=code)
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
        return render(request, 'create_deck.html', {
            'error': 'You can only have 2 decks. Delete one to create another.',
            'teams': Team.objects.all(),
        })

    if request.method == 'POST':
        team_id   = request.POST.get('team_id')
        deck_name = request.POST.get('deck_name', '').strip()
        team      = get_object_or_404(Team, id=team_id)
        if UserDeck.objects.filter(user=request.user, team=team).exists():
            return render(request, 'create_deck.html', {
                'error': f'You already have a deck for {team.name}.',
                'teams': Team.objects.all(),
            })
        deck = UserDeck.objects.create(
            user=request.user,
            team=team,
            name=deck_name or f"{team.name} Deck",
        )
        players = PlayerCard.objects.filter(team=team)

        DeckCard.objects.bulk_create([
        DeckCard(deck=deck, player_card=player)
        for player in players
        ])

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

@login_required
def exit_match(request, code):
    if request.method != 'POST':
        return redirect('mp_game', code=code)

    room = get_object_or_404(GameRoom, code=code)
    state = get_game_state(code)

    if state.get('game_over'):
        return redirect('mp_result', code=code)

    my_role = _my_role(request, room)
    opp_role = _opponent_role(my_role)

    # Mark game as over
    state['game_over'] = True
    state['winner'] = opp_role
    state['exit_by'] = my_role
    save_game_state(room.code, state, save_to_db=False) 

    # Notify the OTHER player via WebSocket
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
    
    channel_layer = get_channel_layer()
    room_group = f"s7app_{code}"
    
    async_to_sync(channel_layer.group_send)(
        room_group,
        {
            "type": "player_exit",
            "message": f"{request.user.username} has exited the match.\nYou win by default! 🎉",
            "exited_by": my_role,
            "winner": opp_role,
            "game_over": True,
        }
    )

    # Redirect the player who exited
    return redirect('mp_result', code=code)
@login_required
def watch_matches(request):
    """View live and completed matches"""
    live_matches = GameRoom.objects.filter(status='live')
    completed_matches = GameRoom.objects.filter(status='completed').order_by('-created_at')
    
    context = {
        'live_matches': live_matches,
        'completed_matches': completed_matches,
    }
    return render(request, 'watch_matches.html', context)
@login_required
def watch_match_detail(request, code):
    """Watch live match or view completed match"""
    room = get_object_or_404(GameRoom, code=code)
    state = get_game_state(code)
    
    # Build match info
    current_innings = state.get('innings', 1)
    round_number = state.get('round_number', 1)
    batting_first = state.get('batting_first', 'player1')
    
    # Determine batting team for current innings
    if current_innings == 1:
        batting_team = batting_first
    else:
        batting_team = 'player2' if batting_first == 'player1' else 'player1'
    
    bowling_team = 'player2' if batting_team == 'player1' else 'player1'
    
    # Build INNINGS 1 rounds (all 7 or until over)
    innings1_rounds = []
    for r in range(1, 8):
        batter_key = f'{batting_first}_played_round_1_{r}'
        bowler_key = f'{"player2" if batting_first == "player1" else "player1"}_played_round_1_{r}'
        
        batter_card_id = state.get(batter_key)
        bowler_card_id = state.get(bowler_key)
        
        if batter_card_id and bowler_card_id:
            try:
                batter_card = PlayerCard.objects.get(id=batter_card_id)
                bowler_card = PlayerCard.objects.get(id=bowler_card_id)
                
                runs = state.get(f'runs_in_round_1_{r}', 0)
                wicket = state.get(f'wicket_in_round_1_{r}', False)
                
                innings1_rounds.append({
                    'round': r,
                    'batter': batter_card.name,
                    'batter_image': batter_card.image.url if batter_card.image else None,
                    'bowler': bowler_card.name,
                    'bowler_image': bowler_card.image.url if bowler_card.image else None,
                    'runs': runs,
                    'wicket': wicket,
                })
            except PlayerCard.DoesNotExist:
                pass
    
    # Build INNINGS 2 rounds (if match has reached innings 2)
    innings2_rounds = []
    if current_innings >= 2:
        batting_team_2 = 'player2' if batting_first == 'player1' else 'player1'
        bowling_team_2 = batting_first
        
        for r in range(1, 8):
            batter_key = f'{batting_team_2}_played_round_2_{r}'
            bowler_key = f'{bowling_team_2}_played_round_2_{r}'
            
            batter_card_id = state.get(batter_key)
            bowler_card_id = state.get(bowler_key)
            
            if batter_card_id and bowler_card_id:
                try:
                    batter_card = PlayerCard.objects.get(id=batter_card_id)
                    bowler_card = PlayerCard.objects.get(id=bowler_card_id)
                    
                    runs = state.get(f'runs_in_round_2_{r}', 0)
                    wicket = state.get(f'wicket_in_round_2_{r}', False)
                    
                    innings2_rounds.append({
                        'round': r,
                        'batter': batter_card.name,
                        'batter_image': batter_card.image.url if batter_card.image else None,
                        'bowler': bowler_card.name,
                        'bowler_image': bowler_card.image.url if bowler_card.image else None,
                        'runs': runs,
                        'wicket': wicket,
                    })
                except PlayerCard.DoesNotExist:
                    pass
    
    # Winner info
    winner = state.get('winner')
    winner_name = None
    if winner and winner != 'Tie':
        winner_user = room.player1 if winner == 'player1' else room.player2
        winner_name = winner_user.username if winner_user else 'Unknown'
    
    context = {
        'room': room,
        'current_innings': current_innings,
        'round_number': round_number,
        'batting_first': batting_first,
        'batting_team': batting_team,
        'bowling_team': bowling_team,
        'p1_runs': state['scores'].get('player1', 0),
        'p2_runs': state['scores'].get('player2', 0),
        'p1_wickets': state['wickets'].get('player1', 0),
        'p2_wickets': state['wickets'].get('player2', 0),
        'last_batter': state.get('last_batter'),
        'last_bowler': state.get('last_bowler'),
        'innings1_rounds': innings1_rounds,
        'innings2_rounds': innings2_rounds,
        'message': state.get('message', ''),
        'game_over': state.get('game_over', False),
        'winner': winner,
        'winner_name': winner_name,
        'target': state.get('target'),
        'is_live': room.status == 'live',
    }
    return render(request, 'watch_match_detail.html', context)

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from . import models   # or specific imports
@login_required
def profile(request):
    user = request.user
    
    # All completed matches this user played
    completed_matches = GameRoom.objects.filter(
        status='completed'
    ).filter(
        Q(player1=user) | Q(player2=user)   # ← CORRECTED
    ).order_by('-created_at')
    
    total_matches = completed_matches.count()
    wins = 0
    losses = 0
    draws = 0
    
    # Deck usage tracking
    deck_usage = {}  # {team_name: count}
    
    for match in completed_matches:
        state = match.state or {}
        winner = state.get('winner')
        exit_by = state.get('exit_by')
        
        # Determine my role
        my_role = 'player1' if match.player1 == user else 'player2'
        
        # Count wins/losses
        if winner == 'Tie':
            draws += 1
        elif winner == my_role:
            wins += 1
        elif winner:
            losses += 1
        
        # Count deck usage
        my_deck = match.player1_deck if my_role == 'player1' else match.player2_deck
        if my_deck and my_deck.team:
            team_name = my_deck.team.name
            deck_usage[team_name] = deck_usage.get(team_name, 0) + 1
    
    # Win percentage
    win_percentage = round((wins / total_matches * 100), 1) if total_matches > 0 else 0
    
    # Deck usage percentages
    deck_stats = []
    for team_name, count in sorted(deck_usage.items(), key=lambda x: x[1], reverse=True):
        percentage = round((count / total_matches * 100), 1) if total_matches > 0 else 0
        deck_stats.append({
            'team': team_name,
            'count': count,
            'percentage': percentage,
        })
    
    # Recent 5 matches
    recent_matches = []
    for match in completed_matches[:5]:
        state = match.state or {}
        winner = state.get('winner')
        exit_by = state.get('exit_by')
        my_role = 'player1' if match.player1 == user else 'player2'
        opp_role = 'player2' if my_role == 'player1' else 'player1'
        opponent = match.player2 if my_role == 'player1' else match.player1
        
        if winner == 'Tie':
            result = 'Draw'
            result_class = 'draw'
        elif winner == my_role:
            result = 'Win'
            result_class = 'win'
        else:
            result = 'Loss'
            result_class = 'loss'
        
        my_deck = match.player1_deck if my_role == 'player1' else match.player2_deck
        
        recent_matches.append({
            'code': match.code,
            'opponent': opponent.username if opponent else 'Unknown',
            'result': result,
            'result_class': result_class,
            'my_score': state['scores'].get(my_role, 0) if state.get('scores') else 0,
            'opp_score': state['scores'].get(opp_role, 0) if state.get('scores') else 0,
            'deck_team': my_deck.team.name if my_deck and my_deck.team else 'Unknown',
            'date': match.created_at,
            'exited': exit_by == my_role,
        })
    
    context = {
        'user': user,
        'total_matches': total_matches,
        'wins': wins,
        'losses': losses,
        'draws': draws,
        'win_percentage': win_percentage,
        'deck_stats': deck_stats,
        'recent_matches': recent_matches,
    }
    return render(request, 'profile.html', context)