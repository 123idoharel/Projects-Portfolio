"""
core/adapters — Hardware Abstraction Layer
==========================================

This package isolates the parking system from its data sources.
Every external input — spot occupancy sensors, vehicle positioning,
pedestrian positioning — goes through an adapter.

Today all adapters use simulated data. To connect real hardware,
replace the Simulated* adapter with the appropriate concrete class.
The rest of the system is unaffected.

Quick reference
---------------
Spot occupancy:
    SimulatedSensorAdapter    → current behaviour (sim writes directly)
    RestPollingSensorAdapter  → poll a REST endpoint every N seconds
    MqttSensorAdapter         → subscribe to MQTT broker (event-driven)
    WebhookSensorAdapter      → sensor POSTs events to /api/spot_event

Vehicle position:
    SimulatedVehiclePositionAdapter  → mathematical route-following (current)
    RfidZoneVehicleAdapter           → RFID zone checkpoints + dead reckoning

Pedestrian position:
    SimulatedPedestrianPositionAdapter → frontend simulates locally (current)
    BlePositionAdapter                 → BLE RSSI trilateration from phone app
"""

from .sensor_adapter import (
    SensorAdapter,
    SimulatedSensorAdapter,
    RestPollingSensorAdapter,
    MqttSensorAdapter,
    WebhookSensorAdapter,
    external_to_internal,
    SPOT_ID_MAP,
)

from .position_adapter import (
    PositionSample,
    VehiclePositionAdapter,
    PedestrianPositionAdapter,
    SimulatedVehiclePositionAdapter,
    SimulatedPedestrianPositionAdapter,
    ServerSimulatedPedestrianPositionAdapter,
    BlePositionAdapter,
    BleVehiclePositionAdapter,
    RfidZoneVehicleAdapter,
    snap_route_index,
)

__all__ = [
    "SensorAdapter", "SimulatedSensorAdapter", "RestPollingSensorAdapter",
    "MqttSensorAdapter", "WebhookSensorAdapter",
    "external_to_internal", "SPOT_ID_MAP",
    "PositionSample",
    "VehiclePositionAdapter", "PedestrianPositionAdapter",
    "SimulatedVehiclePositionAdapter", "SimulatedPedestrianPositionAdapter",
    "ServerSimulatedPedestrianPositionAdapter",
    "BlePositionAdapter", "BleVehiclePositionAdapter",
    "RfidZoneVehicleAdapter",
    "snap_route_index",
]
