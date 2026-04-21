def summarize_backtest(total_return: float, win_rate_value: float, max_drawdown: float) -> dict:
    return {
        "total_return": total_return,
        "win_rate": win_rate_value,
        "max_drawdown": max_drawdown,
    }

