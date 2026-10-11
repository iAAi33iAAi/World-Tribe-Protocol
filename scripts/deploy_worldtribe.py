import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from web3 import Web3
from web3.providers.eth_tester import EthereumTesterProvider


ROOT = Path(__file__).resolve().parent.parent
BUILD_PATH = ROOT / "build" / "WorldTribe_compiled.json"
DEFAULT_CONFIG_PATH = ROOT / "config" / "deployment.json"
DEFAULT_PROVIDER_URL = "http://localhost:8545"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deploy the WorldTribe contract and write deployment metadata."
    )
    parser.add_argument(
        "--provider-url",
        default=None,
        help=(
            "Ethereum JSON-RPC URL. If omitted, uses an in-memory tester chain for "
            "a smoke deployment."
        ),
    )
    parser.add_argument(
        "--config-out",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to write deployment config. Default: {DEFAULT_CONFIG_PATH}",
    )
    return parser.parse_args()


def load_compiled_contract() -> dict:
    if not BUILD_PATH.exists():
        raise SystemExit(
            f"Compiled artifact not found at {BUILD_PATH}. Run compile_worldtribe.py first."
        )

    compiled = json.loads(BUILD_PATH.read_text(encoding="utf-8"))
    try:
        return compiled["contracts"]["WorldTribe.sol"]["WorldTribe"]
    except KeyError as exc:
        raise SystemExit("Compiled artifact is missing WorldTribe contract metadata.") from exc


def get_web3(provider_url: str | None) -> tuple[Web3, bool]:
    if provider_url:
        return Web3(Web3.HTTPProvider(provider_url)), False
    return Web3(EthereumTesterProvider()), True


def deploy_contract(w3: Web3, contract_meta: dict) -> tuple[str, str, int]:
    abi = contract_meta["abi"]
    bytecode = contract_meta["evm"]["bytecode"]["object"]

    if not w3.eth.accounts:
        raise SystemExit("No accounts available from the configured provider.")

    w3.eth.default_account = w3.eth.accounts[0]
    contract_factory = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx_hash = contract_factory.constructor().transact()
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    return receipt.contractAddress, receipt.transactionHash.hex(), receipt.blockNumber


def write_deployment_config(
    out_path: Path,
    provider_url: str | None,
    contract_address: str,
    transaction_hash: str,
    deployment_block: int,
    ephemeral: bool,
) -> Path:
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    deployment = {
        "contract_name": "WorldTribe",
        "source": "WorldTribe.sol",
        "contract_address": contract_address,
        "transaction_hash": transaction_hash,
        "deployment_block": deployment_block,
        "provider_url": provider_url,
        "ephemeral": ephemeral,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "notes": (
            "Ephemeral eth-tester deployment. Re-run with --provider-url for a reusable node."
            if ephemeral
            else "Deployment config for sidecar and dashboard consumers."
        ),
    }
    out_path.write_text(json.dumps(deployment, indent=2) + "\n", encoding="utf-8")
    return out_path


def main() -> None:
    args = parse_args()
    contract_meta = load_compiled_contract()
    w3, ephemeral = get_web3(args.provider_url)

    if not w3.is_connected():
        if ephemeral:
            raise SystemExit("Failed to connect to the in-memory eth-tester provider.")
        raise SystemExit("Failed to connect to the configured JSON-RPC provider.")

    contract_address, transaction_hash, deployment_block = deploy_contract(w3, contract_meta)
    config_path = write_deployment_config(
        args.config_out,
        args.provider_url,
        contract_address,
        transaction_hash,
        deployment_block,
        ephemeral,
    )

    print(f"Deployed WorldTribe to {contract_address}")
    print(f"Deployment config written to {config_path}")
    if ephemeral:
        print("Note: this deployment lives only in the current process.")


if __name__ == "__main__":
    main()
