from django.urls import path
from . import views

urlpatterns = [
    path("", views.pos_terminal, name="pos_terminal"),
    path("checkout/", views.pos_checkout, name="pos_checkout"),
    path("receipt/<int:sale_id>/", views.pos_receipt, name="pos_receipt"),
    path("receipt/<int:sale_id>/print/", views.pos_receipt_print, name="pos_receipt_print"),
    path("hold/", views.pos_hold_cart, name="pos_hold_cart"),
    path("recall/<int:held_id>/", views.pos_recall_cart, name="pos_recall_cart"),
    path("held-carts/", views.pos_list_held_carts, name="pos_list_held_carts"),
    path("held-carts/<int:held_id>/delete/", views.pos_delete_held_cart, name="pos_delete_held_cart"),
    path("barcode/<str:code>/", views.pos_barcode_search, name="pos_barcode_search"),
    path("history/", views.pos_sales_history, name="pos_sales_history"),
    path("history/<int:sale_id>/", views.pos_sale_detail, name="pos_sale_detail"),
    path("reports/", views.pos_reports, name="pos_reports"),
    path("settings/", views.pos_settings, name="pos_settings"),
]

