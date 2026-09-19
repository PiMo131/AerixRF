# Stage-1 T3 false-alarm budget (ANTSDR ambient corpus)

Root: `/home/jarvis/rf-datasets/aerix_antsdr_ambient_2026_09_18/original`
Sessions: 6; total windows: 1160

| session | windows | fhss_1mhz_grid_candidate | fhss_2mhz_grid_candidate | rc_link_family_candidate | hopping_candidate | fixed_channel_burst_candidate | droneid_cadence_candidate | wifi_beacon_like | ble_connection_like | INSUFFICIENT_CHANNELS | droneid@session |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-09-18_111812_t4b1_check | 20 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 20 | no |
| 2026-09-18_112825_soak10min_b | 122 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 122 | no |
| 2026-09-18_115101_probe_default | 60 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 60 | no |
| 2026-09-18_115203_probe_k32_4m | 59 | 0 | 0 | 0 | 9 | 1 | 0 | 0 | 0 | 59 | no |
| 2026-09-18_123428_a_iq_default | 300 | 0 | 0 | 0 | 0 | 45 | 0 | 0 | 0 | 300 | no |
| 2026-09-18_133337_soak600_k32_4m_iq | 599 | 0 | 0 | 0 | 1 | 159 | 0 | 6 | 0 | 599 | no |
| TOTAL | 1160 | 0 | 0 | 0 | 12 | 205 | 0 | 6 | 0 | 1160 | 0 |

## Budget verdict (design S9)

- **fhss_1mhz_grid_candidate == 0**: PASS -- 0/1160
- **fhss_2mhz_grid_candidate == 0**: PASS -- 0/1160
- **rc_link_family_candidate <= 1**: PASS -- 0/1160
- **droneid_cadence_candidate == 0 (window and session)**: PASS -- 0/1160 windows, 0/6 sessions
- **hopping_candidate <= 5% of windows**: PASS -- 12/1160 = 1.03%

**Overall: PASS**

Discount tags (informational, not budgeted): wifi_beacon_like=6, ble_connection_like=0, INSUFFICIENT_CHANNELS=1160.
