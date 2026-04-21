def is_illiquid(total_depth_usdc: float | None, minimum_depth_usdc: float = 50.0) -> bool:
    if total_depth_usdc is None:
        return True
    return total_depth_usdc < minimum_depth_usdc

