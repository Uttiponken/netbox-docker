#!/usr/bin/env bash
# Creates the folders under data/ that docker-compose.offline.yml bind-mounts, before the first start: each one
# owned by the user its image runs as, mode 700 (the list is in that file's header). Without them Docker would
# create the folders itself, empty and owned by root, and NetBox could not write its uploads.
#
#   scripts/init-data.sh          in the installation folder (.env from offline.env.example), after the images
#                                 are built, pulled or loaded
#
# The owners are read from the images (`id`), so a newer image with another uid still gets its own folders. Safe to
# run again: it creates only what is missing and sets the owner and mode of the folders themselves, never of the
# files in them, so it does not touch a database. The work is done in a container, so the host needs only Docker.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
exec </dev/null

images=$(docker compose config --images)
image_of() {  # image_of <regex> <name>: the image of the compose chain that matches
  printf '%s\n' "$images" | grep -m1 -E "$1" \
    || { echo "no $2 image in the compose chain: is .env made from offline.env.example?" >&2; return 1; }
}
netbox_image=$(image_of '^netbox:' NetBox)
postgres_image=$(image_of '(^|/)(postgis/postgis|postgres):' Postgres)
valkey_image=$(image_of '(^|/)valkey/valkey:' Valkey)
for image in "$netbox_image" "$postgres_image" "$valkey_image"; do
  docker image inspect "$image" >/dev/null 2>&1 \
    || { echo "the image $image is not here: build, pull or load it first (OPERATIONS.md 3.2)" >&2; exit 1; }
done
owner_in() {  # owner_in <image> <user> [<group id>]: "uid:gid" of that user in the image
  local owner
  owner=$(docker run --rm --network none --entrypoint sh "$1" -c "printf '%s:%s' \"\$(id -u $2)\" \"${3:-\$(id -g $2)}\"")
  [[ $owner =~ ^[0-9]+:[0-9]+$ ]] || { echo "no user $2 in $1 (got '$owner')" >&2; return 1; }
  echo "$owner"
}
netbox_owner=$(owner_in "$netbox_image" netbox 0)     # upstream runs NetBox as "netbox:root"
postgres_owner=$(owner_in "$postgres_image" postgres)
valkey_owner=$(owner_in "$valkey_image" valkey)

mkdir -p data    # data/ itself is the installation owner's (mode 700), set in the container: Docker may have made it as root
docker run --rm --user 0 --network none --entrypoint sh -v "$PWD/data:/data:z" "$netbox_image" -c "
  set -eu
  chown $(id -u):$(id -g) /data && chmod 700 /data
  mk() { mkdir -p \"/data/\$1\"; chown \"\$2\" \"/data/\$1\"; chmod 700 \"/data/\$1\"; }
  mk netbox $netbox_owner
  mk netbox/media $netbox_owner
  mk netbox/reports $netbox_owner
  mk netbox/scripts $netbox_owner
  mk postgres $postgres_owner
  mk redis $valkey_owner
  mk redis-cache $valkey_owner
  ls -ldn /data/* /data/netbox/*"   # listed in here: the host user cannot look into folders owned by these users
