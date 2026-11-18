# Build with all plugins on an online host, replace an existing netbox-docker on an offline host, keep the data

This guide builds this repository (NetBox 4.7 + the plugins in `plugin_requirements.txt` + the example plugin +
**netbox-tracepath-plugin** + PostGIS/netbox-pathways) on an internet-connected Linux host, carries the result into an
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

**What is built.** One image, `netbox:latest-plugins-postgis`, with NetBox 4.7.4 (netbox-docker release 5.1.1; the
base image is pinned by digest in `Dockerfile-Plugins`, so every build starts from the same image) and
these plugins baked in: netbox-secrets, netbox-bgp, netbox-fms, netbox-inventory, netbox-otp-plugin,
netbox-floorplan-plugin, netbox-wdm, netbox-pathways, netbox-plugin-dns, netbox-notices, netbox-cable-labels,
netbox-topology-views, netbox-documents, the example plugin and **netbox-tracepath-plugin**. Two more
images are pulled as they are: `postgis/postgis:18-3.6-alpine` (the database) and `valkey/valkey:9.1-alpine`
(Redis). About 2.3 GB before compression (2.29 GB for the three images, measured for v1.3.0 with
`docker image inspect` on the arm64 development machine).

**Where the data lives.** The new installation keeps its whole state in **`data/` in its own folder**, as bind
mounts (`data/postgres`, `data/netbox/media`, `reports`, `scripts`, `data/redis`, `data/redis-cache`), not in named
Docker volumes: it is backed up, moved and removed as one folder. `scripts/init-data.sh` creates those folders with
the right owners before the first start. The **old** installation may still keep its state in named volumes (an
older netbox-docker); this guide reads it either way.

**Rules this guide follows. Keep them if you change anything.**

1. **Back up first, and prove the backup is readable** (a dump you have never listed is not a backup).
2. **Never point the new Postgres at the old Postgres data** (its volume or its `data/postgres`). The new database is
   PostgreSQL 18; a data directory from another major version will not start. The data travels as a logical dump
   (`pg_dump` → `pg_restore`), which works across major versions.
3. **The new installation gets its own folder and its own Compose project name.** Its data goes to its own `data/`,
   and the old installation's volumes and files stay untouched. That is also your rollback.
4. **Nothing is built or pulled on the target.** There is no internet there; everything arrives in the bundle.
5. **Carry over `SECRET_KEY` and `API_TOKEN_PEPPER_1`** from the old installation. Other values would invalidate
   sessions and API tokens.
6. **Both hosts have the same CPU architecture** (check `uname -m` on both; this guide assumes `x86_64`). An image
   built on arm64 does not run on x86_64.
7. **The plugins are inside the image.** The development file `docker-compose.override.yml` (which mounts source
   trees into the containers) must not be used for this. A missing mount directory would be created empty and hide
   the plugin, and it would not start.

**Variables in this guide.** The commands use these instead of fixed paths and names. Each section sets the ones it
introduces and saves them to a file (`~/netbox-build-vars.sh` on the build host, `~/netbox-replace-vars.sh` on the
target), and every section that may start in a new shell loads that file again first. No secret goes into either
file.

| Variable | Holds | Example | Set in |
|---|---|---|---|
| `BUILD_DIR` | the folder on the build host that holds both checkouts | `$HOME/nbbuild` | A2 |
| `TRACEPATH_TAG` | the netbox-tracepath-plugin version that is built in | `v0.8.0` | A2 |
| `TEST_PROJECT` | the Compose project name of the build test | `nbtest` | A4 |
| `TEST_PORT` | the port the build test publishes | `18000` | A4 |
| `BUNDLE_DIR` | the bundle's folder on this host: where A5 writes it, where B puts it on the target | `$HOME/nbbuild/bundle`, `/opt/nb-bundle` | A5, B |
| `OLD_INSTALL_DIR` | the old installation's folder (its `docker-compose.yml`) | `/opt/netbox-docker` | C |
| `NEW_INSTALL_DIR` | the folder of the installation that this pass through F makes: the rehearsal's (E) or the real one | `/opt/netbox-plugins` | C, E |
| `NEW_PROJECT` | that installation's Compose project name | `netbox-plugins` | C, E |
| `NEW_PORT` | the port that installation publishes | `8000` | C, E |
| `BACKUP_DIR` | the folder for this backup (another disk is better) | `/opt/netbox-backups/2026-11-18` | C |
| `OLD_PROJECT` | the old installation's Compose project name, read from its containers | `netbox-docker` | C |
| `OLD_IMAGE` | the old installation's NetBox image, read from its container | `netboxcommunity/netbox:v4.6.10-4.0.2` | D4 |
| `NEW_DB_PASSWORD` | the new database's password; a secret, written straight into the env files, never saved, unset right after | (generated) | F4 |
| `TOKEN` | an existing API token, for the check in F10; a secret, typed with `read -rs`, never saved, unset after | | F10 |
| `UPDATE_DIR` | a later version's files, unpacked beside the installation | (made by `mktemp`) | G3 |

**What was tested** (on the development machine, with this repository's own data, last for v1.3.0 on 2026-11-02):
the offline overlay builds; the backup commands of D; F2 to F10 on a restored copy of a database from this
repository's v1.0.0 (NetBox 4.7.3, nine plugins), with every row count identical, the file volumes restored from
their archives, the old API token working, the plugin migrations applied on first start (`OPERATIONS.md` §6.7) and
the plugins, including netbox-tracepath-plugin 0.8.0 from inside the image, printing PDFs with no source tree
mounted; and a first start on an empty database (A4). The step from NetBox 4.6 was rehearsed the same way for
v1.0.0 (`OPERATIONS.md` §6.6). With the state in `data/` (2026-11-18, on a Linux server with Docker 29 and
Compose 5.7, the sample data loaded): `scripts/init-data.sh`, D on an installation that keeps its files in `data/`
and D4 on one that keeps them in named volumes, and E/F into a new folder, with identical row counts, the files
restored and no migration left. **Not tested:** your database with your plugins and versions. Step E exists for that:
it does the upgrade on a copy so a problem shows up before anything is replaced.

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
cat > ~/netbox-build-vars.sh <<'EOF'
BUILD_DIR=$HOME/nbbuild                  # the folder that holds both checkouts
TRACEPATH_TAG=v0.8.0                     # the netbox-tracepath-plugin version that is built in
EOF
. ~/netbox-build-vars.sh
mkdir -p "$BUILD_DIR" && cd "$BUILD_DIR"
git clone https://github.com/Uttiponken/netbox-docker.git
git clone --branch "$TRACEPATH_TAG" https://github.com/Uttiponken/netbox-tracepath-plugin.git
ls netbox-docker/docker-compose.offline.yml netbox-docker/offline.env.example   # both must exist
```

**Without git, from zip files:** download both from GitHub (*Code → Download ZIP*; for the plugin take the tag from
*Releases*), unzip them next to each other and rename the folders, because a zip unpacks as `netbox-docker-main`
and `netbox-tracepath-plugin-<version without the v>`:

```bash
. ~/netbox-build-vars.sh
mkdir -p "$BUILD_DIR" && cd "$BUILD_DIR"
unzip "$HOME/Downloads/netbox-docker-main.zip" && mv netbox-docker-main netbox-docker
unzip "$HOME/Downloads/netbox-tracepath-plugin-${TRACEPATH_TAG#v}.zip" \
  && mv "netbox-tracepath-plugin-${TRACEPATH_TAG#v}" netbox-tracepath-plugin
```

(Adjust `$HOME/Downloads` if the zip files are elsewhere.) A zip has no git history, so the two `git` commands below
that record the version do not work; write the versions into `MANIFEST.txt` by hand instead (A5).

The two directories must be siblings: the build copies the plugin from `../netbox-tracepath-plugin`. Both
repositories are public, so no login is needed. Record what you are building:

```bash
git -C "$BUILD_DIR/netbox-docker" rev-parse HEAD
git -C "$BUILD_DIR/netbox-tracepath-plugin" describe --tags
```

### A3. Configure and build

```bash
. ~/netbox-build-vars.sh
cd "$BUILD_DIR/netbox-docker"
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

Use a throwaway project so nothing real is touched: the function below gives each `docker compose` command the test's
project name and port, without changing `.env` or the shell. Its data goes to `data/` in the build folder, which is
removed at the end. A brand-new NetBox database needs PostGIS **before** NetBox starts, otherwise the pathways
migration fails.

```bash
. ~/netbox-build-vars.sh
cat >> ~/netbox-build-vars.sh <<'EOF'
TEST_PROJECT=nbtest                      # the Compose project name of the build test
TEST_PORT=18000                          # the port the build test publishes
EOF
. ~/netbox-build-vars.sh
cd "$BUILD_DIR/netbox-docker"
test_compose() { COMPOSE_PROJECT_NAME="$TEST_PROJECT" NETBOX_HTTP_PORT="$TEST_PORT" docker compose "$@"; }

scripts/init-data.sh                           # data/ with the right owners
test_compose up -d --wait postgres
test_compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE EXTENSION IF NOT EXISTS postgis"'   # the PostGIS image usually has done it already: "already exists, skipping" is fine
test_compose up -d                             # first start: migrations, takes several minutes
```

On a new database the first start takes a few minutes (about 3 on the development machine, about 15 on a small
Linux server). `test_compose up -d` may end with `dependency failed to start: container …-netbox-1 is unhealthy`:
the web container's health check gives up before the migrations are done, so the worker is not started. That is
harmless. Wait until the web container is healthy, then start the rest:

```bash
test_compose logs -f netbox                    # wait for "Listening at", Ctrl-C to leave
test_compose ps netbox                         # healthy
test_compose up -d                             # now the worker starts as well
test_compose ps                                # everything healthy

test_compose exec -T netbox sh -c 'cd /opt/netbox/netbox && python manage.py shell -c "from django.conf import settings; print(settings.PLUGINS)"'
test_compose exec -T netbox sh -c 'cd /opt/netbox/netbox && python manage.py showmigrations | grep -c "\[ \]"'   # 0
test_compose exec -T netbox sh -c 'uv pip list 2>/dev/null | grep -i netbox'                                # the pinned versions
echo "optionally open http://localhost:$TEST_PORT and look at Plugins → Plugins"

# throw the test away: its containers and network, then its data (through a container: the files belong to 70 and 999)
test_compose down
docker run --rm --user 0 --network none --entrypoint rm -v "$BUILD_DIR/netbox-docker:/w:z" netbox:latest-plugins-postgis \
  -rf /w/data
unset -f test_compose
```

### A5. Export the bundle

```bash
. ~/netbox-build-vars.sh
echo 'BUNDLE_DIR=$BUILD_DIR/bundle         # the bundle'"'"'s folder on this host' >> ~/netbox-build-vars.sh
. ~/netbox-build-vars.sh
mkdir -p "$BUNDLE_DIR" && cd "$BUNDLE_DIR"

docker save netbox:latest-plugins-postgis postgis/postgis:18-3.6-alpine docker.io/valkey/valkey:9.1-alpine \
  | gzip > images.tar.gz

# the repository as it is (no .git, no caches, no data); .env is NOT included, you create it on the target
tar czf netbox-docker-repo.tar.gz -C "$BUILD_DIR" \
  --exclude='netbox-docker/.git' --exclude='netbox-docker/.env' --exclude='netbox-docker/data' \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='build-stage*.log' netbox-docker

# what is in it, for your records
{
  echo "built: $(date -u +%FT%TZ) on $(uname -m)"
  echo "netbox-docker: $(git -C "$BUILD_DIR/netbox-docker" rev-parse HEAD)"
  echo "netbox-tracepath-plugin: $(git -C "$BUILD_DIR/netbox-tracepath-plugin" describe --tags)"
  docker image inspect --format '{{index .RepoTags 0}} {{.Id}}' netbox:latest-plugins-postgis postgis/postgis:18-3.6-alpine docker.io/valkey/valkey:9.1-alpine
  docker run --rm --entrypoint /usr/local/bin/uv netbox:latest-plugins-postgis pip list 2>/dev/null | grep -i -E "^netbox|^django "
} > MANIFEST.txt

cp "$BUILD_DIR/netbox-docker/docs/OFFLINE-REPLACE-INSTALL.md" .      # this guide travels with the bundle
sha256sum images.tar.gz netbox-docker-repo.tar.gz MANIFEST.txt OFFLINE-REPLACE-INSTALL.md > SHA256SUMS
sha256sum SHA256SUMS                   # write this one line down: compare it on the target (B)
ls -lh
```

The Docker Engine and Compose packages are **not** in the bundle: the target already runs Docker. If its Compose
is the old `docker-compose` v1, install the Compose v2 plugin first (`OPERATIONS.md` §7.3 shows how to carry the
`.deb` packages).

## B. Carry it across

Move the five files in the bundle folder across your air gap using your site's approved process. On the target,
put them in a working directory and check them. The first command starts the target's variables file:

```bash
cat > ~/netbox-replace-vars.sh <<'EOF'
BUNDLE_DIR=/opt/nb-bundle                # the bundle's folder on the target
EOF
. ~/netbox-replace-vars.sh
cd "$BUNDLE_DIR" && sha256sum SHA256SUMS && sha256sum -c SHA256SUMS
```

The first line must match the one you wrote down in A5 (that proves the list itself was not changed); then every
file must say OK.

---

## C. On the target: look at the old installation (changes nothing)

Set these once and adjust them. `OLD_INSTALL_DIR` is the folder of the **old** installation (where its
`docker-compose.yml` lives). Run the old installation's own `docker compose` command in it; the examples assume
plain `docker compose`.

```bash
cat >> ~/netbox-replace-vars.sh <<EOF
OLD_INSTALL_DIR=/opt/netbox-docker                # the old installation
NEW_INSTALL_DIR=/opt/netbox-plugins               # the new one (does not exist yet)
NEW_PROJECT=netbox-plugins                        # the new one's Compose project name
NEW_PORT=8000                                     # the port it publishes (the old installation's, for the real run)
BACKUP_DIR=/opt/netbox-backups/$(date +%F)        # where this backup goes: another disk is better
EOF
. ~/netbox-replace-vars.sh
cd "$OLD_INSTALL_DIR"
docker compose ps                             # it should be running and healthy
```

Write down the facts that decide how careful to be:

```bash
# Compose project name, and the real names of its volumes (an older installation) or its data/ folder (a newer one)
OLD_PROJECT=$(docker inspect "$(docker compose ps -q postgres)" --format '{{index .Config.Labels "com.docker.compose.project"}}')   # its project name
echo "OLD_PROJECT=$OLD_PROJECT                # the old installation's Compose project name" >> ~/netbox-replace-vars.sh
echo "$OLD_PROJECT"; docker volume ls | grep "$OLD_PROJECT"; ls -d "$OLD_INSTALL_DIR/data" 2>/dev/null

# NetBox version, PostgreSQL version, database size, extensions
docker compose exec -T netbox sh -c 'cd /opt/netbox/netbox && python manage.py shell -c "from django.conf import settings; print(settings.RELEASE.full_version)"' | tail -1
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "select version()" -c "select pg_size_pretty(pg_database_size(current_database()))" -c "select extname from pg_extension order by 1"'

# Which apps (core and plugins) have data in the database
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "select string_agg(distinct app, '"'"', '"'"' order by app) from django_migrations"'

# Free space for the backup, and the size of the file volumes
df -h "$(dirname "$BACKUP_DIR")"; docker system df -v | grep "$OLD_PROJECT"
```

How to read it:

| What you found | What it means |
|---|---|
| PostgreSQL major **is not 18** | Normal. That is why the data moves as a dump, never as a volume or folder. |
| NetBox is **4.7.x** | The simple case. The new image starts on the restored data. |
| NetBox is **4.6.x** | One minor step. The new container runs the 4.7 migrations on first start: read `OPERATIONS.md` §6.6 and rehearse in step E. |
| The old installation runs **netbox-fms 0.5 or older** (`docker compose exec -T netbox sh -c 'uv pip list 2>/dev/null' \| grep -i fms`) | Its migration 0039 (in 0.6.0 and later) deletes all fiber circuit path assignments; the circuits have to be assigned to the derived paths again (`OPERATIONS.md` §6.6 item 4). Export them before the cut-over if you need the list. |
| The old installation runs **older versions of the other plugins** | Their migrations run on first start. The ones that change data: netbox-wdm 0.3.0 renames the C-band grid keys (`dwdm_100ghz` → `dwdm_c_100ghz`), netbox-pathways 0.3.0 moved a structure's map point from `location` to `geometry`. Scripts that write the old names have to follow. |
| The app `netbox_secrets` is in `django_migrations` | The new image carries netbox-secrets 3.2.0. Coming from 3.1.x, the first start runs its migrations 0012 (secret roles from MPTT to `ltree`, cannot be undone) and 0013; the stored secrets and user keys stay. Old session keys are rejected: after the cut-over each user deletes theirs and creates it again with the private key (`OPERATIONS.md` §1). Keep the backup and the user keys' private keys. |
| NetBox is an **older 4.x** | The new container runs all newer migrations on first start (`migrate`, `trace_paths`, `reindex`), which is why you rehearse in step E. Read the NetBox release notes for every version in between. |
| NetBox is **3.x** | Stop and ask for an upgrade path first: NetBox 4.0 had requirements on the version you upgrade from. |
| The app `netbox_trace_print` is in `django_migrations` | The old installation already ran this plugin under its earlier name (≤ 0.6.2). Rename its tables once, **before** F9: README of netbox-tracepath-plugin, "Upgrading from netbox-trace-print". |
| An app in `django_migrations` that is **not** among the plugins in section 0 | Its data stays in the database but the new NetBox has no code for it. If you still need that plugin, add it to `plugin_requirements.txt` and rebuild (A3) before going on. |
| The old installation has its own settings (LDAP, SSO, SMTP, proxy) | Steps F4 and F5 carry them over. Note them now: read `$OLD_INSTALL_DIR/env/*.env` and `$OLD_INSTALL_DIR/configuration/*.py`. |

## D. On the target: BACK UP the old installation first

Do this before you load, import or start anything of the new build. It needs a short downtime: the web and worker
containers are stopped so nothing can change between the database dump and the file archives.

```bash
. ~/netbox-replace-vars.sh
mkdir -p "$BACKUP_DIR" && chmod 700 "$BACKUP_DIR"
cd "$OLD_INSTALL_DIR"

# D1. Stop writers. The database and Redis keep running.
docker compose stop netbox netbox-worker
```

```bash
# D2. The database: one consistent dump in PostgreSQL's custom format
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$BACKUP_DIR/netbox-db.dump"

# prove that it is readable and not empty
ls -lh "$BACKUP_DIR/netbox-db.dump"
docker compose exec -T postgres sh -c 'pg_restore --list' < "$BACKUP_DIR/netbox-db.dump" | head -8
docker compose exec -T postgres sh -c 'pg_restore --list' < "$BACKUP_DIR/netbox-db.dump" | grep -c "TABLE DATA"
```

```bash
# D3. Row counts now, to compare after the restore
cat > "$BACKUP_DIR/counts.sql" <<'EOF'
SELECT 'sites', count(*) FROM dcim_site UNION ALL SELECT 'devices', count(*) FROM dcim_device
UNION ALL SELECT 'interfaces', count(*) FROM dcim_interface UNION ALL SELECT 'cables', count(*) FROM dcim_cable
UNION ALL SELECT 'circuits', count(*) FROM circuits_circuit UNION ALL SELECT 'ip addresses', count(*) FROM ipam_ipaddress
UNION ALL SELECT 'users', count(*) FROM users_user UNION ALL SELECT 'api tokens', count(*) FROM users_token
UNION ALL SELECT 'tenants', count(*) FROM tenancy_tenant ORDER BY 1;
EOF
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F": "' < "$BACKUP_DIR/counts.sql" | tee "$BACKUP_DIR/counts.txt"
```

The files (uploaded images and attachments, reports, scripts) are archived in a container from the old NetBox image,
without network; an older installation keeps them in named volumes, a newer one in `data/netbox`. The archives are
handed to you (`chown`) with mode 600:

```bash
# D4. The files
OLD_IMAGE=$(docker inspect "$(docker compose ps -a -q netbox)" --format '{{.Config.Image}}')      # -a: the container is stopped now
echo "OLD_IMAGE=$OLD_IMAGE                # the old installation's NetBox image" >> ~/netbox-replace-vars.sh
for pair in media:netbox-media-files reports:netbox-reports-files scripts:netbox-scripts-files; do
  if [ -d "$OLD_INSTALL_DIR/data/netbox" ]; then src="$OLD_INSTALL_DIR/data/netbox/${pair%%:*}"   # data/ (a newer installation)
  else src="${OLD_PROJECT:?}_${pair#*:}"; fi                                                       # a named volume (an older one)
  docker run --rm --user 0 --network none --entrypoint sh -v "$src:/data:ro" -v "$BACKUP_DIR:/backup" "$OLD_IMAGE" \
    -c "tar czf /backup/netbox-${pair%%:*}.tar.gz -C /data . && chown $(id -u):$(id -g) /backup/netbox-${pair%%:*}.tar.gz" \
    && echo "archived $src"
done
ls -lh "$BACKUP_DIR"

# D5. The configuration, including the secrets in env/ (so keep this archive private); not data/
tar czf "$BACKUP_DIR/config.tar.gz" --exclude='./.git' --exclude='./data' -C "$OLD_INSTALL_DIR" .
chmod 600 "$BACKUP_DIR"/*
```

```bash
# D6. Checksums, then a copy OFF this host (another disk or machine) and a read test of the copy
( cd "$BACKUP_DIR" && sha256sum * > SHA256SUMS && cat SHA256SUMS )
# cp -a "$BACKUP_DIR" /mnt/other-disk/ && ( cd "/mnt/other-disk/$(basename "$BACKUP_DIR")" && sha256sum -c SHA256SUMS )
```

**Optional but cheap while the stack is down: a byte-level copy of the old database's files.** It lets you bring
the old installation back exactly as it was, even without the dump:

```bash
docker compose stop postgres
if [ -d "$OLD_INSTALL_DIR/data/postgres" ]; then src="$OLD_INSTALL_DIR/data/postgres"; else src="${OLD_PROJECT:?}_netbox-postgres"; fi
docker run --rm --user 0 --network none --entrypoint sh -v "$src:/data:ro" -v "$BACKUP_DIR:/backup" "$OLD_IMAGE" \
  -c "tar czf /backup/postgres-files.tar.gz -C /data . && chown $(id -u):$(id -g) /backup/postgres-files.tar.gz"
chmod 600 "$BACKUP_DIR/postgres-files.tar.gz"
docker compose start postgres
```

**Bring the old installation back up if you are not cutting over right now:** `docker compose start netbox netbox-worker`.
Any change made after this point is not in the backup.

---

## E. Rehearse on the target (strongly recommended, no impact on the old installation)

Do steps F1 to F11 once as a **rehearsal**: it proves that the dump restores, that your NetBox version upgrades
(its migrations run on first start), how long it takes (that is your downtime for the real run), and that the
plugins work on your data. For the rehearsal, the installation that F makes gets its own folder, project name and
port, which keep it apart from everything else. Appended to the variables file, they replace the values from C:

```bash
cat >> ~/netbox-replace-vars.sh <<'EOF'
NEW_INSTALL_DIR=/opt/netbox-rehearsal             # the rehearsal's folder
NEW_PROJECT=nbrehearsal                           # its Compose project name
NEW_PORT=18000                                    # its port
EOF
. ~/netbox-replace-vars.sh
```

The old installation may keep running during the rehearsal (leave out F1). When you are satisfied, remove the
rehearsal: its containers and network, then its folder (`data/` through a container, because its files belong to
the containers' users):

```bash
. ~/netbox-replace-vars.sh
cd "$NEW_INSTALL_DIR" && docker compose down
docker run --rm --user 0 --network none --entrypoint rm -v "$NEW_INSTALL_DIR:/w:z" netbox:latest-plugins-postgis -rf /w/data
cd / && rm -rf "${NEW_INSTALL_DIR:?}"
```

Then set the values for the real run and do it:

```bash
cat >> ~/netbox-replace-vars.sh <<'EOF'
NEW_INSTALL_DIR=/opt/netbox-plugins               # the real new installation
NEW_PROJECT=netbox-plugins                        # its Compose project name
NEW_PORT=8000                                     # the port the old installation used
EOF
. ~/netbox-replace-vars.sh
```

---

## F. Cut over

The real run starts here; the rehearsal runs the same steps with the settings from E.

### F1. Stop the old installation (not in the rehearsal)

```bash
. ~/netbox-replace-vars.sh
cd "$OLD_INSTALL_DIR" && docker compose down        # NO -v: the old volumes are your way back
```

### F2. Unpack the new installation and load the images

```bash
. ~/netbox-replace-vars.sh
sudo mkdir -p "$NEW_INSTALL_DIR" && sudo chown "$USER" "$NEW_INSTALL_DIR" && chmod 700 "$NEW_INSTALL_DIR"
tar xzf "$BUNDLE_DIR/netbox-docker-repo.tar.gz" -C "$NEW_INSTALL_DIR" --strip-components=1
gunzip -c "$BUNDLE_DIR/images.tar.gz" | docker load
docker images | grep -E "netbox|postgis|valkey"
```

### F3. Settings of the new installation, and its data folders

```bash
. ~/netbox-replace-vars.sh
cd "$NEW_INSTALL_DIR"
cp offline.env.example .env
sed -i "s/^COMPOSE_PROJECT_NAME=.*/COMPOSE_PROJECT_NAME=${NEW_PROJECT:?}/; s/^NETBOX_HTTP_PORT=.*/NETBOX_HTTP_PORT=${NEW_PORT:?}/" .env
cat .env
docker compose config --images | sort -u        # exactly: netbox:latest-plugins-postgis, postgis, valkey
scripts/init-data.sh                             # data/ with the owners the images run as (it lists them)
```

### F4. Carry the old secrets and settings over

The `env/*.env` files are read by the containers when they start; they are not part of the image. Two values
**must** come from the old installation, otherwise every session and API token stops working: `SECRET_KEY` and
`API_TOKEN_PEPPER_1`. Everything else in the shipped files can stay as it is, except the database password, which
you should replace with a strong one (the same value in two files).

```bash
. ~/netbox-replace-vars.sh
cd "$NEW_INSTALL_DIR"
setkey() { grep -v "^$2=" "$1" > "$1.tmp"; printf '%s=%s\n' "$2" "$3" >> "$1.tmp"; mv "$1.tmp" "$1"; }   # set KEY=VALUE in a file

for k in SECRET_KEY API_TOKEN_PEPPER_1; do
  v=$(grep "^$k=" "$OLD_INSTALL_DIR/env/netbox.env" | cut -d= -f2-)
  [ -n "$v" ] || echo "!! $k is not in $OLD_INSTALL_DIR/env/netbox.env: find it where the old installation keeps it (a secrets file, configuration.py)"
  setkey env/netbox.env "$k" "$v"
done
unset v

NEW_DB_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=')     # the new database's password: never saved elsewhere
setkey env/netbox.env DB_PASSWORD "$NEW_DB_PASSWORD"
setkey env/postgres.env POSTGRES_PASSWORD "$NEW_DB_PASSWORD"
unset NEW_DB_PASSWORD

# on an air-gapped host: do not look up new NetBox releases
setkey env/netbox.env RELEASE_CHECK_URL ""
chmod 600 env/*.env
```

Then look at what else the old installation had set (email, proxy, CORS, metrics, ...) and copy those lines:

```bash
diff "$OLD_INSTALL_DIR/env/netbox.env" env/netbox.env | grep '^<' | grep -v -E "SECRET_KEY|PASSWORD|PEPPER"
```

Lines marked `<` exist only in the old file. Leave the Redis settings and `DB_HOST`, `DB_NAME`, `DB_USER` as shipped.
The database does not need the old database's user name or password: the dump is restored without owners.

### F5. Carry custom NetBox settings over

The container reads its configuration from **`extensions/postgis-pathways/configuration/`** (not from
`configuration/`): the PostGIS overlay points the mount there. If the old installation had its own settings in
`configuration/*.py` (LDAP, `extra.py`, logging), merge them into that directory's files. Keep these lines:
`DATABASES["default"]["ENGINE"]` in `extra.py` and the `PLUGINS` list in `plugins.py`.

```bash
diff -ru "$OLD_INSTALL_DIR/configuration" "$NEW_INSTALL_DIR/extensions/postgis-pathways/configuration" | less
```

### F6. Start only the database and restore the dump

```bash
. ~/netbox-replace-vars.sh
cd "$NEW_INSTALL_DIR"
docker compose up -d --wait postgres

docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' \
  < "$BACKUP_DIR/netbox-db.dump" 2>&1 | tail -20
```

The database is brand new, so `--clean --if-exists` has nothing to remove; the output should be empty or a few
harmless notices. Real errors (`ERROR:`) need to be read before you go on.

### F7. PostGIS, then compare the row counts

```bash
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At \
  -c "CREATE EXTENSION IF NOT EXISTS postgis" -c "select extname from pg_extension order by 1"'
```

The line "extension postgis already exists, skipping" is correct if the old database already used PostGIS. If it did
not, this creates it, and it **must** exist before NetBox starts (the pathways migration needs it); the last line of
the output lists `postgis`.

```bash
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F": "' < "$BACKUP_DIR/counts.sql" > "$BACKUP_DIR/counts-after.txt"
diff "$BACKUP_DIR/counts.txt" "$BACKUP_DIR/counts-after.txt" && echo IDENTICAL
```

If a number differs, do not continue: the dump or the restore is not what you think it is.

### F8. Restore the files

Each archive from D4 is unpacked into its folder in `data/netbox`, and the files are given to the owner of that
folder (the user the image runs as, set by `scripts/init-data.sh` in F3), whatever uid the old installation used:

```bash
. ~/netbox-replace-vars.sh
cd "$NEW_INSTALL_DIR"
for d in media reports scripts; do
  docker run --rm --user 0 --network none --entrypoint sh \
    -v "$NEW_INSTALL_DIR/data/netbox/$d:/data:z" -v "$BACKUP_DIR:/backup:ro" netbox:latest-plugins-postgis \
    -c "tar xzf /backup/netbox-$d.tar.gz -C /data && chown -R \"\$(stat -c %u:%g /data)\" /data" && echo "restored $d"
done
```

### F9. Start everything and watch the first start

```bash
docker compose up -d
docker compose logs -f netbox        # leave with Ctrl-C
```

On a database from an older NetBox the first start applies the missing migrations, then runs `trace_paths`,
`remove_stale_contenttypes`, `clearsessions` and `reindex --lazy` before the web server starts ("Listening at"). On
a large database that can take a long time; it is normal for `docker compose ps` to show *starting* meanwhile.

If the migrations take longer than the health check allows, `docker compose up -d` ends with `dependency failed to
start: container …-netbox-1 is unhealthy` and the worker is not started. Nothing is wrong: keep following the log
until "Listening at", wait for `docker compose ps netbox` to say *healthy*, then run `docker compose up -d` once more
to start the worker.

```bash
docker compose up -d                 # only needed if the first call stopped at "unhealthy"
docker compose ps                    # netbox and netbox-worker: healthy
```

### F10. Verify (do all of it)

```bash
. ~/netbox-replace-vars.sh
cd "$NEW_INSTALL_DIR"
docker compose exec -T netbox sh -c 'cd /opt/netbox/netbox && python manage.py showmigrations | grep -c "\[ \]"'    # 0
docker compose exec -T netbox sh -c 'cd /opt/netbox/netbox && python manage.py shell -c "from django.conf import settings; print(settings.RELEASE.full_version, settings.PLUGINS)"' | tail -1
docker compose logs netbox | grep -i -E "unable to load|traceback" | head          # nothing
docker volume ls | grep "${NEW_PROJECT:?}_"                                       # nothing: the state is in data/
```

In the browser (`http://<host>:<port>`, the port is `NEW_PORT`):

- Log in with an account that existed before. Sessions from the old installation are gone; passwords are in the database.
- **Plugins → Plugins** lists all of them, tracepath included. Open each plugin's own menu once.
- **API token:** with an existing token, the status page answers 200. The token is typed without being shown and goes
  to curl on its standard input, so it is in neither the shell history nor the process list:

  ```bash
  read -rsp 'An existing API token: ' TOKEN; echo
  printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" | curl -s -o /dev/null -w '%{http_code}\n' -K - \
    "http://localhost:$NEW_PORT/api/status/"                                       # 200
  unset TOKEN
  ```
  This only works because `SECRET_KEY` and `API_TOKEN_PEPPER_1` were carried over (F4).
- Open an object that has an uploaded image, attachment or document: the file loads (the media came across).
- **Tracepath:** pick a cable or an interface that has a cable and print it; the PDF opens.
- Compare a couple of objects and the totals with what the old installation showed.
- **FMS and WDM diagrams:** open a fiber circuit path (netbox-fms) and a WDM circuit's trace tab (netbox-wdm). Both
  draw without internet, because the image serves D3 itself.
- **What still needs the internet:** only the background of the netbox-pathways map, which comes from public tile
  servers (`tile.openstreetmap.org`, `server.arcgisonline.com`). On an air-gapped network it stays empty; the
  pathways, structures and cables on it still draw. Its `map_tiles` and `map_base_layers` settings can point at a
  tile server on your own network. Every other plugin page works offline.

### F11. Rehearsal only: stop here

Time the steps, write down anything that needed attention, remove the rehearsal (the commands are in E) and do the
real run.

---

## G. After the cut-over

### G1. Roll back (as long as nobody has made changes in the new installation)

```bash
. ~/netbox-replace-vars.sh
cd "$NEW_INSTALL_DIR" && docker compose down
cd "$OLD_INSTALL_DIR" && docker compose up -d
```

The old installation starts with exactly the data it had when you stopped it; its volumes (or its `data/`) were
never touched. Changes made in the new installation after the cut-over are **not** in the old one, and its database
cannot take a dump from the newer NetBox, so decide on a rollback early. If the old data is damaged, restore
`BACKUP_DIR` into a fresh PostgreSQL of the old major version (or use `postgres-files.tar.gz` from step D).

### G2. Clean up (after an acceptance period you choose, for example two weeks)

```bash
. ~/netbox-replace-vars.sh
cd "$OLD_INSTALL_DIR" && docker compose down -v      # deletes the OLD volumes: the point of no return
docker image prune                                   # old images that nothing uses
```

If the old installation kept its state in `data/` instead, `down -v` leaves that folder: remove it through a
container, as for the rehearsal in E. Keep `BACKUP_DIR` for as long as your retention rules say. It holds the only
copy of the old installation's data once its volumes or folder are gone.

### G3. Updating the new installation later

Rebuild on the online host (A3, A4), export a new bundle (A5), carry it over (B), then on the target take a backup
first: repeat D with the installation you are updating as the "old" one. Appended to the variables file:

```bash
. ~/netbox-replace-vars.sh
cat >> ~/netbox-replace-vars.sh <<EOF
OLD_INSTALL_DIR=$NEW_INSTALL_DIR                  # the installation being updated is the one to back up
OLD_PROJECT=$NEW_PROJECT                          # its Compose project name
BACKUP_DIR=/opt/netbox-backups/$(date +%F)        # this backup's folder
EOF
. ~/netbox-replace-vars.sh
```

Then unpack the new version beside the installation and copy in what belongs to the release. What is the
installation's own stays: `.env`, `env/*.env` (the secrets), `data/`, and your changes to the two `configuration/`
folders, which you merge by hand as in F5 (a new release may add plugins to `plugins.py`):

```bash
. ~/netbox-replace-vars.sh
UPDATE_DIR=$(mktemp -d)                                         # the new version's files
tar xzf "$BUNDLE_DIR/netbox-docker-repo.tar.gz" -C "$UPDATE_DIR" --strip-components=1
diff -ru "$NEW_INSTALL_DIR/extensions/postgis-pathways/configuration" "$UPDATE_DIR/extensions/postgis-pathways/configuration" | less
tar cf - -C "$UPDATE_DIR" --exclude=./env --exclude=./configuration --exclude=./extensions/postgis-pathways/configuration . \
  | tar xf - -C "$NEW_INSTALL_DIR"                              # the release's files, not env/ and configuration/
# now merge the configuration changes you saw in the diff into $NEW_INSTALL_DIR/extensions/postgis-pathways/configuration
rm -rf "${UPDATE_DIR:?}"
gunzip -c "$BUNDLE_DIR/images.tar.gz" | docker load
cd "$NEW_INSTALL_DIR" && docker compose up -d     # recreates the containers from the new image; data/ stays
```

Same PostgreSQL major version, so `data/postgres` stays in place from now on; keep taking the D-style dumps before
every update. **An installation from before the move to `data/`** (its state is still in named volumes): move it
with `OPERATIONS.md` §6.9 at this point, between unpacking and `up -d`.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `exec format error` when a container starts | The image was built for another CPU architecture than the target's. Build on a host with the same `uname -m`. |
| `pull access denied` / `manifest unknown` on the target | Compose tried to pull. The image tag is not loaded (`docker images`), or you are not using the offline chain. Check `docker compose config --images` and that `.env` has `COMPOSE_FILE=...` as in `offline.env.example`. |
| `database files are incompatible with server` | The new Postgres found an old data directory in `data/postgres`: files from another installation or another PostgreSQL major. Start the new installation with an empty `data/postgres` (F3) and restore the dump (F6). Do not touch the old installation's data. |
| The new `postgres` container exits (code 3) during F6, its log showing `duplicate key value violates unique constraint "pg_extension_name_index"` | The restore started while the image was still setting up the new database. `docker-compose.offline.yml` prevents that by checking Postgres over TCP, so `--wait` waits for the setup; an older copy of the file checks the socket. Remove `data/postgres` (through a container, as in E), run `scripts/init-data.sh`, and start F6 again. |
| `could not change permissions of directory` or `data directory "…" has wrong ownership` from Postgres | `data/postgres` is not owned by uid 70. Run `scripts/init-data.sh` again. |
| Migration error `type "geometry" does not exist` | PostGIS was not created before NetBox started (F7). Create it, then `docker compose restart netbox`. |
| `Unable to load plugin ...` in the log, or a plugin's pages are missing | The plugin is not in the image, or the configuration shadowing happened: the container reads `extensions/postgis-pathways/configuration/plugins.py` (F5). A development override with source mounts was used by mistake; remove `docker-compose.override.yml` and make sure `.env` sets `COMPOSE_FILE`. |
| `bind source path does not exist` or the plugin fails to import with an empty directory | `docker-compose.override.yml` is being used. See the row above. |
| Everyone is logged out and API tokens do not work | `SECRET_KEY` or `API_TOKEN_PEPPER_1` differ from the old installation (F4). Put the old values back, `docker compose up -d`. |
| First start takes very long | Migrations, `trace_paths` and `reindex` on a big database. Follow `docker compose logs -f netbox`. |
| `dependency failed to start: container …-netbox-1 is unhealthy`, and no worker | The first start outlasted the health check. Wait until `docker compose ps netbox` says healthy, then `docker compose up -d` again. |
| Permission denied writing uploads or reports | The folders in `data/netbox` are not owned by 999: `scripts/init-data.sh` (the folders), and F8's `chown -R` (the files). |
| `rm: cannot remove '…/data/…': Permission denied` | The files in `data/` belong to the containers' users (70, 999). Remove them through a container, as in E. |
| `port is already allocated` | The old installation or the rehearsal still publishes that port. Stop it, or set another `NETBOX_HTTP_PORT` in `.env`. |
