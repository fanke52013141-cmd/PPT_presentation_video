from fastapi import APIRouter, FastAPI

from route_inventory import iter_effective_routes


def test_inventory_expands_included_router_paths() -> None:
    child = APIRouter(prefix="/child")

    @child.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    app = FastAPI()
    app.include_router(child, prefix="/api")

    routes = {
        (route.path, route.methods)
        for route in iter_effective_routes(app)
    }
    assert ("/api/child/health", frozenset({"GET"})) in routes

