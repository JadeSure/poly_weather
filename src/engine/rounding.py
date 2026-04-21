import math


def celsius_to_fahrenheit(value_c: float) -> float:
    return value_c * 9.0 / 5.0 + 32.0


def fahrenheit_to_celsius(value_f: float) -> float:
    return (value_f - 32.0) * 5.0 / 9.0


def truncate_temperature(value: float) -> int:
    """Drop the fractional component without rounding."""
    return math.trunc(value)


def settlement_temperature(value_c: float, unit: str) -> int:
    if unit.upper() == "C":
        return truncate_temperature(value_c)
    if unit.upper() == "F":
        return truncate_temperature(celsius_to_fahrenheit(value_c))
    raise ValueError(f"Unsupported temperature unit: {unit}")

