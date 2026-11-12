

from django.urls import path
from . import views

urlpatterns = [
    path("movement/", views.stock_movement_view, name="stock_movement"),
]