# Tuning the test boards for PREEMPT_RT

This guide explains how the boards in our LAVA lab are set up for
PREEMPT_RT latency testing, why each setting is there, and what we
learned getting there. The goal of the setup is simple: **the same
kernel should give the same results in every test round**, so that a
change in the results means a change in the kernel, not in the lab.

It is written for anyone who sets up a similar lab, adds a board, or
wonders why a setting looks the way it does. The settings themselves
live in `config.yml`, `configs/` and the job templates in `jobs/`; this
file explains them. When you change a setting, update this file in the
same commit.

Numbers in parentheses like (job 474) are LAVA jobs of our lab; a
"round" is one full run of all tests on all boards (`srt-build lava`).

## At a glance

| What | Where | Why |
|---|---|---|
| No RT group scheduling | `configs/config-no-rt-group-sched` | It caused RT throttling on bbb and rpi3-32 |
| Fixed CPU frequency | `configs/config-cpufreq-fixed` | Same speed in every run |
| c2d: watchdog driver built in | `configs/c2d/config-min` | Stops a firmware SMI that froze both CPUs for 1 ms |
| rt-isolcpus: `isolcpus=domain,...` | `config.yml` `flavors` | Keeps normal tasks off the measured CPUs |
| pi-stress: `rcutree.kthread_prio=5` | `jobs/rt/smoke/0006-pi-stress.jinja2` | RCU stalled under pi_stress |
| rt osnoise: fair server off (6.12) | `config.yml` `flavors: rt` | It made osnoise results depend on luck |
| osnoise: 800 ms runtime, rtla on CPU 0 | test-definitions `rtla-osnoise.sh` | Avoids measuring RT throttling and rtla itself |
| bbb: boot retry | `jobs/boards/bbb.yaml` | U-Boot sometimes misses the Ethernet PHY |
| Kernel log check after each test | `jobs/job-base.jinja2` | LAVA only looks for splats during boot |
| stress-ng: some stressors excluded, `--oom-avoid` | `jobs/rt/stress-ng-class/` | They outrank the measurement, hand the CPU to the fair server, or flood the log |
| Report: max latency above 1 ms is a problem | `srt_build/report.py` | A Complete job can still have measured 15 s |
| One boot per flavor, fixed test order | `config.yml` `flavors: combined` | More test time per round, same conditions for every test |
| rtla timerlat: user-space threads, FIFO 98 | test-definitions `rtla-timerlat.sh`, `PRIORITY` in the jobs | Comparable to cyclictest |

## The boards

| Board | Hardware | CPUs | Kernel defconfig | Housekeeping / isolated CPUs |
|---|---|---|---|---|
| bbb | BeagleBone Black, TI AM335x (Cortex-A8) | 1 | `omap2plus_defconfig` | - |
| c2d | PC, Core 2 Duo E8400, Intel ICH7 | 2 | `x86_64_defconfig` | 0 / 1 |
| rpi3-32 | Raspberry Pi 3 B+, 32-bit (ARMv7) | 4 | `bcm2835_defconfig` | 0 / 1-3 |
| rpi3-64 | Raspberry Pi 3 B+, 64-bit (ARMv8) | 4 | arm64 `defconfig` | 0 / 1-3 |

All boards boot over the network (U-Boot or iPXE, TFTP, NFS root) and
load no modules, so everything a test needs must be built into the
kernel. Each test is its own LAVA job: power on, boot, run one test
for one minute with `hackbench` as background load, check the kernel
log, power off.

The tests run in two main flavors that boot **the same rt kernel
image** with different command lines:

- **rt**: no extra arguments. All CPUs are shared by the test and the
  load, like a plain RT system.
- **rt-isolcpus**: CPU 0 does the housekeeping and runs the load, the
  test measures the other CPUs, which are isolated from the scheduler,
  ticks, RCU callbacks and interrupts.

A few smoke-test flavors (`nohz`, `vp`, `ll`, `up`, `lazy`) only check
that other preemption models boot and work.

## Kernel configuration

Every flavor merges a few config fragments onto the board's defconfig
(`config.yml`, `kernel_config`). `srt-build config <board> --check`
shows what each flavor ends up with and which requested options didn't
stick, which is worth running whenever a fragment changes:
`make olddefconfig` silently drops options whose dependencies are
missing.

### For all boards and flavors

**No RT group scheduling** (`configs/config-no-rt-group-sched`). RT
group scheduling gives every cgroup its own RT time budget and
throttles RT tasks that use it up. It is a known source of trouble on
RT systems, and the defconfigs disagree about it: `omap2plus_defconfig`
and `bcm2835_defconfig` turn it on, x86_64 and arm64 `defconfig` don't.
So bbb and rpi3-32 were configured differently from the other two
without anybody choosing that. With it, "sched: RT throttling
activated" showed up in every round on bbb and rpi3-32 under pi-stress
and on rpi3-32 under rtla-osnoise rt-isolcpus (rounds 5-7), and once
rpi3-32 osnoise reported a 532 ms gap (job 367). Since it is off
(round 8 on), no job has throttled.

**Fixed CPU frequency** (`configs/config-cpufreq-fixed`). A CPU that
changes its clock gives different latencies depending on when it last
did. cpufreq stays on, with only the performance governor, so every
CPU runs at one fixed frequency from boot on. Simply turning cpufreq
off is not enough: on x86 `SCHED_MC_PRIO` turns it back on, and
without a cpufreq driver the CPU runs at whatever clock the firmware
left. The drivers have to be built in (bbb `CPUFREQ_DT`, Pis
`ARM_RASPBERRYPI_CPUFREQ`).

### For the rt kernel

`configs/config-base-rt`, `configs/config-rcu`, `configs/rt/config-rt-trace`:

- `PREEMPT_RT`, `HZ=250`.
- `NO_HZ_FULL` and `RCU_NOCB_CPU` built in. They only take effect with
  `nohz_full=` and `rcu_nocbs=` on the command line; without them the
  kernel stops the tick on idle CPUs only. That is why rt and
  rt-isolcpus can share one image.
- The tracers rtla needs (`OSNOISE_TRACER`, `TIMERLAT_TRACER`,
  `HIST_TRIGGERS`), `SCHED_DEBUG` (cyclicdeadline) and `POSIX_MQUEUE`
  (pmqtest; `bcm2835_defconfig` lacks it).
- No lock debugging (`LOCKDEP`, `PROVE_LOCKING`): it changes the very
  latencies we measure. `DEBUG_ATOMIC_SLEEP` stays on.
- `CPU_IDLE` off where possible. x86 (`ACPI_PROCESSOR` selects it) and
  arm64 keep it; c2d's rt-isolcpus limits the C-states with
  `processor.max_cstate=1` instead.
- Debug info via `DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT`: in 6.12,
  `DEBUG_INFO=y` on its own does nothing.

### Per board

`configs/<board>/config-min`:

- **c2d: the ICH7 watchdog driver** (`LPC_ICH`, `ITCO_WDT`). The BIOS
  leaves the chipset's TCO watchdog running, set to raise a System
  Management Interrupt (SMI) when it first expires. That froze both
  CPUs for 0.26-1.1 ms once, about 36 s after boot, which is exactly
  when the tests run, and made every test on c2d look like a broken
  kernel (jobs 21, 79-97). hwlat found a 1076 us gap with interrupts
  off, which only firmware can cause. With the driver, Linux takes over
  the watchdog and the SMI never fires (job 97).
- **rpi3-32: `SMP=y`**. `bcm2835_defconfig` builds a uniprocessor
  kernel, because it also serves the single-core Pi 1.
- **Pis: thermal and hwmon** built in, so heat and undervoltage can be
  ruled out when looking at an outlier.
- **bbb: `RTC_DRV_OMAP`, `CPUFREQ_DT`** built in (modules in the
  defconfig).

## Kernel command line

The flavors' arguments are in `config.yml`, `flavors`; LAVA appends
them to the command line.

**rt-isolcpus**: `nohz_full=<isolated> rcu_nocbs=<isolated>
irqaffinity=<housekeeping> isolcpus=domain,managed_irq,<isolated>
skew_tick=1`, plus `processor.max_cstate=1` on c2d. The load runs on
the housekeeping CPU only (`taskset`). Every rt-isolcpus round also
runs an `isolcpus` job that checks the isolation is really in effect:
few ticks on the isolated CPUs, RCU callbacks offloaded, the default
IRQ affinity, and `/sys/devices/system/cpu/isolated`.

The **`domain`** part matters. Without it (`isolcpus=managed_irq,...`)
the isolated CPUs stay in the scheduler's load balancing, so systemd,
sshd and the test scripts still run there. 6.12's fair server (see
below) then runs those normal tasks ahead of the measuring RT thread:
rpi3-64 cyclictest hit 0.5-1.2 ms in 4 of 10 runs (job 233, traced in
hack job 241). With `domain`, 10 runs stayed below 60 us (job 242), and
in round 6 c2d osnoise went from 158 to 23 us and rpi3-32 timerlat from
837 to 76 us. `domain` is what most RT setups use anyway.

**pi-stress jobs**: `rcutree.kthread_prio=5`. pi_stress busy-loops
threads at SCHED_FIFO priority 1-4. RCU's own threads run at FIFO 1 by
default, so they starved for the whole run and RCU reported a stall
("rcu_preempt self-detected stall", c2d jobs 125 and 260). Running
RCU's threads above pi_stress fixed it (jobs 222-224, every round
since).

## Settings applied at test time

**The fair server is off for rt rtla-osnoise on 6.12** (`config.yml`,
`flavors: rt: fair_server_off`, listed per kernel release and test).
Linux 6.12 added the *fair server*: it reserves 50 ms of every second
for normal tasks, so that RT tasks cannot starve them completely. It
only steps in when normal tasks have not run for most of its period,
and then it runs them ahead of RT tasks.

rtla-osnoise keeps its RT thread busy for 80 % of every second, so on a
shared CPU the background load does starve, and the fair server steps
in. Because its 1 s period and osnoise's 1 s cycle line up differently
in every run, some runs are hit and others not at all: in round 8,
osnoise on the Pis jumped from about 250 us to 1250 and 6882 us, and
reruns of the same job gave 230-2549 us (jobs 554-559). A trace (hack
job 562, rpi3-32) shows it happening: the RT thread `osnoise/2` is
switched out while still runnable, hackbench runs right after
`dl_server_start` for up to 1.5 ms, and `osnoise/2` gets the CPU back
at `dl_server_stop`. On rpi3-64 (hack job 561), 1 of 4 runs with the
fair server hit 4 ms, none of 4 without it.

So the osnoise job sets every CPU's
`/sys/kernel/debug/sched/fair_server/cpu*/runtime` to 0 before the test
and checks that it took. The kernel then logs "Fair server disabled in
CPU N, system may crash due to starvation", which is expected.

All other tests keep the fair server, which is how 6.12 runs out of the
box:

- Their RT threads mostly sleep, so normal tasks never starve and the
  fair server never steps in. With it off for every test (round 9),
  they measured the same as with it on (round 8).
- pi-stress *needs* it. Its threads busy-loop on every CPU; with the
  fair server off, normal tasks got no CPU time at all, a hackbench
  task holding an RCU read lock stalled RCU, and the test shell timed
  out on all four boards (round 9, e.g. c2d job 583).
- rt-isolcpus keeps it, so the fair server is still tested.

Newer kernels have fixes for the fair server (mainline e636ffb9e31b4,
f5a538c07df26 and others, not backported to 6.12); test them before
adding a new release to the list.

**rtla osnoise** (test-definitions `rtla-osnoise.sh`) runs its threads
for 800 ms of every 1 s period (`-r 800000`). With the default 900 ms,
the osnoise threads plus the threaded interrupts exceeded the RT time
limit (`sched_rt_runtime_us`, 950 ms per second), RT throttling paused
the osnoise thread, and osnoise reported that pause as 20-48 ms of
noise (rounds 1-2, rpi3-32). rtla itself runs on the housekeeping CPUs:
it is a normal task, and on a measured CPU its own work showed up as
up to 2.4 ms of noise (rpi3-64 job 68).

## The test round

A round runs each flavor's tests in **one boot**, one after the other,
in a fixed order (`config.yml`, `flavors: <flavor>: combined`). For rt:

| # | Test | Duration | Load |
|---|---|---|---|
| 0 | settle | 30 s | none: the end of the boot is no load to measure under |
| 1 | rtla-timerlat | 5 min | hackbench |
| 2 | rtla-osnoise | 5 min | hackbench (fair server off before, back on after) |
| 3-10 | cyclictest, cyclicdeadline, pmqtest, ptsematest, svsematest, sigwaittest, signaltest, rt-migrate-test | 1 min each | hackbench |
| 11 | rtla-timerlat-stress | 5 min | a fixed stress-ng mix (below) |

rt-isolcpus runs its isolation check, then timerlat and osnoise
(5 min each) and cyclictest (1 min). pi-stress keeps a boot of its
own: it needs `rcutree.kthread_prio` on the command line and takes the
board down when something goes wrong (round 9). The other flavors run
a smoke test each, one boot as before.

Why: a boot per test spent most of a round booting, and one minute
catches a test's worst case only by chance (the 30-40 % spread between
rounds above). A fixed order keeps the conditions the same for every
test in every round: same uptime, same tests before it. The rtla tools
come first and run longest because they show *where* latency comes
from; the rt-tests stayed at one minute, they have rarely shown
anything the others didn't. A kernel log check follows every test, so
a splat is pinned to the test that caused it.

For chasing a strange result, `srt-build lava --split` (or `--tests`)
gives one boot per test again.

**The background load is stopped after each test** (test-definitions
`sh-test-lib`). It used `ps` to find it, which fails in our rootfs
(no NUMA in the kernels), and killing the loop left the running
workload behind. With a boot per test nobody noticed; in one boot it
would have run under all later tests.

**rtla timerlat measures with user-space threads at SCHED_FIFO 98**
(`-u`, `-P f:98`). The user-space latency (`u0-max-latency`, rtla's
"Usr") is the one that compares with cyclictest; the same priority as
cyclictest keeps the two comparable. timerlat also reports the IRQ and
kernel thread latencies (`i*`, `t*`) of the same wakeups.

**rtla-timerlat-stress** runs one instance each of stress-ng's cpu,
vm (10 % of memory), hdd (32 MB, in /tmp), sock, pipe, switch and
fork stressors, all at normal priority, with `--oom-avoid`. The mix
is fixed: the point is the same load every round, not coverage; the
stress round (`--testsuites stress-ng-class`, below) is for coverage.

## Stress tests (stress-ng)

Besides the smoke tests, `--testsuites stress-ng-class` runs one job
per stress-ng class (network, io, os, scheduler, memory, pipe): rtla
timerlat on every CPU for 15 minutes (os: 1 hour) while `stress-ng
--class <class> --seq 0` runs each of the class's stressors in turn,
one instance per CPU. The test definition restarts stress-ng whenever
it finishes, so the load lasts as long as the measurement.
`--testsuites stress-ng` has one job per stressor (373); it is for
narrowing down a class result, not for rounds.

**Some stressors are left out** (`-x` in the os and scheduler jobs).
The first run (pilot, jobs 716-727, still with cyclictest at FIFO 98)
measured 15 s in the scheduler class on bbb and c2d, 48 ms (bbb) and
3.8 ms (c2d) in the os class. Running every stressor of both classes
on its own next to cyclictest (c2d, hack jobs 728/729,
`contrib/hack/stress-ng-hunt.sh`) found the cause:

| Stressor | Max us (c2d) | Why it is excluded |
|---|---|---|
| softlockup | 15330708 | Spins at FIFO 99 to provoke the soft-lockup detector; starves everything below for its whole 15 s slot |
| cpu-sched | 9776 | Gives its tasks random RT and deadline policies |
| hrtimers | 8328 | High-resolution timer flood; worth its own investigation (below) |
| schedmix | 3418 | Mixes RT and deadline policies |
| cyclic | 829 | Its own RT measurement loop, at a high FIFO priority |
| mutex | see below | FIFO threads that never sleep: the fair server then runs normal tasks ahead of the measurement |
| schedpolicy | see below | Same, while its workers switch between FIFO, RR and normal |
| acct, led, procfs, loop | 11-16 | Harmless for latency, but 600-1200 kernel messages each: process accounting, the KVM's USB keyboard LEDs, invalid `/proc/mtrr` writes, loop devices |

A load that runs above the measuring thread's priority measures the
test, not the kernel. All other stressors of the two classes stayed
below 600 us on c2d.

**`--oom-avoid`** for every class: without it the memory stressors in
the os class ran into the OOM killer (bbb job 718, c2d job 724), whose
task dumps fill the console and the log.

**The console flood itself did not cost latency** on c2d: 1231
messages from acct in 15 s left cyclictest at 11 us (the RT kernel
prints from a thread). The stressors are left out for clean logs.

### The fair server under a FIFO load

Round 11 (jobs 730-753, rtla timerlat) still measured 4-185 ms in
the scheduler class and 13-168 ms in the os class on bbb and the Pis,
with the stressors above excluded. No stressor on its own came close.
A night of traced runs on all four boards (hack jobs 755-777,
`contrib/hack/stress-night.sh`, data in `~/lava-runs/night1`) found
the cause:

- The job's own command ran for 2 hours per class and board under
  `rtla timerlat top -a 1000` (stop at 1 ms, keep the trace): 77 stops
  in 130 ten-minute runs. 40 came while **mutex** ran (rpi3-64 up to
  95 ms, rpi3-32 50 ms, c2d 2.3 ms, bbb 1.5 ms), 13 while
  **schedpolicy** ran (up to 3.6 ms), 5 in varyload and workload
  (1.1-1.4 ms). c2d's os class had none.
- In every mutex and schedpolicy stop, the task that kept the FIFO 98
  timerlat thread waiting ran at **normal priority**: mostly rtla's own
  main process (it collects the samples), else console printing
  (`pr/ttyS0`), sshd, systemd or a stress-ng worker. On an RT kernel
  only the fair server runs a normal task ahead of FIFO 98.

What happens: mutex runs two threads per instance that take a shared
lock at random FIFO priorities (1-86) and never sleep; schedpolicy
switches its workers between FIFO, RR and normal while they spin.
Normal tasks get no CPU time, and the fair server (50 ms of every
second, as a deadline task above every FIFO priority) runs whatever
normal task is waiting, for up to its whole 50 ms. That is the fair
server doing its job, not a kernel bug; but a measurement under such a
load measures the fair server. So mutex and schedpolicy are excluded
like the stressors that outrank the measurement directly.

The rest of the night's evidence:

- **On their own they are harmless where nothing else waits**: mutex
  and schedpolicy alone under rtla stayed below 0.2 ms on bbb and the
  Pis (`stress-night.sh hunt`, and on rpi3-64 with the fair server on
  and off, hack job 755, `contrib/hack/stressor-trace.sh`). c2d is the
  exception: mutex alone 2-2.6 ms there.
- **cyclictest has the same problem**: traced runs with mutex
  (`cyclictest-trace.sh` with `LOAD`, jobs 772/773) caught the fair
  server running cyclictest's own main thread ahead of its FIFO 98
  threads for 4-31 ms on rpi3-64, and the console printer, sshd and
  systemd on c2d (2-20 ms). cyclictest's main thread is busy at the
  start of a run, so with cyclictest the hits looked like a startup
  effect. The pilot's per-stressor numbers (cyclictest) therefore
  overstate mutex and hrtimers.
- **With rtla, on their own**, only schedmix (up to 31 ms), cpu-sched
  (7 ms) and cyclic (13 ms on bbb, 6 ms on the Pis) exceed 1 ms on
  bbb and the Pis; on c2d also hrtimers (3.9 ms) and mutex. cyclic
  hurts only while it starts. loadavg leaves rtla without results
  (it starts so many threads that rtla's can't start).
- bbb's 48 ms in the pilot's os class did not come back: with mutex
  in the mix bbb's worst stop was 1.5 ms.

### rtla does not lock its memory

rtla timerlat's user-space threads (`-u`, the column comparable to
cyclictest) are not locked in memory, in 6.12 and in mainline. Under
the memory and io classes their latency went up to 1.9 s in round 11
while the kernel side stayed below 1 ms: the threads waited for page
faults. On rpi3-64 under the memory class (hack job 754,
`contrib/hack/mlock-ab.sh`): rtla 40 ms with 283 major faults,
cyclictest without `-m` 133 ms, with `-m` 0.9 ms, rtla with
`mlockall()` in its user-space threads 0.9 ms and no faults. The fix is
posted upstream (rtla/timerlat: Lock the memory of the user-space
threads). Until a kernel with it is in the lab, read the stress tests'
**Thr** column (kernel side): it does not depend on rtla's memory.

## Board and lab quirks

**bbb: the Ethernet PHY is sometimes missing after power-on.** U-Boot
prints "Could not get PHY for cpsw: addr 0", falls back to USB
networking, and the TFTP download times out (jobs 329, 474). A longer
power-off didn't help (job 474 came after an hour off). Rather than
change U-Boot, LAVA boots bbb a second time if the first boot fails
(`boot_failure_retry: 2` in `jobs/boards/bbb.yaml`); the job timeout
grows by 2 minutes for it. It saved jobs 573 and 647. `jobs report`
shows such jobs as "retried", not as failed, and the dashboard counts
them, so we can see whether it gets worse.

**rpi3-64: kernel arguments didn't arrive.** LAVA's stock device
template for the 64-bit Pi 3 replaced the job's extra kernel arguments
with its own, so before round 5 rpi3-64 silently ran every flavor
without its arguments. The lab's LAVA has a fixed template (sent
upstream as LAVA MR 3577). The `isolcpus` check job catches this kind
of problem now.

**rpi3-32, up flavor**: the kernel warns in `arm_dt_init_cpu_maps`
because the device tree lists 4 CPUs and the kernel is uniprocessor.
Expected; the checks ignore it (`report.KNOWN_KERNEL_WARNINGS`).

**Noise floors.** Each board has an interrupt that sets its lowest
achievable latency in the rt flavor:

- Pis: the dwc2 USB controller's interrupt thread (`irq/..-dwc2_hso`),
  up to 250-380 us. The Pi 3's Ethernet sits on USB, so this interrupt
  never stops.
- bbb: the cpsw Ethernet interrupt thread (`irq/31-4a100000`), up to
  about 400 us.

## Reference results

Round 10 (2026-11-12, v6.12.117-rt23, srt-build 81767ac) is the first
round with every setting above in place and no problems. Max latency
in us, one-minute runs with hackbench:

| Test | bbb | c2d | rpi3-32 | rpi3-64 |
|---|---|---|---|---|
| cyclictest | 155 | 11 | 86 | 112 |
| cyclicdeadline | 166 | 25 | 162 | 165 |
| pmqtest | 131 | 24 | 84 | 108 |
| ptsematest | 123 | 16 | 79 | 93 |
| svsematest | 128 | 22 | 104 | 93 |
| sigwaittest | 152 | 20 | 241 | 178 |
| signaltest | 315 | 44 | 148 | 214 |
| rt-migrate-test | 256 | 50 | 191 | 200 |
| rtla-osnoise | 536 | 30 | 245 | 404 |
| rtla-timerlat | 256 | 20 | 389 | 163 |
| cyclictest rt-isolcpus | - | 9 | 73 | 43 |
| rtla-osnoise rt-isolcpus | - | 17 | 25 | 36 |
| rtla-timerlat rt-isolcpus | - | 22 | 73 | 87 |

**How much variation is normal.** The same kernel on the same boards
gives somewhat different maxima every round: one minute catches the
worst case only by chance. Over rounds 5-10 the max latency of a test
changed by 5-9 % in the median and by up to 30-40 % for one test in ten.
For small values the percentages are larger: c2d going from 12 to
24 us is +100 % but only 12 us. So treat a result as suspicious only
if it is clearly outside both, e.g. more than 40 % *and* more than
20 us above the reference.

rt-migrate-test and signaltest report only the threads that measure a
latency: rt-migrate-test's lowest-priority thread waits for the others
by design (about 20 ms), and signaltest's other threads include thread
0's 10 ms sleep.

## Lessons learned

**Run the same kernel twice before you compare kernels.** Until we
reran an unchanged kernel (rounds 5-7) we did not know how much the
results move on their own, and every change looked like a finding.

**An outlier is either always there or depends on the run.** A stall
at a fixed time after boot on all CPUs (c2d's 36 s) points at firmware;
check with hwlat. A hit that some runs get and others don't, of the
same job, points at a timing interaction (the fair server's period
against the test's), and a single rerun proves nothing either way: the
fair server's effect showed in 1 of 3 reruns.

**Catch it with a trace, not with more runs.** Long runs with tracing
that stop at a threshold (`rtla osnoise hist -s <us> --trace` with
`sched_switch`/`sched_wakeup` events and kprobes on the suspect
functions) caught the fair server in the first five minutes, after
many plain reruns only showed that something was wrong. `srt-build
jobs hack` boots a board like a given job and keeps it for SSH;
`contrib/hack/` has the scripts used (`osnoise-trace.sh`,
`fair-server-ab.sh`, `cyclictest-trace.sh`). The
stop threshold depends on the board: 1 ms suits bbb and the Pis, c2d
needs about 200 us.

**Ask "is it the same on every board?"** RT group scheduling was on for
two boards only because their defconfigs said so. Compare the boards'
configurations, not just their results.

**Check that a setting really arrived.** rpi3-64 ran four rounds
without its kernel arguments, and nobody noticed because the jobs
passed. Every setting should come with a check that fails the job:
the `isolcpus` job checks the isolation, the osnoise job checks the
fair server is off, `kernel-log-clean` checks for splats.

**A global switch has side effects.** Turning the fair server off for
every test fixed osnoise and broke pi-stress. Change the narrowest
thing that fixes the problem.

**Know what your load does before you trust its numbers.** stress-ng
is a kernel stress tool, not a latency workload: some of its stressors
deliberately run at the top RT priority. The scheduler class "measured"
15 s on two boards; one stressor held the CPUs for its 15 s slot.

**A FIFO load that never sleeps measures the fair server.** On 6.12,
when RT threads keep every CPU busy, the fair server runs normal tasks
ahead of every FIFO priority, for up to 50 ms a second. Whatever
normal task is waiting then delays the measurement, often the
measuring tool's own main process. The trace shows it: a task at
priority 120 running while the FIFO 98 thread waits.

**The measuring tool is part of the system.** rtla's user-space
threads stall on page faults because rtla doesn't lock its memory, and
both rtla and cyclictest have a normal-priority main thread the fair
server can run ahead of their measuring threads. Before blaming the
kernel, check what the trace says the tool itself was doing.

**Look at the numbers, not just the job state.** LAVA marked those
jobs Complete, and so did `jobs report` until it learned to flag any
max latency above 1 ms.

**Test your checks.** The kernel log check once matched its own
pattern, echoed to the console, and flagged every job of two rounds;
a name clash in artifact uploads failed 20 uploads in one round. Both
looked like lab problems until we looked closer.

## How we got here

| Round | Date | What happened |
|---|---|---|
| 1-3 | Nov 9-10 | First rounds on v6.12.116-rt22. Fixed osnoise result parsing and RT throttling in osnoise (800 ms runtime, rtla off the measured CPUs). Found c2d's watchdog SMI. |
| 4 | Nov 10 | New baseline: rt idle-tickless with a shared rt/rt-isolcpus image; isolation checks. Found that rpi3-64 never got its kernel arguments. |
| 5 | Nov 11 | v6.12.117-rt23. `isolcpus=domain`, RCU priority for pi-stress. |
| 6-7 | Nov 11 | Same kernel twice: measured the normal variation; kernel log check, parser fix for rt-migrate-test/signaltest, upload name clash fixed. Job 367's 532 ms osnoise gap. |
| 8 | Nov 11 | Kernels rebuilt without RT group scheduling: no more RT throttling. osnoise on the Pis jumped to 1.2-6.9 ms: the fair server. |
| 9 | Nov 12 | Fair server off for every rt test: osnoise fine, pi-stress broke on all boards. First bbb boot retry. |
| 10 | Nov 12 | Fair server off for rt osnoise only. 75 of 75 jobs clean: the reference above. |
| stress-ng pilot | Nov 12 | stress-ng classes on bbb and c2d (jobs 716-727): 15 s, 48 ms, 3.8 ms. Hunted down per stressor (hack jobs 728/729); excluded the stressors that outrank the measurement; measurement switched to rtla timerlat. |
| 11 | Nov 12 | stress-ng classes on all boards with rtla (jobs 730-753): user-space column up to 1.9 s under memory/io (rtla doesn't lock its memory, hack job 754, fix sent upstream); scheduler and os classes still 4-185 ms. |
| stress-ng night | Nov 12-13 | Traced class runs, per-stressor hunts and cyclictest traces on all boards (hack jobs 755-777): the fair server runs normal tasks ahead of FIFO 98 while mutex or schedpolicy spin. Both excluded. |

## Tried, didn't help

- **A periodic tick for rt** (`nohz=off`, rpi3-32, hack jobs 225/226):
  no difference to idle-tickless.
- **A longer power-off for bbb's PHY problem**: it also happened after
  an hour off (job 474).
- **Unplugging the PiKVM keyboard, disabling BIOS legacy USB** (c2d
  stall): no change; it was the watchdog's SMI.
- **Switching the fair server off for every test**: see above.

## Open questions

- rpi3-32 rtla-osnoise rt-isolcpus once reported 532 ms (job 367,
  round 6). It did not come back in 21 tries; RT throttling, gone since
  round 8, is the likely cause.
- Automatic regression checks against the reference, with a threshold
  per board and test as described above.
- stress-ng: varyload and workload stopped class runs at 1.1-1.4 ms
  on the Pis (5 of 130 runs); not traced further. mutex alone on c2d
  (2-2.6 ms) and hrtimers alone on c2d (3.9 ms) only matter if they
  are put back. loadavg leaves rtla without results.
