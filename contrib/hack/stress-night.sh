#!/bin/sh
# stress-night.sh: long unattended stress-ng runs under rtla timerlat.
#
# The measurement is rtla timerlat with user-space threads at FIFO 98
# (the stress-ng jobs' settings). A patched rtla in /root/rtla (one that
# locks its threads' memory) is used if present; with the stock rtla the
# user-space column (Usr) stalls on page faults under memory pressure,
# while the kernel-thread column (Thr) still holds. Every result line
# goes to the console, so it survives in the LAVA job log; traces go to
# /root/out (copy them off before the session ends).
#
# Modes:
#   startup N STRESSOR...
#       Does a stressor delay the measurement only while it starts? Per
#       stressor N times each: cyclictest started together with the
#       stressor (as stress-ng-hunt.sh does), cyclictest started 3 s
#       after it, and rtla started together with it; 15 s each.
#   class CLASS MINUTES STOP_US
#       The stress-ng-class job's command in a loop, for MINUTES, under
#       rtla timerlat top -a STOP_US in 10 minute runs. A run that stops
#       prints rtla's auto-analysis (what blocked the timerlat thread)
#       and which stressor was running, and keeps its trace in
#       /root/out/trace-<class>-<n>.txt.
#   hunt SECS CLASS...
#       Every stressor of the classes on its own for SECS (one per CPU)
#       with rtla started together with it; one line per stressor with
#       the max IRQ, Thr and Usr latency per CPU. EXCLUDE as in
#       stress-ng-hunt.sh.
#
# On a board: srt-build jobs hack <stress-ng job> --minutes <run + 10> \
#     --file contrib/hack/stress-night.sh [--file rtla] \
#     --run "./stress-night.sh class scheduler 120 1000"
# Found (jobs 756-777): mutex and schedpolicy starve CFS with FIFO
# threads, and the fair server then runs a CFS task (often rtla's own
# main process) ahead of the FIFO 98 measurement, for up to 95 ms.
mode=$1
shift
cd /root || exit 1
mkdir -p out
RTLA=rtla
if [ ! -x /root/rtla ] && [ -n "$RTLA_URL" ]; then
    u=$RTLA_URL-$(uname -m)
    { curl -sf -o /root/rtla "$u" || wget -q -O /root/rtla "$u"; } 2>/dev/null \
        && chmod +x /root/rtla || rm -f /root/rtla
fi
[ -x /root/rtla ] && RTLA=/root/rtla
# class mode stops on the thread latency: with the stock rtla, measure
# with kernel threads, as its user-space threads stall on page faults
CLASS_MODE=-u
[ "$RTLA" = rtla ] && CLASS_MODE=-k
EXCLUDE=${EXCLUDE:-bigheap brk stack env}
T=/sys/kernel/tracing
X_SCHEDULER=softlockup,cpu-sched,schedmix,cyclic,hrtimers
X_OS=bigheap,brk,stack,env,softlockup,cpu-sched,schedmix,cyclic,hrtimers,acct,led,procfs,loop

up() { cut -d' ' -f1 /proc/uptime; }

ctmax() { grep -o 'Max: *[0-9]*' "$1" | tr -s ' ' | cut -d' ' -f2 | tr '\n' ' '; }

# "max: IRQ Thr Usr" per CPU from rtla timerlat hist output
rtlamax() {
    awk '/^max:/ { for (i = 2; i <= NF; i += 3) printf "%s/%s/%s ", $i, $(i+1), $(i+2) }' "$1"
}

stop_stress() {
    for p in /proc/[0-9]*; do
        grep -qx 'stress-ng.*' "$p/comm" 2>/dev/null && kill -9 "${p#/proc/}" 2>/dev/null
    done
    sleep 3
}

echo "stress-night $mode $*: $(nproc) CPUs, rtla $RTLA ($($RTLA --version 2>&1 | grep -m1 version)), class mode $CLASS_MODE, $(uname -r)"
( while :; do sleep 120; echo "alive $(up)"; done ) &
alive=$!

case $mode in
startup)
    n=$1
    shift
    for s in "$@"; do
        for i in $(seq 1 "$n"); do
            stress-ng --"$s" 0 -t 15 > /dev/null 2>&1 &
            sng=$!
            cyclictest -q -S -m -p 98 -i 1000 -D 16 > ct.txt 2>&1
            wait "$sng"
            a=$(ctmax ct.txt)
            sleep 2
            stress-ng --"$s" 0 -t 18 > /dev/null 2>&1 &
            sng=$!
            sleep 3
            cyclictest -q -S -m -p 98 -i 1000 -D 12 > ct.txt 2>&1
            wait "$sng"
            b=$(ctmax ct.txt)
            sleep 2
            stress-ng --"$s" 0 -t 15 > /dev/null 2>&1 &
            sng=$!
            $RTLA timerlat hist -u -P f:98 -d 16s > tl.txt 2>&1
            wait "$sng"
            c=$(rtlamax tl.txt)
            echo "startup $s $i: ct-sync $a| ct-late $b| rtla-sync irq/thr/usr $c"
            stop_stress
        done
    done
    ;;
class)
    class=$1 minutes=$2 stop=$3
    case $class in
    scheduler) x="-x $X_SCHEDULER" ;;
    os) x="-x $X_OS" ;;
    *) x="" ;;
    esac
    # the job's command, looped as the test-definitions' bg_run.sh does
    # shellcheck disable=SC2086
    ( while :; do stress-ng -v --oom-avoid --temp-path /tmp --class "$class" \
        --seq 0 -t 15 $x; sleep 1; done ) > out/sng-$class.log 2>&1 &
    bg=$!
    end=$(( $(cut -d. -f1 /proc/uptime) + minutes * 60 ))
    n=0
    while [ "$(cut -d. -f1 /proc/uptime)" -lt "$end" ]; do
        n=$((n + 1))
        rm -f timerlat_trace.txt
        $RTLA timerlat top $CLASS_MODE -P f:98 -d 10m -a "$stop" -q \
            -e sched:sched_switch -e sched:sched_wakeup \
            > "out/run-$class-$n.txt" 2>&1
        rc=$?
        at=$(up)
        hog=$(grep 'dispatching hogs' out/sng-$class.log | tail -1 | sed 's/.*hogs: //')
        if [ -f timerlat_trace.txt ]; then
            mv timerlat_trace.txt "out/trace-$class-$n.txt"
            echo "class $class run $n at $at: STOPPED during '$hog', trace-$class-$n.txt"
            sed -n '/auto-analysis/,$p' "out/run-$class-$n.txt" | head -40
        else
            echo "class $class run $n at $at: no stop; $(grep '^ALL' "out/run-$class-$n.txt" | tr -s ' ')"
        fi
    done
    kill "$bg"
    stop_stress
    ;;
hunt)
    secs=$1
    shift
    for class in "$@"; do
        list=$(stress-ng --class "$class?" 2>&1 | sed -n 's/.*stressors: *//p')
        echo "class $class: $(echo "$list" | wc -w) stressors"
        for s in $list; do
            case " $EXCLUDE " in *" $s "*) echo "$class/$s: skipped"; continue ;; esac
            before=$(dmesg | wc -l)
            timeout -k 5 $((secs + 30)) stress-ng --oom-avoid --temp-path /tmp \
                --"$s" 0 -t "$secs" > /dev/null 2>&1 &
            sng=$!
            $RTLA timerlat hist -u -P f:98 -d "$((secs + 1))s" > tl.txt 2>&1
            wait "$sng"
            rc=$?
            new=$(dmesg | tail -n +"$((before + 1))" | wc -l)
            echo "$class/$s: irq/thr/usr $(rtlamax tl.txt)rc $rc klog $new"
            stop_stress
        done
    done
    ;;
*)
    echo "usage: $0 startup|class|hunt ..."
    ;;
esac
kill "$alive"
echo "stress-night $mode done"
