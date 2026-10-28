# NetBox Docker Deployment — Operations Runbook

Status: living document. Update the version tables whenever a plugin or NetBox
version changes. What comes next, and which plugins wait for a release, is in
`ROADMAP.md`.

Last verified: 2026-09-26, on netbox-docker `docker compose` (Docker Engine
24.0.2 / Compose v2.19.0). Target execution/staging OS for this runbook:
**Debian 13 "trixie"** (instructions are identical on Debian 12 "bookworm" —
substitute the codename in the apt source line). The Docker prerequisites for
**Ubuntu 24.04** and **Fedora** are in §2.2 and §2.3.

> **Two ways this runbook can read.** It started as the notes of the development setup, where a
> `docker-compose.override.yml` (git-ignored, not in the repository) mounts source folders into the containers.
> For building and installing from the repository, use §3 and `OFFLINE-REPLACE-INSTALL.md`: they use
> `docker-compose.offline.yml` and a `.env` made from `offline.env.example` instead. Where a later section still
> names `docker-compose.override.yml` or counts eight plugins, read it as that development setup (the deployment
> now has thirteen: `netbox_tracepath_plugin`, `netbox_pathways`, `netbox_dns`, `notices`, `netbox_cable_labels`
> and `netbox_topology_views` were added, `netbox_secrets` was dropped for NetBox 4.7, see §1).

---

## 1. What this deployment is

A [netbox-docker](https://github.com/netbox-community/netbox-docker) based
NetBox install, based on **netbox-docker release `5.1.1`** (NetBox
**v4.7.x**; this repository's tag `v1.0.0` is the first on 4.7, before it the
deployment ran NetBox 4.6 on release 5.0.2), with a custom `Dockerfile-Plugins`
image built on NetBox **4.7.4** (`netboxcommunity/netbox:v4.7.4-5.1.1`, pinned by
digest so every build starts from the same image, see §6.3), carrying:

| Plugin (pip package)         | App label             | Pinned version | Why this version |
|-------------------------------|------------------------|----------------|-------------------|
| netbox-bgp                     | `netbox_bgp`           | 0.20.2         | Latest. Hard-pins to NetBox 4.7.x only (0.19.0 was the 4.6 release). |
| netbox-fms                     | `netbox_fms`           | 0.6.0          | Latest. Alpha software; `min_version=4.5`, no max. 0.6.0 derives fiber paths by analysis, see §6.6. |
| netbox-inventory                | `netbox_inventory`     | 2.7.1          | Latest. Hard-pins to NetBox 4.7 (2.6.1 was the 4.6 release). |
| netbox-otp-plugin               | `netbox_otp_plugin`    | 1.3.6          | Latest. Supports NetBox 4.0–4.99. |
| netbox-floorplan-plugin          | `netbox_floorplan`    | 0.10.0         | Latest. Hard-pins to NetBox 4.7.x only (0.9.2 was the 4.6 release). |
| netbox-wdm                      | `netbox_wdm`           | 0.2.2          | Latest. Alpha software; `min_version=4.5`, no max. Companion to netbox-fms. |
| (your own plugin)               | `netbox_example_plugin`| 0.1.0          | Scaffold in `custom-plugins/netbox-example-plugin/`. |
| (your own plugin)               | `netbox_tracepath_plugin`| 0.8.0        | PDF cable traces, from its own repository, see §3.1. |
| netbox-pathways (PostGIS overlay) | `netbox_pathways`     | 0.3.0          | Latest. Declares no NetBox range; tested on 4.7.3. See §10. |
| netbox-plugin-dns               | `netbox_dns`           | 1.7.3          | Latest. The 1.7.x line is `min_version=4.7.0` (1.6.x is for 4.5/4.6). Not the abandoned PyPI package `netbox-dns`. |
| netbox-notices                  | `notices`              | 1.3.0          | Latest. `min_version=4.5`, no max. Maintenance/outage calendar and iCal feed; FullCalendar is bundled. |
| netbox-cable-labels             | `netbox_cable_labels`  | 0.1.0          | Only release. 4.2–4.99.99. Labels unlabelled cables `#<pk>`; that write bypasses the change log. |
| netbox-topology-views           | `netbox_topology_views`| 5.0.0          | Latest. `min_version=4.7.0`. Fixes XSS issues in 4.7.0; saving positions needs add/change on the coordinate models. |

**netbox-secrets is not installed.** Its released 3.1.1 declares
`max_version = "4.6.99"`, so NetBox 4.7 refuses to load it, and no release for
4.7 exists yet (the work is in an unmerged pull request). It was dropped from
`plugin_requirements.txt` and both `plugins.py` files. Nothing else depends on
it. If your database holds secrets, they stay in the `netbox_secrets_*` tables
untouched; they are not visible or editable until the plugin is added back
(pin the new release, add `netbox_secrets` to both `plugins.py` files, rebuild),
and the private key of the user key is needed to read them again. Keep the
database backup (§5) and the private key file.

**netbox-documents is wanted but not installed yet.** Its 0.8.5 declares no
`max_version`, so NetBox 4.7 loads it, but the Documents list page fails with
`AttributeError: 'str' object has no attribute 'permissions_required'` (4.7
removed the dict form of view `actions`) and the documents panel never renders
on objects with the default configuration. The fix is an unmerged pull request
(#112 upstream). Add it back the same way as netbox-secrets once a release works
on 4.7.

**netbox-routing cannot run next to netbox-bgp.** Both define the GraphQL types
`CommunityType`, `CommunityListType` and `PrefixListType`; with both in
`PLUGINS`, NetBox exits at startup with `DuplicatedTypeName: Type CommunityType
is defined multiple times in the schema`. The image builds without complaint, so
only the start check in §3.3 catches this. Tested on 4.7.3 with netbox-routing
0.5.1: alone it works. The plan is to replace netbox-bgp with netbox-routing
once netbox-routing has a stable release, and to rebuild the sample dataset for
it at the same time; the `netbox_bgp_*` tables then stay in the database
untouched.

**The load-bearing fact of this whole deployment:** several of these plugins
declare an *exact* NetBox major.minor they support (not a range), and the
newest release of a plugin does not necessarily target the newest NetBox.
NetBox silently skips a plugin whose range does not match the running version,
which is how netbox-secrets dropped out here. **Any future upgrade must
re-derive this table from scratch — see §6.**

Files that make this reproducible (all in this repository):

```
netbox-docker/
├── Dockerfile-Plugins                 # builds netbox:latest-plugins
├── plugin_requirements.txt            # pinned third-party plugin versions
├── docker-compose.override.yml        # build target, port, SSO env stub (gitignored upstream — keep your own copy in version control)
├── configuration/
│   ├── configuration.py               # from netbox-docker 5.1.1, unmodified
│   └── plugins.py                     # PLUGINS + PLUGINS_CONFIG
└── custom-plugins/
    └── netbox-example-plugin/         # your own plugin, editable-installed
```

Everything else in the directory is the unmodified `netbox-community/netbox-docker`
repository at tag `5.1.1` (commit `7689fec7a70717f7e72feecb383e7a3f55538b5f`), merged into this repository.

---

## 2. Prerequisites

Everything in this runbook needs **Docker Engine**, the **Docker Compose v2 plugin** (`docker compose`, version
**2.17 or newer**: the offline overlay uses `additional_contexts`; tested with v2.19) and the **buildx** plugin,
plus **git**. Install them from Docker's own package repository for your OS, not from the distribution's
`docker.io` / `docker` packages, which are older and bring a different Compose. Choose the subsection for your
system; everything after §2 is the same on all of them.

| System | Section |
|---|---|
| Debian 13 (and 12) | §2.1 |
| Ubuntu 24.04 LTS | §2.2 |
| Fedora 43 / 44 | §2.3 |

### 2.1 Docker Engine + Compose plugin: Debian 13 (official Docker apt repo)

```bash
# Remove any distro-packaged docker first, if present
sudo apt-get remove -y docker.io docker-doc docker-compose podman-docker containerd runc 2>/dev/null || true

sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Allow your user to run docker without sudo (log out/in after this)
sudo usermod -aG docker "$USER"
```

Verify:

```bash
docker --version              # tested against 24.0.2 or newer
docker compose version        # tested against v2.19.0 or newer
```

### 2.2 Docker Engine + Compose plugin: Ubuntu 24.04 (official Docker apt repo)

The commands follow Docker's installation guide for Ubuntu (docs.docker.com/engine/install/ubuntu/); they were not
run on this repository's development machine, so check the version output at the end.

```bash
# Remove unofficial packages first, if present
sudo apt remove $(dpkg --get-selections docker.io docker-compose docker-compose-v2 docker-doc docker-buildx podman-docker containerd runc | cut -f1) 2>/dev/null || true

# Docker's signing key and apt repository
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Allow your user to run docker without sudo (log out and in after this)
sudo usermod -aG docker "$USER"
```

The service starts and is enabled by the package. Verify:

```bash
sudo systemctl status docker --no-pager | head -3
docker --version              # 24.0.2 or newer
docker compose version        # v2.19.0 or newer (v2.17 is the minimum)
docker run --rm hello-world   # after logging out and in again; otherwise use sudo
```

**A specific version instead of the latest** (to match another host exactly):

```bash
apt list --all-versions docker-ce 2>/dev/null | head
VERSION_STRING="<a version from the list, for example 5:29.8.2-1~ubuntu.24.04~noble>"
sudo apt install -y docker-ce=$VERSION_STRING docker-ce-cli=$VERSION_STRING containerd.io docker-buildx-plugin docker-compose-plugin
sudo apt-mark hold docker-ce docker-ce-cli          # keep `apt upgrade` from moving it
```

**Air-gapped host:** download the packages on the online host exactly as in §7.3 (the same four packages and
`apt-get install --download-only`), then install them with `sudo dpkg -i *.deb`.

### 2.3 Docker Engine + Compose plugin: Fedora (official Docker rpm repo)

The commands follow Docker's installation guide for Fedora (docs.docker.com/engine/install/fedora/), which supports
the two newest Fedora releases (43 and 44 at the time of writing); they were not run on this repository's
development machine, so check the version output at the end.

```bash
# Remove unofficial packages first, if present
sudo dnf remove -y docker docker-client docker-client-latest docker-common docker-latest \
                   docker-latest-logrotate docker-logrotate docker-selinux docker-engine-selinux docker-engine 2>/dev/null || true

# Docker's repository (Fedora 41 and newer use dnf5, where config-manager is built in)
sudo dnf config-manager addrepo --from-repofile https://download.docker.com/linux/fedora/docker-ce.repo

sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
# The first install asks you to accept Docker's GPG key: compare the fingerprint it shows with the one on
# docs.docker.com/engine/install/fedora/ before you accept.

# Unlike the Debian/Ubuntu packages, the install does NOT start the service
sudo systemctl enable --now docker

# Allow your user to run docker without sudo (log out and in after this)
sudo usermod -aG docker "$USER"
```

Verify:

```bash
sudo systemctl status docker --no-pager | head -3
docker --version              # 24.0.2 or newer
docker compose version        # v2.19.0 or newer (v2.17 is the minimum)
docker run --rm hello-world   # after logging out and in again; otherwise use sudo
```

SELinux can stay **enforcing**: the compose files label every bind mount with `:z`. Published ports (NetBox on 8000)
are opened by Docker itself; if clients on other hosts cannot reach it, check the firewalld zone and any network
firewall in front of the host.

**A specific version instead of the latest:**

```bash
dnf list docker-ce --showduplicates | sort -r | head
sudo dnf install -y docker-ce-<VERSION_STRING> docker-ce-cli-<VERSION_STRING> containerd.io docker-buildx-plugin docker-compose-plugin
```

Keep `dnf upgrade` from moving it with the `versionlock` plugin (`sudo dnf versionlock add docker-ce docker-ce-cli`).

**Air-gapped host:** on the online host download the packages with their dependencies, carry the files across,
and install them there:

```bash
mkdir docker-rpms && cd docker-rpms
dnf download --resolve --alldeps docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
# on the air-gapped host, in the carried directory:
sudo dnf install -y ./*.rpm
```

### 2.4 git

```bash
sudo apt-get install -y git      # Debian, Ubuntu
sudo dnf install -y git          # Fedora
```

### 2.5 Disk space

Budget **~3 GB** for the built image set (see §7.2 for exact sizes) plus
room for the Postgres data volume, which grows with your inventory — a few
hundred MB is typical for a NetBox instance of a few thousand objects, but
size for your actual scale.

---

## 3. Build & reproduce from scratch

This builds the deployment as it is in this repository today. Run it on any internet-connected Linux host
(Debian, Ubuntu or Fedora) with Docker installed (§2). To carry the result to an air-gapped host and replace an
existing installation, continue with `OFFLINE-REPLACE-INSTALL.md`: it uses exactly this build.

**The repository already contains everything that makes this deployment specific**: `Dockerfile-Plugins`,
`plugin_requirements.txt`, `configuration/plugins.py`, `custom-plugins/`, the PostGIS/pathways extension in
`extensions/`, the offline overlay `docker-compose.offline.yml` and the settings template `offline.env.example`.
**Nothing has to be copied in.** (Older versions of this runbook told you to restore a `docker-compose.override.yml`
from your own archive. That file is the development setup, it mounts source folders into the containers, it is
not part of the repository and it is not used here: `docker-compose.offline.yml` replaces it.)

### 3.1 Get the two source trees, side by side

The image is built from this repository **and** from the plugin repository, which must sit next to it under the
exact name `netbox-tracepath-plugin` (the build reads `../netbox-tracepath-plugin`).

```bash
mkdir -p /opt/nbbuild && cd /opt/nbbuild        # or wherever you keep this
git clone https://github.com/Uttiponken/netbox-docker.git
git clone --branch v0.8.0 https://github.com/Uttiponken/netbox-tracepath-plugin.git
```

**Without git, from zip files** (GitHub: *Code → Download ZIP*; for the plugin pick the tag `v0.8.0` under
*Releases* or *Tags*, not the branch): unzip both next to each other and **rename the folders**, because a zip unpacks
as `netbox-docker-main` and `netbox-tracepath-plugin-0.8.0`:

```bash
mkdir -p /opt/nbbuild && cd /opt/nbbuild
unzip /path/to/netbox-docker-main.zip && mv netbox-docker-main netbox-docker
unzip /path/to/netbox-tracepath-plugin-0.8.0.zip && mv netbox-tracepath-plugin-0.8.0 netbox-tracepath-plugin
ls netbox-docker/Dockerfile-Plugins netbox-docker/docker-compose.offline.yml netbox-tracepath-plugin/pyproject.toml
```

### 3.2 Settings and build

```bash
cd /opt/nbbuild/netbox-docker
cp offline.env.example .env      # project name, port and the compose files to use (read the comments in it)

# Stage 1: the base plugin image. COMPOSE_FILE here overrides the one in .env for this command only.
COMPOSE_FILE=docker-compose.yml:docker-compose.offline.yml docker compose build --no-cache netbox 2>&1 | tee build-stage1.log
# Stage 2: the PostGIS image on top of it, with the full chain from .env
docker compose build --no-cache netbox 2>&1 | tee build-stage2.log
```

**Verification: do this every time, it is the whole point.**

```bash
grep -i "unable to load plugin" build-stage1.log build-stage2.log
```

This must print **nothing**. If it prints a line like `Unable to load plugin netbox_x: Plugin netbox_x requires
NetBox maximum version Y (current: Z)`, that plugin silently failed to load: NetBox does not error out, it just
drops it. Do not proceed until this is silent.

A silent grep does not prove that NetBox starts. Two plugins that each load fine can still break NetBox together
(netbox-bgp and netbox-routing define GraphQL types with the same names, see §1); that only shows when the image is
started, so the start check in §3.3 is part of the verification, not optional.

### 3.3 Start it

A new database needs PostGIS before NetBox starts. The PostGIS image normally has created it already, so this
command usually only says "already exists, skipping". Keep it anyway.

```bash
docker compose up -d --wait postgres
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE EXTENSION IF NOT EXISTS postgis"'
docker compose up -d
```

The first start applies all migrations and takes a few minutes. `docker compose up -d` may end with
`dependency failed to start: container …-netbox-1 is unhealthy`: the health check gave up before the migrations were
done and the worker was not started. That is harmless. Follow `docker compose logs -f netbox` until "Listening at",
wait until `docker compose ps netbox` says healthy, then run `docker compose up -d` again. Both `netbox` and
`netbox-worker` should then show `(healthy)`:

```bash
docker compose ps
```

If `netbox` instead exits, or keeps restarting with "Waiting on DB...", look for a Python error in the log; it is
usually a plugin, not the database:

```bash
docker compose logs netbox | grep -iE "Error|Exception" | sort | uniq -c
```

`DuplicatedTypeName: Type X is defined multiple times in the schema` means two plugins define a GraphQL type with
the same name (§1). Take one of them out of `PLUGINS` in the `plugins.py` that is mounted (the PostGIS one when the
PostGIS overlay is in the chain) and restart.

Confirm that every expected plugin registered (on top of the build-time grep above):

```bash
docker compose exec -T netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py shell -c "
from django.conf import settings
print(settings.PLUGINS)
"
```

Expected output:

```
['netbox_bgp', 'netbox_fms', 'netbox_example_plugin', 'netbox_inventory', 'netbox_otp_plugin', 'netbox_floorplan', 'netbox_wdm', 'netbox_tracepath_plugin', 'netbox_pathways', 'netbox_dns', 'notices', 'netbox_cable_labels', 'netbox_topology_views']
```

Create your admin user (interactive: run it yourself, not scripted, so the password never touches a log or
transcript):

```bash
docker compose exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py createsuperuser
```

Log in at `http://<host>:8000/` (the port in `.env`) and confirm that **Plugins → Plugins** lists all thirteen as Active,
matching the table in §1.

The example plugin's model migrations are committed under `custom-plugins/netbox-example-plugin/.../migrations/`,
so the following is only needed if you change that model:

```bash
docker compose exec -T -e DEVELOPER=true netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py makemigrations netbox_example_plugin
docker compose exec -T netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py migrate
```

---

## 4. Adding another plugin (or changing a pinned version)

This is the procedure that was breaking before. Follow it exactly, one
plugin at a time:

1. **Find the exact PyPI package name and Django app label.** They often
   differ (e.g. pip package `netbox-floorplan-plugin` → app label
   `netbox_floorplan`). Get this from the plugin's own README, not a
   third-party blog post.

2. **Check every candidate version's declared NetBox compatibility before
   installing anything.** Don't trust "latest" — check what it actually
   declares. This needs the pip package name and the Django app label from
   step 1 (they often differ):

   ```bash
   docker run --rm netbox:latest-plugins python3 -c "
   import urllib.request, json, tarfile, io

   pkg = 'REPLACE_ME'         # pip package name, e.g. 'netbox-bgp'
   app_label = 'REPLACE_ME'   # Django app label, e.g. 'netbox_bgp'

   data = json.load(urllib.request.urlopen(f'https://pypi.org/pypi/{pkg}/json'))
   for v in sorted(data['releases'].keys(), key=lambda s: [int(x) for x in s.split('.') if x.isdigit()]):
       rel = data['releases'][v]
       sdist = next((f for f in rel if f['packagetype']=='sdist'), None)
       if not sdist:
           continue
       raw = urllib.request.urlopen(sdist['url']).read()
       tf = tarfile.open(fileobj=io.BytesIO(raw))
       m = next((m for m in tf.getmembers() if m.name.endswith(f'{app_label}/__init__.py')), None)
       if not m:
           print(v, 'app __init__.py not found — check app_label'); continue
       content = tf.extractfile(m).read().decode(errors='ignore')
       lines = [l.strip() for l in content.splitlines() if 'min_version' in l or 'max_version' in l]
       print(v, lines if lines else '(no min/max_version declared)')
   "
   ```

   (This is the same technique used to catch the netbox-bgp/netbox-secrets/
   netbox-floorplan version traps in §1 — it reads the plugin's own
   `PluginConfig.min_version`/`max_version` straight from the package, which
   is authoritative; READMEs go stale. Verified working against netbox-bgp
   as of this writing — see output history in this runbook's revision log
   or re-run it yourself.)

3. **Pick the version whose range includes your current NetBox version.**
   If nothing does, you cannot add this plugin without also changing your
   NetBox version — and if you change your NetBox version, **every other
   already-installed plugin needs to be re-checked** (go to §6).

4. Add one line to `plugin_requirements.txt`, with a comment recording the
   min/max you found and why.

5. Add the app label to `PLUGINS` in `configuration/plugins.py`, plus any
   `PLUGINS_CONFIG` entry the plugin's README says is required. **Read the
   README's config section fully** — e.g. `netbox-otp-plugin` defaults
   `otp_required=True`, which locks out every user with no TOTP device
   registered; that has to be explicitly overridden to `False` until you're
   ready to enforce it.

6. Rebuild and check for silent load failures, same as §3:

   ```bash
   docker compose build --no-cache netbox 2>&1 | grep -i "unable to load plugin"
   ```

7. Recreate and wait for health:

   ```bash
   docker compose up -d --wait
   docker compose ps
   ```

   A plugin can pass step 6 and still stop NetBox from starting, for example
   with a GraphQL type name another plugin already uses (§1, §3.3). If
   `netbox` does not become healthy, read its log before anything else.

8. Apply migrations (usually automatic on container start, but confirm):

   ```bash
   docker compose exec -T netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py migrate <app_label>
   ```

9. Confirm in **Plugins → Plugins** in the UI that it shows Active with the
   version you expect, and exercise its main page once.

10. Commit `plugin_requirements.txt`, `configuration/plugins.py`, and this
    runbook's table in §1 in the same commit.

Only move to the next plugin after this one is verified. Adding several at
once is exactly how "differs in subtle ways" failures become unattributable.

---

## 5. Backups

Back up **before every upgrade**, and on whatever schedule your data
criticality demands otherwise (daily is reasonable for an actively-used
CMDB).

### 5.1 What needs backing up

| Item | Where it lives | Backup method |
|---|---|---|
| PostgreSQL database (all NetBox data) | `postgres` container, volume `netbox-docker_netbox-postgres` | `pg_dump` (below) |
| Media files (uploaded images/attachments) | volume `netbox-docker_netbox-media-files` | tar the volume |
| Reports & scripts | volumes `netbox-docker_netbox-reports-files`, `netbox-docker_netbox-scripts-files` | tar the volumes |
| `SECRET_KEY` and `API_TOKEN_PEPPERS` | wherever you inject them (env, secrets file, or `configuration/configuration.py` override) | keep in your secrets store — **losing `SECRET_KEY` invalidates all sessions and encrypted secret-plugin data is NOT recoverable without it if netbox-secrets uses it for key derivation; treat it as a credential, not a config value** |
| This repository (Dockerfile-Plugins, plugin_requirements.txt, configuration/, custom-plugins/, docker-compose.override.yml) | git | commit everything **except `env/*.env`** — see §8, these contain plaintext credentials; keep `docker-compose.override.yml` in your own private repo since upstream gitignores it |

Redis (`redis`, `redis-cache`) is not backed up — it holds only the task
queue and cache, both safely rebuildable. A restart loses in-flight
background jobs, which is acceptable.

### 5.2 Database backup

```bash
mkdir -p /opt/netbox-backups
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc \
  > "/opt/netbox-backups/netbox-db-$(date +%Y%m%d-%H%M%S).dump"
```

(`-Fc` = custom format, compressed, restorable with `pg_restore` and safe
across minor Postgres versions within the same major version.) Read
`$POSTGRES_USER`/`$POSTGRES_DB` from `env/postgres.env` if you haven't
exported them into your shell.

### 5.3 Volume backups

```bash
for vol in netbox-media-files netbox-reports-files netbox-scripts-files; do
  docker run --rm \
    -v "netbox-docker_${vol}:/data:ro" \
    -v /opt/netbox-backups:/backup \
    alpine tar czf "/backup/${vol}-$(date +%Y%m%d-%H%M%S).tar.gz" -C /data .
done
```

### 5.4 Configuration backup

If everything in §1's file tree is already committed to your own git repo,
`git log` is your configuration backup history. Otherwise:

```bash
tar czf "/opt/netbox-backups/netbox-config-$(date +%Y%m%d-%H%M%S).tar.gz" \
  Dockerfile-Plugins plugin_requirements.txt docker-compose.override.yml \
  configuration/ custom-plugins/ env/
```

This archive contains the `env/*.env` credential files (§8) — store it with
the same access controls as the database backup, not in general-purpose git.

### 5.5 Restore procedure

```bash
docker compose down
docker volume rm netbox-docker_netbox-postgres   # only if restoring to a clean DB
docker compose up -d postgres
docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists \
  < /opt/netbox-backups/netbox-db-YYYYMMDD-HHMMSS.dump
docker compose up -d --wait
```

For volumes, reverse the tar step: extract the archive's contents back into
a fresh volume mounted at `/data` before starting the stack.

---

## 6. Upgrade procedure

**Never** bump the NetBox base image tag without redoing the whole
compatibility check in §1 for every installed plugin. This is not optional
— it is the single thing that was breaking this deployment before.

### 6.1 Pre-upgrade checks (do this before touching anything)

1. Decide the target NetBox version.
2. For **every** plugin currently installed (§1's table), run the version
   probe from §4 step 2 against the target NetBox version. Record, for each
   plugin, the newest version whose `min_version`–`max_version` range
   includes the target.
3. If any plugin has **no** version compatible with the target, you must
   either: stay on the current NetBox version, drop that plugin, or wait for
   an upstream release. Do not proceed with a partial upgrade "to see what
   breaks" — that produces exactly the unattributable failures this
   deployment was built to avoid.
4. Check the target netbox-docker release's `docker-compose.yml` and
   `Dockerfile` for changes to the health check, entrypoint scripts
   (`docker/*.sh`), or `requirements-container.txt` — mixing an old compose
   file with a new base image (or vice versa) causes exactly the
   `/opt/netbox/health.sh: not found` class of failure hit during initial
   setup. **Check out the entire target tag, don't cherry-pick files.**
5. Read the NetBox release notes for the target version for breaking
   changes (settings renames, deprecated flags — e.g. `LOGIN_REQUIRED` is
   deprecated as of 4.7 and slated for removal in 5.0).

### 6.2 Take a backup

Full backup per §5, before any command below.

### 6.3 Perform the upgrade (staging first)

Do this on a copy of the environment — restore the §5 backup into a
separate staging stack (different `COMPOSE_PROJECT_NAME` / directory, or a
second host) rather than upgrading production directly.

```bash
cd netbox-docker
git fetch --tags
git checkout <new-netbox-docker-tag>            # whole tag, per §6.1 step 4
# re-apply configuration/plugins.py, Dockerfile-Plugins content as needed —
# Dockerfile-Plugins' FROM line must point at the new tag's default image tag
```

`Dockerfile-Plugins` pins the base image by digest, because the netbox-docker tags move: `v4.7-5.1.1` follows every
NetBox 4.7.x patch, and even a patch tag such as `v4.7.4-5.1.1` is republished when upstream rebuilds it. Use the
exact patch tag (`v<netbox>-<netbox-docker>`) and look up its digest on the build host:

```bash
docker buildx imagetools inspect docker.io/netboxcommunity/netbox:v4.7.4-5.1.1 | grep -m1 '^Digest:'
# FROM docker.io/netboxcommunity/netbox:v4.7.4-5.1.1@sha256:<that digest>
```

With a digest, Docker fetches exactly that image when it is not on the host yet; no `--pull` is needed.

Update `plugin_requirements.txt` with the versions selected in §6.1 step 2.
Update `configuration/plugins.py` if any plugin's config keys changed
(check its CHANGELOG).

```bash
docker compose build --no-cache netbox 2>&1 | grep -i "unable to load plugin"   # must be silent
docker compose up -d --wait
docker compose exec -T netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py migrate
```

Watch the migration output. NetBox/Django migrations are one-directional —
there is no automatic downgrade. This is why the backup and the staging
copy are not optional.

Verify:
- All plugins listed active in **Plugins → Plugins**, versions match plan.
- Spot-check each plugin's main page loads without a 500.
- Run any test suite / smoke checks you have for custom plugins.
- Check `docker compose logs netbox` for new deprecation warnings.

### 6.4 Promote to production

Only after staging verification passes:

```bash
# on the production host
docker compose down
# (backup already taken in 6.2; take a fresh one if time has passed)
git checkout <new-netbox-docker-tag>
# re-apply plugin_requirements.txt / configuration changes from 6.3
docker compose build --no-cache netbox 2>&1 | grep -i "unable to load plugin"
docker compose up -d --wait
docker compose exec -T netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py migrate
```

### 6.5 Rollback plan

If verification fails after promotion:

```bash
docker compose down
git checkout <previous-netbox-docker-tag>
# revert plugin_requirements.txt / configuration.py / plugins.py to previous commit
docker compose up -d --wait   # runs against the OLD image; DB schema may now be ahead
```

If migrations already ran against the new schema, the old NetBox code may
not tolerate the new schema. In that case, restore the pre-upgrade database
backup from §5.2 as well:

```bash
docker compose down
docker compose up -d postgres
docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists \
  < /opt/netbox-backups/netbox-db-<pre-upgrade-timestamp>.dump
docker compose up -d --wait
```

This is precisely why the staging rehearsal in §6.3 exists — to find this
failure mode before it happens against the real database.

### 6.6 Upgrade log: NetBox 4.6.10 to 4.7.3 (this repository's `v1.0.0`)

Rehearsed on a restored copy of the development database before it was committed. What changed, in the order it
matters when you upgrade a database that still runs the 4.6 stack (the installation this repository's earlier
commits describe):

1. **Back up first** (§5.2). The migrations cannot be undone.
2. **netbox-secrets stays behind.** The new image does not load it (§1). The stored secrets remain in the database
   and can be read again once a release supports 4.7.
3. **52 migrations apply on first start** (NetBox 4.7, netbox-bgp, -inventory, -floorplan, -fms, -pathways). The
   inventory asset `contact` field becomes contact assignments, and netbox-bgp makes `remote_address` nullable.
4. **netbox-fms 0.6.0 deletes all fiber circuit path assignments** (its migration 0039) and derives fiber paths by
   analysis instead (`FiberStrandPath`, wait about 30 s for the worker job after the first start). Assign the
   circuits to the derived paths again with `POST /api/plugins/fms/fiber-circuits/<id>/assign/` and the body
   `{"strand_paths": [<ids>]}`, or run `reconcile_fiber_paths`. Loss and wavelength sit on the assignment now.
   Unlanded spare strands appear as informational `dangling_reference` path anomalies.
5. **netbox-pathways 0.3.0**: a structure's map point is the field `geometry` (`location` is now a link to a NetBox
   Location), and an innerduct's `color` is a hex code. The Pathways list page (`/plugins/pathways/pathways/`)
   returns a server error on NetBox 4.7; every other page works.
6. **API tokens keep working** (same `API_TOKEN_PEPPER_1`). A new image reads the health check from
   `/opt/netbox/health.sh`, so use the whole 5.1.1 compose file, never a mix (§6.1 step 4).

---

## 7. Air-gapped deployment: build, transfer, install

> **Replacing an existing netbox-docker installation and keeping its data?** Use
> `OFFLINE-REPLACE-INSTALL.md`: it covers the PostGIS image set, the backup of the old installation, a rehearsal
> and the cut-over. This section describes the generic build, transfer and install.

Two Linux hosts (Debian 13, Ubuntu 24.04 or Fedora, see §2): **staging** (internet access, used to build) and
**air-gapped** (no internet access, runs production).

### 7.1 On staging: build

Follow §2 and §3 in full on the staging host. Confirm the stack runs and
verifies cleanly there before proceeding — do not transfer an unverified
build.

### 7.2 On staging: export images

```bash
mkdir -p /opt/netbox-airgap-transfer
cd /opt/netbox-airgap-transfer

# Confirm the exact image set in use
docker compose -f /opt/netbox-docker/docker-compose.yml \
               -f /opt/netbox-docker/docker-compose.override.yml config --images
# Expect: netbox:latest-plugins, docker.io/postgres:18-alpine, docker.io/valkey/valkey:9.1-alpine

docker save -o images.tar \
  netbox:latest-plugins \
  docker.io/postgres:18-alpine \
  docker.io/valkey/valkey:9.1-alpine
```

Approximate sizes at time of writing: `netbox:latest-plugins` ~830 MB,
`postgres:18-alpine` ~300 MB, `valkey:9.1-alpine` ~45 MB (single image, used
for both `redis` and `redis-cache` services) — budget ~1.2 GB for
`images.tar`, plus compression if you gzip it.

### 7.3 On staging: export the repository and Docker installer packages

```bash
cd /opt/netbox-airgap-transfer

# The full repo, including the untracked files that make this build specific
tar czf netbox-docker-repo.tar.gz -C /opt netbox-docker \
  --exclude='netbox-docker/.git'

# Docker Engine + Compose .deb packages (Debian, Ubuntu; for Fedora see §2.3) and their dependencies, for offline
# install on the air-gapped host (only needed the first time / OS reinstall —
# skip if the air-gapped host already has Docker provisioned by your normal
# OS image process)
mkdir -p docker-debs && cd docker-debs
apt-get install -y --download-only --reinstall \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
cp /var/cache/apt/archives/*.deb .
cd ..
```

Checksum everything you're about to move, so you can verify integrity after
transfer through whatever media/scanning process your site requires:

```bash
sha256sum images.tar netbox-docker-repo.tar.gz docker-debs/*.deb > SHA256SUMS
```

### 7.4 Transfer

Move `images.tar`, `netbox-docker-repo.tar.gz`, `docker-debs/`, and
`SHA256SUMS` across your air gap via your site's approved removable-media /
data-diode process. This runbook does not prescribe that process — follow
your organization's media-handling and malware-scanning procedures for
crossing the air gap.

### 7.5 On the air-gapped host: verify and install

```bash
cd /path/to/transferred/files
sha256sum -c SHA256SUMS   # must report OK for every file before proceeding
```

Install Docker offline (skip if already provisioned):

```bash
cd docker-debs
sudo dpkg -i *.deb
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

Load the images and unpack the repo:

```bash
docker load -i images.tar
docker images   # confirm netbox:latest-plugins, postgres:18-alpine, valkey:9.1-alpine present

sudo mkdir -p /opt
sudo tar xzf netbox-docker-repo.tar.gz -C /opt
cd /opt/netbox-docker
```

Because the image is already loaded under the tag `netbox:latest-plugins`
that `docker-compose.override.yml` references, **do not run
`docker compose build`** on the air-gapped host — there is no internet
access to fetch base layers or plugin packages, and none is needed since
the image is already local:

```bash
docker compose up -d --wait
docker compose ps   # confirm all healthy
```

Restore your database backup if this is replacing an existing instance
(§5.5), or create a fresh superuser if this is a new instance (§3, final
step).

Re-run the same verification as §3: check `settings.PLUGINS`, check
**Plugins → Plugins** in the UI, exercise each plugin's page.

### 7.6 Updating the air-gapped host later

There is no `docker compose pull` or `build` path available air-gapped.
Every update — a plugin version bump, a NetBox upgrade, a security patch —
must be rebuilt on staging (§6.3) and re-shipped through §7.2–§7.5 as a new
`images.tar`. Keep `SHA256SUMS` per shipment so you have an audit trail of
exactly what image was installed when.

---

## 8. Security hardening before production use

This deployment as built is fine for verification/development. Before it
holds real data, or is exposed to more than a trusted admin, fix these:

### 8.1 Rotate every default credential

`env/postgres.env`, `env/redis.env`, and `env/redis-cache.env` ship from the
upstream `netbox-docker` repository **with plaintext passwords already
committed in git history**, visible to anyone who has ever cloned it. They
are fine for a first build to prove the stack works, but must be rotated
before production:

```bash
# generate new random passwords
for f in env/postgres.env env/redis.env env/redis-cache.env; do
  echo "$f:"; grep -o '^[A-Z_]*PASSWORD' "$f"
done
```

Replace each `*_PASSWORD` value with a freshly generated secret (e.g.
`openssl rand -base64 32`), then recreate the affected containers. Changing
`POSTGRES_PASSWORD` after the database volume already exists requires
updating the password inside Postgres itself, not just the env file:

```bash
docker compose exec -T postgres psql -U "$POSTGRES_USER" -c \
  "ALTER USER $POSTGRES_USER WITH PASSWORD 'the-new-password';"
# then update env/postgres.env to match, and recreate the netbox/netbox-worker containers
```

### 8.2 Never commit `env/*.env` to git as-is

These files are not gitignored by upstream netbox-docker. Either:
- add `env/*.env` to your own `.gitignore` and distribute them out-of-band
  (your secrets manager, or manually per host), or
- template them (`env/postgres.env.example`) and inject real values via
  your deployment process instead of committing them.

The air-gapped transfer procedure in §7 moves these files as plain tar
contents — treat `netbox-docker-repo.tar.gz` and its checksum with the same
handling rules as a credentials export, not as ordinary software.

### 8.3 `SECRET_KEY` and `API_TOKEN_PEPPERS`

Generate these once, store them in your secrets management process (not
git), and inject them via the `secret_key` / `api_token_pepper_1` Docker
secrets mechanism already wired into `configuration/configuration.py`
(`_read_secret`), or via environment variables if you don't use Docker
secrets. Losing `SECRET_KEY` invalidates all active sessions; back it up
with the same rigor as the database (§5.1).

### 8.4 TLS / reverse proxy

`docker compose up` as configured here serves plain HTTP on port 8000. For
anything beyond local verification, put a reverse proxy (nginx, Caddy,
Traefik) in front with TLS termination — this is not included in this
deployment and is a separate, deliberate addition. Do not expose port 8000
directly beyond a trusted network.

### 8.5 `otp_required` and `LOGIN_REQUIRED`

`netbox_otp_plugin`'s `otp_required` is deliberately `False` (§1) — decide
your 2FA rollout plan (enroll every user via `manage.py addtotp`, then flip
to `True`) rather than leaving it off indefinitely if 2FA is a requirement
for you. Separately, `LOGIN_REQUIRED` is currently `True` by default in this
config (anonymous users get no read access), which is almost certainly what
you want for a network CMDB — just noting it's a setting that exists.

**Don't mistake the login page for the setting.** The plugin's login form
(`netbox_otp_plugin/forms.py`) always renders an "OTP Token" field — it's
present on every login screen regardless of `otp_required`, and the field
itself is `required=False` at the HTML level. The actual check only runs
if `user_has_device(user) or otp_required`; with the setting off and no
user having enrolled a device yet, that check never fires and login
succeeds with the field left blank. Verified live: created a throwaway
user with no registered device, logged in through the real form with OTP
left empty, succeeded. If you ever see a login actually *fail* without an
OTP token, that means either `otp_required` got flipped to `True`
somewhere, or that specific user already has a device enrolled — check
`from django_otp import user_has_device; user_has_device(user)` in
`manage.py shell` to tell which.

---

## 9. Recommended additional plugins for network/optical documentation

You asked specifically about documenting endpoints through network hardware
to owned/leased optics (dark fiber, wavelength services), and about
visualization. Two real candidates, with real caveats — I'm not recommending
either be added silently, since both have a nontrivial catch:

### 9.1 `netbox-pathways` — the one that actually matches "dark fiber / leased
wavelength / geographic outside-plant documentation"

[jsenecal/netbox-pathways](https://github.com/jsenecal/netbox-pathways) —
alpha, pip package `netbox-pathways`, app label `netbox_pathways`. Models
conduits, aerial spans, structures (poles, manholes, cabinets), and which
NetBox cables physically traverse which pathway, with real GIS geometry
(PostGIS), a Leaflet map, GeoJSON export for QGIS, and printable pull
sheets. It's designed for exactly the "outside plant" documentation problem
— comparable in scope to SmallWorld/ArcFM. It's built by the same author as
`netbox-fms` and `netbox-wdm` and is meant to complement them: FMS/WDM
describe what's inside a cable and which wavelengths are lit; pathways
describes where the cable physically runs.

Version 0.2.2 declared support for NetBox 4.5.3–4.6.x; 0.3.0 (the pin
now, for NetBox 4.7) declares no range and was tested on 4.7.3. It needs
PostGIS, and its structure map point moved from `location` to `geometry` in
0.3.0, which the sample data follows.

**This is now built, tested, and available as an optional extension** — see
**§10**. It is not merged into the base deployment (§1–§8): it requires a
PostGIS-enabled PostgreSQL and GDAL/GEOS/PROJ system libraries the base
stack doesn't carry, so it's packaged as a separate, deliberately opt-in
overlay you apply on top of the base files. §10 covers adoption, the actual
verification performed (creating a real geometry object end-to-end down to
the raw PostGIS row), reverting, backup/restore specifics, and — the part
that matters most for staying reproducible — what to check before an
upgrade that a plain NetBox-plus-plugins upgrade doesn't have to worry
about.

### 9.2 `netbox-topology-views` — general L1 diagram, but has a version gap right now

[netbox-community/netbox-topology-views](https://github.com/netbox-community/netbox-topology-views)
draws a topology diagram from your existing cable connections (with
draw.io/PNG export). This is the closest thing to a generic "visualize the
network" plugin, and is likely what you were searching for.

**Caveat**: its own compatibility table jumped from `v4.5.1` (NetBox 4.5.x)
to `v4.7.0` (NetBox 4.7.x only), with no release for 4.6. The stack now runs
NetBox 4.7, so `v4.7.0` matches, but it has not been added or tested here.
Try it on a throwaway copy of the stack (§6.3) before adding it.

### 9.3 What you already have covering part of this

`netbox-fms` and `netbox-wdm` both ship their own visualizations already
active in your instance: FMS has DAG-based fiber path/splice visualization,
and WDM has an interactive circuit-trace flow diagram on `WdmCircuit` detail
pages. For end-to-end optical circuit visualization specifically (as opposed
to general L1 device topology), you likely already have more than
`netbox-topology-views` would add.

**My recommendation, in order:** if geographic/outside-plant documentation
of your fiber and leased circuits is the priority, `netbox-pathways` is the
better fit for what you described and is worth the PostGIS investment.
`netbox-topology-views` is lower-value right now and worth a trial on a
throwaway copy of the 4.7 stack.

---

## 10. Optional extension: PostGIS + netbox-pathways

**Status: built and verified end-to-end**, kept as a separate, opt-in overlay
— not merged into the base deployment (§1–§8). Adopt it or don't; it does
not change anything about the base plugins or the base build/upgrade/
backup procedures if you leave it alone.

### 10.1 Why this is a separate overlay, not a `plugin_requirements.txt` line

Every other plugin in this deployment is "pin a version, add to `PLUGINS`,
rebuild." `netbox-pathways` is different in three ways that touch
infrastructure the base stack doesn't have:

1. It needs a **PostGIS-enabled PostgreSQL**, not plain `postgres:18-alpine`.
2. It needs **GDAL/GEOS/PROJ system libraries** inside the `netbox` image —
   `django.contrib.gis` loads these via `ctypes` at Python import time, so
   they must exist in the image, not just be pip-installable.
3. It needs a `srid` key in its `PLUGINS_CONFIG` or it refuses to load
   outright (a loud failure — Django raises `ImproperlyConfigured` — unlike
   the silent version-mismatch failures elsewhere in this deployment).

Because of this, adopting it changes the database engine setting for the
*entire* NetBox instance (`DATABASES['default']['ENGINE']`), not just which
plugins are active. That's a big enough change to keep it as a deliberate,
reversible choice rather than something silently baked into the base files.

### 10.2 What the overlay actually is

```
extensions/postgis-pathways/
├── Dockerfile-Plugins.postgis      # FROM netbox:latest-plugins + GDAL/GEOS/PROJ + netbox-pathways
├── docker-compose.postgis.yml      # postgres -> postgis/postgis image; netbox/-worker -> new build + config mount
└── configuration/
    ├── configuration.py            # unmodified copy of the base file
    ├── logging.py                  # unmodified copy of the base file
    ├── extra.py                    # DATABASES ENGINE -> postgis
    └── plugins.py                  # base plugins + netbox_pathways, with srid config
```

**Why a full parallel `configuration/` directory, not just an `extra.py`
tweak on top of the base:** the base `docker-compose.yml` bind-mounts
`./configuration:/etc/netbox/config:z,ro` at *runtime*, which shadows
anything a `Dockerfile` `COPY`s into that path at *build* time. The first
version of this extension only shipped a standalone `extra.py`/`plugins.py`
and silently ran with the base (non-postgis) config at runtime despite a
successful build — the image was correct, but the running container never
used it. `docker-compose.postgis.yml` overrides the mount target
`/etc/netbox/config` to point at this extension's own `configuration/`
directory instead, and the `Dockerfile-Plugins.postgis` `COPY`s from that
exact same source, so the build-time and run-time configs can't drift
apart. **This is the single easiest mistake to make when extending this
pattern yourself — if you add another overlay later, replicate this
structure, don't just drop a file next to the base Dockerfile.**

Also note: `plugins.py` here is a **full replacement**, not an append to
the base one, because NetBox loads config files in a fixed order
(`configuration.py`, `extra.py`, `logging.py`, `plugins.py` — see the
`🧬 loaded config` lines in build/boot output) and `plugins.py` loads last,
so nothing later exists for `extra.py` to append onto. If you change the
base `configuration/plugins.py` (§4), mirror the change into this file too
— they are not kept in sync automatically.

### 10.3 Adopting it

**Order matters** — the extension `netbox`/`netbox-worker` containers will
fail their startup `migrate` if the database doesn't have the `postgis`
extension yet, since `netbox_pathways` migrations create real geometry
columns.

```bash
cd netbox-docker
source env/postgres.env   # provides $POSTGRES_USER / $POSTGRES_DB below

# 1. Backup first (§5) — this changes the DB engine for the whole instance.
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc \
  > /opt/netbox-backups/pre-postgis-$(date +%Y%m%d-%H%M%S).dump

# 2. Build the extension image (needs internet for apt + pip — do this on
#    staging if deploying air-gapped, then ship the resulting image tag
#    `netbox:latest-plugins-postgis` through §7 same as the base image).
docker compose -f docker-compose.yml -f docker-compose.override.yml \
               -f extensions/postgis-pathways/docker-compose.postgis.yml \
               build --no-cache netbox 2>&1 | grep -i "unable to load plugin"   # must be silent

# 3. Swap ONLY postgres first, reusing the existing data volume — PostGIS
#    images are built FROM the same official postgres image for a given
#    major version, so the on-disk data format is unchanged. This is a
#    same-major-version image swap, not a dump/restore.
docker compose -f docker-compose.yml -f docker-compose.override.yml \
               -f extensions/postgis-pathways/docker-compose.postgis.yml \
               up -d --force-recreate postgres

# 4. Create the extension in the database ONCE, before starting netbox —
#    this is the step that must happen before any netbox_pathways migration
#    runs, or the netbox container's automatic migrate will fail.
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "CREATE EXTENSION IF NOT EXISTS postgis;"

# 5. Now bring up netbox and netbox-worker on the extension image.
docker compose -f docker-compose.yml -f docker-compose.override.yml \
               -f extensions/postgis-pathways/docker-compose.postgis.yml \
               up -d --force-recreate netbox netbox-worker
```

From here on, **always pass all three `-f` files together** for any
`compose` command against this deployment (`build`, `up`, `logs`, `exec`,
etc.) — mixing a two-file and three-file invocation is how you end up
running the base image against the postgis database, or vice versa.
Consider wrapping this in a shell alias or a `Makefile` target to avoid
typos, e.g.:

```bash
alias nbc='docker compose -f docker-compose.yml -f docker-compose.override.yml -f extensions/postgis-pathways/docker-compose.postgis.yml'
```

### 10.4 Verifying it actually works (not just that it loaded)

Loading without a warning is necessary but not sufficient — GIS stacks fail
in ways that don't show up as an import error. Do all of these, not just
the first one:

```bash
# Settings actually took effect (catches the mount-shadowing trap in §10.2)
nbc exec -T netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py shell -c "
from django.conf import settings
print(settings.PLUGINS)                          # must include netbox_pathways
print(settings.DATABASES['default']['ENGINE'])   # must be django.contrib.gis.db.backends.postgis
"

# Django's own checks (netbox-pathways registers a geometry/SRID check)
nbc exec -T netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py check

# Migrations actually created real geometry columns, not plain text
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\d netbox_pathways_structure"
# expect a line like: location | geometry(Geometry,4326)

# The Leaflet map widget actually initializes in the browser (not just an
# empty div) — log in, open Pathways → Structures → Add, and in the
# browser console:
#   document.querySelector('.leaflet-container').getBoundingClientRect()
# should report nonzero width/height, and
#   Array.from(document.querySelectorAll('.leaflet-pane')).length
# should be 7 (map/tile/overlay/shadow/marker/tooltip/popup panes).

# The full round trip: create a real object with a real geometry through
# the actual form, then confirm it persisted as a real PostGIS geometry —
# this was the decisive test performed when building this extension:
#   1. Fill in Name, set the hidden `location` input to a WKT point
#      (e.g. via the map widget's draw tool, or for scripted testing,
#      `document.querySelector('input[name="location"]').value = 'POINT (-73.5673 45.5017)'`
#      dispatching a `change` event)
#   2. Submit, then confirm via the API: GET
#      /api/plugins/pathways/structures/?name=<name> returns a GeoJSON
#      `location` field with the right coordinates
#   3. Confirm at the SQL level too:
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT id, name, ST_AsText(location), ST_SRID(location) FROM netbox_pathways_structure;"
# ST_AsText should show the exact point you drew; ST_SRID should be 4326.
```

If you only do the first check (settings/PLUGINS) and skip the rest, you
can end up "verified" against a plugin that loaded but whose map widget
never rendered, or whose geometry silently stored as SRID 0. Do the full
chain.

### 10.5 Reverting / "exchanging back"

**Adopting is a clean, reversible image swap as long as you haven't stored
real pathways data yet.** Reverting is asymmetric once you have:

**Before any real pathways data exists** (e.g. right after adoption, still
evaluating):

```bash
docker compose up -d --force-recreate postgres netbox netbox-worker
```

This is the plain two-file base compose, no `-f` overlay — it puts the base
`postgres:18-alpine` and `netbox:latest-plugins` images back, reusing the
same data volume. The `postgis` extension and the (empty) `netbox_pathways`
tables remain registered in the database, dormant and harmless — the base
`configuration/plugins.py` doesn't list `netbox_pathways`, so Django never
touches those tables in normal operation. This is exactly what was done to
close out the extension's own verification session.

**After real pathways data exists** and you want to fully remove it rather
than leave it dormant:

```bash
# while still running the postgis overlay
nbc exec -T netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py migrate netbox_pathways zero
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DROP EXTENSION IF EXISTS postgis CASCADE;"
# then revert to the base compose files as above
```

`DROP EXTENSION ... CASCADE` removes every object that depends on
PostGIS types — back up first (§5.2) if there's anything in those tables
you might want later; this is not reversible without that backup.

**There is no path back to plain `postgres:18-alpine` while real geometry
data you want to keep still exists** — a non-PostGIS Postgres cannot
represent a `geometry` column at all. If you need to keep the data and
drop PostGIS, the data has to be exported to a non-geometry representation
(e.g. WKT text columns) first, which is a data-modeling decision for you to
make, not something this runbook can do generically.

### 10.6 Backup and restore specifics for the PostGIS variant

`pg_dump -Fc` (§5.2) works identically — a dump of a PostGIS-enabled
database includes a `CREATE EXTENSION postgis` statement as part of its
schema, plus your geometry data in PostGIS's native binary form.

**The restore target must also be PostGIS-capable.** Restoring a dump taken
from a PostGIS database into a plain `postgres:18-alpine` container will
fail at the `CREATE EXTENSION postgis` step, because that image has no
PostGIS extension files installed. Always restore into a `postgis/postgis`
image of a compatible version (see §10.7 on what "compatible" means across
an upgrade).

```bash
docker compose -f docker-compose.yml -f docker-compose.override.yml \
               -f extensions/postgis-pathways/docker-compose.postgis.yml \
               down
docker volume rm netbox-docker_netbox-postgres   # only if restoring to a clean DB
nbc up -d postgres
docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists \
  < /opt/netbox-backups/netbox-db-YYYYMMDD-HHMMSS.dump
nbc up -d --wait
```

### 10.7 Upgrades: what this extension adds on top of §6

A plain NetBox-plus-plugins upgrade (§6) checks one axis of compatibility:
NetBox version × each plugin's `min_version`/`max_version`. This extension
adds three more axes that a "just upgrade netbox-docker" mindset will miss:

1. **PostgreSQL major version × PostGIS image availability.** If a future
   netbox-docker release bumps its default Postgres major version (e.g. 18
   → 19), you must find a `postgis/postgis` image tag for that new major
   (`https://hub.docker.com/r/postgis/postgis/tags`) — the base
   `docker-compose.yml`'s Postgres pin and this overlay's PostGIS pin are
   two independent things that both need to move together. There is no
   guarantee a matching PostGIS build exists the same day; check before
   committing to the Postgres bump.

2. **PostGIS extension version.** Independent of Postgres major version,
   `postgis/postgis` also ships PostGIS version bumps on the same Postgres
   major (this deployment uses `18-3.6-alpine`; a `18-3.7-alpine` could ship
   later). After swapping to a newer PostGIS image tag on the *same*
   Postgres major, run:
   ```bash
   docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "ALTER EXTENSION postgis UPDATE;"
   ```
   Treat a PostGIS *major* version bump (e.g. 3.x → 4.x, if that ever ships)
   with the same caution as a Postgres major upgrade: back up first (§10.6),
   test the `ALTER EXTENSION` in staging, and read PostGIS's own upgrade
   notes — some major bumps have required a dump/restore rather than an
   in-place `ALTER EXTENSION` historically.

3. **`netbox-pathways`'s own NetBox compatibility**, checked exactly like
   any other plugin (§4 step 2) — but easy to forget precisely because it
   lives in a separate overlay you don't touch during a routine upgrade.
   Add it explicitly to your pre-upgrade checklist (§6.1) whenever this
   extension is in use.

4. **GDAL/GEOS/PROJ system library versions.** These come from whatever
   `apt-get install` resolves at build time against the base NetBox image's
   OS release (Ubuntu — see `Dockerfile-Plugins.postgis`'s comment). If a
   future base NetBox image moves to a newer Ubuntu/Debian release, these
   library versions move with it, outside your control via
   `plugin_requirements.txt` pinning. Geometry data stored as WKB is stable
   across GDAL versions in practice, but **test the full chain in staging
   (§6.3) after any base-image bump while this extension is in use** — this
   is exactly the kind of interaction that doesn't show up as a version
   number anywhere and can only be caught by testing.

5. **Platform/architecture.** The official `postgis/postgis` image is
   published for `linux/amd64` only (verified via `docker manifest
   inspect postgis/postgis:18-3.6-alpine` while building this extension —
   no arm64 manifest exists). This is a non-issue on a normal amd64 Debian
   server. If your staging or execution host is ever arm64, you need QEMU
   emulation (`platform: linux/amd64` in the overlay, already set, plus
   `qemu-user-static` on the host) at a real performance cost, or a
   self-built multi-arch PostGIS image — factor this into any hardware
   change, not just software upgrades.

**Net effect on your upgrade checklist (§6.1):** if this extension is
adopted, step 1 of §6.1 ("decide the target NetBox version") gains a
follow-on question — "is there a PostGIS image and a netbox-pathways
release compatible with that target?" — before you proceed to checking the
other plugins. Don't upgrade the base stack and this extension in the
same change; upgrade and verify the base plugins first (§6), then treat
this extension's upgrade as its own separate staging exercise on top.
