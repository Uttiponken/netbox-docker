# Build with all plugins on an online host, replace an existing netbox-docker on an offline host, keep the data

This guide builds this repository (NetBox 4.6 + the plugins in `plugin_requirements.txt` + the example plugin +
**netbox-trace-print** + PostGIS/netbox-pathways) on an internet-connected Linux host, carries the result into an
air-gapped Linux host, and replaces an **older netbox-docker installation** there **without losing its data**.
It also takes a verified backup of the old installation first.

It complements `OPERATIONS.md` (§5 backups, §6 upgrades, §7 air-gapped deployment). Read this one for the
"replace an existing installation" case; it is written for the image set this repository builds today.

---

## 0. Overview

```
 ONLINE BUILD HOST                     AIR GAP                 OFFLINE TARGET HOST
 A  build the images            ──►   B  carry the bundle ──►  C  look at the old installation
    pull postgis + valkey                 (images.tar.gz,          D  BACK UP the old installation
    test, export a bundle                  repo tarball,           E  rehearse on a copy (recommended)
                                           SHA256SUMS)             F  cut over: restore, start, verify
                                                                   G  roll back, or clean up later
```

**What is built.** One image, `netbox:latest-plugins-postgis`, with NetBox v4.6 (netbox-docker release 5.0.2) and
these plugins baked in: netbox-secrets, netbox-bgp, netbox-fms, netbox-inventory, netbox-otp-plugin,
netbox-floorplan-plugin, netbox-wdm, netbox-pathways, the example plugin and **netbox-trace-print**. Two more
images are pulled as they are: `postgis/postgis:18-3.6-alpine` (the database) and `valkey/valkey:9.1-alpine`
(Redis). About 2.3 GB before compression.

**Rules this guide follows. Keep them if you change anything.**

1. **Back up first, and prove the backup is readable** (a dump you have never listed is not a backup).
2. **Never point the new Postgres at the old Postgres data volume.** The new database is PostgreSQL 18; a data
   directory from another major version will not start. The data travels as a logical dump (`pg_dump` →
   `pg_restore`), which works across major versions.
3. **The new installation gets its own Compose project name**, so it creates its own volumes and the old
   volumes stay untouched. That is also your rollback.
4. **Nothing is built or pulled on the target.** There is no internet there; everything arrives in the bundle.
5. **Carry over `SECRET_KEY` and `API_TOKEN_PEPPER_1`** from the old installation. Other values would invalidate
   sessions and API tokens.
6. **Both hosts have the same CPU architecture** (check `uname -m` on both; this guide assumes `x86_64`). An image
   built on arm64 does not run on x86_64.
7. **The plugins are inside the image.** The development file `docker-compose.override.yml` (which mounts source
   trees into the containers) must not be used for this. A missing mount directory would be created empty and hide
   the plugin, and it would not start.

**What was tested** (on the development machine, with this repository's own data): the offline overlay builds; the
backup commands; a restore into a brand-new PostGIS database with every row count identical; the file volumes
restored from their archives; the plugins, including netbox-trace-print 0.6.2 from inside the image, load and
print a PDF with no source tree mounted. **Not tested:** upgrading a database from an older NetBox version, because
that needs your data. Step E exists for that: it does the upgrade on a copy so a problem shows up before anything
is replaced.

---

## A. On the online build host

Needs: Linux x86_64 (same as the target), Docker Engine 24+ with Compose v2 **2.17 or newer** (for
`additional_contexts`), git, about 15 GB free disk.

### A1. Check the host

```bash
uname -m                 # must equal the target's
docker version --format '{{.Server.Version}}'
docker compose version --short
df -h /var/lib/docker
```

### A2. Get the sources, side by side

```bash
mkdir -p ~/nbbuild && cd ~/nbbuild
git clone https://github.com/Uttiponken/netbox-docker.git
git clone --branch v0.6.2 https://github.com/Uttiponken/netbox-trace-print.git
ls netbox-docker/docker-compose.offline.yml netbox-docker/offline.env.example   # both must exist
```

The two directories must be siblings: the build copies the plugin from `../netbox-trace-print`. Both
repositories are private; authenticate first (`gh auth login`, or a token in the URL). Record what you are
building:

```bash
git -C netbox-docker rev-parse HEAD
git -C netbox-trace-print describe --tags
```

### A3. Configure and build

```bash
cd ~/nbbuild/netbox-docker
cp offline.env.example .env            # project name, port, and the compose files to use (read the comments)

# Stage 1: the base plugin image. COMPOSE_FILE here overrides .env for this one command.
COMPOSE_FILE=docker-compose.yml:docker-compose.offline.yml docker compose build --no-cache netbox

# Stage 2: the PostGIS image (built on stage 1), using the full chain from .env
docker compose build --no-cache netbox
```

Look at the output for `Unable to load plugin`: there must be none. Then pull the two other images:

```bash
docker pull --platform linux/amd64 postgis/postgis:18-3.6-alpine
docker pull docker.io/valkey/valkey:9.1-alpine
docker compose config --images | sort -u      # exactly the three images that will be shipped
```

### A4. Test the build here before shipping it

Use a throwaway project so nothing real is touched. A brand-new NetBox database needs PostGIS **before** NetBox
starts, otherwise the pathways migration fails.

```bash
export COMPOSE_PROJECT_NAME=nbtest NETBOX_HTTP_PORT=18000
docker compose up -d --wait postgres
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE EXTENSION IF NOT EXISTS postgis"'
docker compose up -d                           # first start: migrations, takes several minutes
docker compose logs -f netbox                  # wait for "Listening at", Ctrl-C to leave
docker compose ps                              # everything healthy

docker compose exec -T netbox sh -c 'cd /opt/netbox/netbox && python manage.py shell -c "from django.conf import settings; print(settings.PLUGINS)"'
docker compose exec -T netbox sh -c 'cd /opt/netbox/netbox && python manage.py showmigrations | grep -c "\[ \]"'   # 0
docker compose exec -T netbox sh -c 'uv pip list 2>/dev/null | grep -i netbox'                                # the pinned versions
# optionally open http://localhost:18000 and look at Plugins → Plugins

docker compose down -v                         # throw the test stack away, volumes included
unset COMPOSE_PROJECT_NAME NETBOX_HTTP_PORT
```

### A5. Export the bundle

```bash
mkdir -p ~/nbbuild/bundle && cd ~/nbbuild/bundle

docker save netbox:latest-plugins-postgis postgis/postgis:18-3.6-alpine docker.io/valkey/valkey:9.1-alpine \
  | gzip > images.tar.gz

# the repository as it is (no .git, no caches); .env is NOT included, you create it on the target
tar czf netbox-docker-repo.tar.gz -C ~/nbbuild \
  --exclude='netbox-docker/.git' --exclude='netbox-docker/.env' --exclude='__pycache__' --exclude='*.pyc' netbox-docker

# what is in it, for your records
{
  echo "built: $(date -u +%FT%TZ) on $(uname -m)"
  echo "netbox-docker: $(git -C ~/nbbuild/netbox-docker rev-parse HEAD)"
  echo "netbox-trace-print: $(git -C ~/nbbuild/netbox-trace-print describe --tags)"
  docker image inspect --format '{{index .RepoTags 0}} {{.Id}}' netbox:latest-plugins-postgis postgis/postgis:18-3.6-alpine docker.io/valkey/valkey:9.1-alpine
  docker run --rm --entrypoint /usr/local/bin/uv netbox:latest-plugins-postgis pip list 2>/dev/null | grep -i -E "^netbox|^django "
} > MANIFEST.txt

cp ~/nbbuild/netbox-docker/docs/OFFLINE-REPLACE-INSTALL.md .      # this guide travels with the bundle
sha256sum images.tar.gz netbox-docker-repo.tar.gz MANIFEST.txt OFFLINE-REPLACE-INSTALL.md > SHA256SUMS
ls -lh
```

The Docker Engine and Compose packages are **not** in the bundle: the target already runs Docker. If its Compose
is the old `docker-compose` v1, install the Compose v2 plugin first (`OPERATIONS.md` §7.3 shows how to carry the
`.deb` packages).

## B. Carry it across

Move the five files in `~/nbbuild/bundle` across your air gap using your site's approved process. On the target,
put them in a working directory, for example `/opt/nb-bundle`, and check them:

```bash
cd /opt/nb-bundle && sha256sum -c SHA256SUMS      # every line must say OK
```

---

## C. On the target: look at the old installation (changes nothing)

Set these once per shell and adjust them. `OLD` is the directory of the **old** installation (where its
`docker-compose.yml` lives). Run the old installation's own `docker compose` command in it; the examples assume
plain `docker compose`.

```bash
export OLD=/opt/netbox-docker                 # the old installation
export NEW=/opt/netbox-plugins                # the new one (does not exist yet)
export BK=/opt/netbox-backups/$(date +%F)     # where this backup goes: another disk is better
cd "$OLD"
docker compose ps                             # it should be running and healthy
```

Write down the facts that decide how careful to be:

```bash
# Compose project name, and the real names of its volumes
OLDPROJ=$(docker inspect "$(docker compose ps -q postgres)" --format '{{index .Config.Labels "com.docker.compose.project"}}'); echo "$OLDPROJ"
docker volume ls | grep "$OLDPROJ"

# NetBox version, PostgreSQL version, database size, extensions
docker compose exec -T netbox sh -c 'cd /opt/netbox/netbox && python manage.py shell -c "from django.conf import settings; print(settings.RELEASE.full_version)"' | tail -1
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "select version()" -c "select pg_size_pretty(pg_database_size(current_database()))" -c "select extname from pg_extension order by 1"'

# Which apps (core and plugins) have data in the database
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "select string_agg(distinct app, '"'"', '"'"' order by app) from django_migrations"'

# Free space for the backup, and the size of the file volumes
df -h "$(dirname "$BK")"; docker system df -v | grep "$OLDPROJ"
```

How to read it:

| What you found | What it means |
|---|---|
| PostgreSQL major **is not 18** | Normal. That is why the data moves as a dump, never as a volume. |
| NetBox is **4.6.x** | The simple case. The new image starts on the restored data. |
| NetBox is an **older 4.x** | The new container runs all newer migrations on first start (`migrate`, `trace_paths`, `reindex`), which is why you rehearse in step E. Read the NetBox release notes for every version in between. |
| NetBox is **3.x** | Stop and ask for an upgrade path first: NetBox 4.0 had requirements on the version you upgrade from. |
| An app in `django_migrations` that is **not** among the plugins in section 0 | Its data stays in the database but the new NetBox has no code for it. If you still need that plugin, add it to `plugin_requirements.txt` and rebuild (A3) before going on. |
| The old installation has its own settings (LDAP, SSO, SMTP, proxy) | Steps F4 and F5 carry them over. Note them now: read `$OLD/env/*.env` and `$OLD/configuration/*.py`. |

## D. On the target: BACK UP the old installation first

Do this before you load, import or start anything of the new build. It needs a short downtime: the web and worker
containers are stopped so nothing can change between the database dump and the file archives.

```bash
mkdir -p "$BK" && chmod 700 "$BK"
cd "$OLD"

# D1. Stop writers. The database and Redis keep running.
docker compose stop netbox netbox-worker
```

```bash
# D2. The database: one consistent dump in PostgreSQL's custom format
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$BK/netbox-db.dump"

# prove that it is readable and not empty
ls -lh "$BK/netbox-db.dump"
docker compose exec -T postgres sh -c 'pg_restore --list' < "$BK/netbox-db.dump" | head -8
docker compose exec -T postgres sh -c 'pg_restore --list' < "$BK/netbox-db.dump" | grep -c "TABLE DATA"
```

```bash
# D3. Row counts now, to compare after the restore
cat > "$BK/counts.sql" <<'EOF'
SELECT 'sites', count(*) FROM dcim_site UNION ALL SELECT 'devices', count(*) FROM dcim_device
UNION ALL SELECT 'interfaces', count(*) FROM dcim_interface UNION ALL SELECT 'cables', count(*) FROM dcim_cable
UNION ALL SELECT 'circuits', count(*) FROM circuits_circuit UNION ALL SELECT 'ip addresses', count(*) FROM ipam_ipaddress
UNION ALL SELECT 'users', count(*) FROM users_user UNION ALL SELECT 'api tokens', count(*) FROM users_token
UNION ALL SELECT 'tenants', count(*) FROM tenancy_tenant ORDER BY 1;
EOF
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F": "' < "$BK/counts.sql" | tee "$BK/counts.txt"
```

```bash
# D4. The file volumes (uploaded images and attachments, reports, scripts), using the old NetBox image as the tool
OLDIMG=$(docker inspect "$(docker compose ps -a -q netbox)" --format '{{.Config.Image}}')      # -a: the container is stopped now
for vol in netbox-media-files netbox-reports-files netbox-scripts-files; do
  docker run --rm --user 0 --entrypoint tar -v "${OLDPROJ}_${vol}:/data:ro" -v "$BK:/backup" "$OLDIMG" \
    czf "/backup/${vol}.tar.gz" -C /data .
done
ls -lh "$BK"

# D5. The configuration, including the secrets in env/ (so keep this archive private)
tar czf "$BK/config.tar.gz" --exclude='./.git' -C "$OLD" .
chmod 600 "$BK"/*
```

```bash
# D6. Checksums, then a copy OFF this host (another disk or machine) and a read test of the copy
( cd "$BK" && sha256sum * > SHA256SUMS && cat SHA256SUMS )
# cp -a "$BK" /mnt/other-disk/ && ( cd /mnt/other-disk/$(basename "$BK") && sha256sum -c SHA256SUMS )
```

**Optional but cheap while the stack is down: a byte-level copy of the old database volume.** It lets you bring
the old installation back exactly as it was, even without the dump:

```bash
docker compose stop postgres
docker run --rm --user 0 --entrypoint tar -v "${OLDPROJ}_netbox-postgres:/data:ro" -v "$BK:/backup" "$OLDIMG" \
  czf /backup/postgres-volume.tar.gz -C /data .
docker compose start postgres
```

**Bring the old installation back up if you are not cutting over right now:** `docker compose start netbox netbox-worker`.
Any change made after this point is not in the backup.

---

## E. Rehearse on the target (strongly recommended, no impact on the old installation)

Do steps F1 to F11 once as a **rehearsal**: it proves that the dump restores, that your NetBox version upgrades
(its migrations run on first start), how long it takes (that is your downtime for the real run), and that the
plugins work on your data. Use these settings, which keep it apart from everything else:

```bash
export NEW=/opt/netbox-rehearsal
export PROJ=nbrehearsal        # in F3 use this as COMPOSE_PROJECT_NAME
export PORT=18000              # in F3 use this as NETBOX_HTTP_PORT
```

The old installation may keep running during the rehearsal (leave out F1). When you are satisfied, remove it:

```bash
cd "$NEW" && docker compose down -v && cd / && rm -rf "$NEW"      # -v deletes ONLY the rehearsal's volumes
```

Then do the real run with `NEW=/opt/netbox-plugins`, `PROJ=netbox-plugins` and the port the old installation used.

---

## F. Cut over

The real run starts here; the rehearsal runs the same steps with the settings from E.

### F1. Stop the old installation (not in the rehearsal)

```bash
cd "$OLD" && docker compose down        # NO -v: the old volumes are your way back
```

### F2. Unpack the new installation and load the images

```bash
sudo mkdir -p "$NEW" && sudo chown "$USER" "$NEW"
tar xzf /opt/nb-bundle/netbox-docker-repo.tar.gz -C "$NEW" --strip-components=1
gunzip -c /opt/nb-bundle/images.tar.gz | docker load
docker images | grep -E "netbox|postgis|valkey"
```

### F3. Settings of the new installation

```bash
cd "$NEW"
cp offline.env.example .env
# set the name and port: for the real run keep netbox-plugins and use the port the old installation had
sed -i "s/^COMPOSE_PROJECT_NAME=.*/COMPOSE_PROJECT_NAME=${PROJ:-netbox-plugins}/; s/^NETBOX_HTTP_PORT=.*/NETBOX_HTTP_PORT=${PORT:-8000}/" .env
cat .env
docker compose config --images | sort -u        # exactly: netbox:latest-plugins-postgis, postgis, valkey
```

### F4. Carry the old secrets and settings over

The `env/*.env` files are read by the containers when they start; they are not part of the image. Two values
**must** come from the old installation, otherwise every session and API token stops working: `SECRET_KEY` and
`API_TOKEN_PEPPER_1`. Everything else in the shipped files can stay as it is, except the database password, which
you should replace with a strong one (the same value in two files).

```bash
cd "$NEW"
setkey() { grep -v "^$2=" "$1" > "$1.tmp"; printf '%s=%s\n' "$2" "$3" >> "$1.tmp"; mv "$1.tmp" "$1"; }   # set KEY=VALUE in a file

for k in SECRET_KEY API_TOKEN_PEPPER_1; do
  v=$(grep "^$k=" "$OLD/env/netbox.env" | cut -d= -f2-)
  [ -n "$v" ] || echo "!! $k is not in $OLD/env/netbox.env: find it where the old installation keeps it (a secrets file, configuration.py)"
  setkey env/netbox.env "$k" "$v"
done

PW=$(openssl rand -base64 24 | tr -d '/+=')           # a new database password for the NEW database
setkey env/netbox.env DB_PASSWORD "$PW"
setkey env/postgres.env POSTGRES_PASSWORD "$PW"

# on an air-gapped host: do not look up new NetBox releases
setkey env/netbox.env RELEASE_CHECK_URL ""
chmod 600 env/*.env
```

Then look at what else the old installation had set (email, proxy, CORS, metrics, ...) and copy those lines:

```bash
diff "$OLD/env/netbox.env" env/netbox.env | grep '^<' | grep -v -E "SECRET_KEY|PASSWORD|PEPPER"
```

Lines marked `<` exist only in the old file. Leave the Redis settings and `DB_HOST`, `DB_NAME`, `DB_USER` as shipped.
The database does not need the old database's user name or password: the dump is restored without owners.

### F5. Carry custom NetBox settings over

The container reads its configuration from **`extensions/postgis-pathways/configuration/`** (not from
`configuration/`): the PostGIS overlay points the mount there. If the old installation had its own settings in
`configuration/*.py` (LDAP, `extra.py`, logging), merge them into that directory's files. Keep these lines:
`DATABASES["default"]["ENGINE"]` in `extra.py` and the `PLUGINS` list in `plugins.py`.

```bash
diff -ru "$OLD/configuration" extensions/postgis-pathways/configuration | less
```

### F6. Start only the database and restore the dump

```bash
cd "$NEW"
docker compose up -d --wait postgres

docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' \
  < "$BK/netbox-db.dump" 2>&1 | tail -20
```

The database is brand new, so `--clean --if-exists` has nothing to remove; the output should be empty or a few
harmless notices. Real errors (`ERROR:`) need to be read before you go on.

### F7. PostGIS, then compare the row counts

```bash
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At \
  -c "CREATE EXTENSION IF NOT EXISTS postgis" -c "select extname from pg_extension order by 1"'
```

The line "extension postgis already exists, skipping" is correct if the old database already used PostGIS. If it did
not, this creates it, and it **must** exist before NetBox starts (the pathways migration needs it).

```bash
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F": "' < "$BK/counts.sql" > "$BK/counts-after.txt"
diff "$BK/counts.txt" "$BK/counts-after.txt" && echo IDENTICAL
```

If a number differs, do not continue: the dump or the restore is not what you think it is.

### F8. Restore the file volumes

```bash
docker compose create netbox netbox-worker redis redis-cache        # creates the volumes, starts nothing
IMG=netbox:latest-plugins-postgis
for vol in netbox-media-files netbox-reports-files netbox-scripts-files; do
  docker run --rm --user 0 --entrypoint tar -v "${PROJ:-netbox-plugins}_${vol}:/data" -v "$BK:/backup:ro" "$IMG" \
    xzf "/backup/${vol}.tar.gz" -C /data && echo "restored $vol"
done
```

The `netbox` user in the image is uid 999; files restored from the archive keep the owner they had. If the old
installation ran with another uid, fix the ownership: `docker run --rm --user 0 --entrypoint chown -v VOLUME:/data
$IMG -R 999:0 /data` for each volume.

### F9. Start everything and watch the first start

```bash
docker compose up -d
docker compose logs -f netbox        # leave with Ctrl-C
```

On a database from an older NetBox the first start applies the missing migrations, then runs `trace_paths`,
`remove_stale_contenttypes`, `clearsessions` and `reindex --lazy` before the web server starts ("Listening at"). On
a large database that can take a long time; it is normal for `docker compose ps` to show *starting* meanwhile. The
worker starts after the web container is healthy.

```bash
docker compose ps                    # netbox and netbox-worker: healthy
```

### F10. Verify (do all of it)

```bash
docker compose exec -T netbox sh -c 'cd /opt/netbox/netbox && python manage.py showmigrations | grep -c "\[ \]"'    # 0
docker compose exec -T netbox sh -c 'cd /opt/netbox/netbox && python manage.py shell -c "from django.conf import settings; print(settings.RELEASE.full_version, settings.PLUGINS)"' | tail -1
docker compose logs netbox | grep -i -E "unable to load|traceback" | head          # nothing
```

In the browser (`http://<host>:<port>`):

- Log in with an account that existed before. Sessions from the old installation are gone; passwords are in the database.
- **Plugins → Plugins** lists all of them, trace-print included. Open each plugin's own menu once.
- **API token:** `curl -H "Authorization: Bearer <an existing token>" http://<host>:<port>/api/status/` answers 200. This
  only works because `SECRET_KEY` and `API_TOKEN_PEPPER_1` were carried over (F4).
- Open an object that has an uploaded image or attachment: the file loads (the media volume came across).
- **Trace Print:** pick a cable or an interface that has a cable and print it; the PDF opens.
- Compare a couple of objects and the totals with what the old installation showed.
- Maps (netbox-pathways, floorplan) draw their background from a public tile server on the internet. On an air-gapped
  network the map background stays empty; the data is intact.

### F11. Rehearsal only: stop here

Time the steps, write down anything that needed attention, remove the rehearsal (the command is at the end of E)
and do the real run.

---

## G. After the cut-over

### G1. Roll back (as long as nobody has made changes in the new installation)

```bash
cd "$NEW" && docker compose down              # no -v
cd "$OLD" && docker compose up -d
```

The old installation starts with exactly the data it had when you stopped it; its volumes were never touched.
Changes made in the new installation after the cut-over are **not** in the old one, and its database cannot take a
dump from the newer NetBox, so decide on a rollback early. If the old volumes are damaged, restore `$BK` into a
fresh PostgreSQL of the old major version (or use `postgres-volume.tar.gz` from step D).

### G2. Clean up (after an acceptance period you choose, for example two weeks)

```bash
cd "$OLD" && docker compose down -v           # deletes the OLD volumes: the point of no return
docker image prune                            # old images that nothing uses
```

Keep `$BK` for as long as your retention rules say. It holds the only copy of the old installation's data once the
old volumes are gone.

### G3. Updating the new installation later

Rebuild on the online host (A3, A4), export a new bundle (A5), carry it over (B), then on the target:

```bash
cd /opt/netbox-plugins
# take a backup first: repeat D, with  cd /opt/netbox-plugins  and  OLDPROJ=netbox-plugins
gunzip -c /opt/nb-bundle/images.tar.gz | docker load
docker compose up -d                          # recreates the containers from the new image; the database volume stays
```

Same PostgreSQL major version, so the database volume stays in place from now on; keep taking the D-style dumps
before every update.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `exec format error` when a container starts | The image was built for another CPU architecture than the target's. Build on a host with the same `uname -m`. |
| `pull access denied` / `manifest unknown` on the target | Compose tried to pull. The image tag is not loaded (`docker images`), or you are not using the offline chain. Check `docker compose config --images` and that `.env` has `COMPOSE_FILE=...` as in `offline.env.example`. |
| `database files are incompatible with server` | The new Postgres found an old data directory: the new stack uses an old project name and its volume. Use a new `COMPOSE_PROJECT_NAME` (F3). Do not delete the old volume. |
| Migration error `type "geometry" does not exist` | PostGIS was not created before NetBox started (F7). Create it, then `docker compose restart netbox`. |
| `Unable to load plugin ...` in the log, or a plugin's pages are missing | The plugin is not in the image, or the configuration shadowing happened: the container reads `extensions/postgis-pathways/configuration/plugins.py` (F5). A development override with source mounts was used by mistake; remove `docker-compose.override.yml` and make sure `.env` sets `COMPOSE_FILE`. |
| `bind source path does not exist` or the plugin fails to import with an empty directory | `docker-compose.override.yml` is being used. See the row above. |
| Everyone is logged out and API tokens do not work | `SECRET_KEY` or `API_TOKEN_PEPPER_1` differ from the old installation (F4). Put the old values back, `docker compose up -d`. |
| First start takes very long | Migrations, `trace_paths` and `reindex` on a big database. Follow `docker compose logs -f netbox`. |
| Permission denied writing uploads or reports | Ownership of the restored volumes (F8, last paragraph). |
| `port is already allocated` | The old installation or the rehearsal still publishes that port. Stop it, or set another `NETBOX_HTTP_PORT` in `.env`. |
