#!/bin/sh
# stress-ng-hunt.sh: which stressors of a stress-ng class hurt latency.
#
# Runs every stressor of each CLASS on its own for SECS seconds (one
# instance per CPU, as --class X --seq 0 does), with cyclictest on every
# CPU (FIFO 98, 1 ms interval, as the stress-ng jobs) next to it, and
# prints one line per stressor: cyclictest's max latency per CPU, how
# many kernel messages the stressor caused and the most frequent one.
# The lines go to the console, so they survive in the LAVA job log even
# if a stressor takes the board down.
#
# Usage: ./stress-ng-hunt.sh [secs [class...]]
#   EXCLUDE="bigheap brk stack env" (default) stressors to skip
#   FROM=<stressor> start each class's list at this stressor (to go on
#   where a session ran out of time)
#
# On a board: srt-build jobs hack <stress-ng job> --minutes 30 \
#     --file contrib/hack/stress-ng-hunt.sh \
#     --run "./stress-ng-hunt.sh 15 scheduler os"
secs=${1:-15}
shift 2>/dev/null
classes=${*:-scheduler os}
EXCLUDE=${EXCLUDE:-bigheap brk stack env}
cd /root || exit 1
stress-ng --version
for class in $classes; do
    list=$(stress-ng --class "$class?" 2>&1 | sed -n 's/.*stressors: *//p')
    if [ -n "$FROM" ]; then
        list=$(echo "$list" | tr ' ' '\n' | sed -n "/^$FROM\$/,\$p" | tr '\n' ' ')
    fi
    echo "class $class: $(echo "$list" | wc -w) stressors"
    for s in $list; do
        case " $EXCLUDE " in *" $s "*) echo "$class/$s: skipped"; continue ;; esac
        before=$(dmesg | wc -l)
        timeout -k 5 $((secs + 30)) stress-ng --"$s" 0 -t "$secs" \
            > "sng-$s.log" 2>&1 &
        sng=$!
        cyclictest -q -S -m -p 98 -i 1000 -D "$((secs + 1))" > "ct-$s.txt" 2>&1
        wait "$sng"
        rc=$?
        max=$(grep -o 'Max: *[0-9]*' "ct-$s.txt" | tr -s ' ' | cut -d' ' -f2 | tr '\n' ' ')
        dmesg | tail -n +"$((before + 1))" > "dmesg-$s.txt"
        new=$(wc -l < "dmesg-$s.txt")
        top=$(sed 's/^\[[ 0-9.]*\] //; s/[0-9][0-9]*/N/g' "dmesg-$s.txt" \
            | sort | uniq -c | sort -rn | head -1 | cut -c1-80)
        echo "$class/$s: max_us $max rc $rc klog $new $top"
        sleep 2
    done
done
echo "hunt done"
