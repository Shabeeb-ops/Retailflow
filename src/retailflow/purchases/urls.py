from django.urls import path
from . import views

urlpatterns = [
    path("payments/", views.payment_list, name="purchase_payment_list"),
    path("invoices/<int:pk>/payments/add/", views.payment_form, name="add_purchase_payment"),
    path("invoices/", views.invoice_list, name="purchase_invoice_list"),
    path("invoices/<int:pk>/", views.invoice_detail, name="purchase_invoice_detail"),
    path("invoices/<int:pk>/reconcile/", views.invoice_reconcile, name="reconcile_purchase_invoice"),
    path("receipts/", views.receipt_list, name="goods_receipt_list"),
    path("orders/<int:order_pk>/receive/", views.receipt_form, name="add_goods_receipt"),
    path("orders/<int:order_pk>/receipts/<int:pk>/edit/", views.receipt_form, name="edit_goods_receipt"),
    path("receipts/<int:pk>/", views.receipt_detail, name="goods_receipt_detail"),
    path("receipts/<int:pk>/confirm/", views.receipt_confirm, name="confirm_goods_receipt"),
    path("", views.order_list, name="purchase_order_list"),
    path("orders/add/", views.order_form, name="add_purchase_order"),
    path("orders/<int:pk>/", views.order_detail, name="purchase_order_detail"),
    path("orders/<int:pk>/edit/", views.order_form, name="edit_purchase_order"),
    path("orders/<int:pk>/place/", views.order_action, {"action": "place"}, name="place_purchase_order"),
    path("orders/<int:pk>/cancel/", views.order_action, {"action": "cancel"}, name="cancel_purchase_order"),
]
