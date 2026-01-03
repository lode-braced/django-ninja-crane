from django.contrib import admin
from django.urls import path
from ninja import NinjaAPI

from test_app.api import router as persons_router

api = NinjaAPI()
api.add_router("/persons", persons_router)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
]
