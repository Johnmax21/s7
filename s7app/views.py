from django.shortcuts import render, redirect
import random
from .models import PlayerCard

def toss_view(request):
    if request.method == "POST":
        player_choice = request.POST.get("toss_choice")
        toss_result = random.choice(["head", "tails"])
        if player_choice == toss_result:
            return render(request, "toss_result.html", {"won_toss": True, "toss_result": toss_result, "player_choice": player_choice})
        else:
            batting_first = random.choice(["player", "computer"])
            return render(request, "toss_result.html", {"won_toss": False, "toss_result": toss_result, "player_choice": player_choice, "batting_first": batting_first})
    return render(request, "toss.html")

def game_start(request):
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
        computer_card = random.choice(available_for_computer)
        used_by_computer.append(computer_card.id)
        request.session['used_by_computer'] = used_by_computer

        if batting_team == 'player':
            batter = player_card
            bowler = computer_card
        else:
            batter = computer_card
            bowler = player_card

        if batter.batting > bowler.bowling:
            request.session['scores'][batting_team] += batter.runs
            message = f"Runs added: {batter.runs}"
        else:
            request.session['wickets'][batting_team] += 1
            message = "Wicket!"
        request.session['message'] = message

        # Store last cards for transparency
        request.session['last_batter'] = {
            'name': batter.name,
            'batting': batter.batting,
            'bowling': batter.bowling,
            'runs': batter.runs
        }
        request.session['last_bowler'] = {
            'name': bowler.name,
            'batting': bowler.batting,
            'bowling': bowler.bowling,
            'runs': bowler.runs
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
    return render(request, "game.html", context)