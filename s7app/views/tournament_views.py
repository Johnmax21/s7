"""
s7app/views/tournament_views.py — Tournament hosting, seeding, and joining.
"""
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from ..models import Season, Tournament, TournamentParticipant, UserDeck


# ─── public hub ─────────────────────────────────────────────────────────────
def base(request):
    """Base template for tournament pages."""
    return render(request, 'base.html', {})
@login_required
def tournament_hub(request):
    current = Tournament.objects.filter(status__in=['upcoming', 'ongoing']).first()
    past = Tournament.objects.filter(status__in=['completed', 'cancelled']).order_by('-created_at')[:10]

    my_participation = None
    if current:
        my_participation = TournamentParticipant.objects.filter(
            tournament=current, user=request.user
        ).first()

    return render(request, 'tournaments/hub.html', {
        'current': current,
        'past': past,
        'my_participation': my_participation,
        'is_staff': request.user.is_staff,
    })


# ─── admin: create ──────────────────────────────────────────────────────────

@staff_member_required
def create_tournament(request):
    active_season = Season.objects.filter(is_active=True).first()
    blocked = Tournament.objects.filter(status__in=['upcoming', 'ongoing']).exists()

    if request.method == 'POST' and not blocked and active_season:
        tournament = Tournament(
            season=active_season,
            name=request.POST.get('name', '').strip(),
            hosted_by=request.user,
            format=request.POST.get('format'),
            max_participants=int(request.POST.get('max_participants', 8)),
            points_win=int(request.POST.get('points_win', 2)),
            points_tie=int(request.POST.get('points_tie', 1)),
            points_loss=int(request.POST.get('points_loss', 0)),
            rules_text=request.POST.get('rules_text', '').strip(),
        )
        try:
            tournament.full_clean()
            tournament.save()
            messages.success(request, f'"{tournament.name}" created.')
            return redirect('tournament_detail', tournament_id=tournament.id)
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))

    return render(request, 'tournaments/create.html', {
        'active_season': active_season,
        'blocked': blocked,
    })


# ─── detail / seeding / join ────────────────────────────────────────────────

@login_required
def tournament_detail(request, tournament_id):
    tournament = get_object_or_404(Tournament, id=tournament_id)
    participants = TournamentParticipant.objects.filter(
        tournament=tournament
    ).select_related('user', 'deck').order_by('seed', 'joined_at')

    my_participation = participants.filter(user=request.user).first()
    can_join = (
        tournament.status == 'upcoming'
        and not tournament.seeding_locked
        and my_participation is None
        and participants.count() < tournament.max_participants
    )
    my_decks = UserDeck.objects.filter(user=request.user) if can_join else None

    return render(request, 'tournaments/detail.html', {
        'tournament': tournament,
        'participants': participants,
        'my_participation': my_participation,
        'can_join': can_join,
        'my_decks': my_decks,
        'is_staff': request.user.is_staff,
        'unseeded_count': participants.filter(seed__isnull=True).count(),
    })


@login_required
def join_tournament(request, tournament_id):
    if request.method != 'POST':
        return redirect('tournament_detail', tournament_id=tournament_id)

    tournament = get_object_or_404(Tournament, id=tournament_id)
    deck_id = request.POST.get('deck_id')
    deck = UserDeck.objects.filter(id=deck_id, user=request.user).first() if deck_id else None

    participant = TournamentParticipant(tournament=tournament, user=request.user, deck=deck)
    try:
        participant.full_clean()
        participant.save()
        messages.success(request, f'You joined "{tournament.name}".')
    except ValidationError as e:
        messages.error(request, ' '.join(e.messages))

    return redirect('tournament_detail', tournament_id=tournament_id)


@staff_member_required
def set_seeds(request, tournament_id):
    """Bulk-save seed numbers submitted from the seeding table."""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    if request.method != 'POST' or tournament.seeding_locked:
        return redirect('tournament_detail', tournament_id=tournament_id)

    for key, value in request.POST.items():
        if key.startswith('seed_') and value.strip():
            participant_id = key.replace('seed_', '')
            TournamentParticipant.objects.filter(
                id=participant_id, tournament=tournament
            ).update(seed=int(value))

    messages.success(request, 'Seeding updated.')
    return redirect('tournament_detail', tournament_id=tournament_id)


@staff_member_required
def start_tournament(request, tournament_id):
    """One-way door: locks seeding and marks the tournament ongoing.
    Fixture generation (round-robin pairing / knockout bracket) is wired
    in separately — this view only performs the lock + status flip."""
    tournament = get_object_or_404(Tournament, id=tournament_id)
    if request.method != 'POST' or tournament.status != 'upcoming':
        return redirect('tournament_detail', tournament_id=tournament_id)

    participants = TournamentParticipant.objects.filter(tournament=tournament)
    if participants.filter(seed__isnull=True).exists():
        messages.error(request, "Every participant needs a seed before starting.")
        return redirect('tournament_detail', tournament_id=tournament_id)
    if participants.count() < 2:
        messages.error(request, "Need at least 2 participants to start.")
        return redirect('tournament_detail', tournament_id=tournament_id)

    tournament.seeding_locked = True
    tournament.status = 'ongoing'
    tournament.save()
    messages.success(request, f'"{tournament.name}" has started!')
    return redirect('tournament_detail', tournament_id=tournament_id)