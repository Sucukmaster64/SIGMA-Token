import base64
import hashlib
import json
import os
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import ECDSA, SECP256K1, EllipticCurvePublicKey

MINING_REWARD = 50.0
DIFFICULTY = 4
DATA_DIR = os.environ.get("DATA_DIR", "data")


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


class Wallet:
    """ECDSA secp256k1 wallet — key generation, signing, address derivation."""

    def __init__(self, private_key_pem: str = None):
        if private_key_pem:
            self._priv = serialization.load_pem_private_key(
                private_key_pem.encode(), password=None
            )
        else:
            self._priv = ec.generate_private_key(SECP256K1())

    @property
    def address(self) -> str:
        return Wallet.address_from_pubkey(self.public_key_hex)

    @property
    def public_key_hex(self) -> str:
        return self._priv.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.CompressedPoint,
        ).hex()

    @property
    def private_key_pem(self) -> str:
        return self._priv.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()

    def sign(self, message: str) -> str:
        sig = self._priv.sign(message.encode(), ECDSA(hashes.SHA256()))
        return base64.b64encode(sig).decode()

    @staticmethod
    def address_from_pubkey(pubkey_hex: str) -> str:
        raw = bytes.fromhex(pubkey_hex)
        return "0x" + hashlib.sha256(raw).hexdigest()[:40]

    @staticmethod
    def verify(pubkey_hex: str, message: str, signature_b64: str) -> bool:
        try:
            raw = bytes.fromhex(pubkey_hex)
            pub = EllipticCurvePublicKey.from_encoded_point(SECP256K1(), raw)
            sig = base64.b64decode(signature_b64)
            pub.verify(sig, message.encode(), ECDSA(hashes.SHA256()))
            return True
        except (InvalidSignature, Exception):
            return False


class Transaction:
    def __init__(
        self,
        sender: str,
        recipient: str,
        amount: float,
        public_key: str = "",
        signature: str = "",
        timestamp: float = None,
        tx_id: str = None,
    ):
        self.sender = sender
        self.recipient = recipient
        self.amount = amount
        self.public_key = public_key
        self.signature = signature
        self.timestamp = timestamp if timestamp is not None else time.time()
        self.tx_id = tx_id or _sha256(f"{sender}{recipient}{amount}{self.timestamp}")

    def _payload(self) -> str:
        return f"{self.sender}{self.recipient}{self.amount}{self.timestamp}"

    def sign(self, wallet: Wallet):
        self.public_key = wallet.public_key_hex
        self.signature = wallet.sign(self._payload())

    def is_valid(self) -> bool:
        if self.sender == "COINBASE":
            return True
        if not self.public_key or not self.signature:
            return False
        if Wallet.address_from_pubkey(self.public_key) != self.sender:
            return False
        return Wallet.verify(self.public_key, self._payload(), self.signature)

    def to_dict(self) -> dict:
        return {
            "tx_id": self.tx_id,
            "sender": self.sender,
            "recipient": self.recipient,
            "amount": self.amount,
            "public_key": self.public_key,
            "signature": self.signature,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Transaction":
        return cls(
            sender=d["sender"],
            recipient=d["recipient"],
            amount=d["amount"],
            public_key=d.get("public_key", ""),
            signature=d.get("signature", ""),
            timestamp=d["timestamp"],
            tx_id=d.get("tx_id"),
        )


class Block:
    def __init__(
        self,
        index: int,
        transactions: list,
        previous_hash: str,
        nonce: int = 0,
        timestamp: float = None,
        hash: str = None,
    ):
        self.index = index
        self.transactions = transactions
        self.previous_hash = previous_hash
        self.nonce = nonce
        self.timestamp = timestamp if timestamp is not None else time.time()
        self.hash = hash or self.compute_hash()

    def compute_hash(self) -> str:
        content = json.dumps(
            {
                "index": self.index,
                "transactions": [t.to_dict() for t in self.transactions],
                "previous_hash": self.previous_hash,
                "nonce": self.nonce,
                "timestamp": self.timestamp,
            },
            sort_keys=True,
        )
        return hashlib.sha256(content.encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "transactions": [t.to_dict() for t in self.transactions],
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
            "timestamp": self.timestamp,
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Block":
        return cls(
            index=d["index"],
            transactions=[Transaction.from_dict(t) for t in d["transactions"]],
            previous_hash=d["previous_hash"],
            nonce=d["nonce"],
            timestamp=d["timestamp"],
            hash=d["hash"],
        )


class Blockchain:
    def __init__(self, data_dir: str = DATA_DIR):
        self.difficulty = DIFFICULTY
        self.mining_reward = MINING_REWARD
        self.data_dir = data_dir
        self.chain: list[Block] = []
        self.mempool: list[Transaction] = []
        self.nodes: set[str] = set()

        os.makedirs(data_dir, exist_ok=True)
        self._load()
        if not self.chain:
            self._create_genesis()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _chain_path(self):
        return os.path.join(self.data_dir, "chain.json")

    def _nodes_path(self):
        return os.path.join(self.data_dir, "nodes.json")

    def _load(self):
        if os.path.exists(self._chain_path()):
            with open(self._chain_path()) as f:
                self.chain = [Block.from_dict(b) for b in json.load(f)]
        if os.path.exists(self._nodes_path()):
            with open(self._nodes_path()) as f:
                self.nodes = set(json.load(f))

    def _save_chain(self):
        with open(self._chain_path(), "w") as f:
            json.dump([b.to_dict() for b in self.chain], f, indent=2)

    def _save_nodes(self):
        with open(self._nodes_path(), "w") as f:
            json.dump(list(self.nodes), f, indent=2)

    # ── Genesis ───────────────────────────────────────────────────────────────

    def _create_genesis(self):
        genesis_tx = Transaction(
            "COINBASE",
            "genesis",
            self.mining_reward * 1000,
            timestamp=0.0,
            tx_id="genesis_coinbase",
        )
        genesis = Block(
            index=0,
            transactions=[genesis_tx],
            previous_hash="0" * 64,
            nonce=0,
            timestamp=0.0,
        )
        genesis.hash = genesis.compute_hash()
        self.chain.append(genesis)
        self._save_chain()

    # ── Balances ──────────────────────────────────────────────────────────────

    def get_balance(self, address: str) -> float:
        balance = 0.0
        for block in self.chain:
            for tx in block.transactions:
                if tx.recipient == address:
                    balance += tx.amount
                if tx.sender == address:
                    balance -= tx.amount
        return round(balance, 8)

    def get_address_history(self, address: str) -> list[dict]:
        result = []
        for block in self.chain:
            for tx in block.transactions:
                if tx.sender == address or tx.recipient == address:
                    d = tx.to_dict()
                    d["block_index"] = block.index
                    result.append(d)
        return sorted(result, key=lambda x: x["timestamp"], reverse=True)

    # ── Mempool ───────────────────────────────────────────────────────────────

    def add_transaction(self, tx: Transaction) -> tuple[bool, str]:
        if any(t.tx_id == tx.tx_id for t in self.mempool):
            return False, "Already in mempool"
        for block in self.chain:
            if any(t.tx_id == tx.tx_id for t in block.transactions):
                return False, "Already confirmed"
        if not tx.is_valid():
            return False, "Invalid signature"
        if tx.sender != "COINBASE":
            balance = self.get_balance(tx.sender)
            pending_out = sum(t.amount for t in self.mempool if t.sender == tx.sender)
            if balance - pending_out < tx.amount:
                return False, "Insufficient balance"
        self.mempool.append(tx)
        return True, "Transaction added to mempool"

    def add_block(self, block: Block) -> bool:
        """Accept a peer-broadcast block if it extends our current chain."""
        if block.index != len(self.chain):
            return False
        if block.previous_hash != self.chain[-1].hash:
            return False
        if block.hash != block.compute_hash():
            return False
        if not block.hash.startswith("0" * self.difficulty):
            return False
        self.chain.append(block)
        confirmed_ids = {tx.tx_id for tx in block.transactions}
        self.mempool = [tx for tx in self.mempool if tx.tx_id not in confirmed_ids]
        self._save_chain()
        return True

    # ── Mining ────────────────────────────────────────────────────────────────

    def mine(self, miner_address: str) -> Block:
        coinbase = Transaction(
            "COINBASE",
            miner_address,
            self.mining_reward,
            timestamp=time.time(),
            tx_id=_sha256(f"coinbase{time.time()}{miner_address}"),
        )
        block = Block(
            index=len(self.chain),
            transactions=[coinbase] + list(self.mempool),
            previous_hash=self.chain[-1].hash,
        )
        target = "0" * self.difficulty
        computed = block.compute_hash()
        while not computed.startswith(target):
            block.nonce += 1
            computed = block.compute_hash()
        block.hash = computed
        self.chain.append(block)
        self.mempool.clear()
        self._save_chain()
        return block

    # ── Validation & consensus ────────────────────────────────────────────────

    def is_valid_chain(self, chain: list[Block] = None) -> bool:
        chain = chain or self.chain
        for i in range(1, len(chain)):
            b, prev = chain[i], chain[i - 1]
            if b.previous_hash != prev.hash:
                return False
            if b.hash != b.compute_hash():
                return False
            if not b.hash.startswith("0" * self.difficulty):
                return False
        return True

    def replace_chain(self, new_chain: list[Block]) -> bool:
        if len(new_chain) > len(self.chain) and self.is_valid_chain(new_chain):
            self.chain = new_chain
            self._save_chain()
            return True
        return False

    # ── Nodes ─────────────────────────────────────────────────────────────────

    def register_node(self, url: str):
        self.nodes.add(url.rstrip("/"))
        self._save_nodes()

    # ── Serialization ─────────────────────────────────────────────────────────

    def chain_to_list(self) -> list[dict]:
        return [b.to_dict() for b in self.chain]

    @staticmethod
    def chain_from_list(data: list[dict]) -> list[Block]:
        return [Block.from_dict(b) for b in data]
