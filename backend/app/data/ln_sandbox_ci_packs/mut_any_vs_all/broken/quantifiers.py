def all_positive(nums: list) -> bool:
    # BUG: any() only requires ONE positive number
    return any(n > 0 for n in nums)
