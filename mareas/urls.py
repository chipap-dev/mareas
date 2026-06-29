from django.urls import path

from mareas.views import mareas_view, mareas_actualizar_view

app_name = "mareas"

urlpatterns = [
    path("", mareas_view, name="index"),
    path("actualizar/", mareas_actualizar_view, name="actualizar"),
]
