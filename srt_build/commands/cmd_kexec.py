"""Kexec command - install and kexec kernel on remote machine."""
import os
from ..core import run_cmd


def add_parser(subparser):
    """Add kexec command parser."""
    kpsg = subparser.add_parser('kexec')
    kpsg.add_argument('machine', help='Target machine')
    kpsg.add_argument('--append', default='')
    kpsg.add_argument('--rootfs', default='')
    kpsg.set_defaults(func=cmd_kexec)
    return kpsg


def cmd_kexec(ctx):
    """Install kernel and kexec on remote machine via SSH."""
    run_cmd(ctx.install['default'].split(), cwd=ctx.build_path)

    ssh_kexec = ['ssh', ctx.hostname]
    if ctx.kexec:
        ssh_kexec += ctx.kexec
    else:
        ssh_kexec += ['kexec']

    rootfs = ctx.rootfs
    if ctx.args.rootfs != '':
        rootfs = ctx.args.rootfs
    cmdline = ctx.cmdline.format(rootfs=rootfs)

    ssh_kexec += ['--append=\\"' + cmdline + ' ' + ctx.args.append + '\\"']

    if ctx.dtb:
        ssh_kexec += ['--dtb=' + '/tmp/' + os.path.basename(ctx.dtb)]
    ssh_kexec += ['/tmp/' + os.path.basename(ctx.image)]

    run_cmd(ssh_kexec)
