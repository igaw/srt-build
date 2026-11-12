#!/bin/sh
# osnoise-trace.sh: catch rtla-osnoise outliers with a trace.
#
# Repeats the rtla-osnoise test's command (FIFO:1, 800 ms of each 1 s,
# hackbench in a loop as load) in runs of RUN_MIN minutes for TOTAL_MIN
# minutes. A run stops at the first 1 s sample with more than STOP_US
# of noise and keeps its trace as trace-<n>.txt: sched_switch,
# sched_wakeup, sched_migrate_task and, where they can be probed, the
# fair server starting and stopping (dl_server_start/stop). Its thread
# noise histogram (who interrupted the osnoise threads) is noise-<n>.txt.
#
# Usage: ./osnoise-trace.sh [total_min [run_min [stop_us]]]
#   HOUSEKEEPING=0 ./osnoise-trace.sh ...   like rt-isolcpus: rtla and
#       hackbench on these CPUs (comma list, e.g. 0 or 0,1), the others
#       measured
#
# On a board: srt-build jobs hack <osnoise job> --minutes 240 \
#     --file contrib/hack/osnoise-trace.sh --run "./osnoise-trace.sh 180 5 1000"
# then copy /root/trace-*.txt off before the session ends. STOP_US
# depends on the board's noise floor: about 1000 for bbb and the Pis,
# 200 for c2d (doc/TUNING.md). Found the fair server taking over
# (round 8, hack job 562).
TOTAL=${1:-180}
RUN=${2:-5}
STOP=${3:-1000}
cd /root || exit 1
mountpoint -q /sys/kernel/debug || mount -t debugfs none /sys/kernel/debug
T=/sys/kernel/tracing
extra=""
for f in dl_server_start dl_server_stop; do
    if echo "p:srt_$f $f" >> $T/kprobe_events 2>/dev/null; then
        extra="$extra -e kprobes:srt_$f"
    fi
done
echo "kprobes:${extra:- none}"
fs=/sys/kernel/debug/sched/fair_server/cpu0
[ -d $fs ] && echo "fair server cpu0: runtime $(cat $fs/runtime) period $(cat $fs/period)"
cpus="" pin=""
if [ -n "$HOUSEKEEPING" ]; then
    measured=$(awk -v hk=",$HOUSEKEEPING," 'BEGIN { RS = "," } {
        n = split($0, r, "-"); a = r[1]; b = (n > 1) ? r[2] : r[1]
        for (c = a; c <= b; c++) if (index(hk, "," c ",") == 0) { printf "%s%d", s, c; s = "," } }' \
        /sys/devices/system/cpu/online)
    cpus="-H $HOUSEKEEPING -c $measured"
    pin="taskset -c $HOUSEKEEPING"
    echo "rtla and hackbench on CPUs $HOUSEKEEPING, measuring $measured"
fi
# The test's load: hackbench in a loop with 1 s pauses.
( while :; do $pin hackbench >/dev/null 2>&1; sleep 1; done ) &
bg=$!
# A line a minute: LAVA's connection timeout (5 min) needs console output.
( while :; do sleep 60; echo "alive $(cut -d' ' -f1 /proc/uptime)"; done ) &
alive=$!
end=$(( $(cut -d. -f1 /proc/uptime) + TOTAL * 60 ))
n=0
while [ "$(cut -d. -f1 /proc/uptime)" -lt "$end" ]; do
    n=$((n + 1))
    # shellcheck disable=SC2086
    rtla osnoise hist -P F:1 -r 800000 -d "${RUN}m" -s "$STOP" $cpus --trace \
        -e sched:sched_switch -e sched:sched_wakeup -e sched:sched_migrate_task \
        $extra \
        --event osnoise:thread_noise \
        --trigger hist:key=cpu,comm,duration.buckets=1000:sort=duration \
        > "run-$n.txt" 2>&1
    rc=$?
    mv osnoise_thread_noise_hist.txt "noise-$n.txt" 2>/dev/null
    hb=$(grep 'comm: hackbench' "noise-$n.txt" 2>/dev/null | awk -F'hitcount: *' '{s+=$2} END {print s+0}')
    if grep -q "hit stop" "run-$n.txt"; then
        mv osnoise_trace.txt "trace-$n.txt" 2>/dev/null
        what="STOPPED, trace-$n.txt"
    else
        rm -f osnoise_trace.txt
        what="ok"
    fi
    echo "run $n uptime=$(cut -d' ' -f1 /proc/uptime) rc=$rc $(grep '^max:' "run-$n.txt" | tr -s ' ') hackbench hits: $hb $what"
done
kill "$bg" "$alive"
echo "done after $n runs"
