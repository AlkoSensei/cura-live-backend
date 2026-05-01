from livekit.agents import cli

from app.agent.worker import server


if __name__ == "__main__":
    cli.run_app(server)

