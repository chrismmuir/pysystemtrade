"""
A multiple price object is a:

pd. dataframe with the 6 columns PRICE, CARRY, PRICE_CONTRACT, CARRY_CONTRACT, FORWARD, FORWARD_CONTRACT
s
All contracts are in yyyymm format

We require these to calculate back adjusted prices and also to work out carry

They can be stored, or worked out 'on the fly'
"""


import pandas as pd
import numpy as np

from copy import copy

from sysdata.data import baseData
from sysdata.futures.futures_per_contract_prices import dictFuturesContractFinalPricesWithContractID,\
                                                        futuresContractFinalPricesWithContractID



price_column_names = dict(PRICE ='PRICE', CARRY ='CARRY', FORWARD='FORWARD')
contract_suffix = '_CONTRACT'
contract_column_names = dict([(key, column_name + contract_suffix)
                              for key, column_name in price_column_names.items()])

list_of_contract_column_names = list(contract_column_names.values())
list_of_price_column_names = list(price_column_names)

multiple_data_columns = list_of_price_column_names + list_of_contract_column_names
multiple_data_columns.sort()


class futuresMultiplePrices(pd.DataFrame):

    def __init__(self, data):

        data_present = list(data.columns)
        data_present.sort()

        try:
            assert data_present == multiple_data_columns
        except AssertionError:
            raise Exception("futuresMultiplePrices has to conform to pattern")

        super().__init__(data)

        self._is_empty=False


    @classmethod
    def create_from_raw_data(futuresMultiplePrices, roll_calendar, dict_of_futures_contract_closing_prices):
        """

        :param roll_calendar: rollCalendar
        :param dict_of_futures_closing_contract_prices: dictFuturesContractPrices with only one column

        :return: pd.DataFrame with the 6 columns PRICE, CARRY, FORWARD, PRICE_CONTRACT, CARRY_CONTRACT, FORWARD_CONTRACT
        """

        all_price_data_stack = create_multiple_price_stack_from_raw_data(roll_calendar,
                                                                         dict_of_futures_contract_closing_prices)

        multiple_prices = futuresMultiplePrices(all_price_data_stack)
        multiple_prices._is_empty = False

        return multiple_prices

    @classmethod
    def create_empty(futuresMultiplePrices):
        """
        Our graceful fail is to return an empty, but valid, dataframe
        """

        data = pd.DataFrame(columns=multiple_data_columns)

        multiple_prices = futuresMultiplePrices(data)
        multiple_prices._is_empty = True

        return multiple_prices

    @property
    def empty(self):
        return self._is_empty

    def current_contract_dict(self):
        final_row = self.iloc[-1]
        contract_dict = dict([(key, final_row[value]) for key, value in contract_column_names.items()])

        return contract_dict

    def as_dict(self):
        """
        Split up and transform into dict

        :return: dictFuturesContractFinalPricesWithContractID, keys PRICE, FORWARD, CARRY
        """

        self_as_dict = {}
        for key in price_column_names.keys():
            column_names = [price_column_names[key], contract_column_names[key]]
            self_as_dict[key] = futuresContractFinalPricesWithContractID(self[column_names],
                                                                         price_column=price_column_names[key],
                                                                         contract_suffix=contract_suffix)

        self_as_dict = dictFuturesContractFinalPricesWithContractID(self_as_dict)

        return self_as_dict

    @classmethod
    def from_dict(futuresMultiplePrices, prices_dict):
        """
        Re-create from dict, eg results of _as_dict

        :param prices_dict: dictFuturesContractFinalPricesWithContractID keys PRICE, CARRY, FORWARD
        :return: object
        """

        multiple_prices_list = []
        for key_name in price_column_names.keys():
            try:
                relevant_data = prices_dict[key_name]
            except KeyError:
                raise Exception("Create multiple prices as dict needs %s as key" % key_name)

            multiple_prices_list.append(relevant_data)

        multiple_prices_data_frame = pd.concat(multiple_prices_list, axis=1)

        ## Now it's possible we have more price data for some things than others
        ## so we forward fill contract_ids; not prices
        multiple_prices_data_frame[list_of_contract_column_names] = multiple_prices_data_frame[list_of_contract_column_names].ffill()

        multiple_prices_object = futuresMultiplePrices(multiple_prices_data_frame)

        return multiple_prices_object

    def update_multiple_prices_with_dict(self, new_prices_dict):
        """
        Given a dict containing prices, forward, carry prices; update existing multiple prices
        Because of asynchronicity, we allow overwriting of earlier data
        WILL NOT WORK IF A ROLL HAS HAPPENED

        :return:
        """

        # Add contractid labels to new_prices_dict

        # For each key in new_prices dict,
        #   merge the prices together
        #   allowing historic updates, but not overwrites of non nan values

        # from the updated prices dict
        # create a new multiple prices object

        current_prices_dict = self.as_dict()

        try:
            merged_data_as_dict = current_prices_dict.merge_data(new_prices_dict)
        except Exception as e:
            raise e

        merged_data = futuresMultiplePrices.from_dict(merged_data_as_dict)

        return merged_data


def create_multiple_price_stack_from_raw_data(roll_calendar, dict_of_futures_contract_closing_prices):
    """

    :param roll_calendar: rollCalendar
    :param dict_of_futures_closing_contract_prices: dictFuturesContractPrices with only one column

    :return: pd.DataFrame with the 6 columns PRICE, CARRY, FORWARD, PRICE_CONTRACT, CARRY_CONTRACT, FORWARD_CONTRACT
    """

    # We need the carry contracts

    all_price_data_stack=[]
    contract_keys = dict_of_futures_contract_closing_prices.keys()

    for rolling_row_index in range(len(roll_calendar.index))[1:]:
        # Between these dates is where we are populating prices
        last_roll_date = roll_calendar.index[rolling_row_index-1]
        next_roll_date = roll_calendar.index[rolling_row_index]

        end_of_roll_period = next_roll_date
        start_of_roll_period = last_roll_date + pd.DateOffset(seconds=1) # to avoid overlaps

        contracts_now = roll_calendar.loc[next_roll_date, :]
        current_contract = contracts_now.current_contract
        next_contract = contracts_now.next_contract
        carry_contract = contracts_now.carry_contract

        current_contract_str = str(current_contract)
        next_contract_str = str(next_contract)
        carry_contract_str = str(carry_contract)

        if (current_contract_str not in contract_keys) or \
             (carry_contract_str not in contract_keys):

                # missing, this is okay if we haven't started properly yet
                if len(all_price_data_stack)==0:
                    print("Missing contracts at start of roll calendar not in price data, ignoring")
                    continue
                else:
                    raise Exception("Missing contracts in middle of roll calendar %s, not in price data!" % str(next_roll_date))

        current_price_data = dict_of_futures_contract_closing_prices[current_contract_str][start_of_roll_period:end_of_roll_period]
        carry_price_data = dict_of_futures_contract_closing_prices[carry_contract_str][start_of_roll_period:end_of_roll_period]

        if (next_contract_str not in contract_keys):

            if rolling_row_index == len(roll_calendar.index) - 1:
                # Last entry, this is fine
                print("Next contract %s missing in last row of roll calendar - this is okay" % next_contract_str)
                next_price_data = pd.Series(np.nan, current_price_data.index)
                next_price_data.iloc[:]=np.nan
            else:
                raise Exception("Missing contract %s in middle of roll calendar on %s" % (next_contract_str, str(next_roll_date)))
        else:
            next_price_data = dict_of_futures_contract_closing_prices[next_contract_str][
                              start_of_roll_period:end_of_roll_period]


        all_price_data = pd.concat([current_price_data, next_price_data, carry_price_data], axis=1)
        all_price_data.columns = [price_column_names['PRICE'], price_column_names['FORWARD'], price_column_names['CARRY']]

        all_price_data[contract_column_names['PRICE']] = current_contract
        all_price_data[contract_column_names['FORWARD']] = next_contract
        all_price_data[contract_column_names['CARRY']] = carry_contract

        all_price_data_stack.append(all_price_data)

    # end of loop
    all_price_data_stack = pd.concat(all_price_data_stack, axis=0)

    return all_price_data_stack



USE_CHILD_CLASS_ERROR = "You need to use a child class of futuresMultiplePricesData"

class futuresMultiplePricesData(baseData):
    """
    Read and write data class to get multiple prices for a specific future

    We'd inherit from this class for a specific implementation

    """

    def __repr__(self):
        return "futuresMultiplePricesData base class - DO NOT USE"

    def keys(self):
        return self.get_list_of_instruments()

    def get_list_of_instruments(self):
        raise NotImplementedError(USE_CHILD_CLASS_ERROR)

    def get_multiple_prices(self, instrument_code):
        if self.is_code_in_data(instrument_code):
            return self._get_multiple_prices_without_checking(instrument_code)
        else:
            return futuresMultiplePrices.create_empty()

    def _get_multiple_prices_without_checking(self, instrument_code):
        raise NotImplementedError(USE_CHILD_CLASS_ERROR)

    def __getitem__(self, instrument_code):
        return self.get_instrument_data(instrument_code)

    def delete_multiple_prices(self, instrument_code, are_you_sure=False):
        self.log.label(instrument_code=instrument_code)

        if are_you_sure:
            if self.is_code_in_data(instrument_code):
                self._delete_multiple_prices_without_any_warning_be_careful(instrument_code)
                self.log.terse("Deleted multiple price data for %s" % instrument_code)

            else:
                ## doesn't exist anyway
                self.log.warn("Tried to delete non existent multiple prices for %s" % instrument_code)
        else:
            self.log.error("You need to call delete_multiple_prices with a flag to be sure")

    def _delete_multiple_prices_without_any_warning_be_careful(instrument_code):
        raise NotImplementedError(USE_CHILD_CLASS_ERROR)

    def is_code_in_data(self, instrument_code):
        if instrument_code in self.get_list_of_instruments():
            return True
        else:
            return False

    def add_multiple_prices(self, instrument_code, multiple_price_data, ignore_duplication=False):
        self.log.label(instrument_code=instrument_code)
        if self.is_code_in_data(instrument_code):
            if ignore_duplication:
                pass
            else:
                self.log.error("There is already %s in the data, you have to delete it first" % instrument_code)

        self._add_multiple_prices_without_checking_for_existing_entry(instrument_code, multiple_price_data)

        self.log.terse("Added data for instrument %s" % instrument_code)

    def _add_multiple_prices_without_checking_for_existing_entry(self, instrument_code, multiple_price_data):
        raise NotImplementedError(USE_CHILD_CLASS_ERROR)

