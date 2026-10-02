# netbox-example-plugin

Starter scaffold for a custom NetBox plugin, built and run through the same
`Dockerfile-Plugins` image as the third-party plugins.

## Dev loop

`docker-compose.override.yml` bind-mounts this directory into the container
and `Dockerfile-Plugins` installs it with `pip install -e`, so:

```bash
docker compose up -d --build   # first time, or after changing pyproject.toml
docker compose exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py makemigrations netbox_example_plugin
docker compose exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py migrate
docker compose restart netbox netbox-worker
```

Editing `.py` files under `netbox_example_plugin/` takes effect on a plain
`docker compose restart netbox` (no rebuild needed, since the source is bind-mounted
and installed with `-e`). Only rebuild the image when you change `pyproject.toml`
dependencies.

## Renaming this plugin

1. Rename the `netbox_example_plugin/` directory and its `name`/`base_url` in
   `__init__.py`.
2. Update `pyproject.toml`'s `name` and `packages.find.include`.
3. Update `PLUGINS` in `../../configuration/plugins.py`.
4. Update the bind mount path in `../../docker-compose.override.yml`.
