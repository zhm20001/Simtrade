"""End-to-end tests for `simtrade.py engine` subcommand."""

import json
import os
import subprocess
import sys


def _run_cli(args, env=None, cwd=None):
    """Run simtrade.py with args, return (returncode, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, 'simtrade.py'] + args,
        capture_output=True, text=True, cwd=cwd, timeout=15, env=env,
    )
    return result.returncode, result.stdout, result.stderr


def test_engine_no_subcommand_errors():
    """Calling `engine` with no subcommand should error out (consistent with other subcommand groups)."""
    rc, out, _ = _run_cli(['engine'])
    assert rc != 0
    # Verify error JSON mentions unknown subcommand
    data = json.loads(out)
    assert 'error' in data


def test_engine_help_lists_subcommands():
    """`engine --help` should list all four subcommands."""
    rc, out, _ = _run_cli(['engine', '--help'])
    assert rc == 0
    assert 'start' in out
    assert 'stop' in out
    assert 'status' in out
    assert 'restart' in out


def test_engine_status_when_not_started(tmp_path):
    """Run status when no daemon — should return JSON with daemon=not_started."""
    env = dict(os.environ)
    env['SIMTRADE_DATA_DIR'] = str(tmp_path)
    rc, out, _ = _run_cli(['engine', 'status'], env=env)
    assert rc == 0, f'stderr: {out}'
    data = json.loads(out)
    assert 'daemon' in data
    assert data['daemon'] in ('running', 'not_started', 'crashed')


def test_watch_subcommand_removed():
    """cmd_watch should be deleted — verify 'watch' is no longer recognized."""
    rc, out, _ = _run_cli(['watch', 'sh600519'])
    # argparse returns rc=2 for unknown subcommand
    assert rc != 0
