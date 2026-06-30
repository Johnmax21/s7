from django.contrib import admin

from .models import PlayerCard
from .models import Team
from .models import SupportCard
from .models import GameHistory     
from .models import UserDeck
from .models import DeckCard
admin.site.register(DeckCard)
admin.site.register(UserDeck)
admin.site.register(SupportCard)
admin.site.register(GameHistory)
admin.site.register(Team)
admin.site.register(PlayerCard)
# s7app/admin.py
from .models import UserPrizeCard

@admin.register(UserPrizeCard)
class UserPrizeCardAdmin(admin.ModelAdmin):
    list_display  = ['user', 'player_card', 'deck', 'assigned_at']
    list_filter   = ['user']
    search_fields = ['user__username', 'player_card__name']