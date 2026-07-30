def get_setting(cfg: dict, key: str, default=None):
    # BUG: raises KeyError instead of falling back to default
    return cfg[key]
