# td — Todo Orchestrator Agent

A personal task orchestrator that runs from the terminal on macOS. Type natural language like `td add submit the report by friday it blocks the slides` and the agent parses it, saves it to Notion, re-ranks all pending tasks by urgency, and outputs a sequenced pipeline of what to do next.

The core insight: the agent doesn't just store tasks — it reasons about the whole pile holistically on every interaction, considering deadlines, dependencies between tasks, and urgency signals, then produces a numbered pipeline you execute sequentially. You never have to think about priority yourself.

## Prerequisites

- Python 3.11+
- macOS (for sticky notes and system notifications)
- An [OpenAI API key](https://platform.openai.com/api-keys)
- A [Notion integration](https://www.notion.so/my-integrations) with a connected database

### Notion Database Setup

Create a Notion database with these exact property names and types:

| Property       | Type   | Values / Notes                          |
|----------------|--------|-----------------------------------------|
| Name           | Title  | Task description                        |
| Status         | Select | `todo`, `in_progress`, `done`           |
| Priority       | Select | `critical`, `high`, `medium`, `low`     |
| Deadline       | Date   | Optional                                |
| Urgency Score  | Number | 0–100, written automatically by the agent |
| Depends On     | Text   | Free text naming blocking tasks         |
| Notes          | Text   | Any extra context                       |

Then share the database with your Notion integration.

## Installation

```bash
git clone <your-repo-url> && cd todo-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e . --config-settings editable_mode=compat
```

This installs `td` as a command in your virtual environment. To make it available in every new terminal session, add to your `~/.zshrc`:

```bash
export PATH="$HOME/Documents/dev/agents/todo-agent/.venv/bin:$PATH"
```

## First-Time Setup

Run the setup wizard to configure your API keys:

```bash
td setup
```

This prompts for your OpenAI API key, Notion API key, and Notion Database ID, then writes them to a `.env` file. You can re-run `td setup` at any time to update your configuration.

Alternatively, create `.env` manually:

```
OPENAI_API_KEY=sk-...
NOTION_API_KEY=secret_...
NOTION_DATABASE_ID=<32-char ID from the Notion database URL>
```

## Usage

### Add a task

Everything after `add` is the task description — no quotes needed. The agent parses deadline, priority, and dependencies from natural language.

```bash
td add submit the quarterly report by friday it blocks the slides update
td add review alice pr due today high priority
td add buy oat milk
```

Phrases like "due friday", "by end of week", "high priority", "blocks the slides", and "urgent" are all understood.

After adding, the agent fetches all tasks, re-ranks urgency, and prints the updated pipeline.

### Show the pipeline

```bash
td ls
```

Displays the current ranked task list with urgency scores and reasons. No macOS notifications or sticky notes are created.

### Morning briefing

```bash
td brief
```

Ranks all tasks, sends a macOS notification with the top 3, and creates a desktop sticky note with the full pipeline. Designed to run from a cron job:

```bash
# Add to crontab (crontab -e):
0 9 * * * cd /path/to/todo-agent && .venv/bin/td brief
```

### Mark a task done

```bash
td done <notion-page-id>
```

Marks the task as complete in Notion, then re-ranks the pipeline. Tasks that were blocked by the completed task may move up in priority.

You can find the Notion page ID in the task's URL — it's the 32-character hex string at the end.

### Interactive mode

```bash
td
```

Running `td` with no arguments drops into a conversational REPL. You can keep chatting without re-invoking the command. The agent remembers context within the session.

```
You: I need to submit the report by Friday, it blocks the slides
  Thinking...
[pipeline output]

You: actually make that due Thursday
  Thinking...
[updated pipeline]

You: what should I do first today?
  Thinking...
[recommendation]
```

### Verbose mode

Add `-v` to any command to see which tools the agent is calling:

```bash
td ls -v
td add fix the login bug due monday -v
```

## How Urgency Scoring Works

The agent scores each task from 0 to 100 on every interaction. The scoring considers:

| Signal                          | Score boost |
|---------------------------------|-------------|
| Due today                       | +50         |
| Due tomorrow                    | +40         |
| Due this week                   | +20         |
| No deadline                     | +0          |
| Each task blocked by this one   | +10         |
| Words like "urgent", "critical" | +20         |
| Status is `in_progress`         | +10         |

The LLM does the scoring (not a hardcoded formula) so it can pick up nuance that rules miss — for example, understanding that "blocks the client demo" is more urgent than "blocks the internal doc."

## Architecture

```
td (CLI, Typer)
 └─ LangGraph ReAct agent (GPT-4o)
     ├─ get_current_datetime
     ├─ get_all_tasks          ← reads from Notion
     ├─ add_task_to_notion     ← writes to Notion
     ├─ update_urgency_score   ← writes to Notion
     ├─ complete_task_in_notion← writes to Notion
     ├─ compute_pipeline       ← LLM reasoning prompt
     ├─ create_sticky          ← macOS osascript
     └─ send_notification      ← macOS osascript
```

## File Structure

```
todo-agent/
├── .env                   ← API keys (git-ignored)
├── .gitignore
├── agent.py               ← Thin wrapper so `python agent.py` still works
├── pyproject.toml         ← Package config, makes `td` installable
├── requirements.txt       ← Dependencies
└── td_agent/              ← Main package
    ├── __init__.py
    ├── cli.py             ← Typer app, LangGraph agent setup, run loop
    ├── tools.py           ← All @tool functions (Notion + macOS + reasoning)
    └── prompts.py         ← System prompt defining orchestrator behavior
```

## License

Personal project. Use as you like.
