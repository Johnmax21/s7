"""
s7app/views/deck_views.py — Deck management: my_decks, create, build, swap, activate.
"""
import random
import string

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from ..models import DeckCard, PlayerCard, Team, UserDeck, UserPrizeCard


# ─── helpers ────────────────────────────────────────────────────────────────

def _make_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase, k=length))


# ─── views ──────────────────────────────────────────────────────────────────

@login_required
def my_decks(request):
    decks = UserDeck.objects.filter(
        user=request.user
    ).prefetch_related('deckcard_set__player_card')

    prize_card_objects = PlayerCard.objects.filter(
        userprizecard__user=request.user
    )

    return render(request, 'my_decks.html', {
        'decks':              decks,
        'prize_card_objects': prize_card_objects,
    })


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

    return render(request, 'create_deck.html', {'teams': Team.objects.all()})


@login_required
def build_deck(request, deck_id):
    deck = get_object_or_404(UserDeck, id=deck_id, user=request.user)

    current_cards = DeckCard.objects.filter(deck=deck).select_related('player_card')
    current_ids   = list(current_cards.values_list('player_card_id', flat=True))

    prize_card_ids = list(
        UserPrizeCard.objects.filter(
            user=request.user
        ).values_list('player_card_id', flat=True)
    )

    main_in_deck  = [dc for dc in current_cards if dc.player_card.id not in prize_card_ids]
    prize_in_deck = [dc for dc in current_cards if dc.player_card.id in prize_card_ids]

    available_main_cards = PlayerCard.objects.filter(
        team=deck.team
    ).exclude(id__in=current_ids)

    available_prize_cards = UserPrizeCard.objects.filter(
        user=request.user
    ).filter(
        Q(deck=None) | Q(deck=deck)
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

    main_cards = DeckCard.objects.filter(deck=deck).select_related('player_card')
    available_prize_cards = UserPrizeCard.objects.filter(
        user=request.user
    ).select_related('player_card')

    if request.method == 'POST':
        main_dc_id   = int(request.POST.get('main_card_id'))
        prize_upc_id = int(request.POST.get('prize_card_id'))

        main_dc   = get_object_or_404(DeckCard,      id=main_dc_id,   deck=deck)
        prize_upc = get_object_or_404(UserPrizeCard, id=prize_upc_id, user=request.user)

        if prize_upc.deck and prize_upc.deck != deck:
            return render(request, 'swap_card.html', {
                'deck':                  deck,
                'main_cards':            main_cards,
                'available_prize_cards': available_prize_cards,
                'error': f'{prize_upc.player_card.name} is already used in your other deck.',
            })

        new_total = (
            deck.total_weightage()
            - main_dc.player_card.weightage
            + prize_upc.player_card.weightage
        )
        if new_total > 32:
            return render(request, 'swap_card.html', {
                'deck':                  deck,
                'main_cards':            main_cards,
                'available_prize_cards': available_prize_cards,
                'error': f'Swap exceeds weightage limit of 32! (would be {new_total})',
            })

        with transaction.atomic():
            main_dc.delete()
            DeckCard.objects.get_or_create(deck=deck, player_card=prize_upc.player_card)
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
def set_active_deck(request, deck_id):
    deck = get_object_or_404(UserDeck, id=deck_id, user=request.user)
    UserDeck.objects.filter(user=request.user).update(is_active=False)
    deck.is_active = True
    deck.save()
    return redirect('my_decks')
