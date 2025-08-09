from django.db import models

# Create your models here.
class PlayerCard(models.Model):
    name = models.CharField(max_length=100)
    batting = models.IntegerField()
    bowling = models.IntegerField()
    runs = models.IntegerField()
    image = models.ImageField(upload_to='player_images/', null=True, blank=True)



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
