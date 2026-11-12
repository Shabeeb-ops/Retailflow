from django.urls import path
from .import views
from .views import branch_list, add_branch

urlpatterns = [
    path("register/",views.company_registration,name="company_registration"),
    path("branches/", branch_list, name="branch_list"),
    path("branches/add/", add_branch, name="add_branch"),
path(
    "branches/<uuid:branch_id>/edit/",
    views.edit_branch,
    name="edit_branch",
),

]