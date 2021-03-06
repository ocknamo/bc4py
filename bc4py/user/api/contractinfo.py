from bc4py.config import C, P
from bc4py.user.api import web_base
from bc4py.database.builder import builder, tx_builder
from bc4py.database.validator import get_validator_object
from bc4py.database.contract import get_contract_object
from bc4py.contract.watch import watching_tx
import logging
from binascii import hexlify
import bjson
import pickle
from base64 import b64encode


async def contract_info(request):
    try:
        c_address = request.query['c_address']
        f_confirmed = bool(request.query.get('confirmed', False))
        best_block = builder.best_block if f_confirmed else None
        c = get_contract_object(c_address=c_address, best_block=best_block)
        return web_base.json_res(c.info)
    except Exception as e:
        logging.error(e)
        return web_base.error_res()


async def validator_info(request):
    try:
        c_address = request.query['c_address']
        f_confirmed = bool(request.query.get('confirmed', False))
        best_block = builder.best_block if f_confirmed else None
        v = get_validator_object(c_address=c_address, best_block=best_block)
        return web_base.json_res(v.info)
    except Exception as e:
        logging.error(e)
        return web_base.error_res()


async def get_contract_history(request):
    try:
        c_address = request.query['c_address']
        data = list()
        # database
        for index, start_hash, finish_hash, (c_method, c_args, c_storage) in\
                builder.db.read_contract_iter(c_address=c_address):
            data.append({
                'index': index,
                'height': None,
                'start_hash': hexlify(start_hash).decode(),
                'finish_hash': hexlify(finish_hash).decode(),
                'c_method': c_method,
                'c_args': [decode(a) for a in c_args],
                'c_storage': {decode(k): decode(v) for k, v in c_storage.items()} if c_storage else None
            })
        # memory
        index = len(data)
        for block in reversed(builder.best_chain):
            for tx in block.txs:
                if tx.type != C.TX_CONCLUDE_CONTRACT:
                    continue
                _c_address, start_hash, c_storage = bjson.loads(tx.message)
                if _c_address != c_address:
                    continue
                start_tx = tx_builder.get_tx(txhash=start_hash)
                dummy, c_method, c_args = bjson.loads(start_tx.message)
                data.append({
                    'index': index,
                    'height': tx.height,
                    'start_hash': hexlify(start_hash).decode(),
                    'finish_hash': hexlify(tx.hash).decode(),
                    'c_method': c_method,
                    'c_args': [decode(a) for a in c_args],
                    'c_storage': {decode(k): decode(v) for k, v in c_storage.items()} if c_storage else None
                })
                index += 1
        return web_base.json_res(data)
    except Exception as e:
        logging.error(e)
        return web_base.error_res()


async def get_validator_history(request):
    try:
        c_address = request.query['c_address']
        data = list()
        # database
        for index, new_address, flag, txhash, sig_diff in builder.db.read_validator_iter(c_address=c_address):
            data.append({
                'index': index,
                'height': None,
                'new_address': new_address,
                'flag': flag,
                'txhash': hexlify(txhash).decode(),
                'sig_diff': sig_diff})
        # memory
        index = len(data)
        for block in reversed(builder.best_chain):
            for tx in block.txs:
                if tx.type != C.TX_VALIDATOR_EDIT:
                    continue
                _c_address, new_address, flag, sig_diff = bjson.loads(tx.message)
                if _c_address != c_address:
                    continue
                data.append({
                    'index': index,
                    'height': tx.height,
                    'new_address': new_address,
                    'flag': flag,
                    'txhash': hexlify(tx.hash).decode(),
                    'sig_diff': sig_diff})
                index += 1
        return web_base.json_res(data)
    except Exception as e:
        logging.error(e)
        return web_base.error_res()


async def contract_storage(request):
    try:
        c_address = request.query['c_address']
        f_confirmed = bool(request.query.get('confirmed', False))
        best_block = builder.best_block if f_confirmed else None
        c = get_contract_object(c_address=c_address, best_block=best_block)
        if c is None:
            return web_base.json_res({})
        storage = {decode(k): decode(v) for k, v in c.storage.items()}
        return web_base.json_res(storage)
    except Exception as e:
        logging.error(e)
        return web_base.error_res()


async def watching_info(request):
    try:
        f_pickle = bool(request.query.get('pickle', False))
        if not P.F_WATCH_CONTRACT:
            return web_base.error_res(errors='You need to enable watching option!')
        return web_base.json_res([{
            'hash': hexlify(txhash).decode(),
            'type': tx.type,
            'tx': b64encode(pickle.dumps(tx)).decode() if f_pickle else str(tx),
            'time': time,
            'c_address': c_address,
            'related': related_list,
            'args': tuple(map(decode, args)),
             } for txhash, (time, tx, related_list, c_address, *args) in watching_tx.items()
        ])
    except Exception as e:
        logging.error(e)
        return web_base.error_res()


def decode(b):
    if isinstance(b, bytes) or isinstance(b, bytearray):
        return b.decode(errors='ignore')
    elif isinstance(b, set) or isinstance(b, list) or isinstance(b, tuple):
        return tuple(decode(data) for data in b)
    elif isinstance(b, dict):
        return {decode(k): decode(v) for k, v in b.items()}
    else:
        return b
        # return 'Cannot decode type {}'.format(type(b))


__all__ = [
    "contract_info",
    "validator_info",
    "get_contract_history",
    "get_validator_history",
    "contract_storage",
    "watching_info",
]
