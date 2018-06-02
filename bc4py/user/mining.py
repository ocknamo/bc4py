from bc4py import __chain_version__
from bc4py.config import C, V, BlockChainError
from bc4py.utils import set_database_path, set_blockchain_params
from bc4py.contract.finishtx import create_finish_tx_for_mining
from bc4py.chain.block import Block
from bc4py.chain.tx import TX
from bc4py.chain.difficulty import get_bits_by_hash, get_pos_bias_by_hash
from bc4py.chain.utils import GompertzCurve
from bc4py.database.create import create_db, closing
from bc4py.database.user.write import new_keypair
from bc4py.user import float2unit
from multiprocessing import Process, Pipe
from threading import Thread
import os
import time
import logging
import queue
from binascii import hexlify


NEW_UNCONFIRMED = 0
NEW_BLOCK = 1
CLOSE_PROCESS = 2


def mining_process(pipe, params):
    set_database_path(sub_dir=params.get("sub_dir"))
    set_blockchain_params()
    power_save = params.get("power_save")
    unconfirmed = list()
    mining_block = None
    count = 0
    start = int(time.time())
    while True:
        # コマンド受け取り
        if pipe.poll():
            cmd, obj = pipe.recv()
            if cmd == NEW_UNCONFIRMED:
                unconfirmed = obj
            elif cmd == NEW_BLOCK:
                mining_block = obj
            else:
                raise BaseException('Not found command {}'.format(cmd))
            # contractの更新
            if mining_block and unconfirmed:
                try:
                    create_finish_tx_for_mining(unconfirmed, mining_block.height)
                except BaseException as e:
                    logging.debug("Skip {}".format(e))
                    import traceback
                    traceback.print_exc()

            # setup new block
            if mining_block:
                prooftx = mining_block.txs.pop(0)
                mining_block.txs.clear()
                mining_block.txs.append(prooftx)
                mining_block.txs.extend(unconfirmed)
                while mining_block.getsize() > C.SIZE_BLOCK_LIMIT:
                    tx = mining_block.txs.pop()
                    if tx.type == C.TX_FINISH_CONTRACT:
                        mining_block.txs.pop()
                mining_block.bits2target()
                mining_block.target2diff()
                mining_block.update_merkleroot()

        # 採掘実行
        elif mining_block:
            mining_block.txs[0].update_time()
            mining_block.update_time(blocktime=mining_block.txs[0].time)
            while mining_block.time == int(time.time()) - V.BLOCK_GENESIS_TIME:
                c = 10
                while c > 0:
                    c -= 1
                    mining_block.update_nonce()
                    mining_block.update_pow()
                    count += 1
                    if mining_block.pow_check():
                        mining_block.work2diff()
                        for tx in mining_block.txs:
                            tx.height = mining_block.height
                        info = "Mined yay!! BlockDiff={}, WorkDiff={}, ({}h/s)".format(
                            float2unit(mining_block.difficulty),
                            float2unit(mining_block.work_difficulty),
                            float2unit(count / max(0.1, time.time() - start)))
                        pipe.send((True, mining_block, info))
                        count = 0
                        start = int(time.time())
                        mining_block = None
                        unconfirmed.clear()
                        break

                if not mining_block:
                    break
                if power_save:
                    time.sleep(power_save)

            else:
                # 時間切れのTXを除く
                for tx in unconfirmed.copy():
                    if not (tx.time <= mining_block.time <= tx.deadline):
                        unconfirmed.remove(tx)

            if not mining_block:
                continue
            if mining_block.time % 300 == 0:
                hashrate = float2unit(count / max(0.1, time.time() - start))
                info = "Mining now.. BlockDiff={} {}h/s {}".format(
                    float2unit(mining_block.difficulty), hashrate,
                    '(Saved)' if power_save else '')
                pipe.send((False, hashrate, info))
            elif mining_block.time % 10 == 0:
                hashrate = float2unit(count / max(0.1, time.time() - start))
                pipe.send((False, hashrate, None))
        else:
            time.sleep(1)


def new_key():
        with closing(create_db(V.DB_ACCOUNT_PATH)) as db:
            cur = db.cursor()
            sk, pk, ck = new_keypair(C.ANT_UNKNOWN, cur=cur)
            db.commit()
        return ck


class ProcessObject:
    def __init__(self, index, pipe, process):
        assert V.BLOCK_CONSENSUS in (C.BLOCK_POW, C.HYBRID), 'Not pow mining chain.'
        self.time = time
        self.index = index
        self.pipe = pipe
        self.que = queue.LifoQueue()
        self.process = process
        self.hashrate = "0.0"

    def __repr__(self):
        return "<Mining {} {}h/s>".format(self.index, self.hashrate)

    def close(self):
        try: self.pipe.close()
        except OSError as e:
            logging.error("Failed close Pipe: {}".format(e))
        try: self.process.terminate()
        except OSError as e:
            logging.error("Failed close Process: {}".format(e))

    def check_mined_block(self):
        try:
            if self.pipe.poll():
                status, obj, info = self.pipe.recv()
                if status:
                    logging.info(info)
                    return status, obj
                elif info:
                    self.hashrate = obj
                    logging.debug(info)
                    return status, None
                else:
                    self.hashrate = obj
                    return status, None
            else:
                return None, None
        except OSError as e:
            logging.error("Error on pipe: {}".format(e))

    def update_new_block(self, new_block):
        self.pipe.send((NEW_BLOCK, new_block))

    def update_unconfirmed(self, unconfirmed):
        self.pipe.send((NEW_UNCONFIRMED, unconfirmed))


class Mining:
    f_stop = False
    f_mining = False

    def __init__(self):
        self.thread_pool = list()
        self.que = queue.LifoQueue()
        self.mining_address = None
        self.previous_hash = None

    def __repr__(self):
        return "<Mining Core={} Previous={}>"\
            .format(len(self.thread_pool), hexlify(self.previous_hash).decode())

    def getinfo(self):
        return [str(po) for po in self.thread_pool]

    def start(self, core=None):
        if self.f_mining:
            raise BlockChainError('Already POW is running.')
        self.f_mining = True
        self.f_stop = False
        if core is None:
            core = os.cpu_count()
        logging.info("Start mining by {} cores.".format(core))
        for i in range(core):
            try:
                parent_conn, child_conn = Pipe()
                params = dict(genesis_time=V.BLOCK_GENESIS_TIME, power_save=V.F_MINING_POWER_SAVE, sub_dir=V.SUB_DIR)
                process = Process(target=mining_process, name="C-Mining {}".format(i), args=(child_conn, params))
                # process.daemon = True
                process.start()
                po = ProcessObject(index=i, pipe=parent_conn, process=process)
                self.thread_pool.append(po)
                logging.info("Mining process create number={}".format(i))
            except OSError as e:
                logging.error("Failed start mining process: {}".format(e))
                time.sleep(60)
        loop_thread = Thread(target=self.inner_check, name="P-Mining", daemon=True)
        loop_thread.start()

    def close(self):
        self.f_stop = True
        for po in self.thread_pool:
            po.close()
        self.thread_pool.clear()
        self.f_mining = False

    def share_que(self, staking):
        self.que = staking.que

    def inner_check(self):
        while True:
            for po in self.thread_pool:
                status, new_block = po.check_mined_block()
                if status:
                    break
            else:
                time.sleep(0.5)
                continue
            if self.f_stop:
                logging.info("Mining stopped.")
                return
            logging.info("Mined block yay!! {}".format(new_block))
            # 処理
            if new_block is None:
                continue
            elif self.previous_hash != new_block.previous_hash:
                continue
            self.mining_address = None
            self.previous_hash = None
            self.que.put(new_block)

    def update_block(self, base_block):
        self.previous_hash = None
        mining_block = Block(block={
            'merkleroot': b'\xff' * 32,
            'time': 0,
            'previous_hash': base_block.hash,
            'bits': get_bits_by_hash(previous_hash=base_block.hash, consensus=C.BLOCK_POW)[0],
            'pos_bias': get_pos_bias_by_hash(previous_hash=base_block.hash)[0],
            'nonce': b'\xff' * 4})
        mining_block.height = base_block.height + 1
        mining_block.flag = C.BLOCK_POW
        self.setup_prooftx(mining_block)
        mining_block.bits2target()
        mining_block.target2diff()
        mining_block.serialize()
        logging.debug("Update pow block Diff={} {}"
                      .format(float2unit(mining_block.difficulty), hexlify(mining_block.hash).decode()))
        for po in self.thread_pool:
            po.update_new_block(mining_block)
        self.previous_hash = base_block.hash

    def update_unconfirmed(self, unconfirmed):
        for po in self.thread_pool:
            po.update_unconfirmed(unconfirmed)

    def setup_prooftx(self, block):
        now = int(time.time())
        # coinbase txを挿入する
        if self.mining_address:
            mining_address = self.mining_address
        elif V.MINING_ADDRESS:
            mining_address = V.MINING_ADDRESS
        else:
            self.mining_address = new_key()
            mining_address = self.mining_address

        reward = GompertzCurve.calc_block_reward(block.height)
        fees = sum(tx.gas_amount * tx.gas_price for tx in block.txs)
        proof_tx = TX(tx={
            'version': __chain_version__,
            'type': C.TX_POW_REWARD,
            'time': now - V.BLOCK_GENESIS_TIME,
            'deadline': now - V.BLOCK_GENESIS_TIME + 10800,
            'inputs': list(),
            'outputs': [(mining_address, 0, reward + fees)],
            'gas_price': 0,
            'gas_amount': 0,
            'message_type': C.MSG_PLAIN if V.MINING_MESSAGE else C.MSG_NONE,
            'message': V.MINING_MESSAGE if V.MINING_MESSAGE else b''})
        if len(proof_tx.message) > 96:
            raise BlockChainError('POW tx msg is less than 96bytes. [{}b]'.format(len(proof_tx.message)))
        block.txs = [proof_tx]