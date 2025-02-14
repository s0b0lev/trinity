from abc import (
    ABC,
    abstractmethod,
)
import logging
from typing import (
    TYPE_CHECKING,
    Tuple,
    Type,
)

from eth._utils.datatypes import (
    Configurable,
)
from eth.db.backends.base import (
    BaseAtomicDB,
)
from eth.exceptions import (
    BlockNotFound,
)
from eth.validation import (
    validate_word,
)
from eth_typing import (
    Hash32,
)
from eth_utils import (
    ValidationError,
    encode_hex,
)

from eth2._utils.funcs import constantly
from eth2._utils.ssz import (
    validate_imported_block_unchanged,
)
from eth2.beacon.db.chain import (
    BaseBeaconChainDB,
    BeaconChainDB,
)
from eth2.beacon.exceptions import (
    BlockClassError,
    StateMachineNotFound,
)
from eth2.beacon.operations.attestation_pool import AttestationPool
from eth2.beacon.types.attestations import (
    Attestation,
)
from eth2.beacon.types.blocks import (
    BaseBeaconBlock,
)
from eth2.beacon.types.states import (
    BeaconState,
)
from eth2.beacon.typing import (
    FromBlockParams,
    Slot,
)
from eth2.configs import (
    Eth2GenesisConfig,
)

if TYPE_CHECKING:
    from eth2.beacon.state_machines.base import (  # noqa: F401
        BaseBeaconStateMachine,
    )


class BaseBeaconChain(Configurable, ABC):
    """
    The base class for all BeaconChain objects
    """
    chaindb = None  # type: BaseBeaconChainDB
    chaindb_class = None  # type: Type[BaseBeaconChainDB]
    sm_configuration = None  # type: Tuple[Tuple[Slot, Type[BaseBeaconStateMachine]], ...]
    chain_id = None  # type: int

    #
    # Helpers
    #
    @classmethod
    @abstractmethod
    def get_chaindb_class(cls) -> Type[BaseBeaconChainDB]:
        pass

    #
    # Chain API
    #
    @classmethod
    @abstractmethod
    def from_genesis(cls,
                     base_db: BaseAtomicDB,
                     genesis_state: BeaconState,
                     genesis_block: BaseBeaconBlock,
                     genesis_config: Eth2GenesisConfig) -> 'BaseBeaconChain':
        pass

    #
    # State Machine API
    #
    @classmethod
    @abstractmethod
    def get_state_machine_class(
            cls,
            block: BaseBeaconBlock) -> Type['BaseBeaconStateMachine']:
        pass

    @abstractmethod
    def get_state_machine(self, at_slot: Slot=None) -> 'BaseBeaconStateMachine':
        pass

    @classmethod
    @abstractmethod
    def get_state_machine_class_for_block_slot(
            cls,
            slot: Slot) -> Type['BaseBeaconStateMachine']:
        pass

    @classmethod
    @abstractmethod
    def get_genesis_state_machine_class(self) -> Type['BaseBeaconStateMachine']:
        pass

    #
    # State API
    #
    @abstractmethod
    def get_state_by_slot(self, slot: Slot) -> Hash32:
        pass

    #
    # Block API
    #
    @abstractmethod
    def get_block_class(self, block_root: Hash32) -> Type[BaseBeaconBlock]:
        pass

    @abstractmethod
    def create_block_from_parent(self,
                                 parent_block: BaseBeaconBlock,
                                 block_params: FromBlockParams) -> BaseBeaconBlock:
        pass

    @abstractmethod
    def get_block_by_root(self, block_root: Hash32) -> BaseBeaconBlock:
        pass

    @abstractmethod
    def get_canonical_head(self) -> BaseBeaconBlock:
        pass

    @abstractmethod
    def get_score(self, block_root: Hash32) -> int:
        pass

    @abstractmethod
    def get_canonical_block_by_slot(self, slot: Slot) -> BaseBeaconBlock:
        pass

    @abstractmethod
    def get_canonical_block_root(self, slot: Slot) -> Hash32:
        pass

    @abstractmethod
    def import_block(
            self,
            block: BaseBeaconBlock,
            perform_validation: bool=True
    ) -> Tuple[BaseBeaconBlock, Tuple[BaseBeaconBlock, ...], Tuple[BaseBeaconBlock, ...]]:
        pass

    #
    # Attestation API
    #
    @abstractmethod
    def get_attestation_by_root(self, attestation_root: Hash32)-> Attestation:
        pass

    @abstractmethod
    def attestation_exists(self, attestation_root: Hash32) -> bool:
        pass


class BeaconChain(BaseBeaconChain):
    """
    A Chain is a combination of one or more ``StateMachine`` classes.  Each ``StateMachine``
    is associated with a range of slots. The Chain class acts as a wrapper around these other
    StateMachine classes, delegating operations to the appropriate StateMachine depending on the
    current block slot number.
    """
    logger = logging.getLogger("eth2.beacon.chains.BeaconChain")

    chaindb_class = BeaconChainDB  # type: Type[BaseBeaconChainDB]

    def __init__(self,
                 base_db: BaseAtomicDB,
                 attestation_pool: AttestationPool,
                 genesis_config: Eth2GenesisConfig) -> None:
        if not self.sm_configuration:
            raise ValueError(
                "The Chain class cannot be instantiated with an empty `sm_configuration`"
            )
        else:
            # TODO implment validate_sm_configuration(self.sm_configuration)
            # validate_sm_configuration(self.sm_configuration)
            pass

        self.chaindb = self.get_chaindb_class()(base_db, genesis_config)
        self.attestation_pool = attestation_pool

    #
    # Helpers
    #
    @classmethod
    def get_chaindb_class(cls) -> Type['BaseBeaconChainDB']:
        if cls.chaindb_class is None:
            raise AttributeError("`chaindb_class` not set")
        return cls.chaindb_class

    #
    # Chain API
    #
    @classmethod
    def from_genesis(cls,
                     base_db: BaseAtomicDB,
                     genesis_state: BeaconState,
                     genesis_block: BaseBeaconBlock,
                     genesis_config: Eth2GenesisConfig) -> 'BaseBeaconChain':
        """
        Initialize the ``BeaconChain`` from a genesis state.
        """
        sm_class = cls.get_state_machine_class_for_block_slot(genesis_block.slot)
        if type(genesis_block) != sm_class.block_class:
            raise BlockClassError(
                "Given genesis block class: {}, StateMachine.block_class: {}".format(
                    type(genesis_block),
                    sm_class.block_class
                )
            )

        chaindb = cls.get_chaindb_class()(db=base_db, genesis_config=genesis_config)
        chaindb.persist_state(genesis_state)
        attestation_pool = AttestationPool()
        return cls._from_genesis_block(
            base_db,
            attestation_pool,
            genesis_block,
            genesis_config,
        )

    @classmethod
    def _from_genesis_block(cls,
                            base_db: BaseAtomicDB,
                            attestation_pool: AttestationPool,
                            genesis_block: BaseBeaconBlock,
                            genesis_config: Eth2GenesisConfig) -> 'BaseBeaconChain':
        """
        Initialize the ``BeaconChain`` from the genesis block.
        """
        chaindb = cls.get_chaindb_class()(db=base_db, genesis_config=genesis_config)
        genesis_scoring = constantly(0)
        chaindb.persist_block(genesis_block, genesis_block.__class__, genesis_scoring)
        return cls(base_db, attestation_pool, genesis_config)

    #
    # StateMachine API
    #
    @classmethod
    def get_state_machine_class(cls, block: BaseBeaconBlock) -> Type['BaseBeaconStateMachine']:
        """
        Returns the ``StateMachine`` instance for the given block slot number.
        """
        return cls.get_state_machine_class_for_block_slot(block.slot)

    @classmethod
    def get_state_machine_class_for_block_slot(
            cls,
            slot: Slot) -> Type['BaseBeaconStateMachine']:
        """
        Return the ``StateMachine`` class for the given block slot number.
        """
        if cls.sm_configuration is None:
            raise AttributeError("Chain classes must define the StateMachines in sm_configuration")

        for start_slot, sm_class in reversed(cls.sm_configuration):
            if slot >= start_slot:
                return sm_class
        raise StateMachineNotFound("No StateMachine available for block slot: #{0}".format(slot))

    def get_state_machine(self, at_slot: Slot=None) -> 'BaseBeaconStateMachine':
        """
        Return the ``StateMachine`` instance for the given slot number.
        """
        if at_slot is None:
            slot = self.chaindb.get_head_state_slot()
        else:
            slot = at_slot
        sm_class = self.get_state_machine_class_for_block_slot(slot)

        return sm_class(
            chaindb=self.chaindb,
            attestation_pool=self.attestation_pool,
            slot=slot,
        )

    @classmethod
    def get_genesis_state_machine_class(cls) -> Type['BaseBeaconStateMachine']:
        return cls.sm_configuration[0][1]

    #
    # State API
    #
    def get_state_by_slot(self, slot: Slot) -> BeaconState:
        """
        Return the requested state as specified by slot number.

        Raise ``StateSlotNotFound`` if there's no state with the given slot in the db.
        """
        sm_class = self.get_state_machine_class_for_block_slot(slot)
        state_class = sm_class.get_state_class()
        return self.chaindb.get_state_by_slot(slot, state_class)

    #
    # Block API
    #
    def get_block_class(self, block_root: Hash32) -> Type[BaseBeaconBlock]:
        slot = self.chaindb.get_slot_by_root(block_root)
        sm_class = self.get_state_machine_class_for_block_slot(slot)
        block_class = sm_class.block_class
        return block_class

    def create_block_from_parent(self,
                                 parent_block: BaseBeaconBlock,
                                 block_params: FromBlockParams) -> BaseBeaconBlock:
        """
        Passthrough helper to the ``StateMachine`` class of the block descending from the
        given block.
        """
        slot = parent_block.slot + 1 if block_params.slot is None else block_params.slot
        return self.get_state_machine_class_for_block_slot(
            slot=slot,
        ).create_block_from_parent(parent_block, block_params)

    def get_block_by_root(self, block_root: Hash32) -> BaseBeaconBlock:
        """
        Return the requested block as specified by block hash.

        Raise ``BlockNotFound`` if there's no block with the given hash in the db.
        """
        validate_word(block_root, title="Block Hash")

        block_class = self.get_block_class(block_root)
        return self.chaindb.get_block_by_root(block_root, block_class)

    def get_canonical_head(self) -> BaseBeaconBlock:
        """
        Return the block at the canonical chain head.

        Raise ``CanonicalHeadNotFound`` if there's no head defined for the canonical chain.
        """
        block_root = self.chaindb.get_canonical_head_root()

        block_class = self.get_block_class(block_root)
        return self.chaindb.get_block_by_root(block_root, block_class)

    def get_score(self, block_root: Hash32) -> int:
        """
        Return the score of the block with the given hash.

        Raise ``BlockNotFound`` if there is no matching black hash.
        """
        return self.chaindb.get_score(block_root)

    def get_canonical_block_by_slot(self, slot: Slot) -> BaseBeaconBlock:
        """
        Return the block with the given number in the canonical chain.

        Raise ``BlockNotFound`` if there's no block with the given number in the
        canonical chain.
        """
        return self.get_block_by_root(self.chaindb.get_canonical_block_root(slot))

    def get_canonical_block_root(self, slot: Slot) -> Hash32:
        """
        Return the block hash with the given number in the canonical chain.

        Raise ``BlockNotFound`` if there's no block with the given number in the
        canonical chain.
        """
        return self.chaindb.get_canonical_block_root(slot)

    def import_block(
            self,
            block: BaseBeaconBlock,
            perform_validation: bool=True
    ) -> Tuple[BaseBeaconBlock, Tuple[BaseBeaconBlock, ...], Tuple[BaseBeaconBlock, ...]]:
        """
        Import a complete block and returns a 3-tuple

        - the imported block
        - a tuple of blocks which are now part of the canonical chain.
        - a tuple of blocks which were canonical and now are no longer canonical.
        """

        try:
            parent_block = self.get_block_by_root(block.parent_root)
        except BlockNotFound:
            raise ValidationError(
                "Attempt to import block #{}.  Cannot import block {} before importing "
                "its parent block at {}".format(
                    block.slot,
                    block.signing_root,
                    block.parent_root,
                )
            )

        head_state_slot = self.chaindb.get_head_state_slot()
        if head_state_slot >= block.slot:
            # Importing a block older than the head state. Hence head state can not be used to
            # perform state transition.
            prev_state_slot = parent_block.slot
        else:
            prev_state_slot = head_state_slot

        state_machine = self.get_state_machine(prev_state_slot)

        state, imported_block = state_machine.import_block(block)

        # Validate the imported block.
        if perform_validation:
            validate_imported_block_unchanged(imported_block, block)

        # TODO: Now it just persists all state. Should design how to clean up the old state.
        self.chaindb.persist_state(state)

        fork_choice_scoring = state_machine.get_fork_choice_scoring()
        (
            new_canonical_blocks,
            old_canonical_blocks,
        ) = self.chaindb.persist_block(
            imported_block,
            imported_block.__class__,
            fork_choice_scoring,
        )

        self.logger.debug(
            'IMPORTED_BLOCK: slot %s | signed root %s',
            imported_block.slot,
            encode_hex(imported_block.signing_root),
        )

        return imported_block, new_canonical_blocks, old_canonical_blocks

    #
    # Attestation API
    #
    def get_attestation_by_root(self, attestation_root: Hash32)-> Attestation:
        block_root, index = self.chaindb.get_attestation_key_by_root(attestation_root)
        block = self.get_block_by_root(block_root)
        return block.body.attestations[index]

    def attestation_exists(self, attestation_root: Hash32) -> bool:
        return self.chaindb.attestation_exists(attestation_root)
