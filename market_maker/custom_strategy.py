import sys

import random


from .utils import math, log
from .settings import settings


from .market_maker import OrderManager


logger = log.setup_custom_logger("root")


class CustomOrderManager(OrderManager):
    """A sample order manager for implementing your own custom strategy"""

    def place_orders2(self) -> None:
        # implement your custom strategy here

        # params:
        # - entry side (side of the bot - short/long)
        # - VaR limit (position size limit)
        # - normal spread size limit (limit of normal spread orders - over the limit only liquidation avoidance)
        # - profit function
        # - zero profit limit
        # - loss limit

        # check position
        # - entry price
        # - LQ price
        # if no position or position size below initial
        # - build initial position
        # position buildup
        # - normal spread orders up to limit
        # - in case of movement against position avoid liquidation
        # - if over VaR limit no further buildup
        # positon release - ReduceOnly
        # - take profit function normal spread
        # - zero profit over limit
        # - loss over another limit
        # - avoid liquidation

        current_qty = self.position["currentQty"]
        entry_price = float(self.position["avgEntryPrice"])
        liquidation_price = float(self.position["liquidationPrice"])

        # initial position to build up
        initial_size = current_qty < settings.INITIAL_SIZE
        #
        normal_size = not initial_size and (current_qty < settings.NORMAL_SIZE)
        escape_size = not (initial_size or normal_size)

        buy_orders = []
        sell_orders = []

        # populate buy and sell orders, e.g.
        # buy_orders.append({'price': 999.0, 'orderQty': 100, 'side': "Buy"})
        # sell_orders.append({'price': 1001.0, 'orderQty': 100, 'side': "Sell"})

        self.converge_orders(buy_orders, sell_orders)

    def get_price_offset(self, index, spread_price=None):
        """Given an index (1, -1, 2, -2, etc.) return the price for that side of the book.
        Negative is a buy, positive is a sell."""

        start_position = (
            self.start_position_buy if index < 0 else self.start_position_sell
        )

        # If we're attempting to sell, but our sell price is actually lower than the buy,
        # move over to the sell side.
        if index > 0 and start_position < self.start_position_buy:
            start_position = self.start_position_sell
        # Same for buys.
        if index < 0 and start_position > self.start_position_sell:
            start_position = self.start_position_buy

        if spread_price is not None:
            if index > 0 and start_position < spread_price:
                start_position = spread_price * (1.00 + (settings.MIN_SPREAD / 2))

            if index < 0 and start_position > spread_price:
                start_position = spread_price * (1.00 - (settings.MIN_SPREAD / 2))

        if settings.MAINTAIN_SPREADS:
            # Maintain existing spreads for max profit
            # First positions (index 1, -1) should start right at start_position, others should branch from there
            index = index + 1 if index < 0 else index - 1

        else:
            pass  # Offset mode: ticker comes from a reference exchange and we define an offset.

        return math.toNearest(
            start_position * (1 + settings.INTERVAL) ** index,
            self.tickSize,
        )

    def prepare_order(self, index):
        """Create an order object."""

        current_qty = self.position["currentQty"]
        order_qty = self.position[
            "openOrderBuyQty" if index < 0 else "openOrderSellQty"
        ]
        mm_order_qty = sum(o.get("orderQty", 0) for o in self.orders)
        entry_price = float(self.position["avgEntryPrice"] or 0.0)
        liquidation_price = float(self.position["liquidationPrice"] or 0.0)

        # initial position to build up
        initial_size = abs(current_qty) < settings.ORDER_START_SIZE
        # size where trading for spread
        spread_size = not initial_size and (abs(current_qty) < settings.ESCAPE_SIZE)
        # size when no profit is acceptable and position increase only to avoid liquidation
        escape_size = not (initial_size or spread_size)

        if settings.RANDOM_ORDER_SIZE is True:
            quantity = random.randint(settings.MIN_ORDER_SIZE, settings.MAX_ORDER_SIZE)
        else:
            quantity = settings.ORDER_START_SIZE + (
                (abs(index) - 1) * settings.ORDER_STEP_SIZE
            )

        side = "Buy" if index < 0 else "Sell"

        # create position only on given side, opposite orders only reduce
        # todo diferentiate reduce
        reduce = False
        if settings.POSITION_ON_SIDE is not None:
            reduce = (index < 0) == (settings.POSITION_ON_SIDE > 0)

        if initial_size:
            if reduce:
                price = self.get_price_offset(index, spread_price=entry_price)
            else:
                price = self.get_price_offset(index)

        elif spread_size:
            price = self.get_price_offset(index, spread_price=entry_price)

        elif escape_size:
            if reduce:
                if abs(index) == 1:
                    price = math.toNearest(entry_price, self.tickSize)
                    quantity = abs(current_qty) - (
                        settings.ESCAPE_SIZE + settings.ORDER_STEP_SIZE
                    )
                else:
                    price = self.get_price_offset(index, spread_price=entry_price)

            else:
                price = self.get_price_offset(
                    index, spread_price=(entry_price + 9 * liquidation_price) / 10
                )

        if reduce:
            # when reducing, order size cannot exceed position size
            # as we proces orders inwards, wee need to calculate inner orders beforehand
            inner_ord_qty = 0
            if abs(index) > 1:
                inner_ord_qty = sum(
                    settings.ORDER_START_SIZE + (abs(i) * settings.ORDER_STEP_SIZE)
                    for i in range(abs(index) - 1)
                )
                if escape_size:
                    inner_ord_qty += abs(current_qty) - (
                        settings.ESCAPE_SIZE
                        + settings.ORDER_STEP_SIZE
                        + settings.ORDER_START_SIZE
                    )
            inner_ord_qty += order_qty - mm_order_qty

            if quantity > current_qty - inner_ord_qty:
                quantity = max(current_qty - inner_ord_qty, 0)

            if quantity > 0:

                return {
                    "price": price,
                    "orderQty": quantity,
                    "side": side,
                    "execInst": "ReduceOnly",
                }

        else:
            if (index < 0) == (price - liquidation_price < 0):
                price = liquidation_price
            return {
                "price": price,
                "orderQty": quantity,
                "side": side,
            }


def run() -> None:
    order_manager = CustomOrderManager()

    # Try/except just keeps ctrl-c from printing an ugly stacktrace
    try:
        order_manager.run_loop()
    except (KeyboardInterrupt, SystemExit):
        sys.exit()
