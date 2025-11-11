#!/usr/bin/env python3
"""
Demonstration script showing expected output of lava --list-tests
This doesn't require the full srt-build environment
"""

import os

jobs_path = "/workspaces/srt-build/jobs"
flavors = ['rt', 'nohz', 'vp', 'll', 'up', 'none']

print("\nAvailable Test Suites and Tests:")
print("=" * 80)

for flavor in flavors:
    flavor_path = os.path.join(jobs_path, flavor)
    if not os.path.exists(flavor_path):
        continue
    
    print(f"\n{flavor.upper()} Flavor:")
    print("-" * 80)
    
    try:
        items = sorted(os.listdir(flavor_path))
    except OSError:
        continue
    
    for item in items:
        item_path = os.path.join(flavor_path, item)
        if not os.path.isdir(item_path):
            continue
        
        print(f"  Test Suite: {item}")
        
        try:
            test_files = sorted([
                f for f in os.listdir(item_path)
                if f.endswith('.jinja2')
            ])
        except OSError:
            continue
        
        # Show just first 5 tests for demo, then count
        for test_file in test_files[:5]:
            test_path = os.path.join(item_path, test_file)
            try:
                with open(test_path, 'r') as f:
                    content = f.read()
                    for line in content.split('\n'):
                        if 'job_name' in line and '=' in line:
                            parts = line.split('=', 1)
                            if len(parts) == 2:
                                value = parts[1].strip()
                                # Remove Jinja2 closing tag if present
                                if '%}' in value:
                                    value = value.split('%}')[0].strip()
                                # Remove quotes (both single and double)
                                value = value.strip("'\"")
                                print(f"    - {value}")
                                break
                    else:
                        name = test_file.replace('.jinja2', '')
                        print(f"    - {name}")
            except Exception:
                name = test_file.replace('.jinja2', '')
                print(f"    - {name}")
        
        if len(test_files) > 5:
            print(f"    ... and {len(test_files) - 5} more tests")
        
print("\n" + "=" * 80)
print(f"\nTotal flavors found: {len([f for f in flavors if os.path.exists(os.path.join(jobs_path, f))])}")
print("\nUsage examples:")
print("  # Run smoke tests for rt flavor:")
print("  ./srt-build-new lava <machine> --flavors rt --testsuites smoke")
print("\n  # Run specific test:")
print("  ./srt-build-new lava <machine> --flavors rt --tests cyclictest")
print()
