#!/usr/bin/env python3
"""
Demo of the --show-jobs feature
This shows how the feature generates job definitions
"""

print("""
================================================================================
LAVA --show-jobs Feature Demo
================================================================================

The new --show-jobs flag generates and displays the actual LAVA job YAML
definitions for a given test suite without submitting them.

USAGE:
------
./srt-build-new lava <machine> --show-jobs [OPTIONS]

OPTIONS:
--------
--flavors FLAVOR       Filter by flavor (default: rt)
--testsuites SUITE     Test suite to generate jobs for (default: smoke)
--tests TEST          Filter by specific test name

EXAMPLES:
---------

1. Show all smoke test jobs for rt flavor:
   ./srt-build-new lava bbb --show-jobs --testsuites smoke

2. Show stress-ng jobs for rt flavor:
   ./srt-build-new lava rpi3-64 --show-jobs --testsuites stress-ng

3. Show specific test job:
   ./srt-build-new lava c2d --show-jobs --testsuites smoke --tests cyclictest

4. Show jobs for multiple flavors:
   ./srt-build-new lava bbb --show-jobs --flavors rt,nohz --testsuites smoke


OUTPUT FORMAT:
--------------
The command will display:
- Machine and flavor information
- Test suite being processed
- For each test:
  * Test name
  * Template file name
  * Full YAML job definition

WHAT IT DOES:
-------------
1. Loads the board configuration for your machine
2. Finds all test templates in the specified test suite
3. Generates the full LAVA job YAML by rendering Jinja2 templates
4. Displays each job definition with separators
5. Shows total count of jobs generated

USE CASES:
----------
- Debug job generation before submission
- Understand what parameters are being used
- Verify test configuration
- Copy job definitions for manual submission
- Learn LAVA job structure

REQUIREMENTS:
-------------
- Machine argument is required (unlike --list-tests)
- Board configuration file must exist in jobs/boards/<machine>.yaml
- Does NOT require kernel source directory
- Does NOT require lavacli to be installed

================================================================================
""")
