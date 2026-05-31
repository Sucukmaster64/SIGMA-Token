import json
import os
import socket
import threading
import time
from datetime import datetime

import requests
from flask import Flask, abort, jsonify, redirect, render_template, request

from blockchain import Block, Blockchain, Transaction, Wallet

app = Flask(__name__)
blockchain = Blockchain()

PER_PAGE = 20
NODE_URL = os.environ.get("NODE_URL", "").rstrip("/")
DISCOVERY_PORT = int(os.environ.get("DISCOVERY_PORT", "5999"))
# Bypass any HTTP proxy for peer-to-peer calls (proxies interfere with LAN traffic)
_NO_PROXY = {"http": None, "https": None}

# ── Aliases ───────────────────────────────────────────────────────────────────

_aliases: dict[str, str] = {}


def _aliases_path() -> str:
    return os.path.join(blockchain.data_dir, "aliases.json")


def _load_aliases():
    global _aliases
    p = _aliases_path()
    if os.path.exists(p):
        with open(p) as f:
            _aliases = json.load(f)


def _save_aliases():
    with open(_aliases_path(), "w") as f:
        json.dump(_aliases, f, indent=2)


_load_aliases()


@app.context_processor
def inject_aliases():
    return {"aliases": _aliases}


@app.template_filter("dt")
def dt_filter(value):
    if float(value) == 0:
        return "Genesis"
    return datetime.fromtimestamp(float(value)).strftime("%Y-%m-%d %H:%M:%S")


# ── Networking helpers ────────────────────────────────────────────────────────


def _broadcast(path: str, payload: dict):
    """Fire-and-forget POST to all known peer nodes."""
    def _send(url):
        try:
            requests.post(url, json=payload, timeout=3, proxies=_NO_PROXY)
        except Exception:
            pass
    for node in list(blockchain.nodes):
        threading.Thread(target=_send, args=(f"{node}{path}",), daemon=True).start()


def _sync_all():
    """Pull chains from all peers and apply longest-chain consensus."""
    for node in list(blockchain.nodes):
        try:
            resp = requests.get(f"{node}/chain", timeout=5, proxies=_NO_PROXY)
            if resp.status_code == 200:
                remote_chain = Blockchain.chain_from_list(resp.json()["chain"])
                blockchain.replace_chain(remote_chain)
        except requests.RequestException:
            pass


# ── UDP auto-discovery ────────────────────────────────────────────────────────


def _discovery_sender():
    """Broadcast our URL via UDP every 30 s so peers on the LAN find us."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    msg = json.dumps({"sigma_node": NODE_URL}).encode()
    while True:
        try:
            sock.sendto(msg, ("<broadcast>", DISCOVERY_PORT))
        except Exception:
            pass
        time.sleep(30)


def _discovery_listener():
    """Listen for UDP broadcasts and register new peers automatically."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", DISCOVERY_PORT))
    while True:
        try:
            data, _ = sock.recvfrom(1024)
            msg = json.loads(data.decode())
            peer_url = msg.get("sigma_node", "").rstrip("/")
            if peer_url and peer_url != NODE_URL and peer_url not in blockchain.nodes:
                blockchain.register_node(peer_url)
        except Exception:
            pass


if NODE_URL:
    threading.Thread(target=_discovery_sender, daemon=True).start()
    threading.Thread(target=_discovery_listener, daemon=True).start()


# ── REST API ──────────────────────────────────────────────────────────────────


@app.route("/chain")
def get_chain():
    return jsonify({"chain": blockchain.chain_to_list(), "length": len(blockchain.chain)})


@app.route("/pending")
def get_pending():
    return jsonify({"transactions": [t.to_dict() for t in blockchain.mempool]})


@app.route("/transactions/new", methods=["POST"])
def new_transaction():
    data = request.get_json()
    required = ["sender", "recipient", "amount", "public_key", "signature", "timestamp"]
    if not all(k in data for k in required):
        return jsonify({"error": "Missing fields"}), 400
    tx = Transaction(
        sender=data["sender"],
        recipient=data["recipient"],
        amount=float(data["amount"]),
        public_key=data["public_key"],
        signature=data["signature"],
        timestamp=float(data["timestamp"]),
        tx_id=data.get("tx_id"),
    )
    ok, msg = blockchain.add_transaction(tx)
    if not ok:
        return jsonify({"error": msg}), 400
    _broadcast("/transactions/new", tx.to_dict())
    return jsonify({"message": msg, "tx_id": tx.tx_id}), 201


@app.route("/mine", methods=["POST"])
def mine():
    data = request.get_json()
    if not data or "miner_address" not in data:
        return jsonify({"error": "miner_address required"}), 400
    block = blockchain.mine(data["miner_address"])
    _broadcast("/blocks/new", block.to_dict())
    return jsonify({"message": "Block mined", "block": block.to_dict()}), 201


@app.route("/blocks/new", methods=["POST"])
def new_block():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    try:
        block = Block.from_dict(data)
    except Exception:
        return jsonify({"error": "Invalid block data"}), 400
    if blockchain.add_block(block):
        _broadcast("/blocks/new", block.to_dict())
        return jsonify({"message": "Block accepted"}), 201
    if block.index > len(blockchain.chain):
        threading.Thread(target=_sync_all, daemon=True).start()
        return jsonify({"message": "Behind, syncing"}), 202
    return jsonify({"message": "Block rejected"}), 400


@app.route("/balance/<address>")
def balance(address):
    return jsonify({"address": address, "balance": blockchain.get_balance(address)})


@app.route("/address/<address>/history")
def address_history(address):
    return jsonify({"address": address, "transactions": blockchain.get_address_history(address)})


@app.route("/nodes", methods=["GET"])
def list_nodes():
    return jsonify({"nodes": sorted(blockchain.nodes), "count": len(blockchain.nodes)})


@app.route("/nodes/register", methods=["POST"])
def register_nodes():
    data = request.get_json()
    nodes = data.get("nodes", [])
    for node in nodes:
        blockchain.register_node(node)
    return jsonify({"message": f"Registered {len(nodes)} node(s)", "nodes": sorted(blockchain.nodes)})


@app.route("/nodes/sync", methods=["POST"])
def sync_nodes():
    replaced = False
    for node in list(blockchain.nodes):
        try:
            resp = requests.get(f"{node}/chain", timeout=5, proxies=_NO_PROXY)
            if resp.status_code == 200:
                remote_chain = Blockchain.chain_from_list(resp.json()["chain"])
                if blockchain.replace_chain(remote_chain):
                    replaced = True
        except requests.RequestException:
            pass
    return jsonify({"replaced": replaced, "length": len(blockchain.chain)})


@app.route("/wallet/new")
def new_wallet():
    w = Wallet()
    return jsonify({
        "address": w.address,
        "public_key": w.public_key_hex,
        "private_key_pem": w.private_key_pem,
    })


@app.route("/wallet/send", methods=["POST"])
def wallet_send():
    """Sign and submit a transaction using a private key. LAN-only convenience endpoint."""
    data = request.get_json()
    required = ["private_key_pem", "recipient", "amount"]
    if not all(k in data for k in required):
        return jsonify({"error": "Missing fields"}), 400
    try:
        wallet = Wallet(data["private_key_pem"])
    except Exception:
        return jsonify({"error": "Invalid private key"}), 400
    tx = Transaction(wallet.address, data["recipient"], float(data["amount"]))
    tx.sign(wallet)
    ok, msg = blockchain.add_transaction(tx)
    if not ok:
        return jsonify({"error": msg}), 400
    _broadcast("/transactions/new", tx.to_dict())
    return jsonify({"message": msg, "tx_id": tx.tx_id, "from": wallet.address}), 201


@app.route("/aliases", methods=["GET"])
def get_aliases_api():
    return jsonify(_aliases)


@app.route("/aliases", methods=["POST"])
def set_alias():
    data = request.get_json()
    if not data or "address" not in data or "name" not in data:
        return jsonify({"error": "Missing fields"}), 400
    address = data["address"].strip()
    name = data["name"].strip()
    if name:
        _aliases[address] = name
    else:
        _aliases.pop(address, None)
    _save_aliases()
    return jsonify({"ok": True})


# ── Web UI ────────────────────────────────────────────────────────────────────


@app.route("/")
def index():
    page = max(1, request.args.get("page", 1, type=int))
    chain = list(reversed(blockchain.chain))
    total = len(chain)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = min(page, total_pages)
    start = (page - 1) * PER_PAGE
    return render_template(
        "index.html",
        chain=chain[start: start + PER_PAGE],
        length=total,
        mempool_count=len(blockchain.mempool),
        page=page,
        total_pages=total_pages,
    )


@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return redirect("/")
    if q.lower().startswith("0x"):
        return redirect(f"/address/{q}")
    if q.isdigit():
        idx = int(q)
        if idx < len(blockchain.chain):
            return redirect(f"/block/{idx}")
    for block in blockchain.chain:
        if block.hash == q or block.hash.startswith(q):
            return redirect(f"/block/{block.index}")
    for block in blockchain.chain:
        for tx in block.transactions:
            if tx.tx_id == q or tx.tx_id.startswith(q):
                return redirect(f"/block/{block.index}?highlight={tx.tx_id}")
    return redirect(f"/address/{q}")


@app.route("/block/<int:index>")
def block_detail(index):
    if index >= len(blockchain.chain):
        abort(404)
    highlight = request.args.get("highlight", "")
    return render_template(
        "block.html",
        block=blockchain.chain[index],
        total_blocks=len(blockchain.chain),
        highlight=highlight,
    )


@app.route("/wallet")
def wallet_page():
    return render_template("wallet.html", mining_reward=blockchain.mining_reward)


@app.route("/address/<address>")
def address_page(address):
    txs = blockchain.get_address_history(address)
    page = max(1, request.args.get("page", 1, type=int))
    total = len(txs)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = min(page, total_pages)
    start = (page - 1) * PER_PAGE
    return render_template(
        "address.html",
        address=address,
        transactions=txs[start: start + PER_PAGE],
        total_txs=total,
        balance=blockchain.get_balance(address),
        page=page,
        total_pages=total_pages,
        alias=_aliases.get(address, ""),
    )


@app.route("/nodes-ui")
def nodes_ui():
    return render_template(
        "nodes.html",
        nodes=sorted(blockchain.nodes),
        node_url=NODE_URL,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
