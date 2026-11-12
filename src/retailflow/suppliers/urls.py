from django.urls import path
from . import views

urlpatterns = [
    path("", views.supplier_list, name="supplier_list"),
    path("add/", views.supplier_form, name="add_supplier"),
    path("products/", views.supplier_product_list, name="supplier_product_list"),
    path("products/add/", views.supplier_product_form, name="add_supplier_product"),
    path("products/<int:pk>/edit/", views.supplier_product_form, name="edit_supplier_product"),
    path("products/<int:pk>/deactivate/", views.supplier_product_deactivate, name="deactivate_supplier_product"),
    path("<int:pk>/", views.supplier_detail, name="supplier_detail"),
    path("<int:pk>/edit/", views.supplier_form, name="edit_supplier"),
    path("<int:pk>/activate/", views.supplier_status, {"active": True}, name="activate_supplier"),
    path("<int:pk>/deactivate/", views.supplier_status, {"active": False}, name="deactivate_supplier"),
]
