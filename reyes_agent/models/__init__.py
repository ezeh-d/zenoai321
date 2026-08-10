"""Provider-neutral Phase 3 model facade; existing model_router owns state."""
from reyes_agent.models.gateway import ModelGateway, get_gateway

__all__ = ["ModelGateway", "get_gateway"]
