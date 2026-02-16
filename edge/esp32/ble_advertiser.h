/**
 * @file ble_advertiser.h
 * @brief BLE Advertiser Module for ZEFCP Fragment Transmission (ESP32)
 * 
 * Embeds ZEFCP fragments into BLE advertising data and cycles through
 * fragment queue for transmission using ESP-IDF APIs.
 */

#ifndef BLE_ADVERTISER_H
#define BLE_ADVERTISER_H

#include <stdint.h>
#include <stdbool.h>
#include "esp_gap_ble_api.h"
#include "zefcp_fragment.h"

/**
 * @brief Advertiser state structure
 */
typedef struct
{
    bool is_advertising;
    uint8_t adv_buffer[ESP_BLE_ADV_DATA_LEN_MAX];
    uint8_t adv_data_len;
    
    // Fragment queue
    zefcp_fragment_t fragment_queue[32];  // TODO: Make configurable
    uint8_t queue_head;
    uint8_t queue_tail;
    uint8_t queue_count;
    uint8_t current_fragment_idx;
} ble_advertiser_t;

/**
 * @brief Initialize BLE advertiser
 * 
 * @param advertiser Advertiser instance
 */
void ble_advertiser_init(ble_advertiser_t *advertiser);

/**
 * @brief Start advertising ZEFCP fragments
 * 
 * @param advertiser Advertiser instance
 */
void ble_advertiser_start(ble_advertiser_t *advertiser);

/**
 * @brief Stop advertising
 * 
 * @param advertiser Advertiser instance
 */
void ble_advertiser_stop(ble_advertiser_t *advertiser);

/**
 * @brief Add fragment to advertising queue
 * 
 * @param advertiser Advertiser instance
 * @param fragment Fragment to add
 * @return bool true if added successfully, false if queue full
 */
bool ble_advertiser_enqueue_fragment(ble_advertiser_t *advertiser, 
                                     const zefcp_fragment_t *fragment);

/**
 * @brief Update advertising data with next fragment
 * 
 * Called periodically to cycle through fragment queue.
 * 
 * @param advertiser Advertiser instance
 */
void ble_advertiser_update_adv_data(ble_advertiser_t *advertiser);

#endif // BLE_ADVERTISER_H
