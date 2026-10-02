from netbox.views import generic

from .models import ExampleWidget
from .tables import ExampleWidgetTable


class ExampleWidgetView(generic.ObjectView):
    queryset = ExampleWidget.objects.all()


class ExampleWidgetListView(generic.ObjectListView):
    queryset = ExampleWidget.objects.all()
    table = ExampleWidgetTable
