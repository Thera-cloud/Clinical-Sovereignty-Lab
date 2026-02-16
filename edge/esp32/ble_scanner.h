/**
 * @file ble_scanner.h
 * @brief BLE Scanner Module for ZEFCP Fragment Detection (ESP32)
 * 
 * Promiscuous BLE scanning to detect and extract ZEFCP fragments
 * from advertising data structures using ESP-IDF APIs.
 */

#ifndef BLE_SCANNER_H
#define BLE_SCANNER_H

#include <stdint.h>
#include <stdbool.h>
#include "esp_gap_ble_api.h"
#include "zefcp_fragment.h"

/**
 * @brief Scanner state structure
 */
typedef struct
{
    bool is_scanning;
    void (*fragment_callback)(const zefcp_fragment_t *fragment);  // Callback when fragment detected
} ble_scanner_t;

/**
 * @brief Initialize BLE scanner
 * 
 * @param scanner Scanner instance
 */
void ble_scanner_init(ble_scanner_t *scanner);

/**
 * @brief Start scanning for ZEFCP fragments
 * 
 * @param scanner Scanner instance
 */
void ble_scanner_start(ble_scanner_t *scanner);

/**
 * @brief Stop scanning
 * 
 * @param scanner Scanner instance
 */
void ble_scanner_stop(ble_scanner_t *scanner);

/**
 * @brief Handle scan result event
 * 
 * Called from GAP event handler when scan result is received.
 * 
 * @param scanner Scanner instance
 * @param param GAP event parameters
 */
void ble_scanner_on_scan_result(ble_scanner_t *scanner, esp_ble_gap_cb_param_t *param);

/**
 * @brief Extract ZEFCP fragment from advertising data
 * 
 * Searches through AD structures for ZEFCP signature and decodes fragment.
 * 
 * @param adv_data Advertising data buffer
 * @param adv_data_len Length of advertising data
 * @param fragment Output fragment structure
 * @return bool true if fragment found and decoded, false otherwise
 */
bool ble_scanner_extract_fragment(const uint8_t *adv_data, 
                                   uint8_t adv_data_len, 
                                   zefcp_fragment_t *fragment);

/**
 * @brief Set fragment detection callback
 * 
 * @param scanner Scanner instance
 * @param callback Function to call when fragment is detected
 */
void ble_scanner_set_callback(ble_scanner_t *scanner, 
                              void (*callback)(const zefcp_fragment_t *fragment));

#endif // BLE_SCANNER_H
