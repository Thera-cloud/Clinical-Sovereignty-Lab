/**
 * @file ble_scanner.h
 * @brief BLE Scanner Module for ZEFCP Fragment Detection
 * 
 * Promiscuous BLE scanning to detect and extract ZEFCP fragments
 * from advertising data structures.
 */

#ifndef BLE_SCANNER_H
#define BLE_SCANNER_H

#include <stdint.h>
#include <stdbool.h>
#include "ble.h"
#include "ble_gap.h"
#include "nrf_ble_scan.h"
#include "zefcp_fragment.h"

/**
 * @brief Scanner state structure
 */
typedef struct
{
    nrf_ble_scan_t scan_instance;
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
 * @brief Handle advertising report event
 * 
 * Called from BLE event handler when ADV_REPORT event is received.
 * 
 * @param scanner Scanner instance
 * @param adv_report Advertising report data
 */
void ble_scanner_on_adv_report(ble_scanner_t *scanner, const ble_gap_evt_adv_report_t *adv_report);

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
