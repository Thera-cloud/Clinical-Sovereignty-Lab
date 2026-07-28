from broken.api import list_response, looks_fixed


def test_empty_list():
    assert looks_fixed(list_response())
