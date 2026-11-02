# Roadmap

This repository builds NetBox with its plugins baked into one image (`netbox:latest-plugins-postgis`), for test
installations and for an offline (air-gapped) production host. This file says what is done, what comes next and what
waits for someone else's release. The pinned versions and the reason for each are in `OPERATIONS.md` §1; building,
carrying and installing offline is in `OFFLINE-REPLACE-INSTALL.md`. The sample data
([netbox-sampledata](https://github.com/Uttiponken/netbox-sampledata)) has a roadmap of its own.

## Done

- **Plugin image, PostGIS extension and runbook (2026-10-02 to 2026-10-06).** `Dockerfile-Plugins` with every plugin
  pinned exactly and resolved in one `uv pip install`; the PostGIS overlay with netbox-pathways; the print plugin
  (now netbox-tracepath-plugin) built from its own repository; `OPERATIONS.md`; and the offline guide: build the
  images, carry them to an air-gapped host, and replace an existing installation there while keeping its database.
- **v1.0.0 (2026-10-25).** NetBox 4.7.3 on netbox-docker 5.1.1, every plugin moved to its NetBox 4.7 release.
  netbox-secrets dropped, because it has no 4.7 release.
- **v1.1.0 (2026-10-28).** netbox-dns (pip package netbox-plugin-dns), netbox-notices, netbox-cable-labels and
  netbox-topology-views. Checked with a full build and start, the sample data's build and `verify.py`, and the
  netbox-tracepath-plugin smoke test. netbox-documents and netbox-routing were tested too and left out (below).
- **v1.1.1 (2026-10-28): NetBox 4.7.4, base image pinned by digest.** The netbox-docker tags move (`v4.7-5.1.1`
  switched from NetBox 4.7.3 to 4.7.4 on 2026-10-28), so a build on a new host could get a NetBox nobody tested.
  `Dockerfile-Plugins` now names the exact image by its digest.
- **v1.2.0 (2026-10-28): netbox-wdm 0.3.0.** 0.3.0 renames the C-band grid keys (its migration rewrites stored rows)
  and refuses invalid WDM cabling at save time. Needs netbox-sampledata 0.8.2 or later, which writes the key the
  installed version knows; 0.8.1 cannot build on it. Tested on NetBox 4.7.4: an upgrade from 0.2.2 with the sample
  data loaded and an empty database, `verify.py` 70/0 and an unchanged second run on both, the tracepath smoke and
  acceptance tests.
- **v1.2.1 (2026-10-28): D3 served from the image.** netbox-fms and netbox-wdm loaded D3 from a CDN, unpinned and
  unchecked, so their diagrams and the FMS splice editor did not work without internet. `Dockerfile-Plugins` now
  serves D3 7.9.0 (checked by SHA-256) from NetBox's static files and points their five script tags at it; the build
  stops if those tags change or if any plugin template loads a script or stylesheet from the internet. Checked in
  Chromium on a Docker network without internet, with a copy of the dev data: the WDM circuit and channel traces and
  the FMS fiber circuit path draw and the FMS device splice editor loads; with the previous image they stay empty.
- **v1.3.0 (2026-11-02): netbox-fms 0.8.0, netbox-notices 1.4.0, netbox-pathways 0.4.0; builds on Docker 24 again.**
  fms 0.7.0 adds fiber faults and 0.8.0 requires NetBox 4.7.0; notices 1.4.0 can generate notifications from events
  (off unless configured); pathways 0.4.0 shows the tenant on every pathway type. v1.2.1 downloaded D3 with
  `ADD --checksum`, which the BuildKit of Docker Engine 24 (0.11) accepts only with the labs Dockerfile syntax, so
  that release did not build there; `Dockerfile-Plugins` now uses `curl` and `sha256sum`, and also ships the license
  texts of d3-ease, d3-geo and delaunator, which are inside `d3.min.js`. Tested with the guide's commands on a
  restored copy of a v1.0.0 database and from an empty database: `verify.py` 70 passed, 0 failed, an unchanged second
  run, the tracepath smoke and acceptance tests; the development stack was upgraded in place. Documentation:
  `OPERATIONS.md` §7 rewritten (it described an older route with the development override and the image set from
  before PostGIS), §6.7 upgrade log, §8.6 the notices calendar token, §9 notes on the plugins added in v1.1.0, and in
  the offline guide the rows for older plugin versions and what still needs the internet.

## Next

1. **Replace the air-gapped production installation** with `OFFLINE-REPLACE-INSTALL.md`. Not recorded as done; when
   it is, note the date and the version here.
2. **The pathways map background needs the internet.** Its tiles come from `tile.openstreetmap.org` and
   `server.arcgisonline.com`; on the air-gapped host the features still draw, the background stays empty. The guide
   says so (F10). To do: a tile server on the internal network for its `map_tiles` and `map_base_layers` settings, or
   no base layer. Every other plugin works offline (image scanned on 2026-11-02, v1.3.0).
3. **Ask netbox-fms and netbox-wdm to ship D3 themselves.** The image serves D3 since v1.2.1; upstream bundling would
   make that block unnecessary. Requested on 2026-11-02: jsenecal/netbox-fms#238 and jsenecal/netbox-wdm#102.
4. **The next netbox-pathways release.** Already merged upstream, not released: one ltree-based `Pathway` model and
   one API endpoint instead of one per type, the geometry field renamed `path` -> `geometry`, and the fix for the
   Pathways list page (500 on NetBox 4.7, still in 0.4.0). It needs sample data changes (`plant.py`, the metro data)
   and a rehearsal on a copy of the data before the pin moves.

## Waiting for a release upstream

A plugin is added only when a published release works on the NetBox in use: no forks, no commits from unmerged pull
requests. Each one is tested on a full start, not only a build (`OPERATIONS.md` §3.3), because two plugins that each
build and load can still stop NetBox from starting together.

| Plugin | Why it is out | When a working release is published |
|---|---|---|
| netbox-secrets | 3.1.2 (the newest, 2026-10-26) still declares `max_version = "4.6.99"`; 4.7 support is an unmerged pull request. | Pin it, add `netbox_secrets` to both `plugins.py` files, rebuild. The secrets still in the database come back (the user key's private key is needed). The sample data adds its encrypted router logins when its build runs again. |
| netbox-documents | 0.8.5 loads on 4.7, but its Documents list page fails (`'str' object has no attribute 'permissions_required'`) and its panel does not render with the default configuration. The fix is upstream pull request #112. | Pin it, add `netbox_documents` to both `plugins.py` files, rebuild. Its files go to the `netbox-media-files` volume, which the backups already cover. |
| netbox-routing | Cannot run next to netbox-bgp: both define the GraphQL types `CommunityType`, `CommunityListType` and `PrefixListType`, and NetBox exits at startup with `DuplicatedTypeName`. 0.5.1 is pre-1.0 with open BGP bugs. | Replaces netbox-bgp, see below. |

## Planned: netbox-routing replaces netbox-bgp

netbox-bgp stays until netbox-routing has a stable release. Then, in one change:

- `plugin_requirements.txt` and both `plugins.py` files: netbox-bgp out, netbox-routing in; check its NetBox range
  first (`OPERATIONS.md` §4).
- The `netbox_bgp_*` tables stay in the database, untouched. Nothing moves existing netbox-bgp objects into
  netbox-routing; an installation with BGP data of its own has to recreate it there.
- The sample data is rebuilt for netbox-routing at the same time (see its roadmap), and the build, `verify.py` and the
  tracepath smoke test run against the new image before release.

## Recurring

- **A new netbox-docker or NetBox release:** merge upstream, then work out the plugin table again (`OPERATIONS.md`
  §6). Several plugins accept exactly one NetBox minor version. Move the digest in `Dockerfile-Plugins` to the new
  image only after it has been tested.
- **The other images still follow moving tags:** `postgis/postgis:18-3.6-alpine` and `valkey/valkey:9.1-alpine` are
  pulled when the bundle is built. The offline host gets exactly what was bundled, but two builds can differ.
  Pinning them by digest as well is open.
- **D3 for netbox-fms and netbox-wdm (since v1.2.1):** on every upgrade and every bump of either plugin, check for a
  newer D3 7.x and the plugins' changelogs (`OPERATIONS.md` §6.1 step 6). Update the pinned version and checksums
  when D3 moves, together with the license files of the packages inside its bundle (d3-ease, d3-geo,
  delaunator); drop the block in `Dockerfile-Plugins` once both plugins bundle D3 themselves (the build stops when
  they stop using the CDN). Test the diagrams on a host without internet after any change.
- **Every plugin change:** follow `OPERATIONS.md` §4, change both `plugins.py` files, build, start until healthy, run
  the sample data's build and `verify.py` and the tracepath smoke test, and check that the plugin loads nothing from
  the internet (the production host has none).

## Not planned

- **netbox-attachments.** A different plugin from netbox-documents; not wanted at this point.
