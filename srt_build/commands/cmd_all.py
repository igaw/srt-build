"""All command - run config, build, and kexec in sequence."""


def add_parser(subparser):
    """Add all command parser."""
    apsg = subparser.add_parser('all')
    apsg.add_argument('machine', help='Target machine')
    apsg.add_argument('--config')
    apsg.add_argument('--config-base', default='')
    apsg.add_argument('--append', default='')
    apsg.add_argument('--flavor', default='')
    apsg.add_argument('--rootfs', default='')
    apsg.set_defaults(func=cmd_all)
    return apsg


def cmd_all(ctx):
    """Run config, build, and kexec commands in sequence."""
    # Import cmd_config, cmd_build, cmd_kexec from other modules
    # cmd_config(ctx)
    # c = cmd_build(ctx)
    # if c:
    #     return
    # cmd_kexec(ctx)
    pass
