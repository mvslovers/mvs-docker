#!/bin/bash
# mvsce entrypoint: runs MVS/CE's own /mvs.sh, but makes the
# Hercules log reach `docker logs`.
#
# /mvs.sh sends Hercules' stdout to /logs/hercules.log, so `docker logs`
# carries only stderr: no IPL, no console, and a container whose Hercules
# has quit looks exactly like one that is still IPLing
# (mvslovers/brexx370#277). This follows the Hercules log and the console
# hardcopy (/logs/mvslog.txt, device 015) and reports how Hercules ended.
#
# It also keeps Hercules' stdin open until Hercules shuts down. In --daemon (NoUI) mode Hercules
# reads stdin as a script after the rc file, and once that reaches EOF it
# shuts down unless a CPU happens to be started at that very moment
# (impl.c, "We come here only if ... we reached EOF on stdin"). A
# container's stdin is /dev/null, so whether the IPL survived was a race:
# "Script 2: file <stdin> processing ended", then "Begin Hercules
# shutdown" with one track read from the IPL volume. A FIFO opened
# read-write by this shell never reaches EOF.
#
# The console watchdog that used to live here re-typed input lost by
# Hercules' 3215-C console (con1052c.c lost wakeup, brexx370#277). The
# Hercules this image builds carries the fix (SDL-Hercules-390/hyperion#889),
# so it is gone.

cd /

# MVS/CE's /mvs.sh copies the DASDs, config and certificates into the
# image's VOLUMEs. Docker creates those directories; Apple's container
# does not, and /mvs.sh then fails ("cp: cannot create regular file
# '/dasd/'") and Hercules ends at once. On Docker this does nothing.
mkdir -p /config /dasd /logs /printers /punchcards /certs

# MVSCE_NUMCPU overrides the number of CPUs (this image sets NUMCPU 1,
# MVS/CE ships 2; see the Dockerfile). It acts on the template /mvs.sh
# copies to /config/local.cnf, so only on a first start, before that copy
# exists.
if [ -n "$MVSCE_NUMCPU" ]; then
    sed -i "s/^NUMCPU .*/NUMCPU    $MVSCE_NUMCPU/" /MVSCE/conf/local.cnf
fi

rm -f /tmp/hercules.stdin
mkfifo /tmp/hercules.stdin
exec 3<>/tmp/hercules.stdin

cpu=$(sed -n 's/^model name[[:space:]]*: //p' /proc/cpuinfo | head -1)
echo "[*] Host: $(nproc) CPUs, ${cpu:-unknown CPU}, kernel $(uname -r)"

# -F keeps retrying until the files exist and survives /mvs.sh truncating
# hercules.log; tail prints a '==> file <==' header whenever it switches.
tail -n +1 -F /logs/hercules.log /logs/mvslog.txt 2>/dev/null 3>&- &
tailpid=$!

# Hercules (a742398074) quits only at EOF on stdin, also after `quit`, so a
# shutdown that ends in quit (MVS/CE's SHUTDOWN.RC, TK5's poweroff) left
# the container running. Hence stdin is the FIFO read-only, the shell's fd
# 3 is the writer that keeps it from EOF, and once Hercules has begun its
# own shutdown (HHC01420I in the log) the shell lets go of fd 3.
mkdir -p /logs && : > /logs/hercules.log    # no HHC01420I of an earlier run
/mvs.sh < /tmp/hercules.stdin 3>&- &     # 3>&-: or it is a writer itself
herc=$!
while kill -0 "$herc" 2>/dev/null; do
    if grep -q 'HHC01420I' /logs/hercules.log 2>/dev/null; then
        exec 3>&-
        break
    fi
    sleep 1
done
wait "$herc"
rc=$?

sleep 2     # let tail pick up the last lines
kill "$tailpid" 2>/dev/null
if [ "$rc" -gt 128 ]; then
    echo "[*] Hercules ended: exit code $rc (signal $((rc - 128)))"
else
    echo "[*] Hercules ended: exit code $rc"
fi
exit "$rc"
