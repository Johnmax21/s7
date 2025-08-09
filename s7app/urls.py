from django.urls import path,include
from .import views
urlpatterns = [

    path('', views.toss_view, name='toss_view'),
    path('game/', views.game_start, name='game_start'),
    ]