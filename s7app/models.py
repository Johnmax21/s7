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
    
    # Track which deck each player used
    player1_deck = models.ForeignKey('UserDeck', null=True, blank=True, 
                                      related_name='used_as_p1', on_delete=models.SET_NULL)
    player2_deck = models.ForeignKey('UserDeck', null=True, blank=True, 
                                      related_name='used_as_p2', on_delete=models.SET_NULL)

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



# ═══════════════════════════════════════════════════════════════════
# Add these imports to the top of s7app/models.py if not already present
# ═══════════════════════════════════════════════════════════════════
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


# ═══════════════════════════════════════════════════════════════════
# SEASON
# ═══════════════════════════════════════════════════════════════════

class Season(models.Model):
    STATUS_CHOICES = [
        ('upcoming',  'Upcoming'),
        ('active',    'Active'),
        ('completed', 'Completed'),
    ]

    name       = models.CharField(max_length=100)
    code       = models.CharField(max_length=20, unique=True)   # e.g. "S1", "2026-Q1"
    start_date = models.DateField()
    end_date   = models.DateField(null=True, blank=True)

    status    = models.CharField(max_length=20, choices=STATUS_CHOICES, default='upcoming')
    is_active = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_date']
        constraints = [
            # Only one season can be the active one at any given time.
            models.UniqueConstraint(
                fields=['is_active'],
                condition=models.Q(is_active=True),
                name='one_active_season_at_a_time',
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"

    def save(self, *args, **kwargs):
        # Keep status in sync with is_active so the two fields
        # never silently disagree with each other.
        if self.is_active:
            self.status = 'active'
        super().save(*args, **kwargs)


# ═══════════════════════════════════════════════════════════════════
# TOURNAMENT
# ═══════════════════════════════════════════════════════════════════

class Tournament(models.Model):
    FORMAT_CHOICES = [
        ('round_robin', 'Round Robin'),
        ('knockout',    'Knockout'),
    ]
    STATUS_CHOICES = [
        ('upcoming',  'Upcoming'),
        ('ongoing',   'Ongoing'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    SEEDING_METHOD_CHOICES = [
        ('manual', 'Manual (admin sets seed order)'),
        # 'stat_based' reserved for a future upgrade — not implemented yet
    ]

    season    = models.ForeignKey(Season, on_delete=models.CASCADE, related_name='tournaments')
    name      = models.CharField(max_length=150)
    hosted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='hosted_tournaments',
        help_text="Must be a staff/admin account — enforce at the view layer."
    )

    format = models.CharField(max_length=20, choices=FORMAT_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='upcoming')

    max_participants = models.PositiveIntegerField()
    seeding_method    = models.CharField(max_length=20, choices=SEEDING_METHOD_CHOICES, default='manual')
    seeding_locked    = models.BooleanField(
        default=False,
        help_text="Set True the moment fixtures are generated. No participant/seed changes after this."
    )

    # ── Point system — base scoring only. Bonus-point rules (early win,
    # margin win, etc.) are deliberately NOT modeled yet — those rules
    # haven't been decided. Add them as their own migration later; see
    # calculate_bonus_points() below for the extension point. ──────────
    points_win  = models.PositiveIntegerField(default=2)
    points_tie  = models.PositiveIntegerField(default=1)
    points_loss = models.PositiveIntegerField(default=0)

    start_date = models.DateTimeField(null=True, blank=True)
    end_date   = models.DateTimeField(null=True, blank=True)
    rules_text = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            # Only one tournament can be upcoming/ongoing at a time, system-wide.
            models.UniqueConstraint(
                fields=['status'],
                condition=models.Q(status__in=['upcoming', 'ongoing']),
                name='one_active_tournament_at_a_time',
            )
        ]

    def __str__(self):
        return f"{self.name} — {self.get_status_display()}"

    def clean(self):
        if self.status in ('upcoming', 'ongoing'):
            clashing = Tournament.objects.filter(
                status__in=['upcoming', 'ongoing']
            ).exclude(pk=self.pk)
            if clashing.exists():
                raise ValidationError(
                    "Another tournament is already upcoming or ongoing. "
                    "Complete or cancel it before starting a new one."
                )

    def calculate_bonus_points(self, *, winning_round, run_margin):
        """
        Extension point for future bonus-point rules (early win, margin
        win, etc.). Returns 0 for now — no bonus system is active yet.
        Once the rules are decided, add the relevant fields to this model
        via a new migration and implement the logic here. Callers in
        mp_result already call this function, so wiring in real bonus
        logic later won't require touching the stats-update code path.
        """
        return 0


# ═══════════════════════════════════════════════════════════════════
# TOURNAMENT PARTICIPANT
# ═══════════════════════════════════════════════════════════════════

class TournamentParticipant(models.Model):
    STATUS_CHOICES = [
        ('active',     'Active'),
        ('eliminated', 'Eliminated'),
        ('withdrawn',  'Withdrawn'),
    ]

    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name='participants')
    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    deck       = models.ForeignKey(
        'UserDeck', null=True, blank=True, on_delete=models.SET_NULL,
        help_text="Deck locked in for this tournament. Optional until the player confirms one."
    )

    seed = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Set manually by the admin before the tournament starts. Determines bracket/pairing order."
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')

    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['seed', 'joined_at']
        unique_together = [('tournament', 'user')]
        constraints = [
            # Seed numbers must be unique within a tournament.
            models.UniqueConstraint(
                fields=['tournament', 'seed'],
                condition=models.Q(seed__isnull=False),
                name='unique_seed_per_tournament',
            )
        ]

    def __str__(self):
        return f"{self.user.username} in {self.tournament.name} (seed {self.seed or '—'})"

    def clean(self):
        # Block joining a tournament that's already locked/started.
        if self.tournament.seeding_locked and self.pk is None:
            raise ValidationError("This tournament has already started — no new participants can join.")

        # Enforce max_participants at the model level, not just in the view.
        if self.pk is None:
            current_count = TournamentParticipant.objects.filter(tournament=self.tournament).count()
            if current_count >= self.tournament.max_participants:
                raise ValidationError("This tournament is full.")