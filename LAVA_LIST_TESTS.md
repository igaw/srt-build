# LAVA List Tests Feature

## Overview

The `lava` command has been extended with a `--list-tests` flag that allows users to view all available test suites and tests without needing to run them or specify a target machine.

## Changes Made

### 1. `srt_build/commands/cmd_lava.py`

#### Added Functions:
- `extract_test_name(test_path, test_file)`: Extracts the test name from a Jinja2 template file by parsing the `job_name` variable
- `list_tests_for_suite(item_path, testsuite)`: Lists all tests within a specific test suite
- `list_available_tests(ctx)`: Main function that displays all test suites and tests organized by flavor

#### Modified Functions:
- `add_parser(subparser)`: Added `--list-tests` flag to the argument parser
- `cmd_lava(ctx, system_config, kernel_config)`: Added handling for the `--list-tests` flag at the beginning of the function

### 2. `srt_build/main.py`

#### Modified Functions:
- `main()`: Added special handling for `lava --list-tests` to:
  - Skip kernel source directory validation
  - Create a minimal context without requiring a valid machine argument
  - Call the lava command with the list-tests flag

## Usage

### List all test suites and tests:
```bash
./srt-build-new lava --list-tests
```

### Filter by specific flavor:
```bash
./srt-build-new lava --list-tests --flavors rt
```

### Filter by specific test suite:
```bash
./srt-build-new lava --list-tests --testsuites smoke
```

### Filter by both flavor and test suite:
```bash
./srt-build-new lava --list-tests --flavors rt --testsuites smoke
```

## Output Format

The output is organized hierarchically:

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
    ...

NOHZ Flavor:
--------------------------------------------------------------------------------
  Test Suite: smoke
    - smoke-tests nohz

...
```

## Implementation Details

### Flavor Discovery
The system searches for test directories in the following flavors:
- rt (Real-Time)
- nohz (No HZ)
- vp (Virtual Processing)
- ll (Low Latency)
- up (Uniprocessor)
- none (No specific flavor)

### Test Suite Discovery
Within each flavor directory, the system looks for subdirectories representing test suites (e.g., `smoke`, `stress-ng`, `stress-ng-class`).

### Test Name Extraction
For each `.jinja2` template file in a test suite:
1. The system attempts to parse the `job_name` variable from the Jinja2 template
2. If parsing fails, it falls back to using the filename (without the `.jinja2` extension)

### Context Creation
When using `--list-tests`:
- No machine argument is required
- A dummy machine context is created temporarily to access the `job_path` configuration
- No kernel source validation is performed
- No LAVA CLI availability check is performed

## Benefits

1. **Discovery**: Users can easily discover what tests are available before running them
2. **Documentation**: Serves as live documentation of the test infrastructure
3. **Filtering**: Users can filter by flavor and test suite to narrow down their view
4. **No Prerequisites**: Works without requiring kernel source or LAVA CLI installation
5. **Fast**: Quickly scans the filesystem without building or submitting anything

## Examples in Help Text

The output includes helpful usage examples:

```
Usage examples:
  # Run smoke tests for rt flavor:
  ./srt-build-new lava <machine> --flavors rt --testsuites smoke

  # Run specific test:
  ./srt-build-new lava <machine> --flavors rt --tests cyclictest
```

## Backward Compatibility

The changes maintain full backward compatibility:
- Existing `lava` commands work exactly as before
- The `machine` argument is optional only when using `--list-tests`
- All other flags and options remain unchanged
