/**
 * @file ble_advertiser.c
 * @brief BLE Advertiser Implementation
 */

#include "ble_advertiser.h"
#include "nrf_log.h"
#include "app_error.h"
#include <string.h>

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

    // Configure advertising parameters
    ble_gap_adv_params_t adv_params;
    memset(&adv_params, 0, sizeof(adv_params));

    adv_params.properties.type = BLE_GAP_ADV_TYPE_NONCONNECTABLE_SCANNABLE_UNDIRECTED;
    adv_params.primary_phy = BLE_GAP_PHY_1MBPS;
    adv_params.duration = BLE_GAP_ADV_TIMEOUT_GENERAL_UNLIMITED;  // Advertise indefinitely
    adv_params.max_adv_evts = 0;  // No limit
    adv_params.interval = MSEC_TO_UNITS(100, UNIT_0_625_MS);  // 100ms advertising interval
    adv_params.filter_policy = BLE_GAP_ADV_FP_ANY;

    // Set initial advertising data
    ble_advertiser_update_adv_data(advertiser);

    // Configure advertising data
    advertiser->adv_data.adv_data.p_data = advertiser->adv_buffer;
    advertiser->adv_data.adv_data.len = sizeof(advertiser->adv_buffer);
    advertiser->adv_data.scan_rsp_data.p_data = NULL;
    advertiser->adv_data.scan_rsp_data.len = 0;

    // Set advertising data
    ret_code_t err_code = sd_ble_gap_adv_set_configure(&advertiser->adv_handle,
                                                        &advertiser->adv_data,
                                                        &adv_params);
    APP_ERROR_CHECK(err_code);

    // Start advertising
    err_code = sd_ble_gap_adv_start(advertiser->adv_handle, BLE_CONN_CFG_TAG_DEFAULT);
    APP_ERROR_CHECK(err_code);

    advertiser->is_advertising = true;
    NRF_LOG_INFO("BLE advertiser started");
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

    ret_code_t err_code = sd_ble_gap_adv_stop(advertiser->adv_handle);
    APP_ERROR_CHECK(err_code);

    advertiser->is_advertising = false;
    NRF_LOG_INFO("BLE advertiser stopped");
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

    uint8_t buffer[BLE_GAP_ADV_SET_DATA_SIZE_MAX];
    uint8_t offset = 0;

    // Build advertising data structure
    // Start with flags (optional but recommended)
    if (offset + 3 <= sizeof(buffer))
    {
        buffer[offset++] = 2;  // Length
        buffer[offset++] = BLE_GAP_AD_TYPE_FLAGS;
        buffer[offset++] = BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE;
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
    advertiser->adv_data.adv_data.p_data = advertiser->adv_buffer;
    advertiser->adv_data.adv_data.len = offset;
    memcpy(advertiser->adv_buffer, buffer, offset);

    // Update advertising set if currently advertising
    if (advertiser->is_advertising)
    {
        ble_gap_adv_params_t adv_params;
        memset(&adv_params, 0, sizeof(adv_params));
        adv_params.properties.type = BLE_GAP_ADV_TYPE_NONCONNECTABLE_SCANNABLE_UNDIRECTED;
        adv_params.primary_phy = BLE_GAP_PHY_1MBPS;
        adv_params.duration = BLE_GAP_ADV_TIMEOUT_GENERAL_UNLIMITED;
        adv_params.max_adv_evts = 0;
        adv_params.interval = MSEC_TO_UNITS(100, UNIT_0_625_MS);
        adv_params.filter_policy = BLE_GAP_ADV_FP_ANY;

        ret_code_t err_code = sd_ble_gap_adv_set_configure(&advertiser->adv_handle,
                                                            &advertiser->adv_data,
                                                            &adv_params);
        APP_ERROR_CHECK(err_code);
    }
}

/**
 * @brief Handle advertising timeout/complete event
 */
void ble_advertiser_on_timeout(ble_advertiser_t *advertiser)
{
    if (advertiser == NULL)
    {
        return;
    }

    // TODO: Handle timeout if needed
    // For unlimited advertising, this shouldn't be called, but handle gracefully
    NRF_LOG_DEBUG("Advertising timeout (unexpected)");
}
