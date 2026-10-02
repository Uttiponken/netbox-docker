import django_tables2 as tables

from netbox.tables import NetBoxTable

from .models import ExampleWidget


class ExampleWidgetTable(NetBoxTable):
    name = tables.Column(linkify=True)

    class Meta(NetBoxTable.Meta):
        model = ExampleWidget
        fields = ("pk", "id", "name")
        default_columns = ("name",)
