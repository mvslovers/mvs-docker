#!/bin/bash
# tk5 entrypoint: IPLs TK5 the way its own mvs_ipl does in daemon mode
# (hercules -d -f conf/tk5.cnf with HERCULES_RC=scripts/ipl.rc, the
# settings in the Dockerfile's ENV), without mvs_ipl's selection of TK5's
# bundled Hercules builds, which this image does not carry.
#
# Hercules' output goes to `docker logs` and, as with mvs_ipl, to
# log/3033.log; the console hardcopy is log/hardcopy.log (device 030E).
#
# Hercules' stdin stays open: in daemon mode Hercules reads stdin as a
# script after the rc file, and at EOF it shuts down unless a CPU happens
# to be started at that moment (see ../mvsce/entrypoint.sh). A FIFO opened
# read-write by this shell never reaches EOF.

cd /tk5 || exit 1

rm -f /tmp/hercules.stdin
mkfifo /tmp/hercules.stdin
exec 3<>/tmp/hercules.stdin

cpu=$(sed -n 's/^model name[[:space:]]*: //p' /proc/cpuinfo | head -1)
echo "[*] Host: $(nproc) CPUs, ${cpu:-unknown CPU}, kernel $(uname -r)"

hercules -d -f conf/tk5.cnf <&3 2>&1 | tee log/3033.log
rc=${PIPESTATUS[0]}

if [ "$rc" -gt 128 ]; then
    echo "[*] Hercules ended: exit code $rc (signal $((rc - 128)))"
else
    echo "[*] Hercules ended: exit code $rc"
fi
exit "$rc"
