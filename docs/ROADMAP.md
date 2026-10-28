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

## Next

1. **Documentation after v1.1.0.**
   - `OPERATIONS.md` §9.2 and §9.3 still describe netbox-topology-views as untested; it is installed since v1.1.0.
   - Usage notes for the plugins added in v1.1.0:
     - netbox-topology-views: since 5.0.0, users who are not superusers need add/change permission on the
       coordinate models (coordinate, circuitcoordinate, powerpanelcoordinate, powerfeedcoordinate) to save
       positions, and the diagram stays empty until "show cables" and "show unconnected" are ticked.
     - netbox-notices: the iCal feed `/plugins/notices/ical/maintenances.ics` accepts an API token in the URL
       (`?token=`), which ends up in proxy logs and calendar clients. §8 should recommend a separate read-only user
       and token for it.
     - netbox-cable-labels: how to set the label template, and that the labels it writes are not in the change log.
   - `OFFLINE-REPLACE-INSTALL.md`: a general row in the "what you found" table for a plugin app in the old database
     that the new image does not carry (so far only netbox-secrets has a row), and the image size (2.66 GB; the guide
     says about 2.3 GB).
   - `OPERATIONS.md` §4 step 10 should also name `extensions/postgis-pathways/configuration/plugins.py`, and the
     "Last verified" line is from 2026-09-26.
2. **Replace the air-gapped production installation** with `OFFLINE-REPLACE-INSTALL.md`. Not recorded as done; when
   it is, note the date and the version here.

## Waiting for a release upstream

A plugin is added only when a published release works on the NetBox in use: no forks, no commits from unmerged pull
requests. Each one is tested on a full start, not only a build (`OPERATIONS.md` §3.3), because two plugins that each
build and load can still stop NetBox from starting together.

| Plugin | Why it is out | When a working release is published |
|---|---|---|
| netbox-secrets | 3.1.1 declares `max_version = "4.6.99"`; 4.7 support is an unmerged pull request. | Pin it, add `netbox_secrets` to both `plugins.py` files, rebuild. The secrets still in the database come back (the user key's private key is needed). The sample data adds its encrypted router logins when its build runs again. |
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
  §6). Several plugins accept exactly one NetBox minor version.
- **Every plugin change:** follow `OPERATIONS.md` §4, change both `plugins.py` files, build, start until healthy, run
  the sample data's build and `verify.py` and the tracepath smoke test, and check that the plugin loads nothing from
  the internet (the production host has none).

## Not planned

- **netbox-attachments.** A different plugin from netbox-documents; not wanted at this point.
