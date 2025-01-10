from abc import ABC, abstractmethod

class BaseStrategy(ABC):
    @abstractmethod
    def generate_signals(self, prices, daily_open_price):
        """
        Generate trading signals based on price data
        Returns: List of tuples (signal_type, price)
        """
        pass
