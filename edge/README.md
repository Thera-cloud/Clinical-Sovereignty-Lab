# Edge Firmware: ZEFCP/Quakete BLE Mesh Nodes

Edge firmware for dedicated BLE mesh relay nodes implementing the **Zero-Energy Parasitic BLE Communication (ZEFCP)** protocol with the **Quakete** emotional solidarity layer.

## Overview

These firmware images run on low-power BLE-enabled microcontrollers (nRF52840 or ESP32) that act as **BLE relay nodes** in the Sovereign Swarm mesh network. They:

1. **Scan** for ZEFCP fragments embedded in BLE advertising data
2. **Re-emit** detected fragments to extend mesh range
3. **Forward** complete observations to the mesh network
4. **Operate** in zero-energy parasitic mode (no active connections, only advertising/scanning)

## Architecture

### ZEFCP Protocol

ZEFCP embeds micro-fragments (max 27 bytes) into BLE advertising overhead:

```
Fragment Structure (27 bytes max):
├── Signature (4 bytes): 0x5E 0x46 0x43 0x50 ("ZEFCP")
├── Observation ID (16 bytes): UUID identifying emotional observation
├── Sequence (2 bytes): Fragment sequence number (0-indexed)
├── Total (2 bytes): Total fragments for this observation
├── Payload (variable): Fragment data (~5 bytes)
└── CRC-8 (1 byte): Checksum (polynomial 0x07)
```

Fragments are embedded in **Manufacturer Specific Data** (AD type 0xFF) or **Service Data** (AD type 0x16) within BLE advertising packets.

### Quakete Layer

Quakete is the emotional solidarity protocol running on top of ZEFCP:
- Fragments carry emotional observation data
- Multiple fragments reassemble into complete observations
- Nodes relay fragments to extend mesh range
- Backend aggregates observations for Quakete analysis

## Hardware Requirements

### nRF52840
- **Board**: nRF52840-DK or compatible
- **SDK**: Nordic nRF5 SDK with SoftDevice S140
- **Features**: BLE 5.0, 2.4GHz radio, low power

### ESP32
- **Board**: ESP32-DevKitC or compatible
- **Framework**: ESP-IDF v4.4+
- **Features**: BLE 4.2+, WiFi (optional), dual-core

## Directory Structure

```
edge/
├── nrf52840/              # Nordic nRF52840 firmware
│   ├── main.c            # Entry point, BLE initialization
│   ├── zefcp_fragment.h  # Fragment structure and prototypes
│   ├── zefcp_fragment.c  # Fragment encode/decode, CRC-8
│   ├── ble_scanner.h     # BLE scanning module header
│   ├── ble_scanner.c     # Promiscuous scanning implementation
│   ├── ble_advertiser.h  # BLE advertising module header
│   └── ble_advertiser.c  # Fragment advertising implementation
├── esp32/                 # ESP32 firmware
│   ├── main.c            # Entry point (app_main)
│   ├── zefcp_fragment.h  # Fragment structure (portable C)
│   ├── zefcp_fragment.c  # Fragment implementation (portable C)
│   ├── ble_scanner.h     # ESP-IDF BLE scanner header
│   ├── ble_scanner.c     # ESP-IDF scanning implementation
│   ├── ble_advertiser.h  # ESP-IDF advertiser header
│   └── ble_advertiser.c  # ESP-IDF advertising implementation
└── README.md             # This file
```

## Build Instructions

### nRF52840 (Nordic nRF5 SDK)

1. **Install nRF5 SDK**:
   ```bash
   # Download nRF5 SDK v17.1+ from Nordic Semiconductor
   # Extract to ~/nrf5_sdk/
   ```

2. **Install SoftDevice**:
   ```bash
   # Download SoftDevice S140 v7.3+ from Nordic
   # Place in nrf5_sdk/components/softdevice/s140/
   ```

3. **Set environment variables**:
   ```bash
   export NRF5_SDK_ROOT=~/nrf5_sdk
   export NRF5_SOFTDEVICE_PATH=$NRF5_SDK_ROOT/components/softdevice/s140
   ```

4. **Build**:
   ```bash
   cd edge/nrf52840
   # Use Segger Embedded Studio or make
   # Project files need to be created for your IDE
   ```

### ESP32 (ESP-IDF)

1. **Install ESP-IDF**:
   ```bash
   # Follow ESP-IDF installation guide
   # https://docs.espressif.com/projects/esp-idf/en/latest/esp32/get-started/
   
   . $HOME/esp/esp-idf/export.sh
   ```

2. **Create project structure**:
   ```bash
   cd edge/esp32
   idf.py create-project zefcp_node
   # Copy source files to main/
   ```

3. **Configure**:
   ```bash
   idf.py menuconfig
   # Enable BLE: Component config → Bluetooth → Bluetooth → Bluetooth controller
   ```

4. **Build**:
   ```bash
   idf.py build
   ```

## Flashing Instructions

### nRF52840

Using **nRF Connect Programmer** or **J-Link**:

```bash
# Flash SoftDevice first
nrfjprog --program s140_nrf52_7.3.0_softdevice.hex --chiperase

# Flash application
nrfjprog --program zefcp_node.hex --reset
```

### ESP32

Using **esptool**:

```bash
cd edge/esp32
idf.py flash

# Or manually:
esptool.py --port /dev/ttyUSB0 write_flash 0x1000 build/zefcp_node.bin
```

## Integration

### Mobile App Integration

The Flutter mobile app (`mobile/lib/zefcp/`) can:
- **Scan** for ZEFCP fragments using BLE scanning APIs
- **Assemble** fragments into complete observations
- **Forward** observations to backend via WebSocket

Edge nodes extend the mesh range, allowing fragments to propagate beyond direct mobile-to-mobile range.

### Backend Integration

The backend (`backend/app/services/zefcp/`) receives complete observations via:
- **WebSocket**: Mobile app forwards assembled observations
- **REST API**: Direct submission endpoint (if node has network)

Backend aggregates observations for Quakete emotional solidarity analysis.

## Protocol Flow

1. **Source Node** (mobile app or edge node):
   - Splits observation into fragments
   - Embeds fragments into BLE advertising data
   - Advertises fragments continuously

2. **Relay Nodes** (edge firmware):
   - Scan for ZEFCP fragments in advertising data
   - Extract and validate fragments (CRC check)
   - Re-emit fragments in their own advertising packets
   - Forward to fragment reassembly queue

3. **Destination** (mobile app or backend):
   - Receives fragments (directly or via relay)
   - Reassembles fragments by observation_id and sequence
   - Processes complete observation for Quakete analysis

## Power Consumption

Edge nodes operate in **zero-energy parasitic mode**:
- **No active BLE connections** (connectionless)
- **Passive scanning** (low power)
- **Non-connectable advertising** (minimal power)
- **Deep sleep** between scan/advertise cycles (optional)

Typical power consumption: **< 10mA** average (varies by hardware).

## TODO / Implementation Notes

Current firmware is **scaffolding** with proper architecture. Full implementation requires:

- [ ] Fragment reassembly queue management
- [ ] Duplicate fragment detection
- [ ] Fragment timeout/expiration
- [ ] Mesh routing logic (if multi-hop)
- [ ] Quakete protocol layer integration
- [ ] Power management optimizations
- [ ] OTA update support
- [ ] Configuration via BLE GATT (optional)

## Testing

### Unit Tests

Test fragment encode/decode:
```bash
# nRF52840: Use Unity test framework
# ESP32: Use ESP-IDF test framework
```

### Integration Testing

1. Flash firmware to two edge nodes
2. Generate test fragments on mobile app
3. Verify fragments propagate through mesh
4. Check reassembly at destination

## License

Part of the Clinical Sovereignty Lab / Little Nate project.
