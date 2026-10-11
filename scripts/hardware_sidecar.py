import asyncio
import json
import argparse
from pathlib import Path
from web3 import Web3

# Path to your compiled contract metadata
ROOT = Path(__file__).resolve().parent.parent
BUILD_PATH = ROOT / 'build' / 'WorldTribe_compiled.json'
DEPLOYMENT_CONFIG_PATH = ROOT / 'config' / 'deployment.json'


def parse_args():
    parser = argparse.ArgumentParser(
        description="Listen for WorldTribe contract events using deployment config."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEPLOYMENT_CONFIG_PATH,
        help=f"Path to deployment config JSON. Default: {DEPLOYMENT_CONFIG_PATH}",
    )
    parser.add_argument(
        "--provider-url",
        default=None,
        help="Optional provider override. Falls back to the deployment config value.",
    )
    return parser.parse_args()


def load_deployment_config(config_path: Path) -> dict:
    if not config_path.exists():
        raise SystemExit(
            f"Deployment config not found at {config_path}. "
            "Run deploy_worldtribe.py against a reusable node first."
        )

    deployment = json.loads(config_path.read_text(encoding="utf-8"))
    contract_address = deployment.get("contract_address")
    if not contract_address:
        raise SystemExit("Deployment config is missing contract_address.")

    return deployment

def handle_crisis(event):
    """Trigger hardware response for CrisisSignaled event."""
    member = event['args']['member']
    print(f"🚨 [HARDWARE ALERT] Crisis detected for member: {member}")
    print(">>> Activating emergency mentorship protocols and hardware indicators...")
    # Example: GPIO.output(RED_LED_PIN, GPIO.HIGH)

def handle_new_member(event):
    """Trigger hardware response for MemberJoined event."""
    member = event['args']['member']
    balance = event['args']['initialBalance']
    print(f"🌍 [COMMUNITY] New member joined: {member} with {balance} credits.")
    # Example: play_welcome_sound()

async def log_loop(event_filter, poll_interval, callback):
    """Asynchronous loop to check for new entries in the event filter."""
    while True:
        for event in event_filter.get_new_entries():
            callback(event)
        await asyncio.sleep(poll_interval)

async def run_event_listeners(crisis_filter, join_filter, poll_interval=2):
    """Run both contract event listeners inside a single coroutine."""
    await asyncio.gather(
        log_loop(crisis_filter, poll_interval, handle_crisis),
        log_loop(join_filter, poll_interval, handle_new_member),
    )

def main():
    args = parse_args()

    # 1. Initialization
    if not BUILD_PATH.exists():
        print("Error: Contract metadata not found. Run compile_worldtribe.py first.")
        return

    compiled = json.loads(BUILD_PATH.read_text(encoding="utf-8"))
    deployment = load_deployment_config(args.config.resolve())
    provider_url = args.provider_url or deployment.get("provider_url")
    contract_address = deployment["contract_address"]

    if deployment.get("ephemeral") and not args.provider_url:
        raise SystemExit(
            "Deployment config points to an ephemeral tester deployment. "
            "Re-run deploy_worldtribe.py with --provider-url http://localhost:8545 "
            "or pass --provider-url here."
        )

    if not provider_url:
        raise SystemExit("No provider_url configured. Pass --provider-url or update deployment config.")

    w3 = Web3(Web3.HTTPProvider(provider_url))

    if not w3.is_connected():
        print("Failed to connect to the configured Ethereum provider.")
        return

    # 2. Setup Contract from deployment metadata
    contract_meta = compiled['contracts']['WorldTribe.sol']['WorldTribe']
    contract = w3.eth.contract(address=contract_address, abi=contract_meta['abi'])

    print(f"Listening for Tribe events on {contract_address} via {provider_url}...")

    # 3. Create Event Filters
    # Using 'latest' ensures we only catch new events from this point forward
    crisis_filter = contract.events.CrisisSignaled.create_filter(fromBlock='latest')
    join_filter = contract.events.MemberJoined.create_filter(fromBlock='latest')

    try:
        print("System active. Press Ctrl+C to exit.")
        asyncio.run(run_event_listeners(crisis_filter, join_filter))
    except KeyboardInterrupt:
        print("Hardware side-car shutting down.")

if __name__ == "__main__":
    main()
