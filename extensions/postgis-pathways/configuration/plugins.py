# PostGIS + netbox-pathways extension.
#
# This file REPLACES configuration/plugins.py when this extension is
# adopted (see docs/OPERATIONS.md §11). It is the base plugins.py's content
# PLUS netbox_pathways — NOT an append, because plugins.py is the last
# config file NetBox loads (see extra.py's comment on load order), so there
# is nothing earlier to append onto from a separate file.
#
# MAINTENANCE: if you change the base configuration/plugins.py (add/remove
# a core plugin, change a PLUGINS_CONFIG value), you must mirror that change
# here too. The two files are not kept in sync automatically.

PLUGINS = [
    "netbox_secrets",
    "netbox_bgp",
    "netbox_fms",
    "netbox_example_plugin",
    "netbox_inventory",
    "netbox_otp_plugin",
    "netbox_floorplan",  # pip package is netbox-floorplan-plugin, app label is netbox_floorplan
    "netbox_wdm",
    "netbox_trace_print",
    "netbox_pathways",
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
    "netbox_pathways": {
        # Spatial Reference ID. 4326 = WGS84 (plain GPS lat/lon). Required —
        # netbox-pathways will not load without it.
        "srid": 4326,
    },
}
