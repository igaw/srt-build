# Quick Reference: lava --list-tests

## Command Syntax

```bash
./srt-build-new lava --list-tests [--flavors FLAVOR] [--testsuites SUITE]
```

## Arguments

| Argument | Required | Description | Example |
|----------|----------|-------------|---------|
| `--list-tests` | Yes | Enable test listing mode | `--list-tests` |
| `--flavors` | No | Filter by flavor(s) | `--flavors rt` or `--flavors rt,nohz` |
| `--testsuites` | No | Filter by test suite | `--testsuites smoke` |

## Available Flavors

- `rt` - Real-Time kernel tests (most comprehensive)
- `nohz` - No HZ (tickless) kernel tests
- `vp` - Virtual Processing tests
- `ll` - Low Latency tests
- `up` - Uniprocessor tests
- `none` - No specific flavor

## Common Test Suites

### RT Flavor
- `smoke` - Quick smoke tests (11 tests)
- `stress-ng` - Stress-ng based tests (200+ tests)
- `stress-ng-class` - Class-based stress tests (13 classes)

### Other Flavors
- `smoke` - Basic smoke tests (1 test per flavor)

## Common Use Cases

### 1. Discover All Available Tests
```bash
./srt-build-new lava --list-tests
```

### 2. List RT Tests Only
```bash
./srt-build-new lava --list-tests --flavors rt
```

### 3. List Smoke Tests Across All Flavors
```bash
./srt-build-new lava --list-tests --testsuites smoke
```

### 4. List RT Smoke Tests Only
```bash
./srt-build-new lava --list-tests --flavors rt --testsuites smoke
```

### 5. After Listing, Run a Specific Test
```bash
# First, list to find test name
./srt-build-new lava --list-tests --flavors rt --testsuites smoke

# Then run the specific test
./srt-build-new lava rpi3 --flavors rt --testsuites smoke --tests cyclictest
```

## Key RT Smoke Tests

| Test Name | Description |
|-----------|-------------|
| `cyclictest` | Measure timer latency |
| `cyclicdeadline` | Test deadline scheduler |
| `pi-stress` | Priority inheritance stress test |
| `pmqtest` | POSIX message queue test |
| `ptsematest` | POSIX semaphore test |
| `rt-migrate-test` | RT task migration test |
| `signaltest` | Signal handling latency test |
| `sigwaittest` | Signal wait latency test |
| `svsematest` | SysV semaphore test |
| `rtla-osnoise` | RTLA OS noise detection |
| `rtla-timerlat` | RTLA timer latency analysis |

## Important Notes

1. **No Prerequisites**: This command works without:
   - Machine argument
   - Kernel source directory
   - LAVA CLI installation

2. **Fast Execution**: Only scans filesystem, doesn't build or submit anything

3. **Test Names**: Extracted from Jinja2 template `job_name` variables

4. **Filtering**: Both `--flavors` and `--testsuites` can be combined

5. **Backward Compatible**: Existing `lava` commands work unchanged

## Integration with Other Commands

The list-tests output helps you choose parameters for:

```bash
# Build and run specific flavor/suite
./srt-build-new lava <machine> --flavors <FLAVOR> --testsuites <SUITE>

# Run specific test only
./srt-build-new lava <machine> --flavors <FLAVOR> --tests <TEST_NAME>

# Skip build if already built
./srt-build-new lava <machine> --skip-build --flavors <FLAVOR>
```

## Example Workflow

```bash
# 1. Discover available tests
./srt-build-new lava --list-tests --flavors rt --testsuites smoke

# Output shows: cyclictest, pi-stress, etc.

# 2. Run specific test on your machine
./srt-build-new lava rpi3-64 --flavors rt --testsuites smoke --tests cyclictest

# 3. Check results
./srt-build-new jobs results rpi3-64 <job_id>
```

## Tips

- Use `--flavors rt` to see the most comprehensive test list
- Use `--testsuites smoke` for quick validation tests
- Combine filters to narrow down large test lists
- The `stress-ng` suite has 200+ tests - filter to find what you need
- Test names match what you'll see in LAVA job names
