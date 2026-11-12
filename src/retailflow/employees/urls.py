from django.urls import path
from pos.views import pos_terminal


from .import views

urlpatterns = [
    path(
        "",
        views.employee_list,
        name="employee_list"
    ),
    path(
        "add/",
        views.create_employee,
        name="create_employee"
    ),
    path(
        "<int:pk>/edit/",
        views.edit_employee,
        name="edit_employee"
    ),

    path("login/", views.employee_login, name="employee_login"),
    path("dashboard/", views.employee_dashboard, name="employee_dashboard"),
    path("logout/", views.employee_logout, name="employee_logout"),
    path("manager/", views.manager_dashboard, name="manager_dashboard"),
    path("cashier/", pos_terminal, name="pos"),
    path("inventory/", views.inventory, name="inventory"),

]
