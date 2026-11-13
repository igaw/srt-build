#!/bin/sh
# cyclictest-trace.sh: catch cyclictest outliers with a trace.
#
# Up to N runs of DURATION of the rt-isolcpus cyclictest test (FIFO 98,
# 1 ms interval, one thread per measured CPU, hackbench on the
# housekeeping CPU) with ftrace on: scheduler, IRQ, softirq, IPI, timer,
# workqueue, RCU and idle events. cyclictest -b stops tracing at the
# first latency above THRESH us; the trace is kept as hunt-<n>.trace.
#
# Usage: ./cyclictest-trace.sh [n [thresh_us [duration]]]
#   CPUS=1-3 HOUSEKEEPING=0 (defaults) select the CPUs
#   LOAD="stress-ng --mutex 0 -t 60" runs this in a loop (on all CPUs)
#   instead of hackbench on the housekeeping CPU
#   OUT=dir puts the results there (default /root)
#
# On a board: srt-build jobs hack <cyclictest job> --minutes 60 \
#     --file contrib/hack/cyclictest-trace.sh \
#     --run "./cyclictest-trace.sh 10 250"
# Found the fair server running normal tasks ahead of cyclictest on
# isolated CPUs without isolcpus=domain (rpi3-64, hack job 241), and
# with LOAD="stress-ng --mutex 0 -t 120" cyclictest's own main thread
# run by the fair server ahead of its FIFO 98 threads (jobs 772, 773).
n=${1:-5}
th=${2:-250}
dur=${3:-3m}
CPUS=${CPUS:-1-3}
HOUSEKEEPING=${HOUSEKEEPING:-0}
threads=$(echo "$CPUS" | awk -F, '{ for (i = 1; i <= NF; i++) {
    m = split($i, r, "-"); t += (m > 1) ? r[2] - r[1] + 1 : 1 } } END { print t }')
T=/sys/kernel/tracing
OUT=${OUT:-/root}
cd /root || exit 1
mkdir -p "$OUT"
for i in $(seq "$n"); do
    echo 0 > $T/tracing_on
    echo > $T/trace
    echo nop > $T/current_tracer
    echo 8192 > $T/buffer_size_kb
    echo > $T/set_event
    for e in sched:sched_switch sched:sched_wakeup sched:sched_waking \
             sched:sched_migrate_task irq:irq_handler_entry irq:irq_handler_exit \
             irq:softirq_entry irq:softirq_exit ipi:ipi_raise ipi:ipi_entry \
             ipi:ipi_exit timer:hrtimer_expire_entry timer:hrtimer_expire_exit \
             timer:hrtimer_start timer:tick_stop workqueue:workqueue_execute_start \
             workqueue:workqueue_execute_end rcu:rcu_utilization power:cpu_idle \
             power:cpu_frequency; do
        echo "$e" >> $T/set_event 2>/dev/null
    done
    echo 1 > $T/tracing_on
    if [ -n "$LOAD" ]; then
        ( while :; do $LOAD >/dev/null 2>&1; sleep 1; done ) &
    else
        ( while :; do taskset -c "$HOUSEKEEPING" hackbench >/dev/null 2>&1; sleep 1; done ) &
    fi
    bg=$!
    sleep 3
    cyclictest -q -p 98 -i 1000 -t "$threads" -a "$CPUS" -D "$dur" -m -b "$th" \
        --tracemark > "$OUT/hunt-$i.txt" 2>&1
    kill "$bg"
    wait "$bg" 2>/dev/null
    # pkill and ps don't work in this rootfs
    for p in /proc/[0-9]*; do
        grep -qE '^(hackbench|stress-ng)' "$p/comm" 2>/dev/null && kill -9 "${p#/proc/}" 2>/dev/null
    done
    sleep 2
    on=$(cat $T/tracing_on)
    echo 0 > $T/tracing_on
    echo "hunt $i uptime $(cut -d' ' -f1 /proc/uptime): $(grep -o 'Max: *[0-9]*' "$OUT/hunt-$i.txt" | tr -s ' ' | tr '\n' ' ')"
    if [ "$on" = 0 ]; then
        cat $T/trace > "$OUT/hunt-$i.trace"
        echo "  stopped above $th us: hunt-$i.trace ($(wc -l < "$OUT/hunt-$i.trace") lines)"
    fi
done
