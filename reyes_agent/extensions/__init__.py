"""ZENO's inspected, permissioned and rollbackable extension lifecycle."""

from reyes_agent.extensions.adapter import AdapterGenerator, ZenoCapabilityAdapter  # noqa: F401
from reyes_agent.extensions.engine import (  # noqa: F401
    CapabilityHunter,
    ExtensionSandbox,
    ExtensionTestRunner,
    ExtensionUpdateManager,
    SelfExtensionEngine,
    get_extension_engine,
)
from reyes_agent.extensions.inspection import (  # noqa: F401
    CompatibilityAnalyzer,
    IntegrationPlanner,
    RepositoryInspector,
    RepositoryStructureAnalyzer,
    UsefulComponentExtractor,
)
from reyes_agent.extensions.registry import (  # noqa: F401
    ExtensionRegistry,
    ExtensionRollbackManager,
)
from reyes_agent.extensions.source import GitHubImportEngine  # noqa: F401

__all__ = [
    "SelfExtensionEngine", "GitHubImportEngine", "RepositoryInspector",
    "RepositoryStructureAnalyzer", "CompatibilityAnalyzer", "IntegrationPlanner",
    "UsefulComponentExtractor", "AdapterGenerator", "ExtensionSandbox",
    "ExtensionTestRunner", "ExtensionRegistry", "ExtensionRollbackManager",
    "ExtensionUpdateManager", "CapabilityHunter", "ZenoCapabilityAdapter",
    "get_extension_engine",
]
