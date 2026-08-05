"""Concrete specialist agents. Add your own by subclassing Agent."""
from __future__ import annotations

from agents.base import Agent


class Researcher(Agent):
    name = "researcher"
    role = (
        "an internet researcher who finds, cross-checks, and summarizes accurate, "
        "up-to-date information with sources"
    )
    tools = ("web_search", "browse", "read_page")


class Coder(Agent):
    name = "coder"
    role = (
        "a senior software engineer who writes clean, correct, well-structured "
        "code and can scaffold and run projects"
    )
    tools = ("create_project", "write_code", "run_project", "read_file", "write_file")


class Operator(Agent):
    name = "operator"
    role = (
        "a careful desktop operator who controls apps, files, mouse and keyboard "
        "to get things done on the machine, confirming anything destructive"
    )
    tools = ("open_app", "run_command", "gui_click", "gui_type", "screenshot", "list_dir")


class Analyst(Agent):
    name = "analyst"
    role = (
        "a sharp analyst who reasons over information, weighs trade-offs, and "
        "produces clear recommendations and structured breakdowns"
    )
    tools = ()


class Writer(Agent):
    name = "writer"
    role = (
        "a versatile writer who drafts and edits in the requested voice — emails, "
        "docs, posts, summaries — tight and on-brief"
    )
    tools = ()


# registry the orchestrator routes over
ALL_AGENTS = (Researcher, Coder, Operator, Analyst, Writer)
