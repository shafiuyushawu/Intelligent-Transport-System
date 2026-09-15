from __future__ import annotations

from policies.base import BasePolicy, PolicyContext, RouteCatalog, RouteInfo


class LongPolicy(BasePolicy):
    name = "long"

    def blocked_route_ids(self, catalog: RouteCatalog, context: PolicyContext) -> set[str]:
        if not context.congestion_state.get("active", False):
            return set()
        return {route.route_id for route in catalog.routes.values() if route.movement == "straight"}

    def replacement_route_id(
        self,
        route: RouteInfo,
        catalog: RouteCatalog,
        context: PolicyContext,
        rng,
    ) -> str | None:
        if route.movement != "straight":
            return None
        candidates = [item for item in catalog.by_entrance[route.entrance] if item.movement in {"left", "right"}]
        if not candidates:
            return None
        return self.choose_weighted_route(candidates, rng).route_id

    def restriction_label(self, route: RouteInfo) -> str:
        return "ban straight movement through zone_ab"
