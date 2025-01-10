from colorama import Fore

class BalanceManager:
    def __init__(self, binance_client, logger, trading_symbols, usdt_reserve):
        self.client = binance_client
        self.logger = logger
        self.trading_symbols = trading_symbols
        self.total_bought = {symbol: 0 for symbol in trading_symbols}
        self.total_spent = {symbol: 0 for symbol in trading_symbols}
        self.total_trades = 0
        self.usdt_reserve = usdt_reserve
        self.previous_balance = {}
        self.last_trade_changes = {}  # Track changes from the last trade
        self.pending_updates = []  # Track pending balance updates
        self.snapshot_balance = None  # Store initial balance before multiple orders

    def get_balance(self):
        try:
            balances = self.client.get_account(recvWindow=5000)['balances']
            balance_report = {}
            for balance in balances:
                asset = balance['asset']
                if asset == 'USDT' or asset in [symbol.replace('USDT', '') for symbol in self.trading_symbols]:
                    free = float(balance['free'])
                    locked = float(balance['locked'])
                    total = free + locked
                    if total > 0:
                        balance_report[asset] = total
            self.logger.info(f"Balance Report: {balance_report}")
            return balance_report
        except Exception as e:
            self.logger.error(f"Error fetching balance: {str(e)}")
            return None

    def take_balance_snapshot(self):
        """Take a snapshot of current balance before multiple orders"""
        self.snapshot_balance = self.get_balance()
        self.pending_updates = []

    def print_balance_report(self, new_order=None):
        """Print balance report with changes from the last trade and fees"""
        try:
            current_balance = self.get_balance()
            if not current_balance:
                return

            if not self.snapshot_balance:
                self.snapshot_balance = current_balance.copy()
                return

            # Store order details for aggregation
            if new_order and new_order.get('status') == 'FILLED':
                self.pending_updates.append(new_order)

            print(Fore.BLUE + "\nBalance Report:")
            
            # Calculate cumulative changes from snapshot
            for asset, total in current_balance.items():
                previous = self.snapshot_balance.get(asset, 0)
                change = total - previous
                
                if total > 0 or change != 0:
                    change_str = f" ({'+' if change > 0 else ''}{change:.8f})" if change != 0 else ""
                    print(Fore.BLUE + f"{asset}: {total:.8f}{change_str}")

            # Show trade details
            if self.pending_updates:
                print(Fore.GREEN + f"\nTrade Summary:")
                total_cost = 0
                total_qty = 0
                symbol = self.pending_updates[0]['symbol']  # Get symbol from first order
                
                for order in self.pending_updates:
                    fills = order.get('fills', [])
                    for fill in fills:
                        qty = float(fill['qty'])
                        price = float(fill['price'])
                        cost = qty * price
                        total_qty += qty
                        total_cost += cost

                if total_qty > 0:
                    avg_price = total_cost / total_qty
                    trading_fee = total_cost * 0.001  # 0.1% trading fee
                    base_asset = symbol.replace('USDT', '')
                    
                    print(Fore.GREEN + f"Added: {total_qty:.8f} {base_asset}")
                    print(Fore.GREEN + f"Average Price: {avg_price:.8f} USDT")
                    print(Fore.GREEN + f"Total Cost: {total_cost:.8f} USDT")
                    print(Fore.YELLOW + f"Trading Fee: {trading_fee:.8f} USDT")
                    print(Fore.GREEN + f"Total Amount Spent: {(total_cost + trading_fee):.8f} USDT")

            # Reset after printing report
            self.snapshot_balance = current_balance.copy()
            self.pending_updates = []

        except Exception as e:
            self.logger.error(f"Error in balance report: {str(e)}")
            print(Fore.RED + f"Error in balance report: {str(e)}")
            print(Fore.RED + f"Order data: {new_order}")

    def update_trade_totals(self, symbol, quantity, price):
        self.total_bought[symbol] += quantity
        self.total_spent[symbol] += quantity * price
        self.total_trades += 1

    def get_profits(self, current_prices):
        profits = {}
        for symbol in self.trading_symbols:
            if self.total_bought[symbol] > 0:
                avg_price = self.total_spent[symbol] / self.total_bought[symbol]
                current_price = current_prices.get(symbol)
                if current_price:
                    profits[symbol] = (current_price - avg_price) * self.total_bought[symbol]
        return profits

    def has_sufficient_balance(self, required_amount):
        """Check if there's enough USDT above reserve"""
        try:
            balance = self.client.get_asset_balance(asset='USDT')
            available_balance = float(balance['free'])
            return available_balance - self.usdt_reserve >= required_amount
        except Exception as e:
            self.logger.error(f"Error checking balance: {str(e)}")
            return False
