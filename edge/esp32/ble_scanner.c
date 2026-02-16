/**
 * @file ble_scanner.c
 * @brief BLE Scanner Implementation (ESP32)
 */

#include "ble_scanner.h"
#include "esp_log.h"
#include <string.h>

static const char *TAG = "BLE_SCANNER";

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
    esp_ble_scan_params_t scan_params;
    memset(&scan_params, 0, sizeof(scan_params));

    scan_params.scan_type = BLE_SCAN_TYPE_PASSIVE;  // Passive scanning
    scan_params.own_addr_type = BLE_ADDR_TYPE_PUBLIC;
    scan_params.scan_filter_policy = BLE_SCAN_FILTER_ALLOW_ALL;  // Accept all advertisements
    scan_params.scan_interval = 0x50;   // 100ms (0x50 * 0.625ms)
    scan_params.scan_window = 0x28;      // 50ms (0x28 * 0.625ms)
    scan_params.scan_duplicate = BLE_SCAN_DUPLICATE_DISABLE;

    esp_err_t ret = esp_ble_gap_set_scan_params(&scan_params);
    if (ret != ESP_OK)
    {
        ESP_LOGE(TAG, "Set scan params failed: %s", esp_err_to_name(ret));
        return;
    }

    // Start scanning (duration 0 = scan indefinitely)
    ret = esp_ble_gap_start_scanning(0);
    if (ret != ESP_OK)
    {
        ESP_LOGE(TAG, "Start scanning failed: %s", esp_err_to_name(ret));
        return;
    }

    scanner->is_scanning = true;
    ESP_LOGI(TAG, "BLE scanner started");
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

    esp_err_t ret = esp_ble_gap_stop_scanning();
    if (ret != ESP_OK)
    {
        ESP_LOGE(TAG, "Stop scanning failed: %s", esp_err_to_name(ret));
        return;
    }

    scanner->is_scanning = false;
    ESP_LOGI(TAG, "BLE scanner stopped");
}

/**
 * @brief Handle scan result event
 */
void ble_scanner_on_scan_result(ble_scanner_t *scanner, esp_ble_gap_cb_param_t *param)
{
    if (scanner == NULL || param == NULL)
    {
        return;
    }

    if (param->scan_rst.search_evt != ESP_GAP_SEARCH_INQ_RES_EVT)
    {
        return;
    }

    // Extract fragment from advertising data
    zefcp_fragment_t fragment;
    if (ble_scanner_extract_fragment(param->scan_rst.ble_adv, 
                                     param->scan_rst.adv_data_len, 
                                     &fragment))
    {
        ESP_LOGI(TAG, "ZEFCP fragment detected: obs_id=%02x%02x..., seq=%d/%d",
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
