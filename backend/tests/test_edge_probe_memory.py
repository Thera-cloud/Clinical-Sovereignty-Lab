from app.services.edge_probe_memory import canary_from_path, path_class, pattern_ready


def test_path_classes():
    assert path_class("/.env.prod") == "env"
    assert path_class("/.git/config") == "git"
    assert path_class("/info.php") == "php"
    assert path_class("/wp-config.txt") == "wordpress"
    assert path_class("/.ec/abc") == "canary"
    assert path_class("/privacy.html") == "other"


def test_pattern_needs_a_repeat():
    assert pattern_ready(1, 1) is False
    assert pattern_ready(6, 1) is True
    assert pattern_ready(2, 3) is True


def test_canary_token():
    assert canary_from_path("/.ec/abc-123") == "abc-123"
    assert canary_from_path("/.env") == ""
