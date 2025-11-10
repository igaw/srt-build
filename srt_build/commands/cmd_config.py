"""Config command - configure kernel build."""
from shutil import copyfile
from ..core import run_cmd
from ..helpers import run_make


def add_parser(subparser):
    """Add config command parser."""
    bcpsr = subparser.add_parser('config')
    bcpsr.add_argument('machine', help='Target machine')
    bcpsr.add_argument('--config')
    bcpsr.add_argument('--config-base', default='')
    bcpsr.add_argument('--flavor', default='')
    bcpsr.set_defaults(func=cmd_config)
    return bcpsr


def cmd_config(ctx, kernel_config):
    """Configure kernel build based on machine and flavor settings."""
    if not ctx.args.config:
        run_make(ctx, [ctx.defconfig])
        #run_make(ctx, ['kvmconfig'])

        cfgs = [ctx.config_path + '/' + ctx.config]
        for c in kernel_config.get(ctx.args.config_base, []):
            cfgs += [ctx.config_path + '/' + c]
        if ctx.args.flavor:
            for c in kernel_config.get(ctx.args.flavor, []):
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
        for c in kernel_config[ctx.args.config_base]:
            cfgs += [ctx.config_path + '/' + c]
        for cfg in cfgs:
            run_cmd(['scripts/kconfig/merge_config.sh',
                           '-m', '-O', ctx.build_path,
                           ctx.build_path + '/.config',
                           cfg])
            run_make(ctx, ['olddefconfig'])
