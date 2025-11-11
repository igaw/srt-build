# Summary: LAVA Command Extensions

## Two New Features Added

### 1. `--list-tests` - List Available Tests
Lists all test suites and tests without requiring a machine or kernel.

**Usage:**
```bash
# List all tests
./srt-build-new lava --list-tests

# Filter by flavor
./srt-build-new lava --list-tests --flavors rt

# Filter by test suite
./srt-build-new lava --list-tests --testsuites smoke

# Combined filters
./srt-build-new lava --list-tests --flavors rt --testsuites smoke
```

**Requirements:**
- No machine argument needed
- No kernel source needed
- Fast filesystem scan only

---

### 2. `--show-jobs` - Generate and Display Job Definitions
Generates the actual LAVA job YAML definitions for a test suite.

**Usage:**
```bash
# Show jobs for a test suite (requires machine)
./srt-build-new lava <machine> --show-jobs --testsuites smoke

# Show jobs for specific flavor
./srt-build-new lava bbb --show-jobs --flavors rt --testsuites smoke

# Show specific test job
./srt-build-new lava rpi3-64 --show-jobs --testsuites smoke --tests cyclictest

# Show jobs for multiple flavors
./srt-build-new lava c2d --show-jobs --flavors rt,nohz --testsuites smoke
```

**Requirements:**
- **Machine argument IS REQUIRED** (to load board configuration)
- Board config file must exist: `jobs/boards/<machine>.yaml`
- No kernel source needed
- No lavacli needed

**Output:**
- Machine and flavor information
- Test suite name
- For each test:
  - Test name and template file
  - Full YAML job definition
- Total count of jobs generated

---

## Comparison

| Feature | Machine Required | Kernel Source | Output |
|---------|------------------|---------------|--------|
| `--list-tests` | No | No | Test names organized by flavor/suite |
| `--show-jobs` | **Yes** | No | Full YAML job definitions |
| Normal run | Yes | Yes | Submits jobs to LAVA |

---

## Example Workflow

```bash
# 1. Discover available tests (no machine needed)
./srt-build-new lava --list-tests --flavors rt --testsuites smoke

# 2. Preview job definitions (machine needed)
./srt-build-new lava bbb --show-jobs --testsuites smoke --tests cyclictest

# 3. Run actual tests (builds kernel and submits)
./srt-build-new lava bbb --flavors rt --testsuites smoke --tests cyclictest
```

---

## Use Cases

### `--list-tests` Use Cases:
- Discover what tests are available
- Browse test organization
- Plan test runs
- Quick reference

### `--show-jobs` Use Cases:
- **Debug job generation before submission**
- Verify test parameters for specific machine
- Understand LAVA job structure
- Copy job definitions for manual submission
- Check what will be submitted without actually submitting
- Validate board configuration

---

## Implementation Details

Both features share the same test discovery logic but differ in output:

- **`--list-tests`**: Quick scan, no machine context needed
- **`--show-jobs`**: Full job generation, requires machine-specific board config

The machine requirement for `--show-jobs` is essential because:
1. Board configs are machine-specific (`jobs/boards/bbb.yaml`, etc.)
2. Job definitions include machine-specific details (kernel URL, tags, etc.)
3. Different machines may have different test parameters
