from django.db import models

# Create your models here.
class PlayerCard(models.Model):
    name = models.CharField(max_length=100)
    batting = models.IntegerField()
    bowling = models.IntegerField()
    runs = models.IntegerField()