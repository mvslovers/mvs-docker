#!/bin/bash
# tk5 entrypoint: IPLs TK5 the way its own mvs_ipl does in daemon mode
# (hercules -d -f conf/tk5.cnf with HERCULES_RC=scripts/ipl.rc, the
# settings in the Dockerfile's ENV), without mvs_ipl's selection of TK5's
# bundled Hercules builds, which this image does not carry.
#
# Hercules' output goes to `docker logs` and, as with mvs_ipl, to
# log/3033.log; the console hardcopy is log/hardcopy.log (device 030E).
#
# Hercules' stdin stays open until Hercules shuts down: in daemon mode Hercules reads stdin as a
# script after the rc file, and at EOF it shuts down unless a CPU happens
# to be started at that moment (see ../mvsce/entrypoint.sh). A FIFO opened
# read-write by this shell never reaches EOF.

cd /tk5 || exit 1

# The start script local_conf/ipl.rc runs: TK5's minimal one, or its
# standard one for REP101A=default (TK5's full configuration).
if [ "${REP101A:-}" = default ] && [ "${TK5_START_SCRIPT:-STARTMIN}" = STARTMIN ]; then
    export TK5_START_SCRIPT=STARTSTD
fi

rm -f /tmp/hercules.stdin
mkfifo /tmp/hercules.stdin
exec 3<>/tmp/hercules.stdin

cpu=$(sed -n 's/^model name[[:space:]]*: //p' /proc/cpuinfo | head -1)
echo "[*] Host: $(nproc) CPUs, ${cpu:-unknown CPU}, kernel $(uname -r)"

# Hercules (a742398074) quits only at EOF on stdin, also after `quit`, so a
# shutdown that ends in quit (MVS/CE's SHUTDOWN.RC, TK5's poweroff) left
# the container running. Hence stdin is the FIFO read-only, the shell's fd
# 3 is the writer that keeps it from EOF, and once Hercules has begun its
# own shutdown (HHC01420I in the log) the shell lets go of fd 3.
: > log/3033.log    # no HHC01420I of an earlier run
# 3>&-: a child holding fd 3 would be a writer itself, and stdin no EOF
hercules -d -f conf/tk5.cnf < /tmp/hercules.stdin > >(tee log/3033.log 3>&-) 2>&1 3>&- &
herc=$!
while kill -0 "$herc" 2>/dev/null; do
    if grep -q 'HHC01420I' log/3033.log 2>/dev/null; then
        exec 3>&-
        break
    fi
    sleep 1
done
wait "$herc"
rc=$?
sleep 1     # let tee write the last lines

if [ "$rc" -gt 128 ]; then
    echo "[*] Hercules ended: exit code $rc (signal $((rc - 128)))"
else
    echo "[*] Hercules ended: exit code $rc"
fi
exit "$rc"
