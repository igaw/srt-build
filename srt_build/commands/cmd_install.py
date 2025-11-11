"""Install command - install kernel to destination."""

from ..core import run_cmd


def add_parser(subparser):
    """Add install command parser."""
    ipsg = subparser.add_parser("install")
    ipsg.add_argument("machine", help="Target machine")
    ipsg.add_argument("--dest")
    ipsg.add_argument("--postfix")
    ipsg.set_defaults(func=cmd_install)
    return ipsg


def cmd_install(ctx):
    """Install kernel to specified destination."""
    dest = "default"
    if ctx.args.dest:
        dest = ctx.args.dest
    postfix = ""
    if ctx.args.postfix:
        postfix = ctx.args.postfix
    cmd = ctx.install[dest]
    cmd = cmd.format(postfix)
    run_cmd(cmd.split(), cwd=ctx.build_path)
