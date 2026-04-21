def win_rate(total_wins: int, total_trades: int) -> float:
    if total_trades <= 0:
        return 0.0
    return total_wins / total_trades

