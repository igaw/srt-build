# Summary: LAVA Command Extension - List Tests Feature

## What Was Done

Extended the `lava` command with a `--list-tests` flag that displays all available test suites and tests without requiring a machine argument or kernel source.

## Files Modified

### 1. `/workspaces/srt-build/srt_build/commands/cmd_lava.py`

**Added imports:**
- `import os` (to navigate test directories)

**New functions:**
- `extract_test_name(test_path, test_file)` - Parses Jinja2 templates to extract test names
- `list_tests_for_suite(item_path, testsuite)` - Lists all tests in a specific suite
- `list_available_tests(ctx)` - Main listing function that organizes tests by flavor and suite

**Modified functions:**
- `add_parser(subparser)` - Added `--list-tests` flag with help text
- `cmd_lava(ctx, system_config, kernel_config)` - Added check for `--list-tests` flag at the start

### 2. `/workspaces/srt-build/srt_build/main.py`

**Modified functions:**
- `main()` - Added two key changes:
  1. Skip kernel source validation when `--list-tests` is used
  2. Special handling to create a minimal context for `--list-tests` without requiring a valid machine

## Usage Examples

```bash
# List all available tests
./srt-build-new lava --list-tests

# List tests for specific flavor
./srt-build-new lava --list-tests --flavors rt

# List tests for specific test suite
./srt-build-new lava --list-tests --testsuites smoke

# List tests filtering by both
./srt-build-new lava --list-tests --flavors rt --testsuites stress-ng
```

## Output Structure

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
    - [200+ more tests]
  Test Suite: stress-ng-class
    - [various class-based tests]

NOHZ Flavor:
--------------------------------------------------------------------------------
  Test Suite: smoke
    - smoke-tests nohz

LL Flavor:
--------------------------------------------------------------------------------
  Test Suite: smoke
    - smoke-tests ll

[... more flavors ...]

================================================================================

Usage examples:
  # Run smoke tests for rt flavor:
  ./srt-build-new lava <machine> --flavors rt --testsuites smoke

  # Run specific test:
  ./srt-build-new lava <machine> --flavors rt --tests cyclictest
```

## Key Features

1. **No Prerequisites**: Works without kernel source or LAVA CLI installation
2. **Fast Discovery**: Quickly scans filesystem to show available tests
3. **Filtering**: Can filter by flavor and/or test suite
4. **Intelligent Parsing**: Extracts actual test names from Jinja2 templates
5. **Helpful Output**: Includes usage examples for running the tests
6. **Backward Compatible**: Existing lava commands continue to work unchanged

## Technical Details

### Test Discovery Process
1. Scans the `jobs/` directory for flavor subdirectories (rt, nohz, vp, ll, up, none)
2. Within each flavor, finds test suite subdirectories (smoke, stress-ng, etc.)
3. Lists all `.jinja2` template files in each test suite
4. Extracts the `job_name` variable from each template to display the actual test name

### Context Handling
- When `--list-tests` is used, the system creates a minimal context using a dummy machine
- This allows access to the `job_path` configuration without requiring a valid machine
- The original args are restored to the context to preserve the `--list-tests` flag

### Error Handling
- Gracefully handles missing directories or inaccessible files
- Falls back to filename if test name cannot be parsed from template
- Continues processing even if individual tests fail to parse

## Testing

To test the functionality:

1. Run the basic list command:
   ```bash
   ./srt-build-new lava --list-tests
   ```

2. Try with filters:
   ```bash
   ./srt-build-new lava --list-tests --flavors rt
   ./srt-build-new lava --list-tests --testsuites smoke
   ```

3. Verify backward compatibility:
   ```bash
   ./srt-build-new lava rpi3 --flavors rt --testsuites smoke
   # (This should work as before if machine and kernel are configured)
   ```

## Benefits

- **Improved Discoverability**: Users can explore available tests without documentation
- **Self-Documenting**: The tool itself serves as live documentation
- **Development Aid**: Helpful for test development and debugging
- **CI/CD Integration**: Can be used in scripts to dynamically discover tests
- **User-Friendly**: No need to browse directory structure manually
