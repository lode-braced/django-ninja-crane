from django.contrib import admin
from django.urls import path

from crane import VersionedNinjaAPI
from test_app.api import router as persons_router

api = VersionedNinjaAPI(api_label="default", app_label="test_app")
api.add_router("/persons", persons_router)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
]
