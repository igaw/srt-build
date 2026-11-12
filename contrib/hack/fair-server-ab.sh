#!/bin/sh
# fair-server-ab.sh: does 6.12's fair server cause an osnoise outlier?
#
# Runs the rtla-osnoise test's command (all CPUs measured, hackbench in
# a loop) PAIRS times with the fair server on (its default runtime) and
# off (runtime 0 on every CPU), alternating, and prints per run the max
# noise per CPU and how often hackbench interrupted the osnoise threads.
# The kernel logs "Fair server disabled in CPU N" for each off run.
#
# Usage: ./fair-server-ab.sh [pairs]
#
# On a board: srt-build jobs hack <osnoise job> --minutes 45 \
#     --file contrib/hack/fair-server-ab.sh --run "./fair-server-ab.sh 4"
# (the results land in the job log). On rpi3-64 (hack job 561) 1 of 4
# runs with the fair server hit 4 ms, none of 4 without.
N=${1:-4}
FS=/sys/kernel/debug/sched/fair_server
cd /root || exit 1
mountpoint -q /sys/kernel/debug || mount -t debugfs none /sys/kernel/debug
[ -d $FS ] || { echo "no $FS: no fair server in this kernel"; exit 1; }
default=$(cat $FS/cpu0/runtime)
echo "fair server runtime default: $default period: $(cat $FS/cpu0/period)"
( while :; do hackbench >/dev/null 2>&1; sleep 1; done ) &
bg=$!
for i in $(seq 1 "$N"); do
    for fs in on off; do
        rt=$default
        [ $fs = off ] && rt=0
        for c in $FS/cpu*; do echo "$rt" > "$c/runtime"; done
        rtla osnoise hist -P F:1 -r 800000 -d 1m --trace \
            --event osnoise:thread_noise \
            --trigger hist:key=cpu,comm,duration.buckets=1000:sort=duration \
            > "run-$i-$fs.txt" 2>&1
        rc=$?
        mv osnoise_thread_noise_hist.txt "noise-$i-$fs.txt"
        hb=$(grep 'comm: hackbench' "noise-$i-$fs.txt" | awk -F'hitcount: *' '{n+=$2} END {print n+0}')
        echo "run $i fair-server=$fs rc=$rc $(grep '^max:' "run-$i-$fs.txt" | tr -s ' ') hackbench hits: $hb"
    done
done
for c in $FS/cpu*; do echo "$default" > "$c/runtime"; done
kill "$bg"
