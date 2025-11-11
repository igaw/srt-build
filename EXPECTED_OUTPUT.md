# Expected Output Example - lava --list-tests

This shows what users will see when running the new `--list-tests` flag.

## Example 1: List All Tests

Command:
```bash
./srt-build-new lava --list-tests
```

Expected Output:
```
Available Test Suites and Tests:
================================================================================

RT Flavor:
--------------------------------------------------------------------------------
  Test Suite: smoke
    - cyclicdeadline
    - cyclictest
    - pi-stress
    - pmqtest
    - ptsematest
    - rt-migrate-test
    - signaltest
    - sigwaittest
    - svsematest
    - rtla-osnoise
    - rtla-timerlat
  Test Suite: stress-ng
    - stress-ng-access
    - stress-ng-af-alg
    - stress-ng-affinity
    - stress-ng-aio
    - stress-ng-aiol
    - stress-ng-apparmor
    - stress-ng-atomic
    - stress-ng-bad-altstack
    - stress-ng-bad-ioctl
    ... (200+ more tests)
  Test Suite: stress-ng-class
    - stress-ng-class-cpu
    - stress-ng-class-cpu-cache
    - stress-ng-class-device
    - stress-ng-class-filesystem
    - stress-ng-class-interrupt
    - stress-ng-class-io
    - stress-ng-class-memory
    - stress-ng-class-network
    - stress-ng-class-os
    - stress-ng-class-pipe
    - stress-ng-class-scheduler
    - stress-ng-class-security
    - stress-ng-class-vm

NOHZ Flavor:
--------------------------------------------------------------------------------
  Test Suite: smoke
    - smoke-tests nohz

VP Flavor:
--------------------------------------------------------------------------------
  Test Suite: smoke
    - smoke-tests vp

LL Flavor:
--------------------------------------------------------------------------------
  Test Suite: smoke
    - smoke-tests ll

UP Flavor:
--------------------------------------------------------------------------------
  Test Suite: smoke
    - smoke-tests up

NONE Flavor:
--------------------------------------------------------------------------------
  Test Suite: smoke
    - smoke-tests none

================================================================================

Usage examples:
  # Run smoke tests for rt flavor:
  ./srt-build-new lava <machine> --flavors rt --testsuites smoke

  # Run specific test:
  ./srt-build-new lava <machine> --flavors rt --tests cyclictest
```

## Example 2: Filter by Flavor

Command:
```bash
./srt-build-new lava --list-tests --flavors rt
```

Expected Output:
```
Available Test Suites and Tests:
================================================================================

RT Flavor:
--------------------------------------------------------------------------------
  Test Suite: smoke
    - cyclicdeadline
    - cyclictest
    - pi-stress
    - pmqtest
    - ptsematest
    - rt-migrate-test
    - signaltest
    - sigwaittest
    - svsematest
    - rtla-osnoise
    - rtla-timerlat
  Test Suite: stress-ng
    - stress-ng-access
    - stress-ng-af-alg
    ... (200+ more tests)
  Test Suite: stress-ng-class
    - stress-ng-class-cpu
    - stress-ng-class-cpu-cache
    ... (more tests)

================================================================================

Usage examples:
  # Run smoke tests for rt flavor:
  ./srt-build-new lava <machine> --flavors rt --testsuites smoke

  # Run specific test:
  ./srt-build-new lava <machine> --flavors rt --tests cyclictest
```

## Example 3: Filter by Test Suite

Command:
```bash
./srt-build-new lava --list-tests --testsuites smoke
```

Expected Output:
```
Available Test Suites and Tests:
================================================================================

RT Flavor:
--------------------------------------------------------------------------------
  Test Suite: smoke
    - cyclicdeadline
    - cyclictest
    - pi-stress
    - pmqtest
    - ptsematest
    - rt-migrate-test
    - signaltest
    - sigwaittest
    - svsematest
    - rtla-osnoise
    - rtla-timerlat

NOHZ Flavor:
--------------------------------------------------------------------------------
  Test Suite: smoke
    - smoke-tests nohz

VP Flavor:
--------------------------------------------------------------------------------
  Test Suite: smoke
    - smoke-tests vp

LL Flavor:
--------------------------------------------------------------------------------
  Test Suite: smoke
    - smoke-tests ll

UP Flavor:
--------------------------------------------------------------------------------
  Test Suite: smoke
    - smoke-tests up

NONE Flavor:
--------------------------------------------------------------------------------
  Test Suite: smoke
    - smoke-tests none

================================================================================

Usage examples:
  # Run smoke tests for rt flavor:
  ./srt-build-new lava <machine> --flavors rt --testsuites smoke

  # Run specific test:
  ./srt-build-new lava <machine> --flavors rt --tests cyclictest
```

## Example 4: Combined Filter

Command:
```bash
./srt-build-new lava --list-tests --flavors rt --testsuites smoke
```

Expected Output:
```
Available Test Suites and Tests:
================================================================================

RT Flavor:
--------------------------------------------------------------------------------
  Test Suite: smoke
    - cyclicdeadline
    - cyclictest
    - pi-stress
    - pmqtest
    - ptsematest
    - rt-migrate-test
    - signaltest
    - sigwaittest
    - svsematest
    - rtla-osnoise
    - rtla-timerlat

================================================================================

Usage examples:
  # Run smoke tests for rt flavor:
  ./srt-build-new lava <machine> --flavors rt --testsuites smoke

  # Run specific test:
  ./srt-build-new lava <machine> --flavors rt --tests cyclictest
```

## Notes

- Test names are extracted from the `job_name` variable in each Jinja2 template
- If parsing fails, the filename (without .jinja2) is used as the test name
- The output is organized hierarchically: Flavor → Test Suite → Tests
- All tests are displayed in sorted order for easy navigation
- The command works without requiring a machine argument or kernel source
