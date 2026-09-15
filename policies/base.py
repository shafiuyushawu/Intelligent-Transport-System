from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PolicyContext:
    simulation_time: float
    congestion_state: dict[str, Any]
    network_metadata: dict[str, Any]
    vehicle_state: dict[str, Any]
    route_state: dict[str, Any]
    config: dict[str, Any]


@dataclass(frozen=True)
class RouteInfo:
    route_id: str
    entrance: str
    exit: str
    origin_edge: str
    destination_edge: str
    route_edges: tuple[str, ...]
    route_length_m: float
    vehicle_count: int
    raw_weight: float
    normalized_weight: float
    movement: str


@dataclass(frozen=True)
class PolicyAction:
    time_s: float
    policy: str
    vehicle_id: str
    restriction: str
    original_route: str
    replacement_route: str | None
    route_valid: bool
    outcome: str


@dataclass(frozen=True)
class RouteCatalog:
    level: str
    routes: dict[str, RouteInfo]
    by_entrance: dict[str, list[RouteInfo]]
    straight_by_entrance: dict[str, RouteInfo]
    turn_routes_by_entrance: dict[str, list[RouteInfo]]

    @classmethod
    def from_files(cls, metadata_json: str | Path, demand_level: str) -> "RouteCatalog":
        payload = json.loads(Path(metadata_json).read_text(encoding="utf-8"))
        level_payload = payload["mapping"][demand_level]
        routes: dict[str, RouteInfo] = {}
        by_entrance: dict[str, list[RouteInfo]] = {"I": [], "J": [], "K": []}
        for entrance, entries in level_payload.items():
            for entry in entries:
                route = RouteInfo(
                    route_id=str(entry["route_id"]),
                    entrance=str(entry["entrance"]),
                    exit=str(entry["exit"]),
                    origin_edge=str(entry["origin_edge"]),
                    destination_edge=str(entry["destination_edge"]),
                    route_edges=tuple(str(edge) for edge in entry["route_edges"]),
                    route_length_m=float(entry["route_length_m"]),
                    vehicle_count=int(entry["vehicle_count"]),
                    raw_weight=float(entry["weight_raw"]),
                    normalized_weight=float(entry["weight_normalized"]),
                    movement=classify_movement(str(entry["entrance"]), str(entry["exit"])),
                )
                routes[route.route_id] = route
                by_entrance.setdefault(route.entrance, []).append(route)

        straight_by_entrance: dict[str, RouteInfo] = {}
        turn_routes_by_entrance: dict[str, list[RouteInfo]] = {}
        for entrance, items in by_entrance.items():
            turn_routes = [item for item in items if item.movement != "straight"]
            turn_routes_by_entrance[entrance] = turn_routes
            straight_items = [item for item in items if item.movement == "straight"]
            if not straight_items:
                raise ValueError(f"No straight route found for entrance {entrance}")
            straight_by_entrance[entrance] = straight_items[0]

        return cls(
            level=demand_level,
            routes=routes,
            by_entrance=by_entrance,
            straight_by_entrance=straight_by_entrance,
            turn_routes_by_entrance=turn_routes_by_entrance,
        )

    def route(self, route_id: str) -> RouteInfo:
        return self.routes[route_id]

    def route_edges(self, route_id: str) -> list[str]:
        return list(self.routes[route_id].route_edges)


def classify_movement(entrance: str, exit_number: str) -> str:
    index = int(exit_number)
    if index == 4:
        return "straight"
    if entrance in {"I", "J"}:
        return "left" if index < 4 else "right"
    if entrance == "K":
        return "right" if index < 4 else "left"
    raise ValueError(f"Unknown entrance {entrance!r}")


class BasePolicy(ABC):
    name = "base"

    @abstractmethod
    def blocked_route_ids(self, catalog: RouteCatalog, context: PolicyContext) -> set[str]:
        raise NotImplementedError

    @abstractmethod
    def replacement_route_id(
        self,
        route: RouteInfo,
        catalog: RouteCatalog,
        context: PolicyContext,
        rng: Any,
    ) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def restriction_label(self, route: RouteInfo) -> str:
        raise NotImplementedError

    def should_rewrite(self, route: RouteInfo, catalog: RouteCatalog, context: PolicyContext) -> bool:
        return route.route_id in self.blocked_route_ids(catalog, context)

    def choose_weighted_route(self, routes: list[RouteInfo], rng: Any) -> RouteInfo:
        weights = [max(item.raw_weight, 0.0) for item in routes]
        total = sum(weights)
        if total <= 0:
            return routes[0]
        threshold = rng.random() * total
        running = 0.0
        for route, weight in zip(routes, weights):
            running += weight
            if running >= threshold:
                return route
        return routes[-1]
