"""Broken on purpose — catch-all swallows /health."""

ROUTE_ORDER = [
    ("GET", "/{assessment_id}"),  # catch-all first — BUG
    ("GET", "/health"),
]


def health_is_before_catch_all(order=None) -> bool:
    order = order if order is not None else ROUTE_ORDER
    paths = [p for _, p in order]
    try:
        return paths.index("/health") < paths.index("/{assessment_id}")
    except ValueError:
        return False
