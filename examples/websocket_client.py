"""WebSocket client example: connect to a running agent's API."""

from __future__ import annotations

import json
import urllib.request


def main() -> None:
    """Query a running agent node via the REST API."""
    base_url = "http://127.0.0.1:8080"

    print("--- Agent Identity ---")
    with urllib.request.urlopen(f"{base_url}/identity") as resp:
        data = json.loads(resp.read())
        print(f"  PeerID:  {data['peer_id']}")
        print(f"  Address: {data['eth_address']}")
        print(f"  Addrs:   {data['addrs']}")

    print("\n--- Peers ---")
    with urllib.request.urlopen(f"{base_url}/peers") as resp:
        data = json.loads(resp.read())
        print(f"  Count: {data['count']}")
        for p in data["peers"]:
            print(f"    {p['peer_id']}")

    print("\n--- Channels ---")
    with urllib.request.urlopen(f"{base_url}/channels") as resp:
        data = json.loads(resp.read())
        print(f"  Count: {data['count']}")
        for ch in data["channels"]:
            print(f"    {ch['channel_id'][:16]}... state={ch['state']} paid={ch['total_paid']}")

    print("\n--- Balance ---")
    with urllib.request.urlopen(f"{base_url}/balance") as resp:
        data = json.loads(resp.read())
        print(f"  Deposited: {data['total_deposited']} wei")
        print(f"  Paid:      {data['total_paid']} wei")
        print(f"  Remaining: {data['total_remaining']} wei")


if __name__ == "__main__":
    main()
