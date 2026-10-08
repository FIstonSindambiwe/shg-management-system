from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "SHG Management System"
admin.site.site_title = "SHG Admin"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("accounts.urls")),
    path("api/", include("shg.urls")),
]
