"""
s7app/views/stats_views.py — Profile and leaderboard views.
"""
from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import render

from ..models import GameRoom


def profile(request):
    user = request.user

    completed_matches = GameRoom.objects.filter(
        status='completed'
    ).filter(
        Q(player1=user) | Q(player2=user)
    ).order_by('-created_at')

    total_matches = completed_matches.count()
    wins   = 0
    losses = 0
    draws  = 0
    deck_usage = {}

    for match in completed_matches:
        match_state = match.state or {}
        winner  = match_state.get('winner')
        my_role = 'player1' if match.player1 == user else 'player2'

        if winner == 'Tie':
            draws += 1
        elif winner == my_role:
            wins += 1
        elif winner:
            losses += 1

        my_deck = match.player1_deck if my_role == 'player1' else match.player2_deck
        if my_deck and my_deck.team:
            team_name = my_deck.team.name
            deck_usage[team_name] = deck_usage.get(team_name, 0) + 1

    win_percentage = round((wins / total_matches * 100), 1) if total_matches > 0 else 0

    deck_stats = [
        {
            'team':       team_name,
            'count':      count,
            'percentage': round((count / total_matches * 100), 1) if total_matches > 0 else 0,
        }
        for team_name, count in sorted(deck_usage.items(), key=lambda x: x[1], reverse=True)
    ]

    recent_matches = []
    for match in completed_matches[:5]:
        match_state = match.state or {}
        winner  = match_state.get('winner')
        exit_by = match_state.get('exit_by')
        my_role = 'player1' if match.player1 == user else 'player2'
        opp_role = 'player2' if my_role == 'player1' else 'player1'
        opponent = match.player2 if my_role == 'player1' else match.player1

        if winner == 'Tie':
            result       = 'Draw'
            result_class = 'draw'
        elif winner == my_role:
            result       = 'Win'
            result_class = 'win'
        else:
            result       = 'Loss'
            result_class = 'loss'

        my_deck = match.player1_deck if my_role == 'player1' else match.player2_deck
        scores  = match_state.get('scores', {})

        recent_matches.append({
            'code':         match.code,
            'opponent':     opponent.username if opponent else 'Unknown',
            'result':       result,
            'result_class': result_class,
            'my_score':     scores.get(my_role, 0),
            'opp_score':    scores.get(opp_role, 0),
            'deck_team':    my_deck.team.name if my_deck and my_deck.team else 'Unknown',
            'date':         match.created_at,
            'exited':       exit_by == my_role,
        })

    return render(request, 'profile.html', {
        'user':          user,
        'total_matches': total_matches,
        'wins':          wins,
        'losses':        losses,
        'draws':         draws,
        'win_percentage': win_percentage,
        'deck_stats':    deck_stats,
        'recent_matches': recent_matches,
    })


def leaderboard(request):
    board = []
    for user in User.objects.all():
        wins = (
            GameRoom.objects.filter(status='completed')
            .filter(
                Q(player1=user, state__winner='player1') |
                Q(player2=user, state__winner='player2')
            )
            .count()
        )
        board.append({'user': user, 'wins': wins})

    board.sort(key=lambda x: x['wins'], reverse=True)
    for i, row in enumerate(board, start=1):
        row['position'] = i

    return render(request, 'leaderboard.html', {'leaderboard': board})
