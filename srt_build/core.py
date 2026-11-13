"""Core utilities for running commands and managing async operations."""

import logging
from logging import warning, debug, error
import asyncio
import signal
import atexit
import os
import sys
from .config import bcolors


def check_kernel_source_directory():
    """Check if current directory is a Linux kernel source tree."""
    # Check if README starts with "Linux kernel"
    readme_path = "README"
    if os.path.exists(readme_path):
        try:
            with open(readme_path, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                if first_line.startswith("Linux kernel"):
                    return  # Valid kernel source directory
        except Exception:
            pass  # Fall through to error

    # Not a kernel source directory
    print(
        f"{bcolors.FAIL}Error: This does not appear to be a Linux "
        f"kernel source directory.{bcolors.ENDC}"
    )
    print(
        f"\n{bcolors.OKBLUE}Please run this tool from the root of a "
        f"Linux kernel source tree.{bcolors.ENDC}"
    )
    print(f"{bcolors.OKBLUE}Example:{bcolors.ENDC}")
    print("  cd /path/to/linux")
    print("  /path/to/srt-build-new config c2d")
    sys.exit(1)


class LogOutput:
    """Capture stdout and stderr from async subprocess."""

    def __init__(self):
        self.stdout = []
        self.stderr = []

    async def log_stdout(self, line):
        debug(line.rstrip())
        self.stdout.append(line)

    async def log_stderr(self, line):
        error(line.rstrip())
        self.stderr.append(line)


async def _read_stream(stream, callback):
    """Read lines from stream and pass to callback."""
    while True:
        line = await stream.readline()
        try:
            line = line.decode("utf-8")
        except UnicodeDecodeError as err:
            warning("Could not decode line from stream: %s", err)
            continue

        if line:
            await callback(line)
        else:
            break


async def run_cmd_async(cmd, cwd=None):
    """Run command asynchronously and capture output."""
    cmdstr = " ".join(cmd)
    debug("$ %s", cmdstr)

    logo = LogOutput()

    process = await asyncio.create_subprocess_shell(
        cmdstr, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd
    )

    await asyncio.wait(
        [
            asyncio.create_task(_read_stream(process.stdout, logo.log_stdout)),
            asyncio.create_task(_read_stream(process.stderr, logo.log_stderr)),
        ]
    )
    ret = await process.wait()

    return (ret, "".join(logo.stdout))


def run_cmd(cmd, cwd=None):
    """Run command and return exit code and output."""
    debug(cmd)
    try:
        loop = asyncio.get_event_loop()
        (ret, output) = loop.run_until_complete(run_cmd_async(cmd, cwd=cwd))
    except (KeyboardInterrupt, asyncio.CancelledError):
        # Re-raise to let top-level handler deal with it gracefully
        raise KeyboardInterrupt() from None
    except Exception as exc:
        error(f"Exception while running command {cmd}: {exc}")
        return (1, str(exc))
    if ret:
        error(f"Command failed: {cmd} (exit code {ret})")
    return (ret, output)


def interruption():
    """Cancel all async tasks on interruption without noisy output."""
    for task in asyncio.all_tasks():
        task.cancel()


def _atexit_handler():
    """Clean up event loop on exit."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            return
        pending = asyncio.all_tasks(loop)
        if pending:
            for task in pending:
                task.cancel()
            try:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            except Exception as exc:
                warning("Exception during pending task cancellation: %s", exc)
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
    except Exception as exc:
        warning("Exception during atexit event loop shutdown: %s", exc)


def create_logger():
    """Create and configure logger."""
    log = logging.getLogger(__name__)
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    format_str = "%(asctime)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(format_str, date_format)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    log.addHandler(stream_handler)
    return log


def setup(system_config):
    """Set up logging, event loop, and directories."""
    create_logger()
    logging.getLogger("asyncio").setLevel(logging.INFO)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, interruption)
    atexit.register(_atexit_handler)

    # Ensure cache directories exist
    os.makedirs(system_config["base-build-path"], exist_ok=True)
    os.makedirs(system_config["jobfiles-path"], exist_ok=True)
    os.makedirs(system_config["result-path"], exist_ok=True)
