# SIGMA-Token

A personal local-network blockchain built in Python. Features ECDSA wallets, signed transactions, proof-of-work mining, multi-node sync, and a web UI.

---

## Quick start (single node)

```bash
git clone https://github.com/Sucukmaster64/SIGMA-Token.git
cd SIGMA-Token
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000

---

## Multi-node setup (Docker)

Spin up 3 nodes that peer with each other automatically:

```bash
docker compose up --build
```

| Node | URL |
|------|-----|
| node1 | http://localhost:5001 |
| node2 | http://localhost:5002 |
| node3 | http://localhost:5003 |

Nodes register each other on startup and broadcast transactions and mined blocks in real time.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `5000` | HTTP port |
| `DATA_DIR` | `data` | Directory for chain.json, nodes.json, aliases.json |
| `NODE_URL` | _(empty)_ | This node's public URL — enables UDP LAN auto-discovery |
| `PEERS` | _(empty)_ | Comma-separated peer URLs to register on startup |
| `DISCOVERY_PORT` | `5999` | UDP port for LAN peer discovery |
| `DEBUG` | `false` | Enable Flask debug mode |

---

## REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/chain` | Full blockchain as JSON |
| GET | `/pending` | Pending transactions (mempool) |
| POST | `/transactions/new` | Submit a pre-signed transaction |
| POST | `/mine` | Mine next block `{"miner_address": "0x..."}` |
| POST | `/blocks/new` | Accept a peer-broadcast block |
| GET | `/balance/<address>` | Get SIGMA balance |
| GET | `/address/<address>/history` | Transaction history |
| GET | `/wallet/new` | Generate new wallet (address + keys) |
| POST | `/wallet/send` | Sign and submit a transaction `{"private_key_pem", "recipient", "amount"}` |
| GET | `/nodes` | List known peer nodes |
| POST | `/nodes/register` | Register peer nodes `{"nodes": ["http://..."]}` |
| POST | `/nodes/sync` | Sync chain with all peers (longest-chain wins) |
| GET | `/aliases` | Get all address aliases |
| POST | `/aliases` | Set/clear alias `{"address", "name"}` |

---

## Web UI

| Page | URL | Description |
|------|-----|-------------|
| Block Explorer | `/` | Paginated list of all blocks |
| Block Detail | `/block/<n>` | Transactions in a block |
| Address | `/address/<addr>` | Balance + history + alias |
| Wallet | `/wallet` | Create wallet, check balance, send SIGMA, mine |
| Nodes | `/nodes-ui` | Add peers, sync, live peer status |
