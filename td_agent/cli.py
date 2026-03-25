#!/usr/bin/env python3
"""
Todo Orchestrator Agent — td CLI
"""

import os
import sys
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.status import Status

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

app = typer.Typer(
    name="td",
    help="Todo Orchestrator — natural language task management",
    add_completion=False,
    no_args_is_help=False,
    invoke_without_command=True,
)
console = Console()


# ── Agent setup (lazy) ──────────────────────────────────────────────────────

_agent = None
_session = {"configurable": {"thread_id": "main-session"}}


def _get_agent():
    global _agent
    if _agent is None:
        from langchain_openai import ChatOpenAI
        from langgraph.prebuilt import create_react_agent
        from langgraph.checkpoint.memory import MemorySaver
        from td_agent.tools import tools
        from td_agent.prompts import SYSTEM_PROMPT

        model = ChatOpenAI(model="gpt-4o", temperature=0)
        memory = MemorySaver()
        _agent = create_react_agent(
            model=model,
            tools=tools,
            prompt=SYSTEM_PROMPT,
            checkpointer=memory,
        )
    return _agent


# ── Runner ──────────────────────────────────────────────────────────────────

def run(user_message: str, verbose: bool = False) -> None:
    agent = _get_agent()
    final_text = ""

    with Status("[bold cyan]Thinking...", console=console, spinner="dots"):
        for step in agent.stream(
            {"messages": [{"role": "user", "content": user_message}]},
            config=_session,
            stream_mode="updates",
        ):
            for node, update in step.items():
                if verbose and node == "tools":
                    for msg in update.get("messages", []):
                        if hasattr(msg, "name"):
                            console.print(f"  [dim]tool: {msg.name}[/dim]")

                if node == "agent":
                    for msg in update.get("messages", []):
                        if hasattr(msg, "content") and msg.content:
                            if not getattr(msg, "tool_calls", None):
                                final_text = msg.content

    if final_text:
        console.print()
        console.print(final_text)
        console.print()


# ── Commands ────────────────────────────────────────────────────────────────

@app.callback()
def main(ctx: typer.Context):
    """Todo Orchestrator — natural language task management."""
    # If no subcommand was invoked, drop into interactive mode
    if ctx.invoked_subcommand is None:
        _interactive()


@app.command()
def add(
    task: list[str] = typer.Argument(help="Task description in natural language"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show tool calls"),
):
    """Add a task. Everything after 'add' is the task description."""
    description = " ".join(task)
    if not description:
        console.print("[red]Provide a task description.[/red]")
        raise typer.Exit(1)
    # Make the agent aware of command intent; otherwise it may treat the input
    # as a generic "question" (e.g. "learn backend ...") instead of "add task".
    run(
        "User command: add task.\n"
        f"Task: {description}\n",
        verbose=verbose,
    )


@app.command()
def brief(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show tool calls"),
):
    """Morning briefing — rank all tasks, sticky + notification."""
    run(
        "Run the morning briefing. Get all tasks, compute the pipeline, "
        "send a macOS notification with the top 3, and create a sticky "
        "with the full ranked list.",
        verbose=verbose,
    )


@app.command(name="ls")
def list_tasks(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show tool calls"),
):
    """Show current pipeline — no Mac output."""
    run(
        "Show me the current pipeline. Get all tasks, compute urgency, "
        "and print the ranked list with reasons. No Mac notifications needed.",
        verbose=verbose,
    )


@app.command()
def done(
    task_id: str = typer.Argument(help="Notion page ID of the task to complete"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show tool calls"),
):
    """Mark a task complete and re-rank the pipeline."""
    run(
        f"Mark this task as done: {task_id}. "
        "Then reload all tasks and show me the updated pipeline.",
        verbose=verbose,
    )


@app.command()
def setup():
    """Interactive first-time setup — writes .env file."""
    console.print(
        Panel(
            "[bold]td setup[/bold] — Let's configure your environment.",
            title="Setup Wizard",
            border_style="cyan",
        )
    )

    env_path = os.path.join(_PROJECT_ROOT, ".env")
    existing = {}
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    existing[k.strip()] = v.strip()

    openai_key = Prompt.ask(
        "OpenAI API key",
        default=existing.get("OPENAI_API_KEY", ""),
        password=True,
    )
    notion_key = Prompt.ask(
        "Notion API key",
        default=existing.get("NOTION_API_KEY", ""),
        password=True,
    )
    notion_db = Prompt.ask(
        "Notion Database ID",
        default=existing.get("NOTION_DATABASE_ID", ""),
    )

    with open(env_path, "w") as f:
        f.write(f"OPENAI_API_KEY={openai_key}\n")
        f.write(f"NOTION_API_KEY={notion_key}\n")
        f.write(f"NOTION_DATABASE_ID={notion_db}\n")

    console.print("\n[green bold]Done.[/green bold] .env written.")
    console.print("Run [cyan]td ls[/cyan] to verify your connection.\n")


# ── Interactive mode ────────────────────────────────────────────────────────

def _interactive():
    console.print(
        Panel(
            "[bold]td[/bold] interactive mode. Type tasks or questions. Ctrl+C to exit.",
            border_style="cyan",
        )
    )
    try:
        while True:
            user_input = Prompt.ask("[bold cyan]You[/bold cyan]")
            if user_input.strip():
                run(user_input.strip())
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Bye.[/dim]")
        raise typer.Exit()


if __name__ == "__main__":
    app()
