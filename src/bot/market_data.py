import pandas as pd
from datetime import datetime, timezone

class MarketData:
    def __init__(self, binance_client, logger, trading_symbols):
        self.client = binance_client
        self.logger = logger
        self.trading_symbols = trading_symbols

    def get_historical_data(self, symbol, interval, start_str):
        try:
            klines = self.client.get_historical_klines(symbol, interval, start_str)
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_av', 'trades', 'tb_base_av', 'tb_quote_av', 'ignore'
            ])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            self.logger.error(f"Error fetching historical data for {symbol}: {str(e)}")
            return None

    def get_daily_open_price(self, symbol):
        df = self.get_historical_data(symbol, "1d", "1 day ago UTC")
        return float(df['open'].iloc[-1]) if df is not None else None

    def fetch_current_price(self, symbol):
        try:
            ticker = self.client.get_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            self.logger.error(f"Error fetching current price for {symbol}: {str(e)}")
            return None

    def print_daily_open_prices(self):
        for symbol in self.trading_symbols:
            daily_open_price = self.get_daily_open_price(symbol)
            print(f"Daily open price for {symbol} at 00:00 UTC: {daily_open_price}")
            self.logger.info(f"Daily open price for {symbol} at 00:00 UTC: {daily_open_price}")
