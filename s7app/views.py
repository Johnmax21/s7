import contextlib
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
        try:
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f"s7app_{code}",
                {
                    "type": "player_joined",
                    "username": request.user.username,
                    "action": "redirect_toss",
                }
            )
        except Exception as e:
            print(f"Join notify failed: {e}")

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
        try:
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f"s7app_{code}",
                {
                    "type": "toss_result",
                    "action": "reload",
                }
            )
        except Exception as e:
            print(f"Toss notify failed: {e}")

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
        try:
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f"s7app_{code}",
                {
                    "type": "innings_chosen",
                    "action": "redirect_game",
                }
            )
        except Exception as e:
            print(f"Innings notify failed: {e}")

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
    if 'scores' not in state:
        state['scores'] = {'player1': 0, 'player2': 0}
    if 'wickets' not in state:
        state['wickets'] = {'player1': 0, 'player2': 0}
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

    # ── 6.5. Save a recalculation snapshot + open post-round boost window ──
    import time as _time

    state[f'round_snapshot_{innings}_{round_number}'] = {
        'batting_team':       batting_team,
        'batter_card_id':     batter_card.id,
        'bowler_card_id':     bowler_card.id,
        'eff_batting':        eff_batting,
        'eff_bowling':        eff_bowling,
        'eff_runs':           batter_card.runs,   # original card runs, pre-cutter
        'runs_cutter_active': runs_cutter_active,
        'batter_ability_triggered': batter_actual_ability_bonus > 0,
        'bowler_ability_triggered': (
            bowler_actual_ability_bonus > 0
            or (bowler_card.ability == 'runs_cutter' and runs_cutter_active)
        ),
        'batter_role':        batter_role,
        'bowler_role':        bowler_role,
    }
    state[f'boost_window_open_{innings}_{round_number}']    = True
    state[f'boost_window_started_{innings}_{round_number}'] = _time.time()
    state[f'round_boost_clicks_{innings}_{round_number}']   = []

    current_score   = state['scores'][batting_team]
    current_wickets = state['wickets'][batting_team]
    target          = state.get('target')

    # ── 7. Early end: target chased ───────────────────────
    if innings == 2 and target is not None and current_score >= target:
        chasing_team = 'player2' if batting_first == 'player1' else 'player1'
        state['game_over_pending'] = True
        state['winner'] = chasing_team


    # ── 8. Early end: all out or 7 rounds done ────────────
    # ── 8. Early end: all out or 7 rounds done ────────────
    # Skip this whole block if step 7 already decided the result
    if not state.get('game_over_pending'):
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
                # innings == 2 — chasing team failed to reach target in time
                chasing_team   = 'player2' if batting_first == 'player1' else 'player1'
                defending_team = batting_first
                chasing_score  = state['scores'][chasing_team]
                defending_score = state['scores'][defending_team]
                target_val = state.get('target', 0)

                if chasing_score == defending_score:
                    state['winner'] = 'Tie'
                elif chasing_score >= target_val:
                    state['winner'] = chasing_team
                else:
                    state['winner'] = defending_team

                state['game_over'] = True

    is_game_over = state.get('game_over', False)
    is_game_over_pending = state.get('game_over_pending', False)
    is_innings_transition = bool(state.get('innings_transition'))

    should_save_db = is_game_over or is_game_over_pending or is_innings_transition

    # Save to Redis always, DB only at important moments
    save_game_state(room.code, state, save_to_db=should_save_db)
    # At end of _resolve_round, replace the existing group_send with:
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        channel_layer = get_channel_layer()

        is_game_over = state.get('game_over', False)
        is_game_over_pending = state.get('game_over_pending', False)
        is_innings_transition = bool(state.get('innings_transition'))

        if is_game_over:
            async_to_sync(channel_layer.group_send)(
                f"s7app_{room.code}",
                {
                    "type": "game_over",
                    "action": "redirect_result",
                }
            )
        elif is_innings_transition or is_game_over_pending:
            async_to_sync(channel_layer.group_send)(
                f"s7app_{room.code}",
                {
                    "type": "innings_over",
                    "action": "reload",
                }
            )
        else:
            async_to_sync(channel_layer.group_send)(
                f"s7app_{room.code}",
                {
                    "type": "round_result",
                    "round": round_number,          # ← ADD THIS
                    "message": state.get('message', ''),  # ← fine here
                    "action": "reload",
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
    
    if state.get('game_over') and state.get(f'{my_role}_viewing_result', False):
        return redirect('mp_result', code=code)

    innings      = state.get('innings', 1)
    round_number = state.get('round_number', 1)
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

    opp_user = room.player2 if my_role == 'player1' else room.player1
    opp_deck = UserDeck.objects.filter(user=opp_user, is_active=True).first()
    opponent_deck_cards = []
    if opp_deck:
        opp_deck_ids = DeckCard.objects.filter(deck=opp_deck).values_list('player_card_id', flat=True)
        opponent_deck_cards = list(PlayerCard.objects.filter(id__in=opp_deck_ids))

    # ── Helper to build full context ──────────────────────────────
    def build_context(state):
        # ── Read innings/round from THIS state, not outer scope ──
        _innings      = state.get('innings', 1)
        _round_number = state.get('round_number', 1)
        _batting_first = state.get('batting_first', 'player1')

        if _innings == 1:
            _batting_team = _batting_first
        else:
            _batting_team = 'player2' if _batting_first == 'player1' else 'player1'

        _my_used    = state.get(f'used_by_{my_role}', [])
        _my_played_key  = f'{my_role}_played_round_{_innings}_{_round_number}'
        _opp_played_key = f'{opp_role}_played_round_{_innings}_{_round_number}'
        _i_played   = state.get(_my_played_key) is not None
        _opp_played = state.get(_opp_played_key) is not None
        _waiting    = _i_played and not _opp_played

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

        from .models import SupportCard
        _support_cards  = SupportCard.objects.all()
        _active_support = state.get(f'{my_role}_support')
        if _active_support and _round_number >= _active_support.get('until_round', 0):
            _active_support = None

        _bowling_first = 'player2' if _batting_first == 'player1' else 'player1'

        # Timeline innings 1
        _innings1_timeline = []
        for r in range(1, _round_number if _innings == 1 else 8):
            batter_id = state.get(f'{_batting_first}_played_round_1_{r}')
            bowler_id = state.get(f'{_bowling_first}_played_round_1_{r}')
            if batter_id and bowler_id:
                try:
                    bc  = PlayerCard.objects.get(id=batter_id)
                    bwc = PlayerCard.objects.get(id=bowler_id)
                    _innings1_timeline.append({
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

        # Timeline innings 2
        _innings2_timeline = []
        if _innings == 2:
            _batting_second = _bowling_first
            _bowling_second = _batting_first
            for r in range(1, _round_number):
                batter_id = state.get(f'{_batting_second}_played_round_2_{r}')
                bowler_id = state.get(f'{_bowling_second}_played_round_2_{r}')
                if batter_id and bowler_id:
                    try:
                        bc  = PlayerCard.objects.get(id=batter_id)
                        bwc = PlayerCard.objects.get(id=bowler_id)
                        _innings2_timeline.append({
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

        # ── Post-round boost window info ──
        _boost_round = _round_number - 1
        _boost_window_open = state.get(f'boost_window_open_{_innings}_{_boost_round}', False)
        _boost_window_started = state.get(f'boost_window_started_{_innings}_{_boost_round}', 0)
        import time as _time
        _boost_elapsed = _time.time() - _boost_window_started if _boost_window_started else 999
        _boost_window_active = _boost_window_open and _boost_elapsed <= 5

        _boost_seconds_left = max(0, 5 - _boost_elapsed) if _boost_window_active else 0

        _my_post_boost_used = state.get(f'{my_role}_post_boost_used', False)
        _boost_clicks = state.get(f'round_boost_clicks_{_innings}_{_boost_round}', [])
        _i_already_clicked = my_role in _boost_clicks

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
        opp_post_boost_used = state.get(f'{opp_role}_post_boost_used', False)

        opp_already_clicked = opp_role in _boost_clicks

        opp_ability_triggered_last_round = (
            (_snap.get('batter_ability_triggered') and _snap.get('batter_role') == opp_role)
            or (_snap.get('bowler_ability_triggered') and _snap.get('bowler_role') == opp_role)
        )

        opp_can_use_post_boost = (
            _boost_window_active
            and not opp_post_boost_used
            and not opp_already_clicked
            and not opp_ability_triggered_last_round
        )
        transition_wait = (
            (state.get("innings_transition") or state.get("game_over_pending"))
            and _boost_window_active
            and (
                _can_use_post_boost
                or opp_can_use_post_boost
            )
        )

        # ── Per-player innings-2 viewing flag (NEW) ──
        _my_viewing_innings2 = state.get(f'{my_role}_viewing_innings2', False)
        _shared_innings = state.get('innings', 1)
        # This player still needs to see (and click through) the transition screen if
        # the match has already moved to innings 2 in shared state, but THIS player
        # hasn't personally clicked Continue yet.
        _show_transition_to_me = (_shared_innings == 2 and not _my_viewing_innings2)
        # Preserve target info for display even after the shared 'innings_transition'
        # key has been cleared from state by whichever player clicked first.
        _my_transition_target = state.get('target') if _show_transition_to_me else None
        # ── Per-player game-over viewing flag (NEW) ──
        _my_viewing_result = state.get(f'{my_role}_viewing_result', False)
        _shared_game_over = state.get('game_over', False)
        _shared_game_over_pending = state.get('game_over_pending', False)

        # This player still needs to see the "Match Over!" screen and click
        # their own "See Result →" if the match has ended but THEY haven't
        # personally confirmed yet.
        _show_result_screen_to_me = (
            (_shared_game_over or _shared_game_over_pending)
            and not _my_viewing_result
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

            # ── CHANGED: gated by this player's own viewing flag, not shared state ──
            'innings_transition':   (
                {'target': _my_transition_target} if _show_transition_to_me
                else state.get('innings_transition')
            ),

            'game_over_pending':    _show_result_screen_to_me,
            'boost_used':           state.get(f'{my_role}_boost_used', False),
            'boost_active':         state.get(f'{my_role}_boost_active', False),
            'last_wicket_in_round': _last_wicket,
            'recent_runs_high':     _recent_runs >= 30,
            'opponent_score_high':  _opponent_score >= 60,
            'opponent_deck_cards':  opponent_deck_cards,
            'innings1_timeline':    _innings1_timeline,
            'innings2_timeline':    _innings2_timeline,
            'boost_window_active':   _boost_window_active,
            'boost_seconds_left':    round(_boost_seconds_left, 1),
            'can_use_post_boost':    _can_use_post_boost,
            'my_post_boost_used':    _my_post_boost_used,
            'boost_round_for_form':  _boost_round,
            'opponent_can_use_post_boost': opp_can_use_post_boost,
            'must_wait_for_boost': transition_wait,
        }

        if _innings == 2:
            ctx['target']           = state.get('target')
            chasing_runs            = state.get('scores', {}).get(_batting_team, 0)
            target_val              = state.get('target', 0)
            ctx['runs_needed']      = max(0, target_val - chasing_runs)
            ctx['rounds_remaining'] = max(0, 8 - _round_number)

        return ctx

    # ══════════════════════════════════════════════════════════════
    # POST
    # ══════════════════════════════════════════════════════════════
    if request.method == 'POST':

        # ── cancel_boost ─────────────────────────────────────────
        if request.POST.get('action') == 'cancel_boost':
            if state.get(f'{my_role}_boost_active') and not i_played:
                state[f'{my_role}_boost_active'] = False
                state[f'{my_role}_boost_used']   = False
                save_game_state(room.code, state, save_to_db=False)
            if request.headers.get('HX-Request'):
                return render(request, 'partials/status_bar.html',
                              build_context(get_game_state(code)))
            return redirect('mp_game', code=code)

        # ── cancel_support ───────────────────────────────────────
        if request.POST.get('action') == 'cancel_support':
            if state.get(f'{my_role}_support_used') and not i_played:
                state[f'{my_role}_support_used'] = False
                state[f'{my_role}_support']      = None
                save_game_state(room.code, state, save_to_db=False)
            if request.headers.get('HX-Request'):
                return render(request, 'partials/status_bar.html',
                              build_context(get_game_state(code)))
            return redirect('mp_game', code=code)

        # ── use_boost ────────────────────────────────────────────
        if request.POST.get('action') == 'use_boost':
            if not state.get(f'{my_role}_boost_used'):
                state[f'{my_role}_boost_used']   = True
                state[f'{my_role}_boost_active']  = True
                save_game_state(room.code, state, save_to_db=False)
            if request.headers.get('HX-Request'):
                return render(request, 'partials/status_bar.html',
                              build_context(get_game_state(code)))
            return redirect('mp_game', code=code)

        # ── use_support ──────────────────────────────────────────
        if request.POST.get('action') == 'use_support':
            if not state.get(f'{my_role}_support_used'):
                support_type = request.POST.get('support_type')
                state[f'{my_role}_support'] = {
                    'type':        support_type,
                    'from_round':  round_number,
                    'until_round': round_number + 3,
                }
                state[f'{my_role}_support_used'] = True
                save_game_state(room.code, state, save_to_db=False)
            if request.headers.get('HX-Request'):
                return render(request, 'partials/status_bar.html',
                              build_context(get_game_state(code)))
            return redirect('mp_game', code=code)

        # ── continue_result ──────────────────────────────────────
        # ── continue_result ──────────────────────────────────────
        if request.POST.get('action') == 'continue_result':
            fresh_state = get_game_state(code)
            fresh_state[f'{my_role}_viewing_result'] = True
            if fresh_state.get('game_over_pending'):
                fresh_state['game_over'] = True
                fresh_state.pop('game_over_pending', None)
            save_game_state(code, fresh_state, save_to_db=True)
            return redirect('mp_result', code=code)
        
        # ── continue_innings ─────────────────────────────────────
        # ── continue_innings ─────────────────────────────────────
        if request.POST.get('action') == 'continue_innings':
            fresh_state = get_game_state(code)

            # Always mark THIS player as having clicked through —
            # regardless of whether shared transition data still exists
            fresh_state[f'{my_role}_viewing_innings2'] = True

            # The shared game state advances on the FIRST click only.
            # Use 'innings == 1' as the guard, not 'innings_transition exists',
            # since the transition key gets cleared after the first click.
            if fresh_state.get('innings', 1) == 1:
                transition = fresh_state.get('innings_transition')
                if transition:
                    fresh_state['target']           = transition['target']
                    fresh_state['innings']          = 2
                    fresh_state['round_number']     = 1
                    fresh_state['used_by_player1']  = []
                    fresh_state['used_by_player2']  = []
                    fresh_state['player1_support']  = None
                    fresh_state['player2_support']  = None
                    fresh_state['last_batter']      = None
                    fresh_state['last_bowler']      = None
                    fresh_state['message']          = ''
                    fresh_state.pop('innings_transition', None)

            save_game_state(code, fresh_state, save_to_db=True)

            if request.headers.get('HX-Request'):
                return render(request, 'partials/game_panel.html',
                              build_context(get_game_state(code)))
            return redirect('mp_game', code=code)


        # ── use_post_round_boost ─────────────────────────────────
        if request.POST.get('action') == 'use_post_round_boost':
            import time as _time
            fresh_state = get_game_state(code)
            target_innings = int(request.POST.get('boost_innings', innings))
            target_round   = int(request.POST.get('boost_round', round_number - 1))

            window_open    = fresh_state.get(f'boost_window_open_{target_innings}_{target_round}', False)
            window_started = fresh_state.get(f'boost_window_started_{target_innings}_{target_round}', 0)
            elapsed = _time.time() - window_started

            already_used = fresh_state.get(f'{my_role}_post_boost_used', False)

            snap = fresh_state.get(f'round_snapshot_{target_innings}_{target_round}', {})
            my_own_ability_triggered = (
                snap.get('batter_ability_triggered') and snap.get('batter_role') == my_role
            ) or (
                snap.get('bowler_ability_triggered') and snap.get('bowler_role') == my_role
            )

            can_use = (
                window_open and elapsed <= 5
                and not already_used
                and not my_own_ability_triggered
            )

            # ── DEBUG ──
            print(f"=== BOOST CLICK by {my_role} ===")
            print(f"target_innings={target_innings}, target_round={target_round}")
            print(f"window_open={window_open}, elapsed={elapsed:.2f}, already_used={already_used}")
            print(f"my_own_ability_triggered={my_own_ability_triggered}")
            print(f"can_use={can_use}")
            existing_clicks = fresh_state.get(f'round_boost_clicks_{target_innings}_{target_round}', [])
            print(f"existing_clicks={existing_clicks}")
            print(f"==============================")

            if can_use:
                clicks = fresh_state.get(f'round_boost_clicks_{target_innings}_{target_round}', [])
                if my_role not in clicks:
                    bonus = 10 if len(clicks) == 0 else 5
                    clicks.append(my_role)
                    fresh_state[f'round_boost_clicks_{target_innings}_{target_round}'] = clicks
                    fresh_state[f'{my_role}_post_boost_used'] = True
                    save_game_state(code, fresh_state, save_to_db=False)

                    print(f"✅ Applying recalculation: role={my_role}, bonus={bonus}")
                    fresh_state = _recalculate_round_with_boost(
                        room, target_innings, target_round, my_role, bonus
                    )
                    print(f"✅ After recalc: scores={fresh_state.get('scores')}, wickets={fresh_state.get('wickets')}")

                    try:
                        from asgiref.sync import async_to_sync
                        from channels.layers import get_channel_layer
                        channel_layer = get_channel_layer()
                        async_to_sync(channel_layer.group_send)(
                            f"s7app_{code}",
                            {
                                "type": "boost_applied",          # ← changed from "round_result"
                                
                                "round": target_round,
                                "message": fresh_state.get('message', ''),
                                "action": "reload",
                            }
                        )
                        print(f"✅ WS broadcast SUCCEEDED for round {target_round}")  # ← ADD THIS
                    except Exception as e:
                        print(f"❌ WebSocket boost notify failed: {e}")  # ← make sure this prints with traceback
                        import traceback
                        traceback.print_exc()

            if request.headers.get('HX-Request'):
                return render(request, 'partials/_boost_response.html',
                              build_context(get_game_state(code)))
            return redirect('mp_game', code=code)
        # ── play_card ────────────────────────────────────────────
        if request.POST.get('action') == 'play_card':
            fresh_state   = get_game_state(code)
            fresh_innings = fresh_state.get('innings', 1)
            fresh_round   = fresh_state.get('round_number', 1)
            fresh_key     = f'{my_role}_played_round_{fresh_innings}_{fresh_round}'

            if fresh_state.get(fresh_key) is not None:
                # already played — return panel so UI updates
                if request.headers.get('HX-Request'):
                    return render(request, 'partials/game_panel.html',
                                  build_context(fresh_state))
                return redirect('mp_game', code=code)

            selected_id = int(request.POST.get('selected_card_id'))
            fresh_state[fresh_key] = selected_id
            my_used_list = fresh_state.get(f'used_by_{my_role}', [])
            if selected_id not in my_used_list:
                my_used_list.append(selected_id)
            fresh_state[f'used_by_{my_role}'] = my_used_list
            save_game_state(code, fresh_state, save_to_db=False)

            # notify opponent
            try:
                from asgiref.sync import async_to_sync
                from channels.layers import get_channel_layer
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    f"s7app_{code}",
                    {
                        "type":    "card_played",
                        "by_role": my_role,
                        "action":  "reload_if_waiting",
                    }
                )
            except Exception as e:
                print(f"WebSocket card_played notify failed: {e}")

            # check if both played → resolve
            after_save    = get_game_state(code)
            opp_fresh_key = f'{opp_role}_played_round_{fresh_innings}_{fresh_round}'
            opp_played_now = after_save.get(opp_fresh_key) is not None

            if opp_played_now:
                _resolve_round(room, fresh_innings, fresh_round, batting_team, batting_first)
                after_resolve = get_game_state(code)
                if after_resolve.get('game_over'):
                    return redirect('mp_result', code=code)

            # return game panel showing waiting overlay
            if request.headers.get('HX-Request'):
                return render(request, 'partials/game_panel.html',
                              build_context(get_game_state(code)))
            return redirect('mp_game', code=code)

    # ══════════════════════════════════════════════════════════════
    # GET
    # ══════════════════════════════════════════════════════════════
    state   = get_game_state(code)
    context = build_context(state)

    partial = request.GET.get('partial')

    if partial == 'round_check':
        from django.http import JsonResponse
        fresh_state = get_game_state(code)
        my_viewing_innings2 = fresh_state.get(f'{my_role}_viewing_innings2', False)
        my_viewing_result   = fresh_state.get(f'{my_role}_viewing_result', False)
        shared_innings      = fresh_state.get('innings', 1)
        shared_game_over    = fresh_state.get('game_over', False)
        shared_pending      = fresh_state.get('game_over_pending', False)

        i_still_need_innings_transition = (shared_innings == 2 and not my_viewing_innings2)
        i_still_need_result_confirm     = ((shared_game_over or shared_pending) and not my_viewing_result)

        return JsonResponse({
            'round_number':     fresh_state.get('round_number', 1),
            'innings':          fresh_state.get('innings', 1),
            'game_over':        bool(shared_game_over and my_viewing_result),  # only true once THIS player has confirmed
            'boost_counter':    fresh_state.get('boost_update_counter', 0),
            'needs_transition': i_still_need_innings_transition or i_still_need_result_confirm,
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


def _recalculate_round_with_boost(room, innings, round_number, clicking_role, bonus_amount):
    """
    Re-runs the round outcome using the stored snapshot, with bonus_amount
    added to whichever side clicking_role played (batter or bowler).
    Updates scores/wickets/last_batter/last_bowler and re-checks
    innings/game-over conditions. Returns the updated state.
    """
    import math
    state = get_game_state(room.code)
    snap = state.get(f'round_snapshot_{innings}_{round_number}')
    if not snap:
        return state  # nothing to recalculate

    batting_team = snap['batting_team']
    eff_batting  = snap['eff_batting']
    eff_bowling  = snap['eff_bowling']
    eff_runs     = snap['eff_runs']
    runs_cutter_active = snap['runs_cutter_active']

    # Apply the boost bonus to whichever side this player played
    if clicking_role == snap['batter_role']:
        eff_batting += bonus_amount
    elif clicking_role == snap['bowler_role']:
        eff_bowling += bonus_amount

    # ── PERSIST the boosted values back into the snapshot ──
    # so the NEXT click (if any) builds on THIS result, not the original
    snap['eff_batting'] = eff_batting
    snap['eff_bowling'] = eff_bowling
    state[f'round_snapshot_{innings}_{round_number}'] = snap

    # ── Undo the previous round's contribution before reapplying ──
    prev_runs   = state.get(f'runs_in_round_{innings}_{round_number}', 0)
    prev_wicket = state.get(f'wicket_in_round_{innings}_{round_number}', False)

    if prev_wicket:
        state['wickets'][batting_team] = max(0, state['wickets'][batting_team] - 1)
    else:
        state['scores'][batting_team] = max(0, state['scores'][batting_team] - prev_runs)

    # ── Recompute outcome exactly like _resolve_round step 4 ──
    runs_cut_amount = 0
    if eff_batting > eff_bowling:
        new_runs = eff_runs
        if runs_cutter_active:
            runs_cut_amount = min(10, new_runs)
            new_runs = max(0, new_runs - 10)
        state['scores'][batting_team] += new_runs
        state[f'runs_in_round_{innings}_{round_number}']   = new_runs
        state[f'wicket_in_round_{innings}_{round_number}'] = False
        outcome_message = f"Runs added: {new_runs}! (Boost applied)"

    elif eff_batting == eff_bowling:
        partial = eff_runs / 3
        awarded = math.floor(partial + 0.5)
        state['scores'][batting_team] += awarded
        state[f'runs_in_round_{innings}_{round_number}']   = awarded
        state[f'wicket_in_round_{innings}_{round_number}'] = False
        outcome_message = f"Tie! Partial runs: {awarded}! (Boost applied)"

    else:
        state['wickets'][batting_team] += 1
        state[f'runs_in_round_{innings}_{round_number}']   = 0
        state[f'wicket_in_round_{innings}_{round_number}'] = True
        outcome_message = "Wicket! 🎯 (Boost applied)"

    state['message'] = outcome_message

    # ── Update last_batter / last_bowler effective values + boost display ──
    last_batter = state.get('last_batter') or {}
    last_bowler = state.get('last_bowler') or {}

    if clicking_role == snap['batter_role']:
        last_batter['boost_bonus']       = last_batter.get('boost_bonus', 0) + bonus_amount
        last_batter['effective_batting'] = eff_batting
    elif clicking_role == snap['bowler_role']:
        last_bowler['boost_bonus']       = last_bowler.get('boost_bonus', 0) + bonus_amount
        last_bowler['effective_bowling'] = eff_bowling

    last_batter['runs_cut'] = runs_cut_amount
    # ── Re-check innings/game-over conditions since outcome may have flipped ──
    state['last_batter'] = last_batter
    state['last_bowler']  = last_bowler
    # ── Mark this player's post-round boost as used ─────────────────────────────
    state[f'{clicking_role}_post_boost_used'] = True

    # Record that this player clicked boost
    boost_clicks = state.get(f'round_boost_clicks_{innings}_{round_number}', [])
    if clicking_role not in boost_clicks:
        boost_clicks.append(clicking_role)
    state[f'round_boost_clicks_{innings}_{round_number}'] = boost_clicks
    snap = state.get(f'round_snapshot_{innings}_{round_number}', {})

    batter_role = snap.get("batter_role")
    bowler_role = snap.get("bowler_role")

    batter_done = (
        batter_role in boost_clicks
        or snap.get("batter_ability_triggered")
        or state.get(f"{batter_role}_post_boost_used", False)
    )

    bowler_done = (
        bowler_role in boost_clicks
        or snap.get("bowler_ability_triggered")
        or state.get(f"{bowler_role}_post_boost_used", False)
    )

    
    # Determine the other player
    other_role = (
        snap['bowler_role']
        if clicking_role == snap['batter_role']
        else snap['batter_role']
    )

    other_ability_triggered = (
        (snap.get("batter_role") == other_role and snap.get("batter_ability_triggered"))
        or
        (snap.get("bowler_role") == other_role and snap.get("bowler_ability_triggered"))
    )

    other_can_still_boost = (
        not state.get(f'{other_role}_post_boost_used', False)
        and other_role not in boost_clicks
        and not other_ability_triggered
    )
    # Close boost window if nobody can boost anymore
    if not other_can_still_boost:
        state[f'boost_window_open_{innings}_{round_number}'] = False

    # ── Re-check innings/game-over conditions since outcome may have flipped ──
    current_score   = state['scores'][batting_team]
    current_wickets = state['wickets'][batting_team]
    target          = state.get('target')
    batting_first   = state.get('batting_first', 'player1')

    state.pop('innings_transition', None)
    state.pop('game_over_pending', None)
    state.pop('game_over', None)
    state.pop('winner', None)

    if innings == 2 and target is not None and current_score >= target:
        chasing_team = 'player2' if batting_first == 'player1' else 'player1'
        state['game_over_pending'] = True
        state['winner'] = chasing_team
    else:
        innings_over = (current_wickets >= 10) or (state['round_number'] > 7)
        if innings_over:
            if innings == 1:
                first_score = state['scores'][batting_first]
                state['innings_transition'] = {
                    'target':      first_score + 1,
                    'first_score': first_score,
                }
            else:
                chasing_team    = 'player2' if batting_first == 'player1' else 'player1'
                defending_team  = batting_first
                chasing_score   = state['scores'][chasing_team]
                defending_score = state['scores'][defending_team]
                target_val      = state.get('target', 0)
                if chasing_score == defending_score:
                    state['winner'] = 'Tie'
                elif chasing_score >= target_val:
                    state['winner'] = chasing_team
                else:
                    state['winner'] = defending_team
                state['game_over'] = True

    should_save_db = bool(
        state.get('game_over') or state.get('game_over_pending') or state.get('innings_transition')
    )
    state['boost_update_counter'] = state.get('boost_update_counter', 0) + 1
    save_game_state(room.code, state, save_to_db=should_save_db)
    return state

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
    # Innings 2 — chasing team wins if they reached target
        chasing_score = scores.get(chasing_team, 0)
        first_score = scores.get(batting_first, 0)
        
        if chasing_score >= target:
            winner_role = chasing_team  # ← Chaser wins
        elif chasing_score == first_score:
            winner_role = 'Tie'
        else:
            winner_role = batting_first  # ← First batting team wins

    my_role = _my_role(request, room)
    i_won = (winner_role == my_role)

    if winner_role == 'Tie':
        winner_name = 'Draw'
    elif winner_role == 'player1':
        winner_name = room.player1.username
    elif winner_role == 'player2':
        winner_name = room.player2.username if room.player2 else 'Unknown'
    else:
        winner_name = 'Unknown'

    print(f"winner_role: {winner_role}")
    print(f"batting_first: {batting_first}")
    print(f"chasing_team: {chasing_team}")
    print(f"p1_runs: {p1_runs}, p2_runs: {p2_runs}")
    print(f"target: {target}")
    # Only delete Redis AFTER saving to DB above
    delete_game_state(code)
    batting_first_name = room.player1.username if batting_first == 'player1' else (room.player2.username if room.player2 else 'Player 2')
    chasing_name        = room.player1.username if chasing_team == 'player1' else (room.player2.username if room.player2 else 'Player 2')
    context = {
        'room':           room,
        'winner':         winner_name,
        'winner_role':    winner_role,
        'i_won':          i_won,
        'p1_name':        room.player1.username,
        'p2_name':        room.player2.username if room.player2 else 'Player 2',
        'batting_first_name':  batting_first_name,   # ← add
        'chasing_name':        chasing_name,          # ← add
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

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction
from .models import UserDeck, DeckCard, PlayerCard, Team

@login_required
def exit_match(request, code):
    if request.method == 'POST':
        room = get_object_or_404(GameRoom, code=code)
        state = get_game_state(code)
        
        if state.get('game_over') and state.get(f'{my_role}_viewing_result', False):
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