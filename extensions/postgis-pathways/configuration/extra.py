####
## PostGIS + netbox-pathways extension.
##
## This file REPLACES configuration/extra.py when this extension is adopted
## (see docs/OPERATIONS.md §11).
##
## NOTE ON LOAD ORDER: NetBox imports config files in a fixed order —
## configuration.py, extra.py, logging.py, plugins.py — so extra.py can only
## reach back into names already defined by configuration.py (like
## DATABASES). It CANNOT reach forward into plugins.py (PLUGINS,
## PLUGINS_CONFIG), because that file hasn't been loaded yet at this point.
## That's why plugin activation for this extension lives in this
## directory's own `plugins.py` (a full replacement, not an append) rather
## than here — see that file's own comments.
####

from netbox.configuration.configuration import DATABASES

# Switch the database backend to PostGIS. Requires the `postgres` service to
# be running a PostGIS-enabled image (see docker-compose.postgis.yml) with
# `CREATE EXTENSION IF NOT EXISTS postgis;` already run once against the DB
# — see docs/OPERATIONS.md §11.3.
DATABASES["default"]["ENGINE"] = "django.contrib.gis.db.backends.postgis"
