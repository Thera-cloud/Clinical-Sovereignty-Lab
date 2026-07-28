"""Broken — network call holds DB connection."""

FLOW = ["acquire", "insert", "vectorize", "release"]

def vectorize_after_release(flow=None) -> bool:
    # BUG: vectorize must be after release
    flow = flow if flow is not None else FLOW
    return flow.index("vectorize") > flow.index("release")
