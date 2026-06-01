# SIGMA-Token Development Plan

**Goal:** Personal local-network blockchain — multi-node, web UI, REST API

---

## Phase 1 — Foundation ✅
- [x] Remove MySQL dependency, use JSON file persistence (`data/chain.json`)
- [x] ECDSA secp256k1 wallet system (key generation, signing, address derivation)
- [x] Transaction model with signatures and validation
- [x] Mempool with balance/double-spend checks
- [x] Genesis block with initial supply
- [x] Mining with PoW (difficulty 4) and coinbase reward (50 SIGMA)
- [x] Flask app fully connected to blockchain
- [x] REST API: `/chain`, `/pending`, `/transactions/new`, `/mine`, `/balance/<addr>`, `/address/<addr>/history`, `/wallet/new`, `/wallet/send`, `/nodes/register`, `/nodes/sync`
- [x] Web UI: block explorer, block detail, address history, wallet page

## Phase 2 — Web UI Polish ✅
- [x] Pagination on explorer (20 blocks/page)
- [x] Smart search: address, block #, block hash, tx_id prefix (navbar + `/search` route)
- [x] Better mobile layout (collapsible navbar, hidden hash col on small screens, flex-wrap cards)
- [x] Named addresses — alias file (`data/aliases.json`), set/clear on address page, shown throughout UI

## Phase 3 — Multi-node Networking ✅
- [x] `/nodes/register` — add peer node URL
- [x] `/nodes/sync` — pull chain from peers, apply longest-chain consensus
- [x] Transaction broadcast (gossip with dedup) — new txs propagate to all peers
- [x] Block broadcast — mined blocks propagate instantly; lagging nodes auto-sync
- [x] UDP auto-discovery — set `NODE_URL` env var to enable LAN peer discovery
- [x] `/blocks/new` endpoint — accept peer-broadcast blocks with PoW validation
- [x] `/nodes` endpoint + Nodes UI page
- [x] Fixed critical bug: `timestamp=0.0` was falsy, giving each node a different genesis hash

## Phase 4 — Docker ✅
- [x] `Dockerfile` (python:3.11-slim, /data volume)
- [x] `docker-compose.yml` — 3 nodes on ports 5001–5003, peered via PEERS env var
- [x] `PEERS` env var — comma-separated URLs registered on startup
- [x] `NODE_URL`, `PORT`, `DATA_DIR`, `DEBUG`, `DISCOVERY_PORT` all configurable
- [x] Updated README with quickstart, Docker setup, env vars, full API + UI reference

---

## Running Locally

```bash
pip install -r requirements.txt
python app.py
# Open http://localhost:5000
```

Environment variables:
| Var | Default | Description |
|-----|---------|-------------|
| `PORT` | `5000` | Port to listen on |
| `DATA_DIR` | `data` | Directory for chain.json and nodes.json |
| `DEBUG` | `false` | Enable Flask debug mode |

---

## REST API Quick Reference

| Method | Endpoint | Body | Description |
|--------|----------|------|-------------|
| GET | `/chain` | — | Full chain as JSON |
| GET | `/pending` | — | Pending transactions (mempool) |
| POST | `/transactions/new` | `{sender, recipient, amount, public_key, signature, timestamp}` | Submit pre-signed transaction |
| POST | `/mine` | `{miner_address}` | Mine next block |
| GET | `/balance/<address>` | — | Get SIGMA balance |
| GET | `/address/<address>/history` | — | Transaction history |
| GET | `/wallet/new` | — | Generate new wallet (address + keys) |
| POST | `/wallet/send` | `{private_key_pem, recipient, amount}` | Sign & submit transaction |
| POST | `/nodes/register` | `{nodes: ["http://..."]}` | Register peer nodes |
| POST | `/nodes/sync` | — | Sync chain with all peers |
