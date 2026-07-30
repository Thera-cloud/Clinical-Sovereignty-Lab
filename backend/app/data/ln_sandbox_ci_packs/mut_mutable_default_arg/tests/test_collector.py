from broken.collector import append_item


def test_append_item_no_shared_state():
    first = append_item(1)
    second = append_item(2)
    assert first == [1]
    assert second == [2]
