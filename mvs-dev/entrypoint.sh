#!/bin/sh
# Dynamically create/adjust docker group to match the mounted socket GID.
if [ -S /var/run/docker.sock ]; then
    DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)
    if ! getent group "$DOCKER_GID" >/dev/null; then
        groupadd -g "$DOCKER_GID" docker
    fi
    usermod -aG "$DOCKER_GID" dev
fi

# Drop from root to dev user (gosu sets uid, gid, and supplementary groups)
exec gosu dev "$@"
