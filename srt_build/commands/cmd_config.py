"""Config command - configure kernel build."""
import os
from shutil import copyfile
from ..core import run_cmd
from ..helpers import run_make
from ..config import bcolors


def add_parser(subparser):
    """Add config command parser."""
    bcpsr = subparser.add_parser('config')
    bcpsr.add_argument('machine', help='Target machine')
    bcpsr.add_argument('--config')
    bcpsr.add_argument('--config-base', default='')
    bcpsr.add_argument('--flavor', default='')
    bcpsr.add_argument(
        '--list',
        action='store_true',
        help='List available configurations and flavors'
    )
    bcpsr.set_defaults(func=cmd_config)
    return bcpsr


def _fmt_bool(ok):
    if ok:
        return f"{bcolors.OKGREEN}yes{bcolors.ENDC}"
    return f"{bcolors.FAIL}no{bcolors.ENDC}"


def _print_table(headers, rows):
    """Render a simple table with headers and rows (list of lists)."""
    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(str(cell)))
    # header
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("  ".join("-" * w for w in widths))
    # rows
    for r in rows:
        print("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)))


def _flavor_for_group(group):
    """Return flavor name for a kernel_config group, if applicable."""
    flavor_groups = {"rt", "nohz", "vp", "ll", "up", "none"}
    return group if group in flavor_groups else ""


def _display_group(group):
    """Human-friendly group label; map empty key to 'base'."""
    return 'base' if group == '' else group


def _list_configs(ctx, kernel_config):
    """Print available machine and flavor configurations from configs dir."""
    print(f"{bcolors.OKBLUE}Configs directory:{bcolors.ENDC} {ctx.config_path}")

    # Machine-specific configs table
    machine_dir = os.path.join(ctx.config_path, ctx.args.machine)
    print(f"\n{bcolors.BOLD}Machine configs for {ctx.args.machine}:{bcolors.ENDC}")
    mrows = []
    if os.path.isdir(machine_dir):
        for name in sorted(os.listdir(machine_dir)):
            path = os.path.join(machine_dir, name)
            exists = os.path.isfile(path)
            size = os.path.getsize(path) if exists else "-"
            mrows.append([name, path, size, _fmt_bool(exists)])
    headers = ["Name", "Path", "Size", "Exists"]
    if mrows:
        _print_table(headers, mrows)
    else:
        _print_table(headers, [])

    # Kernel config groups - grouped display in single table
    print(f"\n{bcolors.BOLD}Kernel config groups:{bcolors.ENDC}")
    
    # Group entries by (config_base, flavor) combination
    from collections import defaultdict
    grouped = defaultdict(list)
    for group, entries in kernel_config.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not entry:
                continue
            flavor = _flavor_for_group(group)
            display_group = _display_group(group)
            key = (display_group, flavor)
            grouped[key].append(entry)
    
    # Build table with Base Config, Flavor, and Fragments columns
    krows = []
    for (config_base, flavor), fragments in sorted(grouped.items()):
        # Join all fragments in one line, comma-separated
        fragments_str = ", ".join(fragments)
        krows.append([config_base, flavor, fragments_str])
    
    _print_table(["Base Config", "Flavor", "Fragments"], krows)


def cmd_config(ctx, kernel_config):
    """Configure kernel build based on machine and flavor settings."""
    if getattr(ctx.args, 'list', False):
        _list_configs(ctx, kernel_config)
        return
    if not getattr(ctx.args, 'config', None):
        run_make(ctx, [ctx.defconfig])
        #run_make(ctx, ['kvmconfig'])

        cfgs = [ctx.config_path + '/' + ctx.config]
        config_base = getattr(ctx.args, 'config_base', '')
        for c in kernel_config.get(config_base, []):
            cfgs += [ctx.config_path + '/' + c]
        flavor = getattr(ctx.args, 'flavor', '')
        if flavor:
            for c in kernel_config.get(flavor, []):
                cfgs += [ctx.config_path + '/' + c]

        for cfg in cfgs:
            run_cmd(['scripts/kconfig/merge_config.sh',
                           '-m', '-O', ctx.build_path,
                           ctx.build_path + '/.config',
                           cfg])
            run_make(ctx, ['olddefconfig'])
    else:
        # use provided config as base
        copyfile(ctx.args.config, ctx.build_path + '/.config')
        # add machine config
        cfgs = [ctx.config_path + '/' + ctx.config]
        config_base = getattr(ctx.args, 'config_base', '')
        for c in kernel_config.get(config_base, []):
            cfgs += [ctx.config_path + '/' + c]
        for cfg in cfgs:
            run_cmd(['scripts/kconfig/merge_config.sh',
                           '-m', '-O', ctx.build_path,
                           ctx.build_path + '/.config',
                           cfg])
            run_make(ctx, ['olddefconfig'])
