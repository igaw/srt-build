# Tuning the test boards

What the boards in the LAVA lab need so that PREEMPT_RT test results
are reliable and comparable from round to round: kernel configuration,
kernel command line, runtime settings, and the board quirks found on
the way. Each entry says what was done, why, and the evidence (LAVA
job numbers of this lab, rounds of a full `srt-build` run). Things that
were tried and did not help are listed too, so nobody tries them again
without a new reason.

The settings themselves live in `config.yml`, `configs/` and the job
templates in `jobs/`; this file explains them. Update it together with
them.

## The boards

| Board | SoC / CPU | CPUs | Kernel defconfig | Housekeeping / isolated |
|---|---|---|---|---|
| bbb | BeagleBone Black, TI AM335x (Cortex-A8) | 1 | `omap2plus_defconfig` | - |
| c2d | Core 2 Duo E8400, Intel ICH7 | 2 | `x86_64_defconfig` | 0 / 1 |
| rpi3-32 | Raspberry Pi 3 B+, BCM2837, 32-bit (ARMv7) | 4 | `bcm2835_defconfig` | 0 / 1-3 |
| rpi3-64 | Raspberry Pi 3 B+, BCM2837, 64-bit (ARMv8) | 4 | arm64 `defconfig` | 0 / 1-3 |

All boot over the network (TFTP/iPXE, NFS root) without modules, so
everything a test needs must be built in.

## Kernel configuration

Every flavor merges fragments onto the board's defconfig
(`config.yml` `kernel_config`); `srt-build config <board> --check`
shows what a board's flavors end up with and which requested values
didn't stick.

**All boards, all flavors**

- **No RT group scheduling** (`configs/config-no-rt-group-sched`).
  `omap2plus_defconfig` and `bcm2835_defconfig` enable
  `CONFIG_RT_GROUP_SCHED`, x86_64 and arm64 `defconfig` don't, so bbb
  and rpi3-32 were configured differently from the others. With it,
  bbb and rpi3-32 logged "sched: RT throttling activated" in pi-stress
  and rpi3-32 in rtla-osnoise rt-isolcpus in every round (rounds 5-7);
  rpi3-32 osnoise rt-isolcpus once had a 532 ms gap (job 367). Without
  it (round 8) no job throttles. RT group scheduling is a dangerous
  setting for RT systems in general.

**rt flavors** (`configs/config-base-rt`, `config-rcu`,
`rt/config-rt-trace`)

- `PREEMPT_RT`, `HZ=250`, `NO_HZ_FULL=y` and `RCU_NOCB_CPU=y` built
  in. Without `nohz_full=`/`rcu_nocbs=` on the command line the kernel
  only stops the tick on idle CPUs, so the rt and rt-isolcpus flavors
  share one image and differ only in the command line.
- Tracers for rtla (`OSNOISE_TRACER`, `TIMERLAT_TRACER`,
  `HIST_TRIGGERS`), `SCHED_DEBUG` (cyclicdeadline), `POSIX_MQUEUE`
  (pmqtest; `bcm2835_defconfig` lacks it).
- No lock debugging (`LOCKDEP`, `PROVE_LOCKING`, ...): it changes the
  latencies being measured. `DEBUG_ATOMIC_SLEEP=y` stays.
- `CPU_IDLE` off where possible. It can't be on x86
  (`ACPI_PROCESSOR` selects it) nor arm64; c2d's rt-isolcpus limits
  the C-states on the command line instead (`processor.max_cstate=1`).
- Debug info (`DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT`): `DEBUG_INFO=y`
  alone does nothing in 6.12.

**Fixed CPU frequency, all flavors** (`configs/config-cpufreq-fixed`)

- cpufreq on, performance governor only: every policy is pinned to one
  frequency from boot on. Turning `CPU_FREQ` off is not enough: on x86
  `SCHED_MC_PRIO` selects it, and without a driver the CPU runs at
  whatever clock the firmware left. The cpufreq drivers must be built
  in (bbb `CPUFREQ_DT`, Pis `ARM_RASPBERRYPI_CPUFREQ`).

**Per board** (`configs/<board>/config-min`)

- **c2d: ICH7 TCO watchdog** (`LPC_ICH`, `ITCO_WDT`). The BIOS leaves
  the watchdog running with an SMI on its first expiry: both CPUs
  stall for 0.26-1.1 ms once, about 36 s after boot, just when the
  tests run (jobs 21, 79-97; hwlat saw a 1076 us gap with interrupts
  off). With the driver the timer is taken over and the SMI never
  fires (job 97). Ruled out on the way: the PiKVM USB keyboard, BIOS
  legacy USB storage.
- **rpi3-32: `SMP=y`**: `bcm2835_defconfig` builds a uniprocessor
  kernel (it also serves the single-core Pi 1).
- **Pis: thermal and hwmon** built in, to rule out heat and
  undervoltage in outliers (`thermal_zone0`, firmware warnings).
- **bbb: `RTC_DRV_OMAP`, `CPUFREQ_DT`** built in (modules in
  `omap2plus_defconfig`).

## Kernel command line (flavors)

`config.yml` `flavors`; LAVA adds them as `extra_kernel_args`.

- **rt**: no extra arguments: idle-tickless, every CPU shared by the
  tests and the load.
- **rt-isolcpus**: `nohz_full=<isolated> rcu_nocbs=<isolated>
  irqaffinity=<housekeeping> isolcpus=domain,managed_irq,<isolated>
  skew_tick=1`; the background load (hackbench) runs on the
  housekeeping CPU only (`taskset`), the tests measure the isolated
  CPUs. The jobs check that the isolation is in effect (ticks on the
  isolated CPUs, RCU offloading, IRQ affinity,
  `/sys/devices/system/cpu/isolated`).
  - **`domain` is required.** `isolcpus=managed_irq` alone leaves the
    isolated CPUs in the scheduler domains, so normal tasks (systemd,
    sshd, the test scripts) run there too, and 6.12's fair server runs
    them ahead of the measuring RT thread: rpi3-64 cyclictest hit
    0.5-1.2 ms in 4 of 10 runs (job 233, traced in hack job 241).
    With `domain`: 10 runs below 60 us (job 242); round 6 c2d osnoise
    158 -> 23 us, rpi3-32 timerlat 837 -> 76 us.
- **pi-stress jobs**: `rcutree.kthread_prio=5`. pi_stress busy-loops
  at FIFO 1-4 and starved RCU's kthreads (FIFO 1 by default) for ~21 s:
  "rcu_preempt self-detected stall" on c2d (jobs 125, 260). With RCU's
  kthreads above pi_stress no stall (jobs 222-224, rounds 6-8).

## Runtime settings in the jobs

- **Fair server off for rt on 6.12** (`flavors: rt: fair_server_off`).
  6.12's fair server (`dl_server`, 50 ms per 1 s for normal tasks)
  runs normal tasks ahead of RT tasks when it considers them starved.
  Its 1 s period and the tests' cycles line up differently in each
  run, so some runs are hit and others not: round 8 rtla-osnoise on
  the Pis had hackbench run 1.2-2.4 ms ahead of the FIFO osnoise
  thread in some jobs and in none of others (reruns 554-559). Trace
  (hack job 562, rpi3-32): `osnoise/2` switched out while runnable for
  hackbench right after `dl_server_start`, back at `dl_server_stop`.
  rpi3-64 (hack job 561): with the fair server 1 of 4 runs hit 4 ms,
  without it none of 4. The jobs set every CPU's
  `/sys/kernel/debug/sched/fair_server/cpu*/runtime` to 0 and check it;
  the kernel then logs "Fair server disabled in CPU N, system may crash
  due to starvation", which is expected. rt-isolcpus keeps the fair
  server, so its behaviour is still tested. Newer kernels have fixes
  for it (mainline e636ffb9e31b4, f5a538c07df26 and others, not in
  6.12) and get their own decision.
- **rtla osnoise** (test-definitions `rtla-osnoise.sh`): runtime
  800 ms per 1 s period (`-r 800000`): with the default 900 ms the
  osnoise threads plus the threaded IRQs exceeded the RT runtime limit
  (950 ms), RT throttling stopped the osnoise thread and it reported
  20-48 ms of noise (rounds 1-2, rpi3-32). rtla itself runs on the
  housekeeping CPUs when there are some: as a normal task it otherwise
  shows up as thread noise of up to 2.4 ms (rpi3-64 job 68).

## Board and lab quirks

- **bbb: Ethernet PHY missing after power-on**, now and then: U-Boot
  says "Could not get PHY for cpsw: addr 0", falls back to USB and the
  TFTP download times out (jobs 329, 474; the second after an hour of
  power-off, so not a too short power cycle). The jobs boot bbb twice
  if needed (`boot_failure_retry: 2` in `jobs/boards/bbb.yaml`);
  `jobs report` shows such jobs as "retried". U-Boot is not changed.
- **rpi3-64: kernel arguments**: LAVA's stock `bcm2837-rpi-3-b`
  device template overwrote the job's `extra_kernel_args`, so rpi3-64
  never got the flavor's arguments before round 5. Fixed by a device
  type override in the lab's LAVA (sent upstream as LAVA MR 3577).
- **rpi3-32, up flavor**: "arm_dt_init_cpu_maps" warning (4 CPUs in the
  device tree, uniprocessor kernel). Expected, ignored by the checks
  (`report.KNOWN_KERNEL_WARNINGS`).
- **Pis: USB controller IRQ**: most osnoise noise on the Pis is the
  dwc2 USB interrupt thread (`irq/..-dwc2_hso`, up to ~250 us): the
  Ethernet is on USB. It is the Pis' floor in the rt flavor.
- **bbb: Ethernet IRQ**: the cpsw interrupt thread
  (`irq/31-4a100000`) is bbb's largest osnoise source (up to ~400 us).

## Tried, didn't help

- **Periodic tick for rt** (`nohz=off`, rpi3-32, hack jobs 225/226): no
  difference to idle-tickless; rt stays idle-tickless.
- **Disabling the PiKVM keyboard, BIOS legacy USB** (c2d stall): no
  change; it was the TCO watchdog's SMI.

## What the results look like

Single one-minute runs of the same kernel vary: between rounds 5, 6 and
7 (same kernel) the max latency of a test changed by 5-6 % in the
median and up to 30-35 %. A change well beyond that is worth a look,
anything below is noise. Max latency of the rt flavor in rounds 7 and 8 (v6.12.117-rt23; the
round 8 osnoise values on the Pis were fair server hits, see above):

| Test | bbb | c2d | rpi3-32 | rpi3-64 |
|---|---|---|---|---|
| cyclictest | 156-167 us | 10-12 us | 137-154 us | 108-148 us |
| rtla-osnoise | 697-753 us | 32 us | 251 us (r7) | 266 us (r7) |
| rtla-timerlat | 261-294 us | 21-22 us | 316-337 us | 160-219 us |

rt-migrate-test and signaltest report only the threads that measure
latencies (the lowest-priority rt-migrate-test thread waits by design,
signaltest's other threads include thread 0's sleep).

## Open

- rpi3-32 rtla-osnoise rt-isolcpus 532 ms (job 367, round 6): not
  reproduced in 21 tries; RT throttling (now gone) is the suspect.
- Per-board thresholds for stopping traced runs: 1 ms suits the Pis
  and bbb; c2d needs about 200 us.
