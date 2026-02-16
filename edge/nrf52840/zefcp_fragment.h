/**
 * @file zefcp_fragment.h
 * @brief ZEFCP Fragment Structure and Utilities
 * 
 * Zero-Energy Parasitic BLE Communication fragment encoding/decoding.
 * Fragments are embedded into BLE advertising data overhead (27 bytes max).
 */

#ifndef ZEFCP_FRAGMENT_H
#define ZEFCP_FRAGMENT_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

// Maximum fragment size (BLE advertising data limit)
#define ZEFCP_FRAGMENT_MAX_SIZE     27
#define ZEFCP_OBSERVATION_ID_SIZE   16
#define ZEFCP_CRC8_POLYNOMIAL       0x07

// ZEFCP signature (magic bytes to identify fragments in BLE AD)
#define ZEFCP_SIGNATURE_0           0x5E  // 'Z' shifted
#define ZEFCP_SIGNATURE_1           0x46  // 'E' shifted
#define ZEFCP_SIGNATURE_2           0x43  // 'C'
#define ZEFCP_SIGNATURE_3           0x50  // 'P'

/**
 * @brief ZEFCP Fragment Structure
 * 
 * Total size must fit within 27 bytes of BLE advertising data.
 * Structure:
 * - observation_id[16]: UUID identifying the emotional observation
 * - seq: Fragment sequence number (0-indexed)
 * - total: Total number of fragments for this observation
 * - payload[]: Fragment data (variable length)
 * - crc8: CRC-8 checksum (polynomial 0x07)
 */
typedef struct
{
    uint8_t observation_id[ZEFCP_OBSERVATION_ID_SIZE];  // 16 bytes
    uint16_t seq;                                        // 2 bytes
    uint16_t total;                                      // 2 bytes
    uint8_t payload[ZEFCP_FRAGMENT_MAX_SIZE - 21];      // Variable (max ~5 bytes)
    uint8_t crc8;                                        // 1 byte
} zefcp_fragment_t;

/**
 * @brief Encode fragment into byte buffer
 * 
 * @param fragment Fragment structure to encode
 * @param buffer Output buffer (must be at least ZEFCP_FRAGMENT_MAX_SIZE)
 * @param buffer_size Size of output buffer
 * @return size_t Number of bytes written, or 0 on error
 */
size_t zefcp_fragment_encode(const zefcp_fragment_t *fragment, 
                             uint8_t *buffer, 
                             size_t buffer_size);

/**
 * @brief Decode fragment from byte buffer
 * 
 * @param buffer Input buffer containing encoded fragment
 * @param buffer_size Size of input buffer
 * @param fragment Output fragment structure
 * @return bool true if decode successful, false otherwise
 */
bool zefcp_fragment_decode(const uint8_t *buffer, 
                           size_t buffer_size, 
                           zefcp_fragment_t *fragment);

/**
 * @brief Compute CRC-8 checksum
 * 
 * Uses polynomial 0x07 (CRC-8-CCITT).
 * 
 * @param data Input data
 * @param length Length of data
 * @return uint8_t CRC-8 checksum
 */
uint8_t zefcp_crc8(const uint8_t *data, size_t length);

/**
 * @brief Verify fragment CRC
 * 
 * @param fragment Fragment to verify
 * @return bool true if CRC is valid, false otherwise
 */
bool zefcp_fragment_verify_crc(const zefcp_fragment_t *fragment);

/**
 * @brief Check if buffer contains ZEFCP signature
 * 
 * @param buffer Input buffer
 * @param buffer_size Size of buffer
 * @return bool true if signature found, false otherwise
 */
bool zefcp_check_signature(const uint8_t *buffer, size_t buffer_size);

#endif // ZEFCP_FRAGMENT_H
