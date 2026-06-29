from django.shortcuts import render

from mareas.services import get_mareas_context


def mareas_view(request):
    return render(request, "mareas/index.html", get_mareas_context())
