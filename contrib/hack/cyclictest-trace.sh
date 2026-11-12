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
#
# On a board: srt-build jobs hack <cyclictest job> --minutes 60 \
#     --file contrib/hack/cyclictest-trace.sh \
#     --run "./cyclictest-trace.sh 10 250"
# Found the fair server running normal tasks ahead of cyclictest on
# isolated CPUs without isolcpus=domain (rpi3-64, hack job 241).
n=${1:-5}
th=${2:-250}
dur=${3:-3m}
CPUS=${CPUS:-1-3}
HOUSEKEEPING=${HOUSEKEEPING:-0}
threads=$(echo "$CPUS" | awk -F, '{ for (i = 1; i <= NF; i++) {
    m = split($i, r, "-"); t += (m > 1) ? r[2] - r[1] + 1 : 1 } } END { print t }')
T=/sys/kernel/tracing
cd /root || exit 1
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
    ( while :; do taskset -c "$HOUSEKEEPING" hackbench >/dev/null 2>&1; sleep 1; done ) &
    bg=$!
    cyclictest -q -p 98 -i 1000 -t "$threads" -a "$CPUS" -D "$dur" -m -b "$th" \
        --tracemark > "hunt-$i.txt" 2>&1
    kill "$bg"
    wait "$bg" 2>/dev/null
    pkill hackbench
    sleep 2
    on=$(cat $T/tracing_on)
    echo 0 > $T/tracing_on
    echo "hunt $i uptime $(cut -d' ' -f1 /proc/uptime): $(grep -o 'Max: *[0-9]*' "hunt-$i.txt" | tr -s ' ' | tr '\n' ' ')"
    if [ "$on" = 0 ]; then
        cat $T/trace > "hunt-$i.trace"
        echo "  stopped above $th us: hunt-$i.trace ($(wc -l < "hunt-$i.trace") lines)"
    fi
done
