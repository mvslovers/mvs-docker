#!/bin/bash
# mvsce-builder entrypoint: runs MVS/CE's own /mvs.sh, but makes the
# Hercules log reach `docker logs`.
#
# /mvs.sh sends Hercules' stdout to /logs/hercules.log, so `docker logs`
# carries only stderr: no IPL, no console, and a container whose Hercules
# has quit looks exactly like one that is still IPLing
# (mvslovers/brexx370#277). This follows the Hercules log and the console
# hardcopy (/logs/mvslog.txt, device 015) and reports how Hercules ended.
#
# It also keeps Hercules' stdin open. In --daemon (NoUI) mode Hercules
# reads stdin as a script after the rc file, and once that reaches EOF it
# shuts down unless a CPU happens to be started at that very moment
# (impl.c, "We come here only if ... we reached EOF on stdin"). A
# container's stdin is /dev/null, so whether the IPL survived was a race:
# "Script 2: file <stdin> processing ended", then "Begin Hercules
# shutdown" with one track read from the IPL volume. A FIFO opened
# read-write by this shell never reaches EOF.

cd /

rm -f /tmp/hercules.stdin
mkfifo /tmp/hercules.stdin
exec 3<>/tmp/hercules.stdin

cpu=$(sed -n 's/^model name[[:space:]]*: //p' /proc/cpuinfo | head -1)
echo "[*] Host: $(nproc) CPUs, ${cpu:-unknown CPU}, kernel $(uname -r)"

# -F keeps retrying until the files exist and survives /mvs.sh truncating
# hercules.log; tail prints a '==> file <==' header whenever it switches.
tail -n +1 -F /logs/hercules.log /logs/mvslog.txt 2>/dev/null &
tailpid=$!

/mvs.sh <&3
rc=$?

sleep 2     # let tail pick up the last lines
kill "$tailpid" 2>/dev/null
if [ "$rc" -gt 128 ]; then
    echo "[*] Hercules ended: exit code $rc (signal $((rc - 128)))"
else
    echo "[*] Hercules ended: exit code $rc"
fi
exit "$rc"
