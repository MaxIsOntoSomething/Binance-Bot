from binance.enums import *
from colorama import Fore
import time

class TradeExecutor:
    def __init__(self, binance_client, logger, telegram_handler=None):
        self.client = binance_client
        self.logger = logger
        self.telegram = telegram_handler
        self.price_precision = {}
        self.init_price_precision()
        self.order_type = None
        self.use_percentage = None
        self.trade_amount = None
        self.order_times = {}  # Track order times

    def configure_trading_params(self, order_type, use_percentage, trade_amount):
        self.order_type = order_type
        self.use_percentage = use_percentage
        self.trade_amount = trade_amount

    def init_price_precision(self):
        """Initialize price precision for all symbols"""
        try:
            info = self.client.get_exchange_info()
            for symbol_info in info['symbols']:
                for filter in symbol_info['filters']:
                    if filter['filterType'] == 'PRICE_FILTER':
                        self.price_precision[symbol_info['symbol']] = self.get_precision(filter['tickSize'])
        except Exception as e:
            self.logger.error(f"Error getting price precision: {e}")

    def get_precision(self, tick_size):
        """Get decimal precision from tick size"""
        tick_size_str = f"{float(tick_size):.8f}"
        return len(tick_size_str.split('.')[-1].rstrip('0'))

    def round_price(self, symbol, price):
        """Round price to symbol's precision"""
        precision = self.price_precision.get(symbol, 2)
        return round(float(price), precision)

    def execute_trade(self, symbol, quantity, price, order_type="limit"):
        try:
            # Round price to correct precision
            rounded_price = self.round_price(symbol, price)
            
            if order_type == "limit":
                order = self.client.create_order(
                    symbol=symbol,
                    side=SIDE_BUY,
                    type=ORDER_TYPE_LIMIT,
                    timeInForce=TIME_IN_FORCE_GTC,
                    quantity=quantity,
                    price=str(rounded_price),
                    recvWindow=5000
                )
                
                print(Fore.YELLOW + f"Limit order placed: {symbol}")
                print(Fore.YELLOW + f"Price: {rounded_price}")
                print(Fore.YELLOW + f"Quantity: {quantity}")
                
                # Track order time
                self.order_times[order['orderId']] = time.time()
                
                # Monitor order status
                while True:
                    order_status = self.client.get_order(
                        symbol=symbol,
                        orderId=order['orderId']
                    )
                    if order_status['status'] == 'FILLED':
                        print(Fore.GREEN + f"Order filled: {symbol}")
                        self.logger.info(f"BUY ORDER for {symbol}: {order}")
                        break
                    elif order_status['status'] == 'REJECTED':
                        print(Fore.RED + f"Order rejected: {symbol}")
                        break
                    time.sleep(1)
            else:
                order = self.client.create_order(
                    symbol=symbol,
                    side=SIDE_BUY,
                    type=ORDER_TYPE_MARKET,
                    quantity=quantity,
                    recvWindow=5000
                )
            
            print(Fore.GREEN + f"BUY ORDER for {symbol}: {order}")
            
            if self.telegram:
                self.telegram.send_trade_notification(symbol, order)
                
            return order
            
        except Exception as e:
            self.logger.error(f"Error executing trade for {symbol}: {str(e)}")
            print(Fore.RED + f"Error executing trade for {symbol}: {str(e)}")
            return None

    def cancel_old_orders(self):
        """Cancel limit orders that are older than 8 hours"""
        try:
            open_orders = self.client.get_open_orders()
            current_time = time.time()
            for order in open_orders:
                order_id = order['orderId']
                order_time = self.order_times.get(order_id)
                if order_time and (current_time - order_time) > 8 * 3600:
                    self.client.cancel_order(symbol=order['symbol'], orderId=order_id)
                    print(Fore.RED + f"Cancelled old order: {order['symbol']} (Order ID: {order_id})")
                    self.logger.info(f"Cancelled old order: {order['symbol']} (Order ID: {order_id})")
        except Exception as e:
            self.logger.error(f"Error cancelling old orders: {str(e)}")
            print(Fore.RED + f"Error cancelling old orders: {str(e)}")
