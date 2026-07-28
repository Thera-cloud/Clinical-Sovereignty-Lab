from broken.crystallizer import FLOW, vectorize_after_release


def test_order():
    fixed = ["acquire", "insert", "release", "vectorize"]
    assert vectorize_after_release(fixed)
    # also ensure module FLOW itself is fixed for static checks
    assert FLOW.index("vectorize") > FLOW.index("release")
