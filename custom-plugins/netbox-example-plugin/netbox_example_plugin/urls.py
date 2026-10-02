from django.urls import path

from . import views

urlpatterns = [
    path("widgets/", views.ExampleWidgetListView.as_view(), name="examplewidget_list"),
    path("widgets/<int:pk>/", views.ExampleWidgetView.as_view(), name="examplewidget"),
]
