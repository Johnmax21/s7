import csv
from django.shortcuts import render, redirect
import random
from .models import PlayerCard
import os
from datetime import datetime
from collections import defaultdict

# Load strategies from CSV
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATEGIES_FILE = os.path.join(BASE_DIR, 's7app', 'strategies.csv')
HISTORY_FILE = os.path.join(BASE_DIR, 's7app', 'game_history.csv')
OPTIMAL_COUNTERS = {
    'high_bowling': lambda cards: max(cards, key=lambda x: x.batting + x.runs),
    'high_batting': lambda cards: max(cards, key=lambda x: x.bowling),
    'balanced': lambda cards: max(cards, key=lambda x: (x.bowling + x.batting + x.runs) / 3),
}
strategies = {}
with open(STRATEGIES_FILE, newline='', encoding='utf-8') as csvfile:
    reader = csv.DictReader(csvfile)
    for row in reader:
        strategies[row['player_profile']] = row['best_counter']

# Initialize game_history.csv with headers if it doesn't exist
if not os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=['round_number', 'player_card_id', 'player_name', 'computer_card_id', 'computer_name', 'outcome', 'score', 'wickets', 'timestamp'])
        writer.writeheader()

def analyze_history_and_update_strategy():
    # Simple analysis: Adjust strategy if a profile loses too often
    win_counts = defaultdict(lambda: defaultdict(int))
    loss_counts = defaultdict(lambda: defaultdict(int))
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                player_profile = 'high_batting' if int(row['player_card_id']) % 2 == 0 else 'balanced'  # Simplified profile
                computer_strategy = row['computer_name'] or 'N/A'  # Adjust based on your logic
                if row['outcome'] == 'win':
                    win_counts[player_profile][computer_strategy] += 1
                else:
                    loss_counts[player_profile][computer_strategy] += 1

    new_strategies = {}
    for profile in strategies:
        current_counter = strategies[profile]
        wins = win_counts[profile][current_counter]
        losses = loss_counts[profile][current_counter]
        if losses > wins and losses > 2:  # Adjust if losses exceed wins by a threshold
            # Switch to a different strategy with fewer losses
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

from django.contrib.sessions.middleware import SessionMiddleware
import random

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
            batting_first = None  # Set after player choice in toss_result.html
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
    # Update strategy based on history at the start of each game
    analyze_history_and_update_strategy()

    # Clear all session data to start fresh if not in an ongoing game
    if 'innings' not in request.session or request.method == "POST" and 'batting_first' in request.POST:
        request.session.flush()  # This clears all session data
        if request.method == "POST" and 'batting_first' in request.POST:
            # Initialize session from toss result
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
        # Process round
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
            # Invalid selection, handle error (for now, assume valid)
            pass
        used_by_player.append(player_card.id)
        request.session['used_by_player'] = used_by_player

        available_for_computer = PlayerCard.objects.exclude(id__in=used_by_computer)
        # Dataset-driven computer selection
        if not available_for_computer:
            computer_card = None  # Handle edge case of no available cards
        elif batting_team == 'computer':  # Computer is batting
            computer_card = max(available_for_computer, key=lambda x: x.batting + x.runs)  # Prioritize batting and runs
        else:  # Computer is bowling
            # Determine player's card profile
            player_batting_weight = player_card.batting / (player_card.batting + player_card.bowling + 1)  # Normalize batting influence
            player_profile = 'high_batting' if player_batting_weight > 0.6 else 'high_bowling' if player_card.bowling > player_card.batting else 'balanced'
            counter_strategy = strategies.get(player_profile, 'balanced')  # Default to balanced if not found
            computer_card = OPTIMAL_COUNTERS[counter_strategy](available_for_computer)
        if computer_card:
            used_by_computer.append(computer_card.id)
            request.session['used_by_computer'] = used_by_computer
        else:
            # Fallback to random if no valid strategy (should not occur with proper setup)
            computer_card = random.choice(available_for_computer) if available_for_computer else None
            if computer_card:
                used_by_computer.append(computer_card.id)
                request.session['used_by_computer'] = used_by_computer

        if not computer_card or not player_card:
            message = "Error: Insufficient cards available!"
            request.session['message'] = message
        else:
            if batting_team == 'player':
                batter = player_card
                bowler = computer_card
            else:
                batter = computer_card
                bowler = player_card

            if batter.batting > bowler.bowling:
                request.session['scores'][batting_team] += batter.runs
                message = f"Runs added: {batter.runs}"
                round_outcome = 'win'  # Batter wins
            else:
                request.session['wickets'][batting_team] += 1
                message = "Wicket!"
                round_outcome = 'loss'  # Batter loses
            request.session['message'] = message

            # Record gameplay to CSV
            with open(HISTORY_FILE, 'a', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=['round_number', 'player_card_id', 'player_name', 'computer_card_id', 'computer_name', 'outcome', 'score', 'wickets', 'timestamp'])
                writer.writerow({
                    'round_number': round_number,
                    'player_card_id': player_card.id,
                    'player_name': player_card.name,
                    'computer_card_id': computer_card.id if computer_card else None,
                    'computer_name': computer_card.name if computer_card else 'N/A',
                    'outcome': round_outcome,
                    'score': request.session['scores'][batting_team],
                    'wickets': request.session['wickets'][batting_team],
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })

            # Store last cards for transparency including image URL
            request.session['last_batter'] = {
                'name': batter.name,
                'batting': batter.batting,
                'bowling': bowler.bowling,
                'runs': batter.runs,
                'image': batter.image.url if batter.image else None
            }
            request.session['last_bowler'] = {
                'name': bowler.name,
                'batting': bowler.batting,
                'bowling': bowler.bowling,
                'runs': bowler.runs,
                'image': bowler.image.url if bowler.image else None
            }

        request.session['round_number'] += 1
        if request.session['round_number'] > 7:
            if innings == 1:
                first_score = request.session['scores'][batting_first]
                request.session['target'] = first_score + 1  # Target is first innings runs + 1 to win
                request.session['innings'] = 2
                request.session['used_by_player'] = []
                request.session['used_by_computer'] = []
                request.session['round_number'] = 1
                request.session['message'] = "First innings over. Second innings starts!"
                if 'last_batter' in request.session:
                    del request.session['last_batter']
                if 'last_bowler' in request.session:
                    del request.session['last_bowler']
            else:
                # Game over
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

    # Render current state
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
    # Load history from CSV for display (limit to last 10 for performance)
    game_history = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            game_history = list(reader)[-10:]  # Last 10 records
    context['game_history'] = game_history
    return render(request, "game.html", context)