

class CoinObject:
    # スレッドセーフでない事に注意

    def __init__(self, coin_id=None, amount=None, coins=None):
        if amount:
            self.coins = {coin_id: amount}
        elif coins:
            self.coins = coins
        else:
            self.coins = dict()

    def __repr__(self):
        coin = ", ".join("{}={}".format(coin_id, amount) for coin_id, amount in self.coins.items())
        return "<Coins {}>".format(coin)

    def is_all_plus_amount(self):
        for v in self.coins.values():
            if v < 0:
                return False
        return True

    def is_all_minus_amount(self):
        for v in self.coins.values():
            if v > 0:
                return False
        return True

    def copy(self):
        coins = CoinObject()
        coins.coins = self.coins.copy()
        return coins

    def reverse_amount(self):
        for coin_id, amount in self.coins.items():
            self.coins[coin_id] = -1 * amount

    def __setitem__(self, key, value):
        self.coins[key] = value

    def __getitem__(self, item):
        if item in self.coins:
            return self.coins[item]
        return 0

    def __delitem__(self, key):
        if key in self.coins:
            del self.coins[key]

    def __add__(self, other):
        coin = self.coins.copy()
        for coin_id, amount in other.items():
            if coin_id in coin:
                coin[coin_id] += amount
            else:
                coin[coin_id] = amount
            if coin[coin_id] == 0:
                del coin[coin_id]
        coin_object = CoinObject()
        coin_object.coins = coin
        return coin_object

    def __sub__(self, other):
        coin = self.coins.copy()
        for coin_id, amount in other.items():
            if coin_id in coin:
                coin[coin_id] -= amount
            else:
                coin[coin_id] = amount
            if coin[coin_id] == 0:
                del coin[coin_id]
        coin_object = CoinObject()
        coin_object.coins = coin
        return coin_object

    def __dict__(self):
        return self.coins.copy()

    def __contains__(self, item):
        return item in self.coins

    def keys(self):
        return self.coins.keys()

    def values(self):
        return self.coins.values()

    def items(self):
        return self.coins.items()


def float2unit(f):
    if f < 1.0:
        return "%f" % round(f, 6)
    elif f < 10.0:
        return str(round(f, 5))
    elif f < 100.0:
        return str(round(f, 4))
    elif f < 1000.0:
        return str(round(f, 3))
    elif f < 10000.0:
        return str(round(f, 2))
    elif f < 100000.0:
        return str(round(f, 1))
    else:
        return str(round(f, 0))
