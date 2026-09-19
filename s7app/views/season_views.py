"""
s7app/views/season_views.py — Minimal season creation/listing for admins.
"""
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from ..models import Season


@staff_member_required
def season_list(request):
    seasons = Season.objects.all().order_by('-start_date')
    return render(request, 'seasons/list.html', {'seasons': seasons})


@staff_member_required
def create_season(request):
    if request.method == 'POST':
        season = Season(
            name=request.POST.get('name', '').strip(),
            code=request.POST.get('code', '').strip(),
            start_date=request.POST.get('start_date'),
            end_date=request.POST.get('end_date') or None,
            is_active='is_active' in request.POST,
        )
        try:
            season.full_clean()
            if season.is_active:
                # Only one season can be active — deactivate any current one first.
                Season.objects.filter(is_active=True).update(is_active=False)
            season.save()
            messages.success(request, f'"{season.name}" created.')
            return redirect('season_list')
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))

    return render(request, 'seasons/create.html')