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
#   MEASURE=rtla: rtla timerlat hist instead of cyclictest, as the class
#   jobs measure (user threads, FIFO 98, dma latency 0); the line then
#   has the max over all CPUs of the IRQ, kernel thread and user thread
#   latency and the kernel thread's max per CPU
#   ONLY="<stressor>...": run only these of each class's list
#   STRESS_OPTS: more stress-ng options (the class jobs: --oom-avoid)
#   AUTO=<us> (with MEASURE=rtla): rtla stops at the first latency of
#   <us> and prints its auto analysis (what ran in the way) and the
#   stack, for tracing the stressors a first hunt found
#
# On a board: srt-build jobs hack <stress-ng job> --minutes 30 \
#     --file contrib/hack/stress-ng-hunt.sh \
#     --run "./stress-ng-hunt.sh 15 scheduler os"
secs=${1:-15}
shift 2>/dev/null
classes=${*:-scheduler os}
EXCLUDE=${EXCLUDE:-bigheap brk stack env}
MEASURE=${MEASURE:-cyclictest}
cd /root || exit 1
stress-ng --version
[ "$MEASURE" = rtla ] && rtla --version 2>&1 | head -1
dma=""
[ -e /dev/cpu_dma_latency ] && dma="--dma-latency=0"

# rtla timerlat hist for $1 seconds into $2; prints "irq thr usr" maxima
# (all CPUs) and the kernel thread's max per CPU.
measure_rtla() {
    auto=""
    [ -n "$AUTO" ] && auto="-a $AUTO"
    # shellcheck disable=SC2086
    rtla timerlat hist $dma -u -P f:98 -d "${1}s" $auto > "$2" 2>&1
    all=$(sed -n '/^ALL:/,$p' "$2" | sed -n 's/^max: *//p' | tr -s ' ')
    percpu=$(sed -n '/^ALL:/q; s/^max: *//p' "$2" | tr -s ' ' \
        | awk '{for (i = 2; i <= NF; i += 3) printf "%s ", $i}')
    echo "irq/thr/usr ${all:-none} thr_per_cpu $percpu"
}
for class in $classes; do
    list=$(stress-ng --class "$class?" 2>&1 | sed -n 's/.*stressors: *//p')
    if [ -n "$ONLY" ]; then
        list=$(for s in $list; do case " $ONLY " in *" $s "*) echo "$s" ;; esac; done)
    fi
    if [ -n "$FROM" ]; then
        list=$(echo "$list" | tr ' ' '\n' | sed -n "/^$FROM\$/,\$p" | tr '\n' ' ')
    fi
    echo "class $class: $(echo "$list" | wc -w) stressors"
    for s in $list; do
        case " $EXCLUDE " in *" $s "*) echo "$class/$s: skipped"; continue ;; esac
        before=$(dmesg | wc -l)
        # shellcheck disable=SC2086
        timeout -k 5 $((secs + 30)) stress-ng $STRESS_OPTS --"$s" 0 -t "$secs" \
            > "sng-$s.log" 2>&1 &
        sng=$!
        if [ "$MEASURE" = rtla ]; then
            max=$(measure_rtla "$((secs + 1))" "rtla-$s.txt")
            # rtla's analysis starts with "## CPU N hit stop tracing,
            # analyzing it ##" and ends before the histogram.
            [ -n "$AUTO" ] && grep -q "hit stop tracing" "rtla-$s.txt" \
                && sed -n '/hit stop tracing/,/^# RTLA timerlat histogram/p' \
                    "rtla-$s.txt" | sed "s|^|$class/$s: |"
        else
            cyclictest -q -S -m -p 98 -i 1000 -D "$((secs + 1))" > "ct-$s.txt" 2>&1
            max=$(grep -o 'Max: *[0-9]*' "ct-$s.txt" | tr -s ' ' | cut -d' ' -f2 | tr '\n' ' ')
        fi
        wait "$sng"
        rc=$?
        dmesg | tail -n +"$((before + 1))" > "dmesg-$s.txt"
        new=$(wc -l < "dmesg-$s.txt")
        top=$(sed 's/^\[[ 0-9.]*\] //; s/[0-9][0-9]*/N/g' "dmesg-$s.txt" \
            | sort | uniq -c | sort -rn | head -1 | cut -c1-80)
        echo "$class/$s: max_us $max rc $rc klog $new $top"
        sleep 2
    done
done
echo "hunt done"
