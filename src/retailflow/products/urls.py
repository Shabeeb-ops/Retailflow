from django.urls import path
from . import views

urlpatterns = [
    path("add-category/", views.add_category, name="add_category"),
    path("<int:pk>/category-edit/", views.edit_category, name="edit_category"),
    path("add/", views.add_product, name="add_product"),
    path("<int:pk>/edit/", views.edit_product, name="edit_product"),
    path("", views.product_list, name="product_list"),
    path("inline-save/", views.inline_save, name="inline_save"),
    path("import/", views.import_products, name="import_products"),
]