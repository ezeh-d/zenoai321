
"""Example REYES plugin. Copy this file and expose can_handle/handle."""
def can_handle(command: str) -> bool:
    return command.lower().strip() == "plugin hello"

def handle(command: str) -> str:
    return "Hello from the REYES plugin system."
