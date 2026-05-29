from django.db import models
from django.contrib.auth.models import User


class Team(models.Model):
    name = models.CharField(max_length=100)
    logo = models.ImageField(upload_to='team_logos/', null=True, blank=True)
# Create your models here.
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
    # Needed for Spin Basher — mark bowler cards that are spinners
    is_spinner = models.BooleanField(default=False)

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
from django.contrib.auth.models import User

class GameRoom(models.Model):
    code = models.CharField(max_length=8, unique=True)
    player1 = models.ForeignKey(User, related_name='rooms_as_p1', on_delete=models.CASCADE)
    player2 = models.ForeignKey(User, null=True, blank=True, related_name='rooms_as_p2', on_delete=models.SET_NULL)
    state = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)