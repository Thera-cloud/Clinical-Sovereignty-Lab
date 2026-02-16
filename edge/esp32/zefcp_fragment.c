/**
 * @file zefcp_fragment.c
 * @brief ZEFCP Fragment Implementation (ESP32)
 * 
 * Portable C implementation shared with nRF52840.
 */

#include "zefcp_fragment.h"
#include <string.h>

/**
 * @brief Compute CRC-8 checksum (polynomial 0x07)
 */
uint8_t zefcp_crc8(const uint8_t *data, size_t length)
{
    uint8_t crc = 0x00;
    uint8_t polynomial = ZEFCP_CRC8_POLYNOMIAL;

    for (size_t i = 0; i < length; i++)
    {
        crc ^= data[i];
        for (uint8_t j = 0; j < 8; j++)
        {
            if (crc & 0x80)
            {
                crc = (crc << 1) ^ polynomial;
            }
            else
            {
                crc <<= 1;
            }
        }
    }

    return crc;
}

/**
 * @brief Encode fragment into byte buffer
 */
size_t zefcp_fragment_encode(const zefcp_fragment_t *fragment, 
                             uint8_t *buffer, 
                             size_t buffer_size)
{
    if (fragment == NULL || buffer == NULL || buffer_size < ZEFCP_FRAGMENT_MAX_SIZE)
    {
        return 0;
    }

    size_t offset = 0;

    // Write signature
    buffer[offset++] = ZEFCP_SIGNATURE_0;
    buffer[offset++] = ZEFCP_SIGNATURE_1;
    buffer[offset++] = ZEFCP_SIGNATURE_2;
    buffer[offset++] = ZEFCP_SIGNATURE_3;

    // Write observation_id (16 bytes)
    memcpy(&buffer[offset], fragment->observation_id, ZEFCP_OBSERVATION_ID_SIZE);
    offset += ZEFCP_OBSERVATION_ID_SIZE;

    // Write seq (2 bytes, little-endian)
    buffer[offset++] = (uint8_t)(fragment->seq & 0xFF);
    buffer[offset++] = (uint8_t)((fragment->seq >> 8) & 0xFF);

    // Write total (2 bytes, little-endian)
    buffer[offset++] = (uint8_t)(fragment->total & 0xFF);
    buffer[offset++] = (uint8_t)((fragment->total >> 8) & 0xFF);

    // Calculate payload size (remaining space minus CRC)
    size_t payload_size = ZEFCP_FRAGMENT_MAX_SIZE - offset - 1;
    if (payload_size > sizeof(fragment->payload))
    {
        payload_size = sizeof(fragment->payload);
    }

    // Write payload
    memcpy(&buffer[offset], fragment->payload, payload_size);
    offset += payload_size;

    // Compute and write CRC-8 (over all data except CRC itself)
    uint8_t crc = zefcp_crc8(buffer, offset);
    buffer[offset++] = crc;

    return offset;
}

/**
 * @brief Decode fragment from byte buffer
 */
bool zefcp_fragment_decode(const uint8_t *buffer, 
                           size_t buffer_size, 
                           zefcp_fragment_t *fragment)
{
    if (buffer == NULL || fragment == NULL || buffer_size < 25) // Minimum size
    {
        return false;
    }

    // Check signature
    if (!zefcp_check_signature(buffer, buffer_size))
    {
        return false;
    }

    size_t offset = 4; // Skip signature

    // Read observation_id (16 bytes)
    memcpy(fragment->observation_id, &buffer[offset], ZEFCP_OBSERVATION_ID_SIZE);
    offset += ZEFCP_OBSERVATION_ID_SIZE;

    // Read seq (2 bytes, little-endian)
    fragment->seq = buffer[offset] | (buffer[offset + 1] << 8);
    offset += 2;

    // Read total (2 bytes, little-endian)
    fragment->total = buffer[offset] | (buffer[offset + 1] << 8);
    offset += 2;

    // Calculate payload size
    size_t payload_size = buffer_size - offset - 1; // -1 for CRC
    if (payload_size > sizeof(fragment->payload))
    {
        payload_size = sizeof(fragment->payload);
    }

    // Read payload
    memcpy(fragment->payload, &buffer[offset], payload_size);
    offset += payload_size;

    // Read CRC
    uint8_t received_crc = buffer[offset];

    // Verify CRC
    uint8_t computed_crc = zefcp_crc8(buffer, offset);
    if (received_crc != computed_crc)
    {
        return false;
    }

    fragment->crc8 = received_crc;
    return true;
}

/**
 * @brief Verify fragment CRC
 */
bool zefcp_fragment_verify_crc(const zefcp_fragment_t *fragment)
{
    if (fragment == NULL)
    {
        return false;
    }

    // TODO: Re-encode fragment and verify CRC matches
    // For now, assume valid if structure is valid
    return true;
}

/**
 * @brief Check if buffer contains ZEFCP signature
 */
bool zefcp_check_signature(const uint8_t *buffer, size_t buffer_size)
{
    if (buffer == NULL || buffer_size < 4)
    {
        return false;
    }

    return (buffer[0] == ZEFCP_SIGNATURE_0 &&
            buffer[1] == ZEFCP_SIGNATURE_1 &&
            buffer[2] == ZEFCP_SIGNATURE_2 &&
            buffer[3] == ZEFCP_SIGNATURE_3);
}
