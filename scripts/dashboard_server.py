import argparse
import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from web3 import Web3


ROOT = Path(__file__).resolve().parent.parent
BUILD_PATH = ROOT / "build" / "WorldTribe_compiled.json"
DEFAULT_CONFIG_PATH = ROOT / "config" / "deployment.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Serve the World Tribe dashboard and expose live contract state."
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface for the dashboard server. Default: 127.0.0.1",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for the dashboard server. Default: 8000",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to deployment config JSON. Default: {DEFAULT_CONFIG_PATH}",
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


def load_deployment(config_path: Path) -> dict:
    if not config_path.exists():
        raise SystemExit(
            f"Deployment config not found at {config_path}. "
            "Run deploy_worldtribe.py first."
        )

    deployment = json.loads(config_path.read_text(encoding="utf-8"))
    if not deployment.get("contract_address"):
        raise SystemExit("Deployment config is missing contract_address.")
    if not deployment.get("provider_url"):
        raise SystemExit(
            "Deployment config is missing provider_url. "
            "Deploy with --provider-url http://localhost:8545 for dashboard use."
        )
    if deployment.get("ephemeral"):
        raise SystemExit(
            "Deployment config points to an ephemeral tester deployment. "
            "Deploy against a reusable node before starting the dashboard server."
        )
    return deployment


def get_contract(config_path: Path):
    deployment = load_deployment(config_path.resolve())
    contract_meta = load_compiled_contract()
    w3 = Web3(Web3.HTTPProvider(deployment["provider_url"]))
    if not w3.is_connected():
        raise SystemExit("Failed to connect to the configured Ethereum provider.")
    contract = w3.eth.contract(
        address=deployment["contract_address"],
        abi=contract_meta["abi"],
    )
    return w3, contract, deployment


def public_deployment_summary(deployment: dict) -> dict:
    """Expose non-secret deployment metadata without returning the RPC endpoint."""
    return {
        "contract_address": deployment["contract_address"],
        "provider_configured": bool(deployment.get("provider_url")),
        "deployment_block": deployment.get("deployment_block"),
        "generated_at": deployment.get("generated_at"),
    }


def build_status(config_path: Path) -> dict:
    w3, contract, deployment = get_contract(config_path)
    latest_block = w3.eth.block_number
    from_block = deployment.get("deployment_block", 0) or 0

    join_logs = contract.events.MemberJoined.get_logs(from_block=from_block, to_block=latest_block)
    crisis_logs = contract.events.CrisisSignaled.get_logs(
        from_block=from_block, to_block=latest_block
    )
    baseline_logs = contract.events.BaselineUpdated.get_logs(
        from_block=from_block, to_block=latest_block
    )

    members = []
    crisis_members = []
    for log in join_logs:
        member_address = log["args"]["member"]
        member_state = contract.functions.tribe(member_address).call()
        member_snapshot = {
            "address": member_address,
            "is_sovereign": member_state[0],
            "credit_balance": member_state[1],
            "in_crisis": member_state[2],
            "joined_block": log["blockNumber"],
        }
        members.append(member_snapshot)
        if member_snapshot["in_crisis"]:
            crisis_members.append(member_address)

    recent_events = []
    for log in join_logs[-5:]:
        recent_events.append(
            {
                "type": "MemberJoined",
                "member": log["args"]["member"],
                "block": log["blockNumber"],
            }
        )
    for log in crisis_logs[-5:]:
        recent_events.append(
            {
                "type": "CrisisSignaled",
                "member": log["args"]["member"],
                "block": log["blockNumber"],
            }
        )
    for log in baseline_logs[-5:]:
        recent_events.append(
            {
                "type": "BaselineUpdated",
                "old_baseline": log["args"]["oldBaseline"],
                "new_baseline": log["args"]["newBaseline"],
                "block": log["blockNumber"],
            }
        )
    recent_events.sort(key=lambda item: item["block"], reverse=True)

    return {
        "deployment": public_deployment_summary(deployment),
        "contract": {
            "owner": contract.functions.owner().call(),
            "baseline": contract.functions.BASELINE().call(),
            "latest_block": latest_block,
            "member_count": len(members),
            "crisis_count": len(crisis_members),
            "members": members,
            "recent_events": recent_events[:8],
        },
    }


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, config_path: Path, **kwargs):
        self.config_path = config_path
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self.handle_status()
            return
        if parsed.path not in {"/", "/index.html"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        # Only serve the public dashboard entry point. Do not expose source,
        # build artifacts, deployment configuration, or other repository files.
        super().do_GET()

    def do_HEAD(self):
        parsed = urlparse(self.path)
        if parsed.path not in {"/", "/index.html"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        # Keep HEAD parity with GET so it cannot bypass the static-path allowlist.
        super().do_HEAD()

    def handle_status(self):
        try:
            payload = build_status(self.config_path)
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(HTTPStatus.OK)
        except SystemExit as exc:
            body = json.dumps({"error": str(exc)}, indent=2).encode("utf-8")
            self.send_response(HTTPStatus.BAD_REQUEST)

        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    args = parse_args()

    def handler(*handler_args, **handler_kwargs):
        return DashboardHandler(
            *handler_args,
            config_path=args.config.resolve(),
            **handler_kwargs,
        )

    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving dashboard at http://{args.host}:{args.port}")
    print("API endpoint: /api/status")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard server shutting down.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
