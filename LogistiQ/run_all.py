"""
LogistiQ — run_all.py
FIX: launches ALL 6 agents + API server.
Also accepts --demo flag to fire the crisis scenario automatically.

Usage:
  python run_all.py              # start everything, normal mode
  python run_all.py --demo       # start everything + fire crisis after 3s
  python run_all.py --demo-only  # fire crisis only (agents already running)
"""
import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _python() -> str:
    return sys.executable or "python"


def _all_processes() -> list[tuple[str, list[str]]]:
    py = _python()
    agents_dir = ROOT / "agents"
    return [
        ("api",       [py, "-m", "uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]),
        ("scout",     [py, str(agents_dir / "scout.py")]),
        ("router",    [py, str(agents_dir / "router.py")]),
        ("audit",     [py, str(agents_dir / "audit.py")]),
        ("sentinel",  [py, str(agents_dir / "sentinel.py")]),
        ("arbiter",   [py, str(agents_dir / "arbiter.py")]),
        ("commander", [py, str(agents_dir / "commander.py")]),
    ]


async def _stream(name: str, stream) -> None:
    if stream is None:
        return
    while True:
        line = await stream.readline()
        if not line:
            break
        print(f"[{name}] {line.decode(errors='replace').rstrip()}")


async def _start(name: str, cmd: list[str]) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=os.environ.copy(),
    )


async def _fire_crisis() -> None:
    """Trigger the demo crisis scenario via the simulator."""
    print("\n🚨 Firing crisis scenario in 4 seconds...\n")
    await asyncio.sleep(4)
    py = _python()
    proc = await asyncio.create_subprocess_exec(
        py, str(ROOT / "simulator" / "data_generator.py"), "--crisis",
        cwd=str(ROOT),
        env=os.environ.copy(),
    )
    await proc.wait()
    print("\n✓ Crisis scenario fired. Watch the dashboard at http://localhost:8000\n")


async def main(demo: bool, demo_only: bool) -> None:
    if demo_only:
        await _fire_crisis()
        return

    specs = _all_processes()
    procs: list[tuple[str, asyncio.subprocess.Process]] = []
    tasks: list[asyncio.Task] = []

    for name, cmd in specs:
        p = await _start(name, cmd)
        procs.append((name, p))
        tasks.append(asyncio.create_task(_stream(name, p.stdout)))
        tasks.append(asyncio.create_task(_stream(name, p.stderr)))
        await asyncio.sleep(0.3)  # slight stagger so Redis is ready before agents connect

    print("\n" + "="*55)
    print("  LogistiQ running — all 7 processes started")
    print("  Dashboard: http://localhost:8000")
    print("  Press Ctrl+C to stop all agents")
    print("="*55 + "\n")

    if demo:
        tasks.append(asyncio.create_task(_fire_crisis()))

    try:
        await asyncio.gather(*(p.wait() for _, p in procs))
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        for _, p in procs:
            if p.returncode is None:
                p.terminate()
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run LogistiQ — all 6 agents + API")
    parser.add_argument("--demo",      action="store_true", help="Auto-fire crisis scenario after startup")
    parser.add_argument("--demo-only", action="store_true", help="Only fire crisis (agents already running)")
    args = parser.parse_args()
    try:
        asyncio.run(main(args.demo, args.demo_only))
    except KeyboardInterrupt:
        print("\nStopped.")
