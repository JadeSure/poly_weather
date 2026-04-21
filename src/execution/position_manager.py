def compute_unrealized_pnl(avg_entry_price: float, current_price: float, size: float) -> float:
    return (current_price - avg_entry_price) * size

