def passed_threshold(score: float, cutoff: float) -> bool:
    # BUG: '>' excludes a score exactly equal to the cutoff
    return score > cutoff
