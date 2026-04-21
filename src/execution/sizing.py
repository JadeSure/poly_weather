def capped_position_size(
    suggested_size_usdc: float,
    max_trade_size_usdc: float,
) -> float:
    return min(suggested_size_usdc, max_trade_size_usdc)

