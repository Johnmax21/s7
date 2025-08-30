import csv
from django.shortcuts import render, redirect
import random
from .models import PlayerCard
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