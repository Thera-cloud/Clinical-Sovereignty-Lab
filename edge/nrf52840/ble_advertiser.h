/**
 * @file ble_advertiser.h
 * @brief BLE Advertiser Module for ZEFCP Fragment Transmission
 * 
 * Embeds ZEFCP fragments into BLE advertising data and cycles through
 * fragment queue for transmission.
 */

#ifndef BLE_ADVERTISER_H
#define BLE_ADVERTISER_H

#include <stdint.h>
#include <stdbool.h>
#include "ble.h"
#include "ble_gap.h"
#include "zefcp_fragment.h"

/**
 * @brief Advertiser state structure
 */
typedef struct
{
    bool is_advertising;
    uint8_t adv_handle;
    ble_gap_adv_data_t adv_data;
    uint8_t adv_buffer[BLE_GAP_ADV_SET_DATA_SIZE_MAX];
    
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

/**
 * @brief Handle advertising timeout/complete event
 * 
 * Called from BLE event handler when advertising completes.
 * 
 * @param advertiser Advertiser instance
 */
void ble_advertiser_on_timeout(ble_advertiser_t *advertiser);

#endif // BLE_ADVERTISER_H
