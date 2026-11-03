# NetBox Docker Deployment — Operations Runbook

Status: living document. Update the version tables whenever a plugin or NetBox
version changes. What comes next, and which plugins wait for a release, is in
`ROADMAP.md`.

Last verified: 2026-11-02, this repository's `v1.3.0` (§6.7), on Docker Engine
24.0.2 / Compose v2.19.0 (Docker Desktop on an arm64 Mac): the two-stage
`--no-cache` build, an upgrade of a restored database and an empty-database
start, each with the sample data and the netbox-tracepath-plugin tests. Target execution/staging OS for this runbook:
**Debian 13 "trixie"** (instructions are identical on Debian 12 "bookworm" —
substitute the codename in the apt source line). The Docker prerequisites for
**Ubuntu 24.04 / 22.04** and **Fedora** are in §2.2 and §2.3.

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
| netbox-fms                     | `netbox_fms`           | 0.8.0          | Latest. Alpha software; `min_version=4.7.0`, no max. 0.6.0 derives fiber paths by analysis (§6.6); 0.7.0 adds fiber faults (§6.7). |
| netbox-inventory                | `netbox_inventory`     | 2.7.1          | Latest. Hard-pins to NetBox 4.7 (2.6.1 was the 4.6 release). |
| netbox-otp-plugin               | `netbox_otp_plugin`    | 1.3.6          | Latest. Supports NetBox 4.0–4.99. |
| netbox-floorplan-plugin          | `netbox_floorplan`    | 0.10.0         | Latest. Hard-pins to NetBox 4.7.x only (0.9.2 was the 4.6 release). |
| netbox-wdm                      | `netbox_wdm`           | 0.3.0          | Latest. Alpha software; `min_version=4.7.0`, no max. Companion to netbox-fms. Renames the C-band grid keys (migration 0012 rewrites stored rows; clients must send `dwdm_c_100ghz`). |
| (your own plugin)               | `netbox_example_plugin`| 0.1.0          | Scaffold in `custom-plugins/netbox-example-plugin/`. |
| (your own plugin)               | `netbox_tracepath_plugin`| 0.8.0        | PDF cable traces, from its own repository, see §3.1. |
| netbox-pathways (PostGIS overlay) | `netbox_pathways`     | 0.4.0          | Latest. `min_version=4.7.0`, no max. Every pathway type shows its tenant. The Pathways list page still fails on 4.7 (fixed upstream, not released). See §10. |
| netbox-plugin-dns               | `netbox_dns`           | 1.7.3          | Latest. The 1.7.x line is `min_version=4.7.0` (1.6.x is for 4.5/4.6). Not the abandoned PyPI package `netbox-dns`. |
| netbox-notices                  | `notices`              | 1.4.0          | Latest. `min_version=4.5`, no max. Maintenance/outage calendar and iCal feed (§8.6); FullCalendar is bundled. |
| netbox-cable-labels             | `netbox_cable_labels`  | 0.1.0          | Only release. 4.2–4.99.99. Labels unlabelled cables `#<pk>`; that write bypasses the change log. |
| netbox-topology-views           | `netbox_topology_views`| 5.0.0          | Latest. `min_version=4.7.0`. Fixes XSS issues in 4.7.0; saving positions needs add/change on the coordinate models. |

**netbox-secrets is not installed.** Its newest release, 3.1.2, still declares
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
| Ubuntu 24.04 / 22.04 LTS | §2.2 |
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

Coming from Debian's `docker.io`: the notes at the end of §2.2 apply, above all **never purge `docker.io`**.

### 2.2 Docker Engine + Compose plugin: Ubuntu 24.04 and 22.04 (official Docker apt repo)

The commands follow Docker's installation guide for Ubuntu (docs.docker.com/engine/install/ubuntu/), except that
Docker's repository is added before the old packages are removed, so nothing goes if it cannot be reached. Checked
on 2026-11-03 on Ubuntu 22.04.5 (x86_64), coming from Ubuntu's `docker.io` 29.1.3, `docker-compose` 1.29.2
(Compose v1) and `docker-compose-v2`: afterwards Docker Engine 29.9.2, Compose v5.7.0 and buildx 0.38.1, with every
container, image, volume and network kept. Not yet run on Ubuntu 24.04; the commands are the same, the codename
comes from `/etc/os-release`. Coming from Ubuntu's `docker.io`, read the notes after the verify step first.

```bash
# Docker's signing key and apt repository (first, so nothing is removed if this fails)
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
gpg --show-keys /etc/apt/keyrings/docker.asc     # the fingerprint must be 9DC858229FC7DD38854AE2D88D81803C0EBFCD88

sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
apt-cache policy docker-ce | grep Candidate      # must show a version, not "(none)"

# Remove Ubuntu's packages, all of them. `apt install docker-ce` replaces docker.io, containerd, runc and
# docker-buildx by itself, but not docker-compose-v2, and docker-compose-plugin then fails to install ("trying to
# overwrite '/usr/libexec/docker/cli-plugins/docker-compose', which is also in package docker-compose-v2").
sudo apt remove $(dpkg --get-selections docker.io docker-compose docker-compose-v2 docker-doc docker-buildx podman-docker containerd runc | cut -f1) 2>/dev/null || true

sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Allow your user to run docker without sudo (log out and in after this)
sudo usermod -aG docker "$USER"
```

The service starts and is enabled by the package. Verify:

```bash
sudo systemctl status docker --no-pager | head -3
docker --version              # 24.0.2 or newer (29.9.2 on 2026-11-03)
docker compose version        # v2.17 or newer; Docker's packages ship v5 now (v5.7.0 on 2026-11-03)
docker buildx version
docker run --rm hello-world   # after logging out and in again; otherwise use sudo
```

**Coming from Ubuntu's `docker.io`:**

- **Containers, images, volumes and networks stay.** `apt remove` does not touch `/var/lib/docker`, and the new
  daemon keeps the old `overlay2` store: `docker info --format '{{.Driver}}'` should still say `overlay2`.
- **Running containers stop** when the old daemon goes. Those with restart policy `no`
  (`docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' <name>`) stay stopped until you start them again.
- **Compose v1 (`docker-compose`) is gone afterwards.** Run existing projects with `docker compose`; on the next `up`
  it recreates their containers with hyphens instead of underscores in the names (`project-service-1`), on the same
  volumes.
- **Never purge `docker.io`** (`apt purge docker.io`, or a clean-up such as `apt purge '~c'` that purges every
  removed package). Its purge step runs `/var/lib/docker/nuke-graph-directory.sh`, which the package leaves behind,
  and that deletes `/var/lib/docker`: every image, container and volume. The same step also does systemd clean-up
  on `docker.service`, the unit name Docker's packages use too. Delete the script after the swap and leave
  `docker.io` and `containerd` in the `rc` state that `dpkg -l` shows:

  ```bash
  sudo rm -f /var/lib/docker/nuke-graph-directory.sh
  ```

  This was read in Ubuntu 22.04's package scripts (`/var/lib/dpkg/info/docker.io.postrm`); Debian's `docker.io`
  comes from the same packaging, so treat it the same way (§2.1).

**A specific version instead of the latest** (to match another host exactly):

```bash
apt list --all-versions docker-ce 2>/dev/null | head
VERSION_STRING="<a version from the list, for example 5:29.8.2-1~ubuntu.24.04~noble>"
sudo apt install -y docker-ce=$VERSION_STRING docker-ce-cli=$VERSION_STRING containerd.io docker-buildx-plugin docker-compose-plugin
sudo apt-mark hold docker-ce docker-ce-cli          # keep `apt upgrade` from moving it
```

**Air-gapped host:** download the packages on the online host as in §7.3 (the same five packages and
`apt-get install --download-only`), then install them with `sudo dpkg -i ./*.deb`.

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

Budget **~3 GB** for the built image set (sizes in section 0 of
`OFFLINE-REPLACE-INSTALL.md`; a build host needs about 15 GB free) plus
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

   The build also stops if the new plugin's templates load a script or
   stylesheet from the internet, which would not work on the air-gapped host:
   serve it from the image the way `Dockerfile-Plugins` does for D3 (§6.1
   step 6), or leave the plugin out.

   A plugin can pass step 6 and still stop NetBox from starting, for example
   with a GraphQL type name another plugin already uses (§1, §3.3). If
   `netbox` does not become healthy, read its log before anything else.

8. Apply migrations (usually automatic on container start, but confirm):

   ```bash
   docker compose exec -T netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py migrate <app_label>
   ```

9. Confirm in **Plugins → Plugins** in the UI that it shows Active with the
   version you expect, and exercise its main page once.

10. Commit `plugin_requirements.txt`, both `plugins.py` files
    (`configuration/plugins.py` and
    `extensions/postgis-pathways/configuration/plugins.py`, which is the one the
    PostGIS stack reads), and this runbook's table in §1 in the same commit.

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
6. **Offline browser assets.** netbox-fms and netbox-wdm load D3 from a CDN;
   `Dockerfile-Plugins` serves a pinned copy (7.9.0, checked by SHA-256) from
   NetBox's static files instead, so their diagrams work on the air-gapped
   host. Next to it go the license texts the bundle needs: D3's own (ISC) and
   those of three packages inside `d3.min.js` with notices of their own,
   d3-ease (BSD-3-Clause), d3-geo (ISC and MIT) and delaunator (ISC, Mapbox).
   On every upgrade, and whenever one of the two plugins is bumped:
   - check for a newer D3 7.x (`https://registry.npmjs.org/d3`, the plugins
     ask for `d3@7`); if there is one, change the version and checksum of
     `d3.min.js` and of D3's `LICENSE` in `Dockerfile-Plugins`, and take the
     d3-ease, d3-geo and delaunator versions that release depends on
     (`https://registry.npmjs.org/d3/<version>`), with new checksums for their
     license files;
   - read the two plugins' changelogs: once they bundle D3 themselves, or move
     to D3 8, their script tags change and the build stops with "no longer load
     D3 from a CDN". Drop the block, or adjust it to the new tags;
   - after any change, open the WDM circuit trace and the FMS fiber circuit
     path on a host without internet and check that the diagrams draw.
   The same build step stops if any plugin template loads a script or
   stylesheet from the internet.

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

### 6.7 Upgrade log: to this repository's `v1.3.0` (netbox-fms 0.8.0, netbox-notices 1.4.0, netbox-pathways 0.4.0)

Rehearsed on 2026-11-02 with the commands of `OFFLINE-REPLACE-INSTALL.md` (D, then F2 to F10) on a restored copy of
the development database, which still ran this repository's `v1.0.0` (NetBox 4.7.3, nine plugins, netbox-wdm
0.2.2); the development stack was then upgraded in place the same way. What to expect:

1. **Back up first** (§5.2, or step D of the guide). The migrations cannot be undone.
2. **The first start applies the missing migrations** (76 s on the sample data): NetBox 4.7.4 (`extras` 0145),
   netbox-fms 0040 to 0042 (fiber faults, new tables only), netbox-wdm 0009 to 0012 (0012 renames the C-band grid
   keys in the stored rows, `dwdm_100ghz` → `dwdm_c_100ghz`), netbox-notices 0012, and the plugins added in v1.1.0
   from their first migration (netbox-dns, netbox-notices, netbox-topology-views). netbox-pathways 0.4.0 has none.
   Row counts stay identical, and API tokens from the old installation keep working.
3. **netbox-fms 0.7.0 fiber faults.** A path that crosses an open fault is marked defective: circuit assignment
   refuses it, active assignments on it break with "Fiber faulted" and come back when the fault is resolved. After
   the upgrade there are no faults, so nothing changes until someone reports one (Fiber faults list:
   `/plugins/fms/faults/`).
4. **netbox-pathways 0.4.0** shows the tenant on every pathway type. The Pathways list page
   (`/plugins/pathways/pathways/`) still returns a server error on NetBox 4.7; the fix is merged upstream but not
   released. Every other pathways page works.
5. **netbox-notices 1.4.0** can generate outgoing notifications from events; that stays off until
   `auto_generate_notifications` is set (§9.3).
6. **Sample data:** netbox-sampledata 0.8.2 or later (because of netbox-wdm 0.3.0). On the upgraded copy `verify.py`
   passes 70 checks after the dataset's own build, and a second build changes nothing; the netbox-tracepath-plugin
   smoke test and the dataset's tracepath acceptance tests pass.

---

## 7. Air-gapped deployment: build, transfer, install

Every installation on a host without internet follows `OFFLINE-REPLACE-INSTALL.md`. It builds the image set this
repository ships (`netbox:latest-plugins-postgis`, `postgis/postgis:18-3.6-alpine`, `valkey/valkey:9.1-alpine`) on an
online host, tests it there, exports a bundle with checksums (never the development `docker-compose.override.yml`)
and installs from that bundle. This section says which parts of the guide a situation needs, how to start a new
installation, and how to get Docker itself onto a host without internet; the guide expects Docker to be there.

Two Linux hosts with the same CPU architecture (`uname -m`; Debian 13, Ubuntu 24.04 / 22.04 or Fedora, see §2): the
**online build host** and the **air-gapped host**.

### 7.1 Which parts of the guide

| Situation | Follow |
|---|---|
| An older netbox-docker installation runs on the air-gapped host and its data must stay | The whole guide: build and export (A), carry (B), look at and back up the old installation (C, D), rehearse (E), cut over (F), roll back or clean up (G). |
| A new host without NetBox | A, B, F2 and F3 of the guide, then §7.2 below instead of F4 to F8, then F9 and F10. |
| An installation made with the guide gets a new version | G3 of the guide: rebuild, export, carry, back up, load, `docker compose up -d`. |

### 7.2 A new installation

There is no old installation to take `SECRET_KEY` and `API_TOKEN_PEPPER_1` from, and `env/netbox.env` ships with
upstream netbox-docker's public example values, so generate new ones. After F3, in the new directory:

```bash
cd /opt/netbox-plugins
setkey() { grep -v "^$2=" "$1" > "$1.tmp"; printf '%s=%s\n' "$2" "$3" >> "$1.tmp"; mv "$1.tmp" "$1"; }   # as in F4

setkey env/netbox.env SECRET_KEY "$(openssl rand -hex 32)"
setkey env/netbox.env API_TOKEN_PEPPER_1 "$(openssl rand -hex 32)"
PW=$(openssl rand -hex 24)
setkey env/netbox.env DB_PASSWORD "$PW"
setkey env/postgres.env POSTGRES_PASSWORD "$PW"
setkey env/netbox.env RELEASE_CHECK_URL ""        # no internet: do not look up new NetBox releases
chmod 600 env/*.env
```

Keep a copy of `SECRET_KEY` and `API_TOKEN_PEPPER_1` with your other secrets: a restore of this installation needs
the same values (§8.3). Change the Redis passwords as well (§8.1).

PostGIS has to exist before NetBox starts for the first time:

```bash
docker compose up -d --wait postgres
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE EXTENSION IF NOT EXISTS postgis"'
```

Then F9 of the guide (the first start runs every migration, which takes a few minutes, and may end with "unhealthy"
once; the guide says what to do), create the first user (§3.3, `createsuperuser`), and F10 without the checks that
refer to the old installation.

### 7.3 Docker on a host without internet

Skip this if the air-gapped host already has Docker Engine, the Compose v2 plugin (2.17 or newer) and buildx, for
example from your OS image process. Otherwise download the packages on an online host that runs **the same OS
release and architecture** and has Docker's package repository set up (§2.1 to §2.3), carry them across with the
bundle, and install them there. If the air-gapped host has the distribution's `docker.io`, `docker-compose`,
`docker-compose-v2` or `docker-buildx`, remove them first as in §2.1 and §2.2, and never purge `docker.io` (§2.2).

Debian and Ubuntu:

```bash
# on the online host
mkdir -p ~/nbbuild/docker-debs && cd ~/nbbuild/docker-debs
sudo apt-get clean                                  # so the cache holds only what the next command downloads
sudo apt-get install -y --download-only --reinstall \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
cp /var/cache/apt/archives/*.deb . && sha256sum *.deb > SHA256SUMS

# on the air-gapped host, in the carried directory
sha256sum -c SHA256SUMS
sudo dpkg -i ./*.deb
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"                     # log out and in after this
```

`--download-only` fetches only the dependencies the online host does not have yet. If `dpkg -i` reports a missing
dependency, download that package the same way (`apt-get install --download-only --reinstall <package>`) and add it.

Fedora: §2.3, "Air-gapped host" (`dnf download --resolve --alldeps`).

Check the result as in §2 (`docker --version`, `docker compose version`). These commands follow Docker's own
documentation; they were not run on this repository's development machine.

### 7.4 Keeping a record

Every update is a new bundle from the online host (guide G3); nothing is built or pulled on the air-gapped host.
Keep each bundle's `MANIFEST.txt` and `SHA256SUMS`, so you can tell later exactly which images and plugin versions
were installed when.

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

The bundle from `OFFLINE-REPLACE-INSTALL.md` (§7) carries `env/*.env` with
upstream's public example values; the real secrets are only set on the target
(guide step F4, or §7.2). The backup archive `config.tar.gz` from step D of the
guide does hold the real ones: treat it, and every database dump, with the same
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

### 8.6 The netbox-notices calendar feed

netbox-notices publishes maintenances as an iCal feed,
`/plugins/notices/ical/maintenances.ics`. A calendar client cannot log in, so
the feed also accepts a NetBox API token in the URL (`?token=nbt_...`). A token
in a URL ends up in proxy and web server logs and in every calendar client that
subscribes, and it acts with the full rights of its user. Give the feed its own
user whose only permission is to view maintenances (an object permission with
the action *view* on *Notices > maintenance*, which is what the feed checks:
`notices.view_maintenance`), and a token for that user with **Write enabled**
switched off. Never subscribe with an administrator's token.

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

Version 0.2.2 declared support for NetBox 4.5.3–4.6.x; 0.3.0 declared no
range; 0.4.0 (the pin now) requires NetBox 4.7.0. It needs PostGIS, and its
structure map point moved from `location` to `geometry` in 0.3.0, which the
sample data follows. Its next release will be a larger change (one
ltree-based Pathway model and one API endpoint instead of one per type,
already merged upstream): it will need sample data changes and a rehearsal
before it is pinned.

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

### 9.2 `netbox-topology-views` — installed since v1.1.0

[netbox-community/netbox-topology-views](https://github.com/netbox-community/netbox-topology-views)
draws a topology diagram from your existing cable connections (with
draw.io/PNG export). It is installed since this repository's v1.1.0 (5.0.0,
NetBox 4.7 only). Two things to know:

- Since 5.0.0 the view respects object permissions. A user who is not a
  superuser sees only the devices and cables they may view, and needs add and
  change permission on the coordinate models (`coordinate`,
  `circuitcoordinate`, `powerpanelcoordinate`, `powerfeedcoordinate`) to save
  node positions.
- If the diagram stays empty, tick **Show cables** and **Show unconnected** in
  its options; with the sample data it draws nothing without them.

### 9.3 `netbox-notices` and `netbox-cable-labels` — installed since v1.1.0

- **netbox-notices** records provider maintenances and outages, shows them in a
  calendar and publishes an iCal feed; protect that feed as in §8.6. Since
  1.4.0 it can also generate outgoing notifications from events. That is off
  until `PLUGINS_CONFIG["notices"]["auto_generate_notifications"]` lists the
  event statuses that should trigger one.
- **netbox-cable-labels** gives a cable created without a label one from a
  Jinja template, by default `#{{cable.pk}}`. To change it, add
  `"netbox_cable_labels": {"label_template": "<template, the cable is {{cable}}>"}`
  to `PLUGINS_CONFIG` in `extensions/postgis-pathways/configuration/plugins.py`
  (and in `configuration/plugins.py`). The label is written after the cable is
  saved, with a direct database update: it does **not** appear in the change
  log, and the API response to the create still shows the label empty (read
  the cable again to see it).

### 9.4 What the optical plugins already show

`netbox-fms` and `netbox-wdm` both ship their own visualizations: FMS has
DAG-based fiber path and splice visualization, and WDM has an interactive
circuit-trace flow diagram on `WdmCircuit` detail pages (both draw with D3,
which the image serves itself, see §6.1 step 6). For end-to-end optical circuit
visualization they show more than `netbox-topology-views`, which draws the
general L1 device topology; the two complement each other. `netbox-pathways`
(§9.1, §10) adds where the cables physically run.

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
