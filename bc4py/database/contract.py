from bc4py.config import C, BlockChainError
from bc4py.database.builder import builder, tx_builder
from expiringdict import ExpiringDict
from binascii import hexlify
import bjson
from collections import defaultdict, OrderedDict


M_INIT = 'init'
M_UPDATE = 'update'


cashe = ExpiringDict(max_len=100, max_age_seconds=1800)

settings_template = {
    'update_binary': True,
    'update_extra_imports': True}


class Storage(defaultdict):
    def __init__(self, c_address, default_factory=None, **kwargs):
        super(Storage, self).__init__(default_factory, **kwargs)
        # check value is not None
        for k, v in kwargs.items():
            if v is None:
                raise Exception('Not allowed None value...')
        # check key type
        if len({type(k) for k in kwargs}) > 1:
            raise Exception("All key type is same {}".format([type(k) for k in kwargs]))
        self.c_address = c_address
        self.version = 0

    def __repr__(self):
        return "<Storage of {} ver={} {}>".\
            format(self.c_address, self.version, dict(self.items()))

    def marge_diff(self, diff):
        if diff is None:
            return  # skip
        for k, v in diff.items():
            if v is None:
                del self[k]
            else:
                self[k] = v
        self.version += 1

    def export_diff(self, original_storage):
        # check value is not None
        for v in self.values():
            if v is None:
                raise Exception('Not allowed None value...')
        diff = dict()
        for key in original_storage.keys() | self.keys():
            if key in original_storage and key in self:
                if original_storage[key] != self[key]:
                    diff[key] = self[key]  # update
            elif key not in original_storage and key in self:
                diff[key] = self[key]  # insert
            elif key in original_storage and key not in self:
                diff[key] = None  # delete
        # check key type
        if len({type(k) for k in diff}) > 1:
            raise Exception("All key type is same {}".format([type(k) for k in diff]))
        return diff


class Contract:
    def __init__(self, c_address):
        self.c_address = c_address
        self.index = -1
        self.binary = None
        self.extra_imports = None
        self.storage = None
        self.settings = None
        self.start_hash = None
        self.finish_hash = None

    def __repr__(self):
        return "<Contract {} ver={}>".format(self.c_address, self.index)

    @property
    def info(self):
        if self.index == -1:
            return None
        d = OrderedDict()
        d['c_address'] = self.c_address
        d['index'] = self.index
        d['binary'] = hexlify(self.binary).decode()
        d['extra_imports'] = self.extra_imports
        d['storage_key'] = len(self.storage)
        d['settings'] = self.settings
        d['start_hash'] = hexlify(self.start_hash).decode()
        d['finish_hash'] = hexlify(self.finish_hash).decode()
        return d

    def update(self, start_hash, finish_hash, c_method, c_args, c_storage):
        if c_method == M_INIT:
            assert self.index == -1
            c_bin, c_extra_imports, c_settings = c_args
            self.binary = c_bin
            self.extra_imports = c_extra_imports or list()
            self.settings = settings_template.copy()
            if c_settings:
                self.settings.update(c_settings)
            self.storage = Storage(c_address=self.c_address, **c_storage)
        elif c_method == M_UPDATE:
            assert self.index != -1
            c_bin, c_extra_imports, c_settings = c_args
            if self.settings['update_binary']:
                self.binary = c_bin
                if c_settings and not c_settings.get('update_binary', False):
                    self.settings['update_binary'] = False
            if self.settings['update_extra_imports']:
                self.extra_imports = c_extra_imports
                if c_settings and not c_settings.get('update_extra_imports', False):
                    self.settings['update_extra_imports'] = False
        else:
            assert self.index != -1
            self.storage.marge_diff(c_storage)
        self.index += 1
        self.start_hash = start_hash
        self.finish_hash = finish_hash


def decode(b):
    # transfer: [c_address]-[c_method]-[c_args]
    # conclude: [c_address]-[start_hash]-[c_storage]
    return bjson.loads(b)


def encode(*args):
    assert len(args) == 3
    return bjson.dumps(args, compress=False)


def contract_fill(c: Contract, best_block=None, best_chain=None, stop_txhash=None):
    assert c.index == -1, 'Already updated'
    # database
    c_iter = builder.db.read_contract_iter(c_address=c.c_address)
    for index, start_hash, finish_hash, (c_method, c_args, c_storage) in c_iter:
        if finish_hash == stop_txhash:
            return
        c.update(start_hash=start_hash, finish_hash=finish_hash,
                 c_method=c_method, c_args=c_args, c_storage=c_storage)
    # memory
    if best_chain:
        _best_chain = None
    elif best_block and best_block == builder.best_block:
        _best_chain = builder.best_chain
    else:
        dummy, _best_chain = builder.get_best_chain(best_block=best_block)
    for block in reversed(best_chain or _best_chain):
        for tx in block.txs:
            if tx.hash == stop_txhash:
                return
            if tx.type != C.TX_CONCLUDE_CONTRACT:
                continue
            c_address, start_hash, c_storage = decode(tx.message)
            if c_address != c.c_address:
                continue
            start_tx = tx_builder.get_tx(txhash=start_hash)
            dummy, c_method, c_args = decode(start_tx.message)
            c.update(start_hash=start_hash, finish_hash=tx.hash,
                     c_method=c_method, c_args=c_args, c_storage=c_storage)
    # unconfirmed
    if best_block is None:
        for tx in sorted(tx_builder.unconfirmed.values(), key=lambda x: x.time):
            if tx.hash == stop_txhash:
                return
            if tx.type != C.TX_CONCLUDE_CONTRACT:
                continue
            c_address, start_hash, c_storage = decode(tx.message)
            if c_address != c.c_address:
                continue
            start_tx = tx_builder.get_tx(txhash=start_hash)
            dummy, c_method, c_args = decode(start_tx.message)
            c.update(start_hash=start_hash, finish_hash=tx.hash,
                     c_method=c_method, c_args=c_args, c_storage=c_storage)


def get_contract_object(c_address, best_block=None, best_chain=None, stop_txhash=None):
    if best_block:
        key = (best_block.hash, stop_txhash)
        if key in cashe:
            return cashe[key]
    else:
        key = None
    c = Contract(c_address=c_address)
    contract_fill(c=c, best_block=best_block, best_chain=best_chain, stop_txhash=stop_txhash)
    if key:
        cashe[key] = c
    return c


def get_conclude_hash_by_start_hash(c_address, start_hash, best_block=None, best_chain=None, stop_txhash=None):
    # database
    c_iter = builder.db.read_contract_iter(c_address=c_address)
    for index, _start_hash, finish_hash, (c_method, c_args, c_storage) in c_iter:
        if finish_hash == stop_txhash:
            return None
        if _start_hash == start_hash:
            return finish_hash
    # memory
    if best_chain:
        _best_chain = None
    elif best_block and best_block == builder.best_block:
        _best_chain = builder.best_chain
    else:
        dummy, _best_chain = builder.get_best_chain(best_block=best_block)
    for block in reversed(best_chain or _best_chain):
        for tx in block.txs:
            if tx.hash == stop_txhash:
                return None
            if tx.type != C.TX_CONCLUDE_CONTRACT:
                continue
            _c_address, _start_hash, c_storage = decode(tx.message)
            if _c_address != c_address:
                continue
            if _start_hash == start_hash:
                return tx.hash
    # unconfirmed
    if best_block is None:
        for tx in sorted(tx_builder.unconfirmed.values(), key=lambda x: x.time):
            if tx.hash == stop_txhash:
                return None
            if tx.type != C.TX_CONCLUDE_CONTRACT:
                continue
            _c_address, _start_hash, c_storage = decode(tx.message)
            if _c_address != c_address:
                continue
            if _start_hash == start_hash:
                return tx.hash
    return None


__all__ = [
    "M_INIT", "M_UPDATE",
    "Storage",
    "Contract",
    "contract_fill",
    "get_contract_object",
    "get_conclude_hash_by_start_hash",
]
