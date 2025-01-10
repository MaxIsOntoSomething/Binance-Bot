import pandas as pd
from strategies.base_strategy import BaseStrategy

class PriceDropStrategy(BaseStrategy):
    def __init__(self, drop_thresholds):
        self.drop_thresholds = sorted(drop_thresholds)  # Sort thresholds in ascending order

    def generate_signals(self, prices, daily_open_price):
        signals = []
        current_price = prices[-1]
        
        drop_percentage = (daily_open_price - current_price) / daily_open_price
        
        for threshold in self.drop_thresholds:
            if drop_percentage >= threshold:
                signals.append((threshold, current_price))
        
        return signals

