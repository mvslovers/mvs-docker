#!/bin/sh
# Adjust docker group GID to match the mounted socket, if present.
if [ -S /var/run/docker.sock ]; then
    SOCK_GID=$(stat -c '%g' /var/run/docker.sock)
    CUR_GID=$(getent group docker | cut -d: -f3)
    if [ "$SOCK_GID" != "$CUR_GID" ]; then
        groupmod -g "$SOCK_GID" docker 2>/dev/null
    fi
fi

# Drop from root to dev user (gosu sets uid, gid, and supplementary groups)
exec gosu dev "$@"
