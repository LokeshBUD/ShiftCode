def percentage(value, total):
    """Return value as a percentage of total, e.g. percentage(1, 4) -> 25.0."""
    return (value * 100) / total


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def is_even(n):
    return n % 2 == 0
