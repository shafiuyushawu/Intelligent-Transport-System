from __future__ import annotations

from policies.base import BasePolicy, PolicyContext, RouteCatalog, RouteInfo


class HuangPolicy(BasePolicy):
    name = "huang"

    def blocked_route_ids(self, catalog: RouteCatalog, context: PolicyContext) -> set[str]:
        if not context.congestion_state.get("active", False):
            return set()
        return {route.route_id for route in catalog.routes.values() if route.movement != "straight"}

    def replacement_route_id(
        self,
        route: RouteInfo,
        catalog: RouteCatalog,
        context: PolicyContext,
        rng,
    ) -> str | None:
        if route.movement == "straight":
            return None
        return catalog.straight_by_entrance[route.entrance].route_id

    def restriction_label(self, route: RouteInfo) -> str:
        return "ban side-turn movement feeding zone_ab"
