from __future__ import annotations

from policies.base import BasePolicy, PolicyContext, RouteCatalog, RouteInfo


class NormalPolicy(BasePolicy):
    name = "normal"

    def blocked_route_ids(self, catalog: RouteCatalog, context: PolicyContext) -> set[str]:
        return set()

    def replacement_route_id(
        self,
        route: RouteInfo,
        catalog: RouteCatalog,
        context: PolicyContext,
        rng,
    ) -> str | None:
        return None

    def restriction_label(self, route: RouteInfo) -> str:
        return "no additional restrictions"
