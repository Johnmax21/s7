from django.db import models
from django.contrib.auth.models import User


class SupportCard(models.Model):
    SUPPORT_CHOICES = [
        ('batting_support', 'Batting Support'),
        ('pace_support',    'Pace Support'),
        ('spin_support',    'Spin Support'),
    ]

    name       = models.CharField(max_length=100)
    support_type = models.CharField(max_length=20, choices=SUPPORT_CHOICES)
    image      = models.ImageField(upload_to='support_cards/', null=True, blank=True)
    description = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return self.name
class Team(models.Model):
    name = models.CharField(max_length=100)
    logo = models.ImageField(upload_to='team_logos/', null=True, blank=True)
class PlayerCard(models.Model):

    ABILITY_CHOICES = [
        ('none',                  'No Ability'),
        # Batting
        ('opener',                'Opener'),
        ('finisher',              'Finisher'),
        ('mid_over_hitter',       'Mid Over Hitter'),
        ('spin_basher',           'Spin Basher'),
        ('saviour',               'Saviour'),
        # Bowling
        ('powerplay_specialist',  'Powerplay Specialist'),
        ('death_specialist',      'Death Specialist'),
        ('mid_over_specialist',   'Mid Over Specialist'),
        ('runs_cutter',           'Runs Cutter'),
        ('golden_arm',            'Golden Arm'),
        ('breakthrough',          'Breakthrough'),
    ]

    name    = models.CharField(max_length=100)
    batting = models.IntegerField()
    bowling = models.IntegerField()
    runs    = models.IntegerField()
    image   = models.ImageField(upload_to='player_images/', null=True, blank=True)
    team    = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name='players')
    ability = models.CharField(max_length=30, choices=ABILITY_CHOICES, default='none')
    is_spinner = models.BooleanField(default=False)
    weightage  = models.IntegerField(default=1)  

    def __str__(self):
        return f"{self.name} ({self.ability})"



from django.db import models

class GameHistory(models.Model):
    round_number = models.IntegerField()
    player_card_id = models.IntegerField()
    player_name = models.CharField(max_length=100)
    computer_card_id = models.IntegerField()
    computer_name = models.CharField(max_length=100)
    outcome = models.CharField(max_length=10)
    score = models.IntegerField()
    wickets = models.IntegerField()
    timestamp = models.DateTimeField(auto_now_add=True)



# game/models.py (add to existing)

class GameRoom(models.Model):
    STATUS_CHOICES = [
        ('waiting', 'Waiting for Player 2'),
        ('live', 'Live Match'),
        ('completed', 'Completed'),
    ]
    
    code = models.CharField(max_length=8, unique=True)
    player1 = models.ForeignKey(User, related_name='rooms_as_p1', on_delete=models.CASCADE)
    player2 = models.ForeignKey(User, null=True, blank=True, related_name='rooms_as_p2', on_delete=models.SET_NULL)
    state = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='waiting')
    created_at = models.DateTimeField(auto_now_add=True)



class UserDeck(models.Model):
    """A user owns exactly 2 decks. One is chosen as active before a match."""
    user         = models.ForeignKey(User, on_delete=models.CASCADE, related_name='decks')
    team         = models.ForeignKey(Team, on_delete=models.CASCADE)
    name         = models.CharField(max_length=100)          # e.g. "My India Deck"
    cards        = models.ManyToManyField(PlayerCard, through='DeckCard')
    is_active    = models.BooleanField(default=False)        # the deck chosen to play

    def total_weightage(self):
        return sum(dc.player_card.weightage for dc in self.deckcard_set.all())

    def __str__(self):
        return f"{self.user.username} – {self.name}"

    class Meta:
        constraints = [
            # max 2 decks per user
            models.UniqueConstraint(
                fields=['user', 'team'],
                name='unique_user_team_deck'
            )
        ]


class DeckCard(models.Model):
    deck        = models.ForeignKey(UserDeck, on_delete=models.CASCADE)
    player_card = models.ForeignKey(PlayerCard, on_delete=models.CASCADE)
    slot        = models.IntegerField(null=True, blank=True)

    class Meta:
        unique_together = ('deck', 'player_card')

    def __str__(self):
        return f"{self.deck.name} – {self.player_card.name}"
    


class UserPrizeCard(models.Model):
    """Admin assigns prize cards to specific users manually."""
    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name='prize_cards')
    player_card = models.ForeignKey(PlayerCard, on_delete=models.CASCADE)
    assigned_at = models.DateTimeField(auto_now_add=True)
    # Which deck this prize card is slotted into (null = not used in any deck)
    deck        = models.ForeignKey(UserDeck, on_delete=models.SET_NULL, null=True, blank=True, related_name='prize_slots')

    class Meta:
        unique_together = ('user', 'player_card')  # user can't have same prize card twice

    def __str__(self):
        return f"{self.user.username} → {self.player_card.name}"