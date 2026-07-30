from broken.names import clean_name


def test_clean_name():
    assert clean_name('  Alice  ') == 'alice'
    assert clean_name('BOB') == 'bob'
