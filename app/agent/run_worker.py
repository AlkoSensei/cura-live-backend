import sys

from livekit.agents import cli

from app.agent.worker import server

if __name__ == "__main__":
    # Typer expects a subcommand (e.g. `start`). Bare `python -m ...` only sets argv[0].
    if len(sys.argv) == 1:
        sys.argv.append("start")
    cli.run_app(server)

