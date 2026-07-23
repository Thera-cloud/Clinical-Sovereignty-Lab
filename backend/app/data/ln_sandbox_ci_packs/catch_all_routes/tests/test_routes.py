from broken.routes import ROUTE_ORDER, health_is_before_catch_all


def test_health_registered_before_catch_all():
    assert health_is_before_catch_all(ROUTE_ORDER)
