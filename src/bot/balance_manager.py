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

    def print_balance_report(self):
        balance_report = self.get_balance()
        if balance_report:
            print(Fore.BLUE + "Balance Report:")
            for asset, total in balance_report.items():
                print(Fore.BLUE + f"{asset}: {total}")
                self.logger.info(f"Balance: {asset}: {total}")

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
