from bc4py.config import C, V, BlockChainError
from bc4py.chain.checking.signature import *
from bc4py.database.mintcoin import *
from bc4py.database.builder import tx_builder
from bc4py.user import CoinObject
from binascii import hexlify
import bjson


def check_tx_mint_coin(tx, include_block):
    if not (0 < len(tx.inputs) and 0 < len(tx.outputs)):
        raise BlockChainError('Input and output is more than 1.')
    elif tx.message_type != C.MSG_BYTE:
        raise BlockChainError('TX_MINT_COIN message is bytes.')
    elif include_block and 0 == include_block.txs.index(tx):
        raise BlockChainError('tx index is not proof tx.')
    elif tx.gas_amount < tx.size + len(tx.signature)*C.SIGNATURE_GAS + C.MINTCOIN_GAS:
        raise BlockChainError('Insufficient gas amount [{}<{}+{}+{}]'
                              .format(tx.gas_amount, tx.size, len(tx.signature)*C.SIGNATURE_GAS, C.MINTCOIN_GAS))
    # check new mintcoin format
    try:
        mint_id, params, setting = bjson.loads(tx.message)
    except Exception as e:
        raise BlockChainError('BjsonDecodeError: {}'.format(e))
    m_before = get_mintcoin_object(coin_id=mint_id, best_block=include_block, stop_txhash=tx.hash)
    result = check_mintcoin_new_format(m_before=m_before, new_params=params, new_setting=setting)
    if isinstance(result, str):
        raise BlockChainError('Failed check mintcoin block={}: {}'.format(include_block, result))
    # signature check
    require_cks, coins = input_output_digest(tx=tx)
    owner_address = m_before.address
    if owner_address:
        require_cks.add(owner_address)
    signed_cks = get_signed_cks(tx)
    if signed_cks != require_cks:
        raise BlockChainError('Signature check failed. signed={} require={} lack={}'
                              .format(signed_cks, require_cks, require_cks-signed_cks))
    # amount check
    if 0 < len(set(coins.keys()) - {0, mint_id}):
        raise BlockChainError('Unexpected coin_id included. {}'.format(set(coins.keys()) - {0, mint_id}))
    if mint_id in coins:
        # increase/decrease mintcoin amount
        if not m_before.setting['additional_issue']:
            raise BlockChainError('additional_issue is False but change amount.')
        if coins[0] + coins[mint_id] < 0:
            raise BlockChainError('Too many output amount. {}'.format(coins))
        if coins[mint_id] < 0:
            pass  # increase
        if coins[mint_id] > 0:
            pass  # decrease
    else:
        # only change mintcoin status
        if params is None and setting is None:
            raise BlockChainError('No update found.')
        if sum(coins.values()) < 0:
            raise BlockChainError('Too many output amount. {}'.format(coins))


def input_output_digest(tx):
    require_cks = set()
    coins = CoinObject()
    for txhash, txindex in tx.inputs:
        input_tx = tx_builder.get_tx(txhash=txhash)
        if input_tx is None:
            raise BlockChainError('input tx is None. {}:{}'.format(hexlify(txhash).decode(), txindex))
        address, coin_id, amount = input_tx.outputs[txindex]
        require_cks.add(address)
        coins[coin_id] += amount
    coins[0] -= tx.gas_amount * tx.gas_price
    for address, coin_id, amount in tx.outputs:
        coins[coin_id] -= amount
    return require_cks, coins


__all__ = [
    "check_tx_mint_coin",
]
