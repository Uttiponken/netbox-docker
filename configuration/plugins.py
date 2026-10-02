# Add your plugins and plugin settings here.
#
# All plugins listed here must also be pinned in ../plugin_requirements.txt
# (third-party) or built by ../Dockerfile-Plugins (your own), and the image
# must be rebuilt after any change: `docker compose build --no-cache`.

PLUGINS = [
    "netbox_secrets",
    "netbox_bgp",
    "netbox_fms",
    "netbox_example_plugin",
    "netbox_inventory",
    "netbox_otp_plugin",
    "netbox_floorplan",  # pip package is netbox-floorplan-plugin, app label is netbox_floorplan
    "netbox_wdm",
]

PLUGINS_CONFIG = {
    "netbox_secrets": {
        # See https://github.com/netbox-community/netbox-secrets for available keys.
    },
    "netbox_bgp": {
        # See https://github.com/netbox-community/netbox-bgp for available keys.
    },
    # netbox_fms has no required PLUGINS_CONFIG entries.
    "netbox_inventory": {
        # See https://github.com/ArnesSI/netbox-inventory for available keys.
    },
    "netbox_otp_plugin": {
        # Off by default: flip to True only after every user has registered a
        # device with `manage.py addtotp <username>`, or they'll be locked out.
        "otp_required": False,
    },
}
