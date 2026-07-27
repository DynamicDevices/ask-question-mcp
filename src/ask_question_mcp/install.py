"""One-command install / host wiring for ask-question-mcp.

Usage (from a clone after ``uv sync``)::

    uv run ask-question-install --host cursor
    uv run ask-question-install --host cursor --skill
    uv run ask-question-install --host print

Writes / merges the stdio MCP server block, optionally installs the agent
skill, and prints reload + ``check_setup`` next steps. Does not enable voice
env URLs unless ``--voice`` is passed (placeholders only).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


SERVER_KEY = "ask-question"
SKILL_NAME = "ask-multiple-choice"


def repo_root() -> Path:
    """Checkout root when running from source; else CWD."""
    here = Path(__file__).resolve()
    # …/src/ask_question_mcp/install.py → parents[2] = repo root
    candidate = here.parents[2]
    if (candidate / "pyproject.toml").is_file() and (
        candidate / "src" / "ask_question_mcp"
    ).is_dir():
        return candidate
    return Path.cwd().resolve()


def find_uv() -> Path | None:
    which = shutil.which("uv")
    if which:
        return Path(which).resolve()
    home = Path.home()
    for p in (
        home / ".local" / "bin" / "uv",
        home / ".cargo" / "bin" / "uv",
        home / ".local" / "bin" / "uv.exe",
    ):
        if p.is_file():
            return p.resolve()
    return None


def skill_source_dir() -> Path | None:
    """Packaged skill or repo ``skills/ask-multiple-choice``."""
    pkg = Path(__file__).resolve().parent / "skills" / SKILL_NAME
    if (pkg / "SKILL.md").is_file():
        return pkg
    repo = repo_root() / "skills" / SKILL_NAME
    if (repo / "SKILL.md").is_file():
        return repo
    return None


def cursor_mcp_path() -> Path:
    if sys.platform == "win32":
        return Path.home() / ".cursor" / "mcp.json"
    return Path.home() / ".cursor" / "mcp.json"


def claude_desktop_mcp_path() -> Path:
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def server_block(
    *,
    uv: Path,
    directory: Path,
    voice: bool,
) -> dict[str, Any]:
    block: dict[str, Any] = {
        "command": str(uv),
        "args": [
            "run",
            "--directory",
            str(directory),
            "ask-question-mcp",
        ],
    }
    if voice:
        block["env"] = {
            "ASK_QUESTION_TTS_URL": os.environ.get(
                "ASK_QUESTION_TTS_URL", "http://127.0.0.1:8200"
            ).strip()
            or "http://127.0.0.1:8200",
            "ASK_QUESTION_STT_URL": os.environ.get(
                "ASK_QUESTION_STT_URL",
                "http://127.0.0.1:8201/transcribe",
            ).strip()
            or "http://127.0.0.1:8201/transcribe",
        }
    return block


def load_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def merge_mcp_servers(path: Path, block: dict[str, Any]) -> dict[str, Any]:
    """Merge ``ask-question`` into ``mcpServers`` (Cursor / Claude Desktop)."""
    data = load_json_object(path)
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers[SERVER_KEY] = block
    data["mcpServers"] = servers
    write_json(path, data)
    return data


def install_skill(*, force: bool = False) -> Path | None:
    src = skill_source_dir()
    if src is None:
        return None
    dest = Path.home() / ".cursor" / "skills" / SKILL_NAME
    if dest.exists() and not force:
        # Refresh SKILL.md in place when present.
        for name in ("SKILL.md", "reference.md"):
            s = src / name
            if s.is_file():
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s, dest / name)
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    for path in src.iterdir():
        if path.is_file():
            shutil.copy2(path, dest / path.name)
    return dest


def run_uv_sync(uv: Path, directory: Path) -> int:
    try:
        proc = subprocess.run(
            [str(uv), "sync"],
            cwd=str(directory),
            check=False,
        )
        return int(proc.returncode)
    except OSError as exc:
        print(f"uv sync failed: {exc}", file=sys.stderr)
        return 1


def print_claude_code_hint(uv: Path, directory: Path) -> None:
    print(
        "Claude Code — run:\n\n"
        f"  claude mcp add --transport stdio {SERVER_KEY} -- \\\n"
        f"    {uv} run --directory {directory} ask-question-mcp\n\n"
        "Or paste the same JSON under mcpServers into project .mcp.json."
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="ask-question-install",
        description=(
            "Wire ask-question-mcp into a desktop MCP host "
            "(Cursor / Claude Desktop) and optionally install the agent skill."
        ),
    )
    p.add_argument(
        "--host",
        choices=("cursor", "claude-desktop", "claude-code", "print"),
        default="cursor",
        help="Which host config to write (default: cursor)",
    )
    p.add_argument(
        "--directory",
        type=Path,
        default=None,
        help="Repo / package directory (default: detect checkout or cwd)",
    )
    p.add_argument(
        "--uv",
        type=Path,
        default=None,
        help="Absolute path to uv (default: search PATH)",
    )
    p.add_argument(
        "--voice",
        action="store_true",
        help="Include TTS/STT env placeholders (or current env URLs) in mcp.json",
    )
    p.add_argument(
        "--skill",
        action="store_true",
        help=f"Install ~/.cursor/skills/{SKILL_NAME} so agents prefer MCQ",
    )
    p.add_argument(
        "--force-skill",
        action="store_true",
        help="Overwrite existing skill files",
    )
    p.add_argument(
        "--no-sync",
        action="store_true",
        help="Skip uv sync",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without writing files",
    )
    args = p.parse_args(argv)

    directory = (args.directory or repo_root()).resolve()
    if not (directory / "pyproject.toml").is_file():
        print(
            f"No pyproject.toml under {directory}. Pass --directory to the clone.",
            file=sys.stderr,
        )
        return 1

    uv = (args.uv or find_uv())
    if uv is None:
        print(
            "uv not found. Install: https://docs.astral.sh/uv/ "
            "then re-run, or pass --uv /absolute/path/to/uv",
            file=sys.stderr,
        )
        return 1
    uv = uv.resolve()

    block = server_block(uv=uv, directory=directory, voice=bool(args.voice))

    print(f"Repo:  {directory}")
    print(f"uv:    {uv}")
    print(f"Host:  {args.host}")
    print(f"Block: {json.dumps({SERVER_KEY: block}, indent=2)}")

    if not args.no_sync and not args.dry_run:
        print("Running uv sync…")
        code = run_uv_sync(uv, directory)
        if code != 0:
            return code

    if args.host == "print":
        print("\nPaste under mcpServers in your host MCP config:")
        print(json.dumps({SERVER_KEY: block}, indent=2))
    elif args.host == "claude-code":
        if args.dry_run:
            print("(dry-run) would print claude mcp add …")
        print_claude_code_hint(uv, directory)
    else:
        path = cursor_mcp_path() if args.host == "cursor" else claude_desktop_mcp_path()
        print(f"Config: {path}")
        if args.dry_run:
            print("(dry-run) skip write")
        else:
            merge_mcp_servers(path, block)
            print(f"Wrote / merged mcpServers.{SERVER_KEY}")

    if args.skill or args.force_skill:
        if args.dry_run:
            print(f"(dry-run) would install skill → ~/.cursor/skills/{SKILL_NAME}")
        else:
            dest = install_skill(force=bool(args.force_skill))
            if dest is None:
                print(
                    f"Skill source missing (expected skills/{SKILL_NAME}/SKILL.md).",
                    file=sys.stderr,
                )
                return 1
            print(f"Skill: {dest}")

    print(
        "\nNext:\n"
        "  1. Reload the host (Cursor: Developer → Reload Window;\n"
        "     Claude Desktop: quit fully and relaunch).\n"
        "  2. Ask the agent to call check_setup, then a smoke ask_multiple_choice.\n"
        "  3. Leave --voice off unless you run TTS/STT; dialogs work text-only.\n"
        "  4. Agents: prefer ask_multiple_choice over markdown A/B/C "
        f"(skill {SKILL_NAME})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
