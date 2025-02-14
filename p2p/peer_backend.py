from abc import ABC, abstractmethod
from typing import (
    Set,
    Tuple,
)

from lahja import (
    BroadcastConfig,
    EndpointAPI,
)

from p2p.abc import NodeAPI
from p2p.constants import DISCOVERY_EVENTBUS_ENDPOINT
from p2p.events import (
    PeerCandidatesRequest,
    RandomBootnodeRequest,
)


class BasePeerBackend(ABC):
    @abstractmethod
    async def get_peer_candidates(self,
                                  num_requested: int,
                                  connected_remotes: Set[NodeAPI]) -> Tuple[NodeAPI, ...]:
        pass


TO_DISCOVERY_BROADCAST_CONFIG = BroadcastConfig(filter_endpoint=DISCOVERY_EVENTBUS_ENDPOINT)


class DiscoveryPeerBackend(BasePeerBackend):
    def __init__(self, event_bus: EndpointAPI) -> None:
        self.event_bus = event_bus

    async def get_peer_candidates(self,
                                  num_requested: int,
                                  connected_remotes: Set[NodeAPI]) -> Tuple[NodeAPI, ...]:
        await self.event_bus.wait_until_any_endpoint_subscribed_to(PeerCandidatesRequest)
        response = await self.event_bus.request(
            PeerCandidatesRequest(num_requested),
            TO_DISCOVERY_BROADCAST_CONFIG,
        )
        return tuple(
            candidate
            for candidate in response.candidates
            if candidate not in connected_remotes
        )


class BootnodesPeerBackend(BasePeerBackend):
    def __init__(self, event_bus: EndpointAPI) -> None:
        self.event_bus = event_bus

    async def get_peer_candidates(self,
                                  num_requested: int,
                                  connected_remotes: Set[NodeAPI]) -> Tuple[NodeAPI, ...]:
        if len(connected_remotes) == 0:
            await self.event_bus.wait_until_any_endpoint_subscribed_to(RandomBootnodeRequest)
            response = await self.event_bus.request(
                RandomBootnodeRequest(),
                TO_DISCOVERY_BROADCAST_CONFIG
            )

            return tuple(
                candidate
                for candidate in response.candidates
                if candidate not in connected_remotes
            )
        else:
            return ()
