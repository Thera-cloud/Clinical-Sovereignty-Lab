/**
 * @file ble_advertiser.c
 * @brief BLE Advertiser Implementation (ESP32)
 */

#include "ble_advertiser.h"
#include "esp_log.h"
#include <string.h>

static const char *TAG = "BLE_ADVERTISER";

/**
 * @brief Initialize BLE advertiser
 */
void ble_advertiser_init(ble_advertiser_t *advertiser)
{
    if (advertiser == NULL)
    {
        return;
    }

    memset(advertiser, 0, sizeof(ble_advertiser_t));
    advertiser->is_advertising = false;
    advertiser->queue_head = 0;
    advertiser->queue_tail = 0;
    advertiser->queue_count = 0;
    advertiser->current_fragment_idx = 0;
    advertiser->adv_data_len = 0;
}

/**
 * @brief Start advertising ZEFCP fragments
 */
void ble_advertiser_start(ble_advertiser_t *advertiser)
{
    if (advertiser == NULL || advertiser->is_advertising)
    {
        return;
    }

    // Update advertising data with current fragment
    ble_advertiser_update_adv_data(advertiser);

    // Configure advertising parameters
    esp_ble_adv_params_t adv_params;
    memset(&adv_params, 0, sizeof(adv_params));

    adv_params.adv_int_min = 0x20;  // 20ms minimum interval (0x20 * 0.625ms)
    adv_params.adv_int_max = 0x40;  // 40ms maximum interval (0x40 * 0.625ms)
    adv_params.adv_type = ADV_TYPE_NONCONN_IND;  // Non-connectable, scannable
    adv_params.own_addr_type = BLE_ADDR_TYPE_PUBLIC;
    adv_params.channel_map = ADV_CHNL_ALL;
    adv_params.adv_filter_policy = ADV_FILTER_ALLOW_SCAN_ANY_CON_ANY;

    // Set advertising data
    esp_err_t ret = esp_ble_gap_config_adv_data_raw(advertiser->adv_buffer, advertiser->adv_data_len);
    if (ret != ESP_OK)
    {
        ESP_LOGE(TAG, "Config adv data failed: %s", esp_err_to_name(ret));
        return;
    }

    // Start advertising
    ret = esp_ble_gap_start_advertising(&adv_params);
    if (ret != ESP_OK)
    {
        ESP_LOGE(TAG, "Start advertising failed: %s", esp_err_to_name(ret));
        return;
    }

    advertiser->is_advertising = true;
    ESP_LOGI(TAG, "BLE advertiser started");
}

/**
 * @brief Stop advertising
 */
void ble_advertiser_stop(ble_advertiser_t *advertiser)
{
    if (advertiser == NULL || !advertiser->is_advertising)
    {
        return;
    }

    esp_err_t ret = esp_ble_gap_stop_advertising();
    if (ret != ESP_OK)
    {
        ESP_LOGE(TAG, "Stop advertising failed: %s", esp_err_to_name(ret));
        return;
    }

    advertiser->is_advertising = false;
    ESP_LOGI(TAG, "BLE advertiser stopped");
}

/**
 * @brief Add fragment to advertising queue
 */
bool ble_advertiser_enqueue_fragment(ble_advertiser_t *advertiser, 
                                     const zefcp_fragment_t *fragment)
{
    if (advertiser == NULL || fragment == NULL)
    {
        return false;
    }

    // Check if queue is full
    if (advertiser->queue_count >= sizeof(advertiser->fragment_queue) / sizeof(zefcp_fragment_t))
    {
        return false;
    }

    // Add fragment to queue
    memcpy(&advertiser->fragment_queue[advertiser->queue_tail], 
           fragment, 
           sizeof(zefcp_fragment_t));
    
    advertiser->queue_tail = (advertiser->queue_tail + 1) % 
                             (sizeof(advertiser->fragment_queue) / sizeof(zefcp_fragment_t));
    advertiser->queue_count++;

    // Update advertising data if currently advertising
    if (advertiser->is_advertising)
    {
        ble_advertiser_update_adv_data(advertiser);
    }

    return true;
}

/**
 * @brief Update advertising data with next fragment
 */
void ble_advertiser_update_adv_data(ble_advertiser_t *advertiser)
{
    if (advertiser == NULL)
    {
        return;
    }

    uint8_t buffer[ESP_BLE_ADV_DATA_LEN_MAX];
    uint8_t offset = 0;

    // Build advertising data structure
    // Start with flags (optional but recommended)
    if (offset + 3 <= sizeof(buffer))
    {
        buffer[offset++] = 2;  // Length
        buffer[offset++] = 0x01;  // Flags AD type
        buffer[offset++] = 0x06;  // LE General Discoverable Mode
    }

    // Add ZEFCP fragment in Manufacturer Specific Data (0xFF)
    if (advertiser->queue_count > 0)
    {
        const zefcp_fragment_t *fragment = 
            &advertiser->fragment_queue[advertiser->current_fragment_idx];

        // Encode fragment
        uint8_t fragment_buffer[ZEFCP_FRAGMENT_MAX_SIZE];
        size_t fragment_len = zefcp_fragment_encode(fragment, fragment_buffer, sizeof(fragment_buffer));

        if (fragment_len > 0 && offset + fragment_len + 3 <= sizeof(buffer))
        {
            // Manufacturer Specific Data structure: [length][type=0xFF][company_id][data...]
            buffer[offset++] = fragment_len + 3;  // Length (fragment + type + company_id)
            buffer[offset++] = 0xFF;  // Manufacturer Specific Data type
            
            // Company ID (use a custom ID for ZEFCP, e.g., 0x5EFC)
            buffer[offset++] = 0xFC;  // LSB
            buffer[offset++] = 0x5E;  // MSB

            // Copy fragment data
            memcpy(&buffer[offset], fragment_buffer, fragment_len);
            offset += fragment_len;

            // Advance to next fragment (round-robin)
            advertiser->current_fragment_idx = 
                (advertiser->current_fragment_idx + 1) % advertiser->queue_count;
        }
    }

    // Update advertising data
    advertiser->adv_data_len = offset;
    memcpy(advertiser->adv_buffer, buffer, offset);

    // Update advertising set if currently advertising
    if (advertiser->is_advertising)
    {
        esp_err_t ret = esp_ble_gap_config_adv_data_raw(advertiser->adv_buffer, advertiser->adv_data_len);
        if (ret != ESP_OK)
        {
            ESP_LOGE(TAG, "Update adv data failed: %s", esp_err_to_name(ret));
        }
    }
}
