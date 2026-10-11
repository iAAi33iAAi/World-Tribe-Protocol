import json
import asyncio
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
build_path = root / 'build' / 'WorldTribe_compiled.json'
sys.path.insert(0, str(root / 'scripts'))

with open(build_path) as f:
    compiled = json.load(f)
import pytest
from web3 import Web3
from web3.providers.eth_tester import EthereumTesterProvider
import hardware_sidecar

@pytest.fixture
def w3():
    return Web3(EthereumTesterProvider())

@pytest.fixture
def contract(w3):
    # Optimization: Extract metadata once from the module-level 'compiled' object
    contract_meta = compiled['contracts']['WorldTribe.sol']['WorldTribe']
    abi = contract_meta['abi']
    bytecode = contract_meta['evm']['bytecode']['object']
    
    w3.eth.default_account = w3.eth.accounts[0]
    world_tribe_factory = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx_hash = world_tribe_factory.constructor().transact()
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    return w3.eth.contract(address=receipt.contractAddress, abi=abi)

def test_baseline_value(contract):
    assert contract.functions.BASELINE().call() == 1000

def test_join_tribe(w3, contract):
    user = w3.eth.accounts[1]
    tx = contract.functions.joinTribe().transact({'from': user})
    receipt = w3.eth.wait_for_transaction_receipt(tx)
    
    # Verify State
    member = contract.functions.tribe(user).call()
    assert member[0] is True # isSovereign
    assert member[1] == 1000 # creditBalance
    assert member[2] is False # inCrisis

    # Verify Event Emission
    event_logs = contract.events.MemberJoined().process_receipt(receipt)
    assert len(event_logs) == 1
    assert event_logs[0]['args']['member'] == user
    assert event_logs[0]['args']['initialBalance'] == 1000

def test_red_alert(w3, contract):
    user = w3.eth.accounts[0]
    contract.functions.joinTribe().transact({'from': user})
    
    tx_hash = contract.functions.triggerRedAlert().transact({'from': user})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    member = contract.functions.tribe(user).call()
    assert member[2] is True

    # Verify CrisisSignaled Event
    logs = contract.events.CrisisSignaled().process_receipt(receipt)
    assert len(logs) == 1, "Crisis event not emitted"

def test_maintain_equilibrium(w3, contract):
    user = w3.eth.accounts[0]
    maintainer = w3.eth.accounts[1]
    contract.functions.joinTribe().transact({'from': user})
    
    # 1. Spend credits to drop below BASELINE
    contract.functions.spendCredits(500).transact({'from': user})
    mid_member = contract.functions.tribe(user).call()
    assert mid_member[1] == 500, "Credit spending failed"

    # 2. Trigger maintenance
    tx = contract.functions.maintainEquilibrium(user).transact({'from': maintainer})
    w3.eth.wait_for_transaction_receipt(tx)
    
    # 3. Verify restoration
    member = contract.functions.tribe(user).call()
    assert member[1] == 1000, "Equilibrium restoration failed"

@pytest.mark.parametrize("account_index", [2, 3, 4, 5])
def test_multi_account_onboarding(w3, contract, account_index):
    """Tests that multiple independent accounts can join and maintain state."""
    user = w3.eth.accounts[account_index]
    
    # Each account joins the tribe independently
    contract.functions.joinTribe().transact({'from': user})
    
    member = contract.functions.tribe(user).call()
    assert member[0] is True  # isSovereign
    assert member[1] == 1000  # creditBalance

def test_owner_can_set_baseline(w3, contract):
    old_baseline = contract.functions.BASELINE().call()
    owner = w3.eth.accounts[0]
    new_value = 2000
    tx_hash = contract.functions.setBaseline(new_value).transact({'from': owner})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    
    assert contract.functions.BASELINE().call() == new_value

    # Verify BaselineUpdated Event
    logs = contract.events.BaselineUpdated().process_receipt(receipt)
    assert logs[0]['args']['oldBaseline'] == old_baseline
    assert logs[0]['args']['newBaseline'] == new_value

def test_non_owner_cannot_set_baseline(w3, contract):
    non_owner = w3.eth.accounts[1]
    # Using a more specific error check is better practice
    with pytest.raises(Exception, match="revert"):
        contract.functions.setBaseline(5000).transact({'from': non_owner})


def test_nonmember_cannot_trigger_red_alert(w3, contract):
    nonmember = w3.eth.accounts[1]
    with pytest.raises(Exception, match="revert"):
        contract.functions.triggerRedAlert().transact({"from": nonmember})

    member = contract.functions.tribe(nonmember).call()
    assert member[0] is False
    assert member[2] is False


def test_nonmember_cannot_be_replenished(w3, contract):
    nonmember = w3.eth.accounts[1]
    with pytest.raises(Exception, match="revert"):
        contract.functions.maintainEquilibrium(nonmember).transact(
            {"from": w3.eth.accounts[0]}
        )

    member = contract.functions.tribe(nonmember).call()
    assert member[0] is False
    assert member[1] == 0


def test_owner_cannot_set_zero_baseline(w3, contract):
    owner = w3.eth.accounts[0]
    with pytest.raises(Exception, match="revert"):
        contract.functions.setBaseline(0).transact({"from": owner})

    assert contract.functions.BASELINE().call() == 1000


def test_run_event_listeners_starts_both_loops(monkeypatch):
    calls = []

    async def fake_log_loop(event_filter, poll_interval, callback):
        calls.append((event_filter, poll_interval, callback.__name__))

    monkeypatch.setattr(hardware_sidecar, "log_loop", fake_log_loop)

    asyncio.run(hardware_sidecar.run_event_listeners("crisis", "join", poll_interval=3))

    assert calls == [
        ("crisis", 3, "handle_crisis"),
        ("join", 3, "handle_new_member"),
    ]
