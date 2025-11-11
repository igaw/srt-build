# SRT-Build Refactored Structure

The srt-build tool has been refactored into a modular Python package structure.

## Directory Structure

```
srt-build/
├── srt-build          # Original monolithic script (deprecated)
├── srt-build-new      # New entry point script
├── srt_build/         # Main package directory
│   ├── __init__.py
│   ├── main.py        # Main entry point and argument parser
│   ├── config.py      # Configuration management
│   ├── core.py        # Core utilities (async, logging, command execution)
│   ├── helpers.py     # Helper functions for builds and LAVA jobs
│   ├── results.py     # Result handling and display
│   └── commands/      # Command implementations
│       ├── __init__.py
│       ├── cmd_config.py      # Config command + parser
│       ├── cmd_build.py       # Build command + parser
│       ├── cmd_install.py     # Install command + parser
│       ├── cmd_lava.py        # LAVA command + parser
│       ├── cmd_smoke.py       # Smoke test command + parser
│       ├── cmd_jobs.py        # Jobs parent command + parser
│       ├── cmd_jobs_list.py   # Jobs list subcommand + parser
│       ├── cmd_jobs_results.py # Jobs results subcommand + parser
│       ├── cmd_jobs_compare.py # Jobs compare subcommand + parser
│       ├── cmd_jobs_cancel.py  # Jobs cancel subcommand + parser
│       ├── cmd_kexec.py       # Kexec command + parser
│       └── cmd_all.py         # All command + parser
```

## Key Features

### Modular Design
- Each command is in its own file with its argument parser
- Shared functionality is in helper modules
- Clear separation of concerns

### Package Structure
- `srt_build/config.py` - Configuration loading and management
- `srt_build/core.py` - Core async operations, logging, command execution
- `srt_build/helpers.py` - Build helpers, LAVA job management
- `srt_build/results.py` - Test result parsing and display
- `srt_build/commands/` - All command implementations

### Command Structure
Each command file contains:
1. `add_parser(subparser)` - Defines the argument parser for that command
2. `cmd_<name>(ctx, ...)` - Implements the command logic

## Usage

Use the new entry point:
```bash
./srt-build-new --help
./srt-build-new config <machine>
./srt-build-new build <machine>
./srt-build-new lava <machine>
# etc.
```

## Migration Notes

The old `srt-build` script remains for backwards compatibility but should be considered deprecated.
The new modular structure in `srt_build/` package is the recommended approach going forward.

## Benefits

1. **Easier Testing** - Each module can be tested independently
2. **Better Maintainability** - Clear file organization and separation of concerns
3. **Extensibility** - Easy to add new commands or helpers
4. **Reusability** - Modules can be imported and used by other tools
5. **Type Safety** - Easier to add type hints in the future
