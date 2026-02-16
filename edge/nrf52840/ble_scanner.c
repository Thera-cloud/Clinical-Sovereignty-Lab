/**
 * @file ble_scanner.c
 * @brief BLE Scanner Implementation
 */

#include "ble_scanner.h"
#include "nrf_log.h"
#include "app_error.h"
#include <string.h>

/**
 * @brief BLE scan event handler
 */
static void scan_evt_handler(scan_evt_t const *p_scan_evt)
{
    // TODO: Handle scan events (timeout, errors, etc.)
    switch (p_scan_evt->scan_evt_id)
    {
        case NRF_BLE_SCAN_EVT_NOT_FOUND:
            // No devices found, continue scanning
            break;

        default:
            break;
    }
}

/**
 * @brief Initialize BLE scanner
 */
void ble_scanner_init(ble_scanner_t *scanner)
{
    if (scanner == NULL)
    {
        return;
    }

    memset(scanner, 0, sizeof(ble_scanner_t));

    // Initialize nRF BLE scan module
    nrf_ble_scan_init_t init_scan;
    memset(&init_scan, 0, sizeof(init_scan));

    init_scan.p_scan_param = NULL;  // Use default scan parameters
    init_scan.evt_handler = scan_evt_handler;
    init_scan.connect_if_match = false;  // Don't auto-connect, just scan

    ret_code_t err_code = nrf_ble_scan_init(&scanner->scan_instance, &init_scan);
    APP_ERROR_CHECK(err_code);

    scanner->is_scanning = false;
    scanner->fragment_callback = NULL;
}

/**
 * @brief Start scanning for ZEFCP fragments
 */
void ble_scanner_start(ble_scanner_t *scanner)
{
    if (scanner == NULL || scanner->is_scanning)
    {
        return;
    }

    // Configure scan parameters for promiscuous scanning
    ble_gap_scan_params_t scan_params;
    memset(&scan_params, 0, sizeof(scan_params));

    scan_params.active = 0;  // Passive scanning (no scan request)
    scan_params.interval = MSEC_TO_UNITS(100, UNIT_0_625_MS);  // 100ms scan interval
    scan_params.window = MSEC_TO_UNITS(50, UNIT_0_625_MS);     // 50ms scan window
    scan_params.timeout = 0;  // No timeout (scan indefinitely)
    scan_params.filter_policy = BLE_GAP_SCAN_FP_ACCEPT_ALL;  // Accept all advertisements

    ret_code_t err_code = nrf_ble_scan_start(&scanner->scan_instance);
    APP_ERROR_CHECK(err_code);

    scanner->is_scanning = true;
    NRF_LOG_INFO("BLE scanner started");
}

/**
 * @brief Stop scanning
 */
void ble_scanner_stop(ble_scanner_t *scanner)
{
    if (scanner == NULL || !scanner->is_scanning)
    {
        return;
    }

    ret_code_t err_code = nrf_ble_scan_stop(&scanner->scan_instance);
    APP_ERROR_CHECK(err_code);

    scanner->is_scanning = false;
    NRF_LOG_INFO("BLE scanner stopped");
}

/**
 * @brief Handle advertising report event
 */
void ble_scanner_on_adv_report(ble_scanner_t *scanner, const ble_gap_evt_adv_report_t *adv_report)
{
    if (scanner == NULL || adv_report == NULL)
    {
        return;
    }

    // Extract fragment from advertising data
    zefcp_fragment_t fragment;
    if (ble_scanner_extract_fragment(adv_report->data.p_data, 
                                     adv_report->data.len, 
                                     &fragment))
    {
        NRF_LOG_INFO("ZEFCP fragment detected: obs_id=%02x%02x..., seq=%d/%d",
                     fragment.observation_id[0], fragment.observation_id[1],
                     fragment.seq, fragment.total);

        // Call callback if set
        if (scanner->fragment_callback != NULL)
        {
            scanner->fragment_callback(&fragment);
        }

        // TODO: Add fragment to reassembly queue
        // TODO: Check if this completes a full observation
    }
}

/**
 * @brief Extract ZEFCP fragment from advertising data
 */
bool ble_scanner_extract_fragment(const uint8_t *adv_data, 
                                   uint8_t adv_data_len, 
                                   zefcp_fragment_t *fragment)
{
    if (adv_data == NULL || fragment == NULL || adv_data_len == 0)
    {
        return false;
    }

    // Parse BLE advertising data structures
    // AD structures: [length][type][data...]
    uint8_t offset = 0;
    while (offset < adv_data_len)
    {
        uint8_t ad_length = adv_data[offset];
        if (ad_length == 0 || offset + ad_length >= adv_data_len)
        {
            break;
        }

        uint8_t ad_type = adv_data[offset + 1];
        uint8_t ad_data_start = offset + 2;
        uint8_t ad_data_len = ad_length - 1;

        // Check for ZEFCP signature in this AD structure
        // We can embed fragments in Manufacturer Specific Data (0xFF) or
        // in Service Data (0x16) or custom type
        if (ad_type == 0xFF || ad_type == 0x16)  // Manufacturer Data or Service Data
        {
            const uint8_t *ad_data = &adv_data[ad_data_start];
            
            // Check for ZEFCP signature
            if (zefcp_check_signature(ad_data, ad_data_len))
            {
                // Decode fragment
                if (zefcp_fragment_decode(ad_data, ad_data_len, fragment))
                {
                    return true;
                }
            }
        }

        offset += ad_length + 1;
    }

    return false;
}

/**
 * @brief Set fragment detection callback
 */
void ble_scanner_set_callback(ble_scanner_t *scanner, 
                              void (*callback)(const zefcp_fragment_t *fragment))
{
    if (scanner == NULL)
    {
        return;
    }

    scanner->fragment_callback = callback;
}
