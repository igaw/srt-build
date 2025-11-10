"""Build command - build kernel and modules."""
import multiprocessing
from logging import error
from ..core import run_cmd
from ..helpers import run_make


def add_parser(subparser):
    """Add build command parser."""
    bpsr = subparser.add_parser('build')
    bpsr.add_argument('machine', help='Target machine')
    bpsr.set_defaults(func=cmd_build)
    bpsr.add_argument('--mods', default=False, action='store_true')
    return bpsr


def cmd_build(ctx):
    """Build kernel, dtbs, and optionally modules."""
    cmd = ['-j' + str(multiprocessing.cpu_count()), ctx.target]
    if ctx.target == 'uImage':
        cmd.append('LOADADDR={}'.format(ctx.loadaddr))
    (ret, _) = run_make(ctx, cmd)
    if ret:
        error('build failed')
        return ret
    if ctx.dtb:
        (ret, _) = run_make(ctx, ['-j' + str(multiprocessing.cpu_count()),
                                        'dtbs'])
        if ret:
            return ret
    if ctx.dtb_cmd:
        (ret, _) = run_cmd(ctx.dtb_cmd.split(), cwd=ctx.build_path)

    if ctx.args.mods:
        cmd = ['-j' + str(multiprocessing.cpu_count()), 'modules']
        (ret, _) = run_make(ctx, cmd)
        if ret:
            error('modules')
            return ret
        (ret, _) = run_make(ctx, ['modules_install'])
        if ret:
            error('module_install failed')
    return ret
