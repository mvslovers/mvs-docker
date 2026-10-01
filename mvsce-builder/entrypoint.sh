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
#
# Holding stdin also lets this script type Hercules commands, which the
# console watchdog below needs.

# Workaround for a lost wakeup in Hercules' 3215-C console (con1052c.c):
# a READ INQUIRY prints its "Enter '/' input" prompt before it registers
# as a waiter, and HAO answers that very prompt. If the answer is quicker,
# the wakeup is lost and the read waits forever: 0009 stays busy, both
# CPUs sit in an enabled wait, the IPL stops right after IEA101A
# (brexx370#277). Once the read is waiting, the same input goes through,
# so when the last thing in the log is the input to 0009 and the log has
# been silent for 15 s, type that input again. Only during the IPL (until
# TCAS is up) and at most three times.
console_watchdog() {
    local log=/logs/hercules.log size prev=-1 still=0 kicks=0 line input
    for _ in $(seq 1 600); do
        sleep 1
        grep -q 'IKT005I' "$log" 2>/dev/null && return
        size=$(wc -c 2>/dev/null < "$log") || continue
        if [ "$size" != "$prev" ]; then
            prev=$size
            still=0
            continue
        fi
        still=$((still + 1))
        [ "$still" -lt 15 ] && continue
        # the last line that is more than a bare timestamp
        line=$(grep -v '^[0-9:]*[[:space:]]*$' "$log" | tail -n 1)
        case "$line" in
            *"HHC00013I '/' input entered for console 0:0009: \""*) ;;
            *) continue ;;
        esac
        input=${line#*console 0:0009: \"}
        input=${input%\"*}
        echo "[*] Console 0:0009 silent for ${still}s after input '$input', typing it again (Hercules con1052c lost wakeup)"
        echo "/$input" >&3
        still=0
        kicks=$((kicks + 1))
        [ "$kicks" -ge 3 ] && return
    done
}

cd /

# MVSCE_NUMCPU overrides the number of CPUs (MVS/CE ships NUMCPU 2). It
# acts on the template /mvs.sh copies to /config/local.cnf, so only on a
# first start, before that copy exists.
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
tail -n +1 -F /logs/hercules.log /logs/mvslog.txt 2>/dev/null &
tailpid=$!

console_watchdog &
watchdogpid=$!

/mvs.sh <&3
rc=$?

sleep 2     # let tail pick up the last lines
kill "$tailpid" "$watchdogpid" 2>/dev/null
if [ "$rc" -gt 128 ]; then
    echo "[*] Hercules ended: exit code $rc (signal $((rc - 128)))"
else
    echo "[*] Hercules ended: exit code $rc"
fi
exit "$rc"
