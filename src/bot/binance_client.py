# src/bot/binance_client.py

from binance.client import Client
import math

class BinanceClientWrapper:
    def __init__(self, api_key, api_secret, testnet=False):
        self.client = Client(api_key, api_secret, testnet=testnet)
        if testnet:
            self.client.API_URL = 'https://testnet.binance.vision/api'
        self.lot_size_cache = {}

    def get_lot_size_info(self, symbol):
        """Get lot size filter info for a symbol with caching"""
        if symbol in self.lot_size_cache:
            return self.lot_size_cache[symbol]
            
        try:
            info = self.client.get_exchange_info()
            for symbol_info in info['symbols']:
                if symbol_info['symbol'] == symbol:
                    for filter in symbol_info['filters']:
                        if filter['filterType'] == 'LOT_SIZE':
                            lot_size = {
                                'minQty': float(filter['minQty']),
                                'maxQty': float(filter['maxQty']),
                                'stepSize': float(filter['stepSize'])
                            }
                            self.lot_size_cache[symbol] = lot_size
                            return lot_size
            return None
        except Exception as e:
            print(f"Error getting lot size info: {e}")
            return None

    def get_precision_from_step_size(self, step_size):
        """Get decimal precision from step size"""
        return int(round(-math.log(float(step_size), 10), 0))

    def format_quantity(self, symbol, quantity):
        """Format quantity according to lot size rules"""
        lot_size = self.get_lot_size_info(symbol)
        if not lot_size:
            return None

        step_size = lot_size['stepSize']
        precision = self.get_precision_from_step_size(step_size)
        
        # Round down to the nearest step
        quantity = float(quantity)
        quantity = math.floor(quantity * (1 / float(step_size))) / (1 / float(step_size))
        
        if quantity < lot_size['minQty']:
            print(f"Quantity {quantity} is below minimum {lot_size['minQty']} for {symbol}")
            return None
        if quantity > lot_size['maxQty']:
            print(f"Quantity {quantity} is above maximum {lot_size['maxQty']} for {symbol}")
            return None
            
        return "{:0.{}f}".format(quantity, precision)

    def get_open_orders(self):
        """Get all open orders"""
        try:
            return self.client.get_open_orders()
        except Exception as e:
            print(f"Error getting open orders: {e}")
            return []

    def cancel_order(self, symbol, orderId):
        """Cancel an order"""
        try:
            return self.client.cancel_order(symbol=symbol, orderId=orderId)
        except Exception as e:
            print(f"Error canceling order: {e}")
            return None
