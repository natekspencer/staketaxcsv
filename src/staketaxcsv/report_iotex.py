"""
usage: python3 report_iotex.py <walletaddress> [--format all|cointracking|koinly|..]

Prints transactions and writes CSV(s) to _reports/IOTX.<walletaddress>.<format>.csv
"""

import json
import logging
import math
import os
import pprint

import staketaxcsv.iotex.processor
from staketaxcsv.common import report_util
from staketaxcsv.common.ErrorCounter import ErrorCounter
from staketaxcsv.common.Exporter import Exporter
from staketaxcsv.iotex import constants as co
from staketaxcsv.iotex.api_graphql import IoTexGraphQL
from staketaxcsv.iotex.api_iotexscan import IoTexScan
from staketaxcsv.iotex.config_iotex import localconfig
from staketaxcsv.iotex.progress_iotex import SECONDS_PER_TX, ProgressIotex
from staketaxcsv.settings_csv import TICKER_IOTEX


def main():
    report_util.main_default(TICKER_IOTEX)


def _read_options(options):
    report_util.read_common_options(localconfig, options)
    logging.info("localconfig: %s", localconfig.__dict__)


def wallet_exists(wallet_address):
    return IoTexGraphQL.account_exists(wallet_address)


def txone(wallet_address, txid):
    progress = ProgressIotex()

    elems = IoTexGraphQL.get_action(txid)

    print("\ndebug data:")
    pprint.pprint(elems)
    print("")

    progress.set_estimate(1)
    exporter = Exporter(wallet_address, localconfig)
    staketaxcsv.iotex.processor.process_txs(wallet_address, elems, exporter, progress)
    print("")

    return exporter


def _max_queries():
    max_txs = localconfig.limit
    max_queries = math.ceil(max_txs / co.IOTEX_API_LIMIT)
    logging.info("max_txs: %s, max_queries: %s", max_txs, max_queries)
    return max_queries


def txhistory(wallet_address, options):
    # Configure localconfig based on options
    _read_options(options)

    progress = ProgressIotex()
    exporter = Exporter(wallet_address, localconfig, TICKER_IOTEX)

    # Retrieve data
    elems = _get_txs(wallet_address, progress)

    # Create rows for CSV
    staketaxcsv.iotex.processor.process_txs(wallet_address, elems, exporter, progress)

    # Log error stats if exists
    ErrorCounter.log(TICKER_IOTEX, wallet_address)

    return exporter


def estimate_duration(wallet_address, options):
    _, _, num_txs = _num_txs(wallet_address)
    return SECONDS_PER_TX * num_txs


def _num_txs(wallet_address):
    num_actions = IoTexGraphQL.num_actions(wallet_address)
    num_stake_actions = IoTexScan.num_stake_actions(wallet_address)
    num_txs = num_actions + num_stake_actions
    return num_actions, num_stake_actions, num_txs


def _get_txs(wallet_address, progress):
    # Debugging only: when --debug flag set, read from cache file
    DEBUG_FILE = "_reports/debugiotex.{}.json".format(wallet_address)
    if localconfig.debug and os.path.exists(DEBUG_FILE):
        with open(DEBUG_FILE, 'r') as f:
            out = json.load(f)
            return out

    num_actions, num_stake_actions, num_txs = _num_txs(wallet_address)
    progress.set_estimate(num_txs)

    start = 0
    count = min(num_actions, co.IOTEX_API_LIMIT)
    out = []
    for i in range(_max_queries()):
        actions = IoTexGraphQL.get_actions_by_address(wallet_address, start, count)
        out.extend([act for act in actions if act.get("action", {}).get("core", {}).get("transfer")])

        if len(actions) < co.IOTEX_API_LIMIT:
            break
        start += count

    message = "Retrieved {} txids...".format(len(out))
    progress.report_message(message)

    count = min(num_stake_actions, co.IOTEX_API_LIMIT)
    ids = []
    ids_set = set()
    for i in range(_max_queries()):
        actions = IoTexScan.get_stake_actions(wallet_address, i, count)

        for act in actions:
            id = act["action_hash"]
            if id not in ids_set and act["act_type"].lower() == co.ACTION_TYPE_DEPOSIT_STAKE:
                ids.append(id)
                ids_set.add(id)

        if len(actions) < co.IOTEX_API_LIMIT:
            break

    start = 0
    count = min(len(ids), co.IOTEX_API_LIMIT)
    for i in range(_max_queries()):
        end = min(start + count, len(ids))
        actions = IoTexGraphQL.get_actions_by_hashes(ids[start:end])
        out.extend(actions)

        if len(actions) < co.IOTEX_API_LIMIT:
            break
        start += count

    message = "Retrieved total {} txids...".format(len(out))
    progress.report_message(message)

    # Debugging only: when --debug flat set, write to cache file
    if localconfig.debug:
        with open(DEBUG_FILE, 'w') as f:
            json.dump(out, f, indent=4)
        logging.info("Wrote to %s for debugging", DEBUG_FILE)

    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
