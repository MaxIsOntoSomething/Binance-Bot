# src/bot/binance_client.py

from binance.client import Client

class BinanceClientWrapper:
    def __init__(self, api_key, api_secret, testnet=False):
        self.client = Client(api_key, api_secret, testnet=testnet)
        if testnet:
            self.client.API_URL = 'https://testnet.binance.vision/api'

    def get_lot_size_info(self, symbols):
        lot_size_info = {}
        exchange_info = self.client.get_exchange_info()
        for symbol_info in exchange_info['symbols']:
            if symbol_info['symbol'] in symbols:
                for filter in symbol_info['filters']:
                    if filter['filterType'] == 'LOT_SIZE':
                        lot_size_info[symbol_info['symbol']] = {
                            'minQty': float(filter['minQty']),
                            'maxQty': float(filter['maxQty']),
                            'stepSize': float(filter['stepSize'])
                        }
        return lot_size_info
