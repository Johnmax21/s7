from django.contrib import admin

from .models import PlayerCard
from .models import Team
from .models import SupportCard
from .models import UserDeck
from .models import DeckCard
admin.site.register(DeckCard)
admin.site.register(UserDeck)
admin.site.register(SupportCard)
admin.site.register(Team)
admin.site.register(PlayerCard)
# s7app/admin.py
from .models import UserPrizeCard

@admin.register(UserPrizeCard)
class UserPrizeCardAdmin(admin.ModelAdmin):
    list_display  = ['user', 'player_card', 'deck', 'assigned_at']
    list_filter   = ['user']
    search_fields = ['user__username', 'player_card__name']

from django.contrib import admin
from .models import Season, Tournament, TournamentParticipant

@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'status', 'is_active', 'start_date']

@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    list_display = ['name', 'season', 'format', 'status', 'hosted_by']

@admin.register(TournamentParticipant)
class TournamentParticipantAdmin(admin.ModelAdmin):
    list_display = ['user', 'tournament', 'seed', 'status']