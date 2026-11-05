"""Ports: giao diện chung cho mọi lời gọi ra ngoài. Engine chỉ gọi port, không gọi thẳng nhà cung cấp."""
from .envelope import STATUSES, Envelope, make_envelope, validate_envelope  # noqa: F401
from .registry import PORTS, PortSpec  # noqa: F401
from .client import Adapter, PortClient  # noqa: F401
