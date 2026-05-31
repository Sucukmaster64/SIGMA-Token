import json
import os
from datetime import datetime

import requests
from flask import Flask, abort, jsonify, redirect, render_template, request

from blockchain import Blockchain, Transaction, Wallet

app = Flask(__name__)
blockchain = Blockchain()

PER_PAGE = 20

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
    )
    ok, msg = blockchain.add_transaction(tx)
    if not ok:
        return jsonify({"error": msg}), 400
    return jsonify({"message": msg, "tx_id": tx.tx_id}), 201


@app.route("/mine", methods=["POST"])
def mine():
    data = request.get_json()
    if not data or "miner_address" not in data:
        return jsonify({"error": "miner_address required"}), 400
    block = blockchain.mine(data["miner_address"])
    return jsonify({"message": "Block mined", "block": block.to_dict()}), 201


@app.route("/balance/<address>")
def balance(address):
    return jsonify({"address": address, "balance": blockchain.get_balance(address)})


@app.route("/address/<address>/history")
def address_history(address):
    return jsonify({"address": address, "transactions": blockchain.get_address_history(address)})


@app.route("/nodes/register", methods=["POST"])
def register_nodes():
    data = request.get_json()
    nodes = data.get("nodes", [])
    for node in nodes:
        blockchain.register_node(node)
    return jsonify({"message": f"Registered {len(nodes)} node(s)", "nodes": list(blockchain.nodes)})


@app.route("/nodes/sync", methods=["POST"])
def sync_nodes():
    replaced = False
    for node in list(blockchain.nodes):
        try:
            resp = requests.get(f"{node}/chain", timeout=5)
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
