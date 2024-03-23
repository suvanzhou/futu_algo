#  Futu Algo: Algorithmic High-Frequency Trading Framework
# 
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
# 
#      http://www.apache.org/licenses/LICENSE-2.0
# 
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# 
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021
#  Copyright (c)  billpwchan - All Rights Reserved


import argparse
import importlib
import json
import sys
from datetime import datetime
from math import ceil
from futu import KLType, Market, SecurityType, SubType
import logging
from engines import *
from strategies.Strategies import Strategies


def __daily_update_filters():
    filters = list(__init_filter(filter_list=['all']))
    stock_filter = StockFilter(stock_filters=filters, full_equity_list=HKEXInterface.get_equity_list_full())
    stock_filter.update_filtered_equity_pools()


def daily_update_data(futu_trade, stock_list: list, force_update: bool = False):
    # Daily Update Filtered Security
    # procs = []
    # proc = Process(target=__daily_update_filters)  # instantiating without any argument
    # procs.append(proc)
    # proc.start()

    # Daily Update HKEX Security List & Subscribed Data
    HKEXInterface.update_security_list_full()

    # Daily Update Stock Fundamentals
    # futu_trade.update_stock_fundamentals()

    # Update Market Plate List
    futu_trade.update_plate_list()

    # Update basic information for all markets
    futu_trade.update_stock_basicinfo()

    # Daily Update Owner Plate for all Stocks
    full_equity_list = HKEXInterface.get_equity_list_full()
    futu_trade.update_owner_plate(stock_list=full_equity_list)

    # Identify the last update date of the data
    default_days = max([DataProcessingInterface.get_num_days_to_update(stock_code) for stock_code in stock_list])

    # Update historical k-line
    for stock_code in stock_list:
        futu_trade.update_DW_data(stock_code, years=ceil(default_days / 365), force_update=force_update,
                                  k_type=KLType.K_DAY)
        futu_trade.update_DW_data(stock_code, years=ceil(default_days / 365), force_update=force_update,
                                  k_type=KLType.K_WEEK)
        futu_trade.update_1M_data(stock_code, force_update=force_update, default_days=default_days)

    # Clean non-trading days data (Obsoleted)
    # DataProcessingInterface.clear_empty_data()


def __dynamic_instantiation(prefix: str, module_name: str, optional_parameter=None):
    filter_module = importlib.import_module(f"{prefix}.{module_name}")
    # Assume the class name is identical with the file name except for the underscore _
    class_ = getattr(filter_module, module_name.replace("_", ""))
    if optional_parameter is not None:
        return class_(optional_parameter)
    else:
        return class_()


def __init_strategy(strategy_name: str, input_data: dict) -> Strategies:
    """
    Return a trading strategy instance using a strategy name in string.
    :param strategy_name: an available strategy module name in the strategies' folder
    :param input_data: Initialized input data for the strategy to calculate the technical indicator
    :return: a strategy instance
    """
    return __dynamic_instantiation(prefix="strategies", module_name=strategy_name, optional_parameter=input_data.copy())


def __init_filter(filter_list: list) -> list:
    """
    Return a list of filters instances using a list of filter names.
    If 'all' is specified, all available filters will be returned
    :param filter_list: a list of filter names (in strings)
    :return: a list of filters
    """

    if "all" in filter_list:
        filter_list = [Path(file_name).name[:-3] for file_name in PATH_FILTERS.rglob("*.py") if
                       "__init__" not in file_name and "Filters" not in file_name]

    return [__dynamic_instantiation(prefix="filters", module_name=filter_name) for filter_name in filter_list]


def init_backtesting(strategy_name: str):
    start_date = datetime(2023, 3, 20).date()
    end_date = datetime(2024, 3, 23).date()
    # stock_list = YahooFinanceInterface.get_top_30_hsi_constituents()
    stock_list = json.loads(config.get('TradePreference', 'StockList'))
    bt = BacktestingEngine(stock_list=stock_list, start_date=start_date, end_date=end_date, observation=100)
    bt.prepare_input_data_file_custom_M(custom_interval=5)
    # bt.prepare_input_data_file_1M()
    strategy = __dynamic_instantiation(prefix="strategies", module_name=strategy_name,
                                       optional_parameter=bt.get_backtesting_init_data())
    bt.init_strategy(strategy)
    bt.calculate_return()
    # bt.create_tear_sheet()


def init_day_trading(futu_trade: trading_engine.FutuTrade, stock_list: list, strategy_name: str,
                     stock_strategy_dict: dict, sub_type: SubType = SubType.K_1M):
    # Subscribe to the stock list first
    if futu_trade.kline_subscribe(stock_list, sub_type=sub_type):
        # Subscription Success -> Get Real Time Data
        input_data = futu_trade.get_data_realtime(stock_list, sub_type=sub_type, kline_num=1000)
        # strategy_map = dict object {'HK.00001', MACD_Cross(), 'HK.00002', MACD_Cross()...}
        strategy_map = {stock_code: __init_strategy(strategy_name=stock_strategy_dict.get(stock_code, strategy_name),
                                                    input_data=input_data) for stock_code in stock_list}
        while True:
            futu_trade.cur_kline_evaluate(stock_list=stock_list, strategy_map=strategy_map, sub_type=sub_type)
    else:
        sys.exit(1)


def init_stock_filter(filter_list: list, full_equity_list: list) -> list:
    filters = __init_filter(filter_list)
    stock_filter = StockFilter(stock_filters=filters, full_equity_list=full_equity_list.copy())
    return stock_filter.get_filtered_equity_pools()


def main():
    # Initialize Argument Parser
    parser = argparse.ArgumentParser()

    # Data Related Arguments
    parser.add_argument("-u", "--update", help="Daily Update Data (Execute Before Market Starts)",
                        action="store_true")
    parser.add_argument("-fu", "--force_update",
                        help="Force Update All Data Up to Max. Allowed Years (USE WITH CAUTION)", action="store_true")

    # Trading Related Arguments
    strategy_list = [file_name.name[:-3] for file_name in PATH_STRATEGIES.rglob("*.py") if
                     "__init__" not in file_name.name and "Strategies" not in file_name.name]
    parser.add_argument("-s", "--strategy", type=str, choices=strategy_list,
                        help="Execute Algo Trade using Pre-defined Strategy (Stock-Strategy Map should be defined in stock_strategy_map.yml)")
    parser.add_argument("--include_hsi", help="Include HSI in the Stock List", action="store_true")
    parser.add_argument("-t", "--time_interval", type=str,
                        choices=["K_1M", "K_3M", "K_5M", "K_15M", "K_30M", "K_60M", "K_DAY", "K_WEEK", "K_MON",
                                 "K_QUARTER", "K_YEAR"], default="K_1M")

    # Backtesting Related Arguments
    parser.add_argument("-b", "--backtesting", type=str, choices=strategy_list,
                        help="Backtesting a Pre-defined Strategy")

    # Retrieve file names for all strategies as the argument option
    filter_list = [file_name.name[:-3] for file_name in PATH_FILTERS.rglob("*.py") if
                   "__init__" not in file_name.name and "Filters" not in file_name.name]
    parser.add_argument("-f", "--filter", type=str, choices=filter_list, nargs="+",
                        help="Filter Stock List based on Pre-defined Filters")
    parser.add_argument("-en", "--email_name", type=str, help="Name of the applied stock filtering techniques")
    parser.add_argument("-m", "--market", type=str, choices=['HK', 'CHINA', 'US'], nargs="+", help="Available Market")

    # Evaluate Arguments
    args = parser.parse_args()

    # Initialization Connection
    futu_trade = trading_engine.FutuTrade()
    email_handler = email_engine.EmailEngine()

    # Initialize Stock List
    stock_list = json.loads(config.get('TradePreference', 'StockList'))

    if args.filter:
        subscription_list = json.loads(config.get('Email', 'SubscriptionList'))
        for market in args.market:
            filtered_stock_list = []
            filtered_stock_dict = {}
            if 'HK' in args.market or 'US' in args.market:
                # HK Market Stock Filter
                full_equity_list = []
                market_code = Market.HK if market == 'HK' else Market.US
                full_equity_list.extend(
                    futu_trade.get_stock_basicinfo(market_code, SecurityType.STOCK)['code'].tolist())
                filtered_stock_list = init_stock_filter(args.filter, full_equity_list)
                filtered_stock_dict = YahooFinanceInterface.get_stocks_email(filtered_stock_list)

            if 'CHINA' in args.market:
                input_df = pd.concat([futu_trade.get_stock_basicinfo(Market.SH, SecurityType.STOCK),
                                      futu_trade.get_stock_basicinfo(Market.SZ, SecurityType.STOCK)], ignore_index=True)
                china_equity_list = input_df['code'].tolist()
                TuShareInterface.update_stocks_history(china_equity_list)

                filtered_stock_list = init_stock_filter(args.filter, china_equity_list)
                filtered_stock_dict = TuShareInterface.get_stocks_email(filtered_stock_list)

            # DO NOT send email if no stock gets selected
            if len(filtered_stock_list) == 0:
                continue
            for subscriber in subscription_list:
                filter_name = args.email_name if args.email_name else "Default Stock Filter"
                email_handler.write_daily_stock_filter_email(subscriber, filter_name, filtered_stock_dict)

            # If the user does not provide any preferred stock list, use top 30 HSI constituents instead
    if args.include_hsi or not stock_list:
        stock_list.extend([stock_code for stock_code in YahooFinanceInterface.get_top_30_hsi_constituents() if
                           stock_code not in stock_list])

    if args.update or args.force_update:
        # Daily Update Data based on all available time files in the data folder
        stock_list.extend(
            [stock_code.name for stock_code in PATH_DATA.iterdir() if
             stock_code.is_dir() and stock_code.name not in stock_list])
        if 'Stock_Pool' in stock_list: stock_list.remove('Stock_Pool')
        daily_update_data(futu_trade=futu_trade, stock_list=stock_list, force_update=args.force_update)

    if args.strategy:
        # Stock Basket => 4 Parts
        # 1. Currently Holding Stocks (i.e., in the trading account with existing position)
        # 2. Filtered Stocks (i.e., based on 1D data if -f option is adopted
        # 3. StockList in config.ini (i.e., if empty, default use all stocks in the data folder)
        # 4. Top 30 HSI Constituents

        # stock_list.extend(YahooFinanceInterface.get_top_30_hsi_constituents())
        if futu_trade.is_normal_trading_time(stock_list=stock_list):
            init_day_trading(futu_trade, stock_list, args.strategy, stock_strategy_map, sub_type=args.time_interval)

    if args.backtesting:
        init_backtesting(args.backtesting)

    futu_trade.display_quota()


if __name__ == '__main__':

    main()
