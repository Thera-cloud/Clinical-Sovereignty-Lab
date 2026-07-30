from broken.lists import last_element


def test_last_element():
    assert last_element([1, 2, 3]) == 3
    assert last_element(['a', 'b']) == 'b'
