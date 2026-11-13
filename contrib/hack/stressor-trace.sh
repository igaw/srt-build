#!/bin/sh
# stressor-trace.sh: why does a stress-ng stressor delay the measurement?
#
# Runs one stressor (one instance per CPU) for SECS seconds under rtla
# timerlat (user-space threads, FIFO 98, as the stress-ng jobs), PAIRS
# times with the fair server on and off, alternating. A run stops at
# the first latency above STOP_US; rtla's auto-analysis (what blocked
# the timerlat thread, IRQ and thread delays) goes to the console and
# the trace to trace-<n>-<fs>.txt: sched_switch, sched_wakeup and, where
# they can be probed, the fair server starting and stopping
# (dl_server_start/stop).
#
# Stressors capped below FIFO 98 (mutex: FIFO 1-86) can still delay it
# if they starve CFS: the fair server then runs CFS tasks as a deadline
# task, above every FIFO priority. If the stops go away with the fair
# server off, that's the cause.
#
# Usage: ./stressor-trace.sh [stressor [secs [stop_us [pairs]]]]
#   (default mutex 60 1000 3)
#
# On a board: srt-build jobs hack <stress-ng-scheduler job> --minutes 30 \
#     --file contrib/hack/stressor-trace.sh --run "./stressor-trace.sh mutex"
# then copy /root/trace-*.txt off before the session ends. mutex alone
# on rpi3-64 (hack job 755) stayed below 0.2 ms either way: the fair
# server only hurts when CFS tasks are waiting (the class mix).
s=${1:-mutex}
secs=${2:-60}
stop=${3:-1000}
pairs=${4:-3}
cd /root || exit 1
mountpoint -q /sys/kernel/debug || mount -t debugfs none /sys/kernel/debug
T=/sys/kernel/tracing
FS=/sys/kernel/debug/sched/fair_server
[ -d $FS ] || { echo "no $FS: no fair server in this kernel"; exit 1; }
default=$(cat $FS/cpu0/runtime)
extra=""
for f in dl_server_start dl_server_stop; do
    if echo "p:srt_$f $f" >> $T/kprobe_events 2>/dev/null; then
        extra="$extra -e kprobes:srt_$f"
    fi
done
echo "stressor-trace: $s ${secs}s stop ${stop}us pairs $pairs, $(nproc) CPUs"
echo "kprobes:${extra:- none}"
echo "fair server runtime $default period $(cat $FS/cpu0/period)," \
    "sched_rt_runtime_us $(cat /proc/sys/kernel/sched_rt_runtime_us)"
# A line a minute: LAVA's connection timeout needs console output.
( while :; do sleep 60; echo "alive $(cut -d' ' -f1 /proc/uptime)"; done ) &
alive=$!
for i in $(seq 1 "$pairs"); do
    for fs in on off; do
        rt=$default
        [ $fs = off ] && rt=0
        for c in $FS/cpu*; do echo "$rt" > "$c/runtime"; done
        timeout -k 5 $((secs + 30)) stress-ng --"$s" 0 -t $((secs + 5)) \
            > "sng-$i-$fs.log" 2>&1 &
        sng=$!
        sleep 2
        # shellcheck disable=SC2086
        rtla timerlat top -u -P f:98 -d "${secs}s" -a "$stop" -q \
            -e sched:sched_switch -e sched:sched_wakeup $extra \
            > "run-$i-$fs.txt" 2>&1
        rc=$?
        if [ -f timerlat_trace.txt ]; then
            mv timerlat_trace.txt "trace-$i-$fs.txt"
            what="STOPPED, trace-$i-$fs.txt"
        else
            what="no stop"
        fi
        # stop the stressor now if rtla stopped early
        kill "$sng" 2>/dev/null
        wait "$sng" 2>/dev/null
        for p in /proc/[0-9]*; do
            grep -qx stress-ng "$p/comm" 2>/dev/null && kill "${p#/proc/}" 2>/dev/null
        done
        sleep 3
        echo "run $i fair-server=$fs rc=$rc $what"
        if [ "$what" != "no stop" ]; then
            sed -n '/auto-analysis/,$p' "run-$i-$fs.txt" | head -40
        else
            tail -8 "run-$i-$fs.txt"
        fi
    done
done
for c in $FS/cpu*; do echo "$default" > "$c/runtime"; done
kill "$alive"
echo "stressor-trace done"
