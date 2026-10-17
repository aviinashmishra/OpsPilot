"""Live system first, workspace records for OpsPilot-owned data, refusal for everything else.

When a system family is connected live, every tool call goes through `HybridAdapter`:

* operations the live adapter implements call the real system;
* reads of data that OpsPilot itself owns (price lists, sales teams, policies, consent, its own
  template registry and outbox) are served from the workspace's records, marked
  `"source": "workspace"`. No CRM or helpdesk holds these, so this is the correct source;
* every other operation raises IntegrationNotConfigured. In particular, provider data (tickets,
  contacts, orders…) is never answered from sample data while a system is live, and external
  writes are never faked.
"""

from __future__ import annotations

from typing import Any

from app.integrations.base import BaseAdapter

# (family, method): reads of data that lives in OpsPilot, not in the external system.
WORKSPACE_OWNED: frozenset[tuple[str, str]] = frozenset({
    ("crm", "get_price_list"), ("crm", "get_proposal_templates"), ("crm", "get_sales_teams"), ("crm", "check_consent"),
    ("helpdesk", "get_policies"),
    ("commerce", "get_brand_guidelines"), ("commerce", "get_delivery_policy"), ("commerce", "get_supplier_lead_time"),
    ("email", "list_templates"), ("email", "list_outbox"),
    ("whatsapp", "check_opt_in"), ("whatsapp", "get_conversation"), ("whatsapp", "list_templates"),
})

_BASES = {"_Unsupported", "_LiveBase", "LiveHttpAdapter", "BaseAdapter", "object"}


def live_implements(adapter: Any, method: str) -> bool:
    return any(method in vars(cls) for cls in type(adapter).__mro__ if cls.__name__ not in _BASES)


class HybridAdapter(BaseAdapter):
    mode = "live"

    def __init__(self, live: Any, workspace: Any, family: str) -> None:
        self.live = live
        self.workspace = workspace
        self.family = family
        self.provider = live.provider  # type: ignore[misc]
        self.display_name = live.display_name  # type: ignore[misc]
        self.capabilities = live.capabilities  # type: ignore[misc]

    def test_connection(self) -> Any:
        return self.live.test_connection()

    def verify_action(self, method: str, request: dict[str, Any], external_ref: str | None) -> Any:
        return self.live.verify_action(method, request, external_ref)

    def source_of(self, method: str) -> str:
        """Where a call to `method` is served from: live | workspace | unavailable."""
        if live_implements(self.live, method):
            return "live"
        if (self.family, method) in WORKSPACE_OWNED and hasattr(type(self.workspace), method):
            return "workspace"
        return "unavailable"

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        source = self.source_of(name)
        if source == "workspace":
            fn = getattr(self.workspace, name)

            def from_workspace(*args: Any, **kwargs: Any) -> Any:
                out = fn(*args, **kwargs)
                return {**out, "source": "workspace"} if isinstance(out, dict) else out

            return from_workspace
        return getattr(self.live, name)  # live method, or the live adapter's IntegrationNotConfigured
