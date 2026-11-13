#!/bin/sh
# mlock-ab.sh: does a measuring tool's unlocked memory make it stall
# under memory pressure?
#
# Three runs of DURATION, each under the same stress-ng class:
#   rtla    rtla timerlat hist -u (user-space threads; rtla doesn't
#           lock its memory), with the major page faults of its threads
#           and the direct reclaims per task (vmscan hist trigger)
#   ct      cyclictest without -m (memory not locked)
#   ct-m    cyclictest -m (mlockall, as the rt-tests jobs run it)
# All at SCHED_FIFO 98, one thread per CPU, 1 ms interval. If ct stalls
# like rtla and ct-m doesn't, the stalls are the tool's page faults or
# reclaim, not the kernel's latency.
#
# Usage: ./mlock-ab.sh [duration [class]]   (default 10m memory)
#
# On a board: srt-build jobs hack <stress-ng-memory job> --minutes 40 \
#     --file contrib/hack/mlock-ab.sh --run "./mlock-ab.sh 10m memory"
# Found that rtla's user-space column stalled for up to 1.9 s under the
# memory class while the kernel side stayed below 1 ms (round 11).
dur=${1:-10m}
class=${2:-memory}
T=/sys/kernel/tracing
R=$T/events/vmscan/mm_vmscan_direct_reclaim_begin
cd /root || exit 1

pids() {
    # processes whose name matches the extended regex $1 (ps and pkill
    # don't work in this rootfs)
    for p in /proc/[0-9]*; do
        if cat "$p/comm" 2>/dev/null | grep -qE "^($1)"; then
            echo "${p#/proc/}"
        fi
    done
}

majflt() {
    # sum of the major faults of all threads of the processes $1 matches
    for p in $(pids "$1"); do
        cat /proc/"$p"/task/*/stat 2>/dev/null
    done | awk '{ sub(/^.*\) /, ""); n += $10 } END { print n + 0 }'
}

stress_start() {
    ( while :; do stress-ng --oom-avoid --class "$class" --seq 0 -t 15 \
        > /dev/null 2>&1; sleep 1; done ) &
    bg=$!
}

stress_stop() {
    kill "$bg" 2>/dev/null
    wait "$bg" 2>/dev/null
    # shellcheck disable=SC2046
    kill $(pids stress-ng) 2>/dev/null
    sleep 5
}

reclaim_on() {
    echo 1 > $T/tracing_on 2>/dev/null
    echo '!hist:keys=common_pid.execname' > $R/trigger 2>/dev/null
    echo 'hist:keys=common_pid.execname' > $R/trigger
}

reclaim_show() {
    echo "  direct reclaims, top tasks:"
    grep -E '^\{' $R/hist | sort -t: -k3 -rn | head -8 | sed 's/^/    /'
    echo '!hist:keys=common_pid.execname' > $R/trigger
}

echo "mlock-ab: $dur under stress-ng --class $class, $(nproc) CPUs"

# 1: rtla timerlat, user-space threads
reclaim_on
stress_start
rtla timerlat hist -u -P f:98 -d "$dur" > rtla.txt 2>&1 &
rt=$!
sleep 5
f0=$(majflt "rtla|timerlatu")
while kill -0 "$rt" 2>/dev/null; do
    sleep 60
    echo "  rtla running, major faults so far: $(( $(majflt "rtla|timerlatu") - f0 ))"
done
stress_stop
echo "rtla: $(grep -E '^(max|over):' rtla.txt | tr -s ' ' | tr '\n' ' ')"
reclaim_show

# 2 and 3: cyclictest without and with mlockall
for mode in ct ct-m; do
    lock=""
    [ "$mode" = ct-m ] && lock="-m"
    reclaim_on
    stress_start
    # shellcheck disable=SC2086
    cyclictest -q -S $lock -p 98 -i 1000 -D "$dur" > "$mode.txt" 2>&1 &
    ct=$!
    sleep 5
    f0=$(majflt cyclictest)
    while kill -0 "$ct" 2>/dev/null; do
        sleep 60
        echo "  $mode running, major faults so far: $(( $(majflt cyclictest) - f0 ))"
    done
    stress_stop
    echo "$mode: max_us $(grep -o 'Max: *[0-9]*' "$mode.txt" | tr -s ' ' | cut -d' ' -f2 | tr '\n' ' ')"
    reclaim_show
done
echo "mlock-ab done"
