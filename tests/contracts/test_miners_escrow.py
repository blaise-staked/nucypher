import pytest
from ethereum.tester import TransactionFailed
import os


@pytest.fixture()
def token(web3, chain):
    creator = web3.eth.accounts[0]
    # Create an ERC20 token
    token, _ = chain.provider.get_or_deploy_contract(
        'NuCypherKMSToken', deploy_args=[2 * 10 ** 9],
        deploy_transaction={'from': creator})
    return token


@pytest.fixture()
def escrow_contract(web3, chain, token):
    def make_escrow(max_allowed_locked_tokens):
        creator = web3.eth.accounts[0]
        # Creator deploys the escrow
        escrow, _ = chain.provider.get_or_deploy_contract(
            'MinersEscrow', deploy_args=[
                token.address, 1, 4 * 2 * 10 ** 7, 4, 4, 2, 100, max_allowed_locked_tokens],
            deploy_transaction={'from': creator})
        return escrow

    return make_escrow


# TODO extract method
def wait_time(chain, wait_hours):
    web3 = chain.web3
    step = 50
    end_timestamp = web3.eth.getBlock(web3.eth.blockNumber).timestamp + wait_hours * 60 * 60
    while web3.eth.getBlock(web3.eth.blockNumber).timestamp < end_timestamp:
        chain.wait.for_block(web3.eth.blockNumber + step)


def test_escrow(web3, chain, token, escrow_contract):
    escrow = escrow_contract(1500)
    creator = web3.eth.accounts[0]
    ursula = web3.eth.accounts[1]
    alice = web3.eth.accounts[2]

    # Give Ursula and Alice some coins
    tx = token.transact({'from': creator}).transfer(ursula, 10000)
    chain.wait.for_receipt(tx)
    tx = token.transact({'from': creator}).transfer(alice, 10000)
    chain.wait.for_receipt(tx)
    assert 10000 == token.call().balanceOf(ursula)
    assert 10000 == token.call().balanceOf(alice)

    # Ursula and Alice give Escrow rights to transfer
    tx = token.transact({'from': ursula}).approve(escrow.address, 3000)
    chain.wait.for_receipt(tx)
    assert 3000 == token.call().allowance(ursula, escrow.address)
    tx = token.transact({'from': alice}).approve(escrow.address, 1100)
    chain.wait.for_receipt(tx)
    assert 1100 == token.call().allowance(alice, escrow.address)

    # Ursula's withdrawal attempt won't succeed because nothing to withdraw
    with pytest.raises(TransactionFailed):
        tx = escrow.transact({'from': ursula}).withdraw(100)
        chain.wait.for_receipt(tx)

    # And can't lock because nothing to lock
    with pytest.raises(TransactionFailed):
        tx = escrow.transact({'from': ursula}).lock(500, 2)
        chain.wait.for_receipt(tx)

    # Check that nothing is locked
    assert 0 == escrow.call().getLockedTokens(ursula)
    assert 0 == escrow.call().getLockedTokens(alice)
    assert 0 == escrow.call().getLockedTokens(web3.eth.accounts[3])

    # Ursula can't deposit tokens before Escrow initialization
    with pytest.raises(TransactionFailed):
        tx = escrow.transact({'from': ursula}).deposit(1, 1)
        chain.wait.for_receipt(tx)

    # Initialize Escrow contract
    tx = escrow.transact().initialize()
    chain.wait.for_receipt(tx)

    # Ursula can't deposit and lock too low value
    with pytest.raises(TransactionFailed):
        tx = escrow.transact({'from': ursula}).deposit(1, 1)
        chain.wait.for_receipt(tx)

    # And can't deposit and lock too high value
    with pytest.raises(TransactionFailed):
        tx = escrow.transact({'from': ursula}).deposit(1501, 1)
        chain.wait.for_receipt(tx)

    # Ursula and Alice transfer some tokens to the escrow and lock them
    tx = escrow.transact({'from': ursula}).deposit(1000, 1)
    chain.wait.for_receipt(tx)
    assert 1000 == token.call().balanceOf(escrow.address)
    assert 9000 == token.call().balanceOf(ursula)
    assert 1000 == escrow.call().getLockedTokens(ursula)
    assert 1000 == escrow.call().calculateLockedTokens(ursula, 1)
    assert 1000 == escrow.call().calculateLockedTokens(ursula, 2)

    events = escrow.pastEvents('Deposited').get()
    assert 1 == len(events)
    event_args = events[0]['args']
    assert ursula.lower() == event_args['owner'].lower()
    assert 1000 == event_args['value']
    assert 1 == event_args['periods']
    events = escrow.pastEvents('Locked').get()
    assert 1 == len(events)
    event_args = events[0]['args']
    assert ursula.lower() == event_args['owner'].lower()
    assert 1000 == event_args['value']
    assert 500 == event_args['releaseRate']
    events = escrow.pastEvents('ActivityConfirmed').get()
    assert 1 == len(events)
    event_args = events[0]['args']
    assert ursula.lower() == event_args['owner'].lower()
    assert escrow.call().getCurrentPeriod() + 1 == event_args['period']
    assert 1000 == event_args['value']

    tx = escrow.transact({'from': ursula}).switchLock()
    chain.wait.for_receipt(tx)
    assert 500 == escrow.call().calculateLockedTokens(ursula, 2)
    events = escrow.pastEvents('LockSwitched').get()
    assert 1 == len(events)
    event_args = events[0]['args']
    assert ursula.lower() == event_args['owner'].lower()
    assert event_args['release']

    tx = escrow.transact({'from': ursula}).switchLock()
    chain.wait.for_receipt(tx)
    assert 1000 == escrow.call().calculateLockedTokens(ursula, 2)
    events = escrow.pastEvents('LockSwitched').get()
    assert 2 == len(events)
    event_args = events[1]['args']
    assert ursula.lower() == event_args['owner'].lower()
    assert not event_args['release']

    tx = escrow.transact({'from': alice}).deposit(500, 2)
    chain.wait.for_receipt(tx)
    assert 1500 == token.call().balanceOf(escrow.address)
    assert 9500 == token.call().balanceOf(alice)
    assert 500 == escrow.call().getLockedTokens(alice)
    assert 500 == escrow.call().calculateLockedTokens(alice, 1)

    events = escrow.pastEvents('Deposited').get()
    assert 2 == len(events)
    event_args = events[1]['args']
    assert alice.lower() == event_args['owner'].lower()
    assert 500 == event_args['value']
    assert 2 == event_args['periods']
    events = escrow.pastEvents('Locked').get()
    assert 2 == len(events)
    event_args = events[1]['args']
    assert alice.lower() == event_args['owner'].lower()
    assert 500 == event_args['value']
    assert 250 == event_args['releaseRate']
    events = escrow.pastEvents('ActivityConfirmed').get()
    assert 2 == len(events)
    event_args = events[1]['args']
    assert alice.lower() == event_args['owner'].lower()
    assert escrow.call().getCurrentPeriod() + 1 == event_args['period']
    assert 500 == event_args['value']

    # Checks locked tokens in next period
    wait_time(chain, 1)
    assert 1000 == escrow.call().getLockedTokens(ursula)
    assert 500 == escrow.call().getLockedTokens(alice)
    assert 1500 == escrow.call().getAllLockedTokens()

    # Ursula's withdrawal attempt won't succeed
    with pytest.raises(TransactionFailed):
        tx = escrow.transact({'from': ursula}).withdraw(100)
        chain.wait.for_receipt(tx)
    assert 1500 == token.call().balanceOf(escrow.address)
    assert 9000 == token.call().balanceOf(ursula)

    # Ursula can deposit more tokens
    tx = escrow.transact({'from': ursula}).confirmActivity()
    chain.wait.for_receipt(tx)
    events = escrow.pastEvents('ActivityConfirmed').get()
    assert 3 == len(events)
    event_args = events[2]['args']
    assert ursula.lower() == event_args['owner'].lower()
    assert escrow.call().getCurrentPeriod() + 1 == event_args['period']
    assert 1000 == event_args['value']

    tx = escrow.transact({'from': ursula}).deposit(500, 0)
    chain.wait.for_receipt(tx)
    assert 2000 == token.call().balanceOf(escrow.address)
    assert 8500 == token.call().balanceOf(ursula)
    events = escrow.pastEvents('ActivityConfirmed').get()
    assert 4 == len(events)
    event_args = events[3]['args']
    assert ursula.lower() == event_args['owner'].lower()
    assert escrow.call().getCurrentPeriod() + 1 == event_args['period']
    assert 1500 == event_args['value']

    # But can't deposit too high value
    with pytest.raises(TransactionFailed):
        tx = escrow.transact({'from': ursula}).deposit(1, 0)
        chain.wait.for_receipt(tx)

    # Ursula starts unlocking
    tx = escrow.transact({'from': ursula}).switchLock()
    chain.wait.for_receipt(tx)
    assert 750 == escrow.call().calculateLockedTokens(ursula, 2)

    # Wait 1 period and checks locking
    wait_time(chain, 1)
    assert 1500 == escrow.call().getLockedTokens(ursula)

    # Confirm activity and wait 1 period
    tx = escrow.transact({'from': ursula}).confirmActivity()
    chain.wait.for_receipt(tx)
    wait_time(chain, 1)
    assert 750 == escrow.call().getLockedTokens(ursula)
    assert 0 == escrow.call().calculateLockedTokens(ursula, 1)

    # And Ursula can withdraw some tokens
    tx = escrow.transact({'from': ursula}).withdraw(100)
    chain.wait.for_receipt(tx)
    assert 1900 == token.call().balanceOf(escrow.address)
    assert 8600 == token.call().balanceOf(ursula)
    events = escrow.pastEvents('Withdrawn').get()
    assert 1 == len(events)
    event_args = events[0]['args']
    assert ursula.lower() == event_args['owner'].lower()
    assert 100 == event_args['value']

    # But Ursula can't withdraw all without mining for locked value
    with pytest.raises(TransactionFailed):
        tx = escrow.transact({'from': ursula}).withdrawAll()
        chain.wait.for_receipt(tx)

    # And Ursula can't lock again too low value
    with pytest.raises(TransactionFailed):
        tx = escrow.transact({'from': ursula}).lock(1, 1)
        chain.wait.for_receipt(tx)

    # Ursula can deposit and lock more tokens
    tx = escrow.transact({'from': ursula}).deposit(500, 0)
    chain.wait.for_receipt(tx)
    tx = escrow.transact({'from': ursula}).lock(100, 0)
    chain.wait.for_receipt(tx)

    # Locked tokens will be updated in next period
    # Release rate will be updated too because of end of previous locking
    assert 750 == escrow.call().getLockedTokens(ursula)
    assert 600 == escrow.call().calculateLockedTokens(ursula, 1)
    assert 600 == escrow.call().calculateLockedTokens(ursula, 2)
    tx = escrow.transact({'from': ursula}).switchLock()
    chain.wait.for_receipt(tx)
    assert 300 == escrow.call().calculateLockedTokens(ursula, 2)
    assert 0 == escrow.call().calculateLockedTokens(ursula, 3)
    wait_time(chain, 1)
    assert 600 == escrow.call().getLockedTokens(ursula)
    assert 300 == escrow.call().calculateLockedTokens(ursula, 1)
    assert 0 == escrow.call().calculateLockedTokens(ursula, 2)

    # Ursula can increase lock
    tx = escrow.transact({'from': ursula}).lock(500, 2)
    chain.wait.for_receipt(tx)
    assert 600 == escrow.call().getLockedTokens(ursula)
    assert 800 == escrow.call().calculateLockedTokens(ursula, 1)
    assert 500 == escrow.call().calculateLockedTokens(ursula, 2)
    assert 200 == escrow.call().calculateLockedTokens(ursula, 3)
    assert 0 == escrow.call().calculateLockedTokens(ursula, 4)
    wait_time(chain, 1)
    assert 800 == escrow.call().getLockedTokens(ursula)

    # Alice starts unlocking and increases lock by deposit more tokens
    tx = escrow.transact({'from': alice}).deposit(500, 0)
    chain.wait.for_receipt(tx)
    tx = escrow.transact({'from': alice}).switchLock()
    chain.wait.for_receipt(tx)
    assert 500 == escrow.call().getLockedTokens(alice)
    assert 1000 == escrow.call().calculateLockedTokens(alice, 1)
    assert 500 == escrow.call().calculateLockedTokens(alice, 2)
    assert 0 == escrow.call().calculateLockedTokens(alice, 3)
    wait_time(chain, 1)
    assert 1000 == escrow.call().getLockedTokens(alice)

    # And increases locked time
    tx = escrow.transact({'from': alice}).lock(0, 2)
    chain.wait.for_receipt(tx)
    assert 1000 == escrow.call().getLockedTokens(alice)
    assert 500 == escrow.call().calculateLockedTokens(alice, 1)
    assert 0 == escrow.call().calculateLockedTokens(alice, 2)

    # Alice increases lock by small amount of tokens
    tx = escrow.transact({'from': alice}).deposit(100, 0)
    chain.wait.for_receipt(tx)
    assert 600 == escrow.call().calculateLockedTokens(alice, 1)
    assert 100 == escrow.call().calculateLockedTokens(alice, 2)
    assert 0 == escrow.call().calculateLockedTokens(alice, 3)

    # # Ursula can't destroy contract
    # with pytest.raises(TransactionFailed):
    #     tx = escrow.transact({'from': ursula}).destroy()
    #     chain.wait.for_receipt(tx)
    #
    # # Destroy contract from creator and refund all to Ursula and Alice
    # tx = escrow.transact({'from': creator}).destroy()
    # chain.wait.for_receipt(tx)
    # assert 0 == token.call().balanceOf(escrow.address)
    # assert 10000 == token.call().balanceOf(ursula)
    # assert 10000 == token.call().balanceOf(alice)

    assert 6 == len(escrow.pastEvents('Deposited').get())
    assert 9 == len(escrow.pastEvents('Locked').get())
    assert 5 == len(escrow.pastEvents('LockSwitched').get())
    assert 1 == len(escrow.pastEvents('Withdrawn').get())
    assert 11 == len(escrow.pastEvents('ActivityConfirmed').get())


def test_locked_distribution(web3, chain, token, escrow_contract):
    escrow = escrow_contract(5 * 10 ** 8)
    NULL_ADDR = '0x' + '0' * 40
    creator = web3.eth.accounts[0]

    # Give Escrow tokens for reward and initialize contract
    tx = token.transact({'from': creator}).transfer(escrow.address, 10 ** 9)
    chain.wait.for_receipt(tx)
    tx = escrow.transact().initialize()
    chain.wait.for_receipt(tx)

    miners = web3.eth.accounts[1:]
    amount = token.call().balanceOf(creator) // 2
    largest_locked = amount

    # Airdrop
    for miner in miners:
        tx = token.transact({'from': creator}).transfer(miner, amount)
        chain.wait.for_receipt(tx)
        amount = amount // 2

    # Lock
    for index, miner in enumerate(miners[::-1]):
        balance = token.call().balanceOf(miner)
        tx = token.transact({'from': miner}).approve(escrow.address, balance)
        chain.wait.for_receipt(tx)
        tx = escrow.transact({'from': miner}).deposit(balance, len(miners) - index + 1)
        chain.wait.for_receipt(tx)

    # Check current period
    address_stop, shift = escrow.call().findCumSum(NULL_ADDR, 1, 1)
    assert NULL_ADDR == address_stop.lower()
    assert 0 == shift

    # Wait next period
    wait_time(chain, 1)
    n_locked = escrow.call().getAllLockedTokens()
    assert n_locked > 0

    # And confirm activity
    for miner in miners:
        tx = escrow.transact({'from': miner}).confirmActivity()
        chain.wait.for_receipt(tx)

    address_stop, shift = escrow.call().findCumSum(NULL_ADDR, n_locked // 3, 1)
    assert miners[0].lower() == address_stop.lower()
    assert n_locked // 3 == shift

    address_stop, shift = escrow.call().findCumSum(NULL_ADDR, largest_locked, 1)
    assert miners[1].lower() == address_stop.lower()
    assert 0 == shift

    address_stop, shift = escrow.call().findCumSum(
        miners[1], largest_locked // 2 + 1, 1)
    assert miners[2].lower() == address_stop.lower()
    assert 1 == shift

    address_stop, shift = escrow.call().findCumSum(NULL_ADDR, 1, 10)
    assert NULL_ADDR != address_stop.lower()
    assert 0 != shift
    address_stop, shift = escrow.call().findCumSum(NULL_ADDR, 1, 11)
    assert NULL_ADDR == address_stop.lower()
    assert 0 == shift

    for index, _ in enumerate(miners[:-1]):
        address_stop, shift = escrow.call().findCumSum(NULL_ADDR, 1, index + 3)
        assert miners[index + 1].lower() == address_stop.lower()
        assert 1 == shift

    # Test miners iteration
    miner = NULL_ADDR
    i = 0
    while True:
        next_miner = escrow.call().getNextMiner(miner)
        if next_miner == NULL_ADDR:
            break
        assert miners[i].lower() == next_miner.lower()
        miner = next_miner
        i += 1


def test_mining(web3, chain, token, escrow_contract):
    escrow = escrow_contract(1500)
    creator = web3.eth.accounts[0]
    ursula = web3.eth.accounts[1]
    alice = web3.eth.accounts[2]

    # Give Escrow tokens for reward and initialize contract
    tx = token.transact({'from': creator}).transfer(escrow.address, 10 ** 9)
    chain.wait.for_receipt(tx)
    tx = escrow.transact().initialize()
    chain.wait.for_receipt(tx)

    policy_manager, _ = chain.provider.get_or_deploy_contract(
        'PolicyManagerMock', deploy_args=[token.address, escrow.address],
        deploy_transaction={'from': creator})
    tx = escrow.transact({'from': creator}).setPolicyManager(policy_manager.address)
    chain.wait.for_receipt(tx)

    # Give Ursula and Alice some coins
    tx = token.transact({'from': creator}).transfer(ursula, 10000)
    chain.wait.for_receipt(tx)
    tx = token.transact({'from': creator}).transfer(alice, 10000)
    chain.wait.for_receipt(tx)

    # Ursula can't confirm and mint because no locked tokens
    with pytest.raises(TransactionFailed):
        tx = escrow.transact({'from': ursula}).mint()
        chain.wait.for_receipt(tx)
    with pytest.raises(TransactionFailed):
        tx = escrow.transact({'from': ursula}).confirmActivity()
        chain.wait.for_receipt(tx)

    # Ursula and Alice give Escrow rights to transfer
    tx = token.transact({'from': ursula}).approve(escrow.address, 2000)
    chain.wait.for_receipt(tx)
    tx = token.transact({'from': alice}).approve(escrow.address, 500)
    chain.wait.for_receipt(tx)

    # Ursula and Alice transfer some tokens to the escrow and lock them
    tx = escrow.transact({'from': ursula}).deposit(1000, 1)
    chain.wait.for_receipt(tx)
    tx = escrow.transact({'from': alice}).deposit(500, 2)
    chain.wait.for_receipt(tx)

    # Using locked tokens starts from next period
    assert 0 == escrow.call().getAllLockedTokens()

    # Ursula can't use method from Miner contract
    with pytest.raises(TypeError):
        tx = escrow.transact({'from': ursula}).mint(ursula, 1, 1, 1, 1, 1)
        chain.wait.for_receipt(tx)

    # Only Ursula confirm next period
    wait_time(chain, 1)
    assert 1500 == escrow.call().getAllLockedTokens()
    tx = escrow.transact({'from': ursula}).confirmActivity()
    chain.wait.for_receipt(tx)

    # Checks that no error
    tx = escrow.transact({'from': ursula}).confirmActivity()
    chain.wait.for_receipt(tx)

    # Ursula and Alice mint tokens for last periods
    wait_time(chain, 1)
    assert 1000 == escrow.call().getAllLockedTokens()
    tx = escrow.transact({'from': ursula}).mint()
    chain.wait.for_receipt(tx)
    tx = escrow.transact({'from': alice}).mint()
    chain.wait.for_receipt(tx)
    assert 1050 == escrow.call().getTokens(ursula)
    assert 521 == escrow.call().getTokens(alice)

    events = escrow.pastEvents('Mined').get()
    assert 2 == len(events)
    event_args = events[0]['args']
    assert ursula.lower() == event_args['owner'].lower()
    assert 50 == event_args['value']
    assert escrow.call().getCurrentPeriod() - 1 == event_args['period']
    event_args = events[1]['args']
    assert alice.lower() == event_args['owner'].lower()
    assert 21 == event_args['value']
    assert escrow.call().getCurrentPeriod() - 1 == event_args['period']

    assert 1 == policy_manager.call().getPeriodsLength(ursula)
    assert 1 == policy_manager.call().getPeriodsLength(alice)
    period = escrow.call().getCurrentPeriod() - 1
    assert period == policy_manager.call().getPeriod(ursula, 0)
    assert period == policy_manager.call().getPeriod(alice, 0)

    # Only Ursula confirm activity for next period
    tx = escrow.transact({'from': ursula}).switchLock()
    chain.wait.for_receipt(tx)
    tx = escrow.transact({'from': ursula}).confirmActivity()
    chain.wait.for_receipt(tx)

    # Ursula can't confirm next period because end of locking
    wait_time(chain, 1)
    assert 500 == escrow.call().getAllLockedTokens()
    with pytest.raises(TransactionFailed):
        tx = escrow.transact({'from': ursula}).confirmActivity()
        chain.wait.for_receipt(tx)

    # But Alice can
    tx = escrow.transact({'from': alice}).confirmActivity()
    chain.wait.for_receipt(tx)

    # Ursula mint tokens for next period
    wait_time(chain, 1)
    assert 500 == escrow.call().getAllLockedTokens()
    tx = escrow.transact({'from': ursula}).mint()
    chain.wait.for_receipt(tx)
    # But Alice can't mining because she did not confirmed activity
    with pytest.raises(TransactionFailed):
        tx = escrow.transact({'from': alice}).mint()
        chain.wait.for_receipt(tx)
    assert 1163 == escrow.call().getTokens(ursula)
    assert 521 == escrow.call().getTokens(alice)

    assert 3 == policy_manager.call().getPeriodsLength(ursula)
    assert 1 == policy_manager.call().getPeriodsLength(alice)
    assert period + 1 == policy_manager.call().getPeriod(ursula, 1)
    assert period + 2 == policy_manager.call().getPeriod(ursula, 2)

    events = escrow.pastEvents('Mined').get()
    assert 3 == len(events)
    event_args = events[2]['args']
    assert ursula.lower() == event_args['owner'].lower()
    assert 113 == event_args['value']
    assert escrow.call().getCurrentPeriod() - 1 == event_args['period']

    # Alice confirm next period and mint tokens
    tx = escrow.transact({'from': alice}).switchLock()
    chain.wait.for_receipt(tx)
    tx = escrow.transact({'from': alice}).confirmActivity()
    chain.wait.for_receipt(tx)
    wait_time(chain, 2)
    assert 0 == escrow.call().getAllLockedTokens()
    tx = escrow.transact({'from': alice}).mint()
    chain.wait.for_receipt(tx)
    assert 1163 == escrow.call().getTokens(ursula)
    assert 634 == escrow.call().getTokens(alice)

    assert 3 == policy_manager.call().getPeriodsLength(ursula)
    assert 3 == policy_manager.call().getPeriodsLength(alice)
    assert period + 3 == policy_manager.call().getPeriod(alice, 1)
    assert period + 4 == policy_manager.call().getPeriod(alice, 2)

    events = escrow.pastEvents('Mined').get()
    assert 4 == len(events)
    event_args = events[3]['args']
    assert alice.lower() == event_args['owner'].lower()
    assert 113 == event_args['value']
    assert escrow.call().getCurrentPeriod() - 1 == event_args['period']

    # Ursula can't confirm and mint because no locked tokens
    with pytest.raises(TransactionFailed):
        tx = escrow.transact({'from': ursula}).mint()
        chain.wait.for_receipt(tx)
    with pytest.raises(TransactionFailed):
        tx = escrow.transact({'from': ursula}).confirmActivity()
        chain.wait.for_receipt(tx)

    # Ursula can lock some tokens again
    tx = escrow.transact({'from': ursula}).lock(500, 4)
    chain.wait.for_receipt(tx)
    tx = escrow.transact({'from': ursula}).switchLock()
    chain.wait.for_receipt(tx)
    assert 500 == escrow.call().getLockedTokens(ursula)
    assert 500 == escrow.call().calculateLockedTokens(ursula, 1)
    assert 375 == escrow.call().calculateLockedTokens(ursula, 2)
    assert 250 == escrow.call().calculateLockedTokens(ursula, 3)
    assert 0 == escrow.call().calculateLockedTokens(ursula, 5)
    # And can increase lock
    tx = escrow.transact({'from': ursula}).lock(100, 0)
    chain.wait.for_receipt(tx)
    assert 600 == escrow.call().getLockedTokens(ursula)
    assert 600 == escrow.call().calculateLockedTokens(ursula, 1)
    assert 450 == escrow.call().calculateLockedTokens(ursula, 2)
    assert 0 == escrow.call().calculateLockedTokens(ursula, 5)
    tx = escrow.transact({'from': ursula}).lock(0, 2)
    chain.wait.for_receipt(tx)
    assert 600 == escrow.call().getLockedTokens(ursula)
    assert 600 == escrow.call().calculateLockedTokens(ursula, 1)
    assert 450 == escrow.call().calculateLockedTokens(ursula, 2)
    assert 0 == escrow.call().calculateLockedTokens(ursula, 5)
    tx = escrow.transact({'from': ursula}).deposit(800, 1)
    chain.wait.for_receipt(tx)
    assert 1400 == escrow.call().getLockedTokens(ursula)
    assert 1400 == escrow.call().calculateLockedTokens(ursula, 1)
    assert 1000 == escrow.call().calculateLockedTokens(ursula, 3)
    assert 400 == escrow.call().calculateLockedTokens(ursula, 6)
    assert 0 == escrow.call().calculateLockedTokens(ursula, 8)

    # Alice can withdraw all
    tx = escrow.transact({'from': alice}).withdrawAll()
    chain.wait.for_receipt(tx)
    assert 10134 == token.call().balanceOf(alice)

    events = escrow.pastEvents('Withdrawn').get()
    assert 1 == len(events)
    event_args = events[0]['args']
    assert alice.lower() == event_args['owner'].lower()
    assert 634 == event_args['value']

    assert 3 == len(escrow.pastEvents('Deposited').get())
    assert 6 == len(escrow.pastEvents('Locked').get())
    assert 3 == len(escrow.pastEvents('LockSwitched').get())
    assert 10 == len(escrow.pastEvents('ActivityConfirmed').get())

    # TODO test max confirmed periods and miners


def test_pre_deposit(web3, chain, token, escrow_contract):
    escrow = escrow_contract(1500)
    creator = web3.eth.accounts[0]

    # Initialize Escrow contract
    tx = escrow.transact().initialize()
    chain.wait.for_receipt(tx)

    # Grant access to transfer tokens
    tx = token.transact({'from': creator}).approve(escrow.address, 10000)
    chain.wait.for_receipt(tx)

    # Deposit tokens for 1 owner
    owner = web3.eth.accounts[1]
    tx = escrow.transact({'from': creator}).preDeposit([owner], [1000], [10])
    chain.wait.for_receipt(tx)
    assert 1000 == token.call().balanceOf(escrow.address)
    assert 1000 == escrow.call().getTokens(owner)
    assert 1000 == escrow.call().getLockedTokens(owner)
    assert 10 == escrow.call().minerInfo(owner)[4]

    # Can't pre-deposit tokens again for same owner
    with pytest.raises(TransactionFailed):
        tx = escrow.transact({'from': creator}).preDeposit(
            [web3.eth.accounts[1]], [1000], [10])
        chain.wait.for_receipt(tx)

    # Can't pre-deposit tokens with too low or too high value
    with pytest.raises(TransactionFailed):
        tx = escrow.transact({'from': creator}).preDeposit(
            [web3.eth.accounts[2]], [1], [10])
        chain.wait.for_receipt(tx)
    with pytest.raises(TransactionFailed):
        tx = escrow.transact({'from': creator}).preDeposit(
            [web3.eth.accounts[2]], [1501], [10])
        chain.wait.for_receipt(tx)
    with pytest.raises(TransactionFailed):
        tx = escrow.transact({'from': creator}).preDeposit(
            [web3.eth.accounts[2]], [500], [1])
        chain.wait.for_receipt(tx)

    # Deposit tokens for multiple owners
    owners = web3.eth.accounts[2:7]
    tx = escrow.transact({'from': creator}).preDeposit(
        owners, [100, 200, 300, 400, 500], [50, 100, 150, 200, 250])
    chain.wait.for_receipt(tx)
    assert 2500 == token.call().balanceOf(escrow.address)
    for index, owner in enumerate(owners):
        assert 100 * (index + 1) == escrow.call().getTokens(owner)
        assert 100 * (index + 1) == escrow.call().getLockedTokens(owner)
        assert 50 * (index + 1) == escrow.call().minerInfo(owner)[4]

    events = escrow.pastEvents('Deposited').get()
    assert 6 == len(events)
    event_args = events[0]['args']
    assert web3.eth.accounts[1].lower() == event_args['owner'].lower()
    assert 1000 == event_args['value']
    assert 10 == event_args['periods']
    event_args = events[1]['args']
    assert owners[0].lower() == event_args['owner'].lower()
    assert 100 == event_args['value']
    assert 50 == event_args['periods']
    event_args = events[2]['args']
    assert owners[1].lower() == event_args['owner'].lower()
    assert 200 == event_args['value']
    assert 100 == event_args['periods']
    event_args = events[3]['args']
    assert owners[2].lower() == event_args['owner'].lower()
    assert 300 == event_args['value']
    assert 150 == event_args['periods']
    event_args = events[4]['args']
    assert owners[3].lower() == event_args['owner'].lower()
    assert 400 == event_args['value']
    assert 200 == event_args['periods']
    event_args = events[5]['args']
    assert owners[4].lower() == event_args['owner'].lower()
    assert 500 == event_args['value']
    assert 250 == event_args['periods']


def test_miner_id(web3, chain, token, escrow_contract):
    escrow = escrow_contract(5 * 10 ** 8)
    creator = web3.eth.accounts[0]
    miner = web3.eth.accounts[1]

    # Initialize contract and miner
    tx = escrow.transact().initialize()
    chain.wait.for_receipt(tx)
    tx = token.transact({'from': creator}).transfer(miner, 1000)
    chain.wait.for_receipt(tx)
    balance = token.call().balanceOf(miner)
    tx = token.transact({'from': miner}).approve(escrow.address, balance)
    chain.wait.for_receipt(tx)
    tx = escrow.transact({'from': miner}).deposit(balance, 1)
    chain.wait.for_receipt(tx)

    # Set miner ids
    miner_id = os.urandom(32)
    tx = escrow.transact({'from': miner}).setMinerId(miner_id)
    chain.wait.for_receipt(tx)
    assert 1 == escrow.call().getMinerIdsCount(miner)
    # TODO change when v4 of web3.py is released
    assert miner_id == escrow.call().getMinerId(miner, 0).encode('latin-1')
    miner_id = os.urandom(32)
    tx = escrow.transact({'from': miner}).setMinerId(miner_id)
    chain.wait.for_receipt(tx)
    assert 2 == escrow.call().getMinerIdsCount(miner)
    # TODO change when v4 of web3.py is released
    assert miner_id == escrow.call().getMinerId(miner, 1).encode('latin-1')
