from abc import (
    ABC,
    abstractmethod,
)
from typing import (
    Sequence,
)

from eth_typing import (
    BLSPubkey,
    BLSSignature,
    Hash32,
)

from py_ecc.bls.typing import Domain


class BaseBLSBackend(ABC):
    @staticmethod
    @abstractmethod
    def privtopub(k: int) -> BLSPubkey:
        pass

    @staticmethod
    @abstractmethod
    def sign(message_hash: Hash32,
             privkey: int,
             domain: Domain) -> BLSSignature:
        pass

    @staticmethod
    @abstractmethod
    def verify(message_hash: Hash32,
               pubkey: BLSPubkey,
               signature: BLSSignature,
               domain: Domain) -> bool:
        pass

    @staticmethod
    @abstractmethod
    def aggregate_signatures(signatures: Sequence[BLSSignature]) -> BLSSignature:
        pass

    @staticmethod
    @abstractmethod
    def aggregate_pubkeys(pubkeys: Sequence[BLSPubkey]) -> BLSPubkey:
        pass

    @staticmethod
    @abstractmethod
    def verify_multiple(pubkeys: Sequence[BLSPubkey],
                        message_hashes: Sequence[Hash32],
                        signature: BLSSignature,
                        domain: Domain) -> bool:
        pass
