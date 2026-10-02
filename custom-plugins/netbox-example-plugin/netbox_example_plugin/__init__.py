from netbox.plugins import PluginConfig


class ExamplePluginConfig(PluginConfig):
    name = "netbox_example_plugin"
    verbose_name = "Example Plugin"
    description = "Starter plugin scaffold for developing your own NetBox plugin in Docker."
    author = "Jean-Pierre"
    version = "0.1.0"
    base_url = "example-plugin"
    min_version = "4.6.0"
    max_version = "4.6.99"


config = ExamplePluginConfig
