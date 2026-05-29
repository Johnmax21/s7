from django.contrib import admin

from django.contrib import admin
from .models import PlayerCard
from .models import Team
from .models import SupportCard
from .models import GameHistory     
admin.site.register(SupportCard)
admin.site.register(GameHistory)
admin.site.register(Team)
admin.site.register(PlayerCard)
