def deg2rah(ra: float) -> str:
    """Converts Right Ascension specified in degrees (0..359) to hour
    (0..23.59)"""

    h = int(ra / 15)
    m = int((ra - h * 15) * 4)

    return f"{h}h{m:02d}m ({ra:.02f}deg)"


def hm2deg(h: int, m: int) -> float:
    """Converts Right Ascension expressed as h:m to degrees. This function
    was written by ChatGPT (☉_☉)"""
    return (h + m/60) * 15
