# Stage-1 T3 false-alarm budget (ANTSDR ambient corpus)

Root: `/home/jarvis/rf-datasets/aerix_antsdr_ambient_2026_09_18/original`
Sessions: 6; total windows: 1160

| session | windows | fhss_1mhz_grid_candidate | fhss_2mhz_grid_candidate | rc_link_family_candidate | hopping_candidate | fixed_channel_burst_candidate | droneid_cadence_candidate | wifi_beacon_like | ble_connection_like | INSUFFICIENT_CHANNELS | droneid@session |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-09-18_111812_t4b1_check | 20 | 0 | 0 | 0 | 17 | 0 | 0 | 0 | 1 | 15 | no |
| 2026-09-18_112825_soak10min_b | 122 | 0 | 0 | 0 | 91 | 0 | 0 | 0 | 4 | 72 | no |
| 2026-09-18_115101_probe_default | 60 | 0 | 0 | 0 | 53 | 0 | 0 | 0 | 4 | 32 | no |
| 2026-09-18_115203_probe_k32_4m | 59 | 0 | 0 | 0 | 47 | 0 | 0 | 0 | 4 | 25 | no |
| 2026-09-18_123428_a_iq_default | 300 | 0 | 0 | 0 | 177 | 0 | 0 | 0 | 18 | 51 | no |
| 2026-09-18_133337_soak600_k32_4m_iq | 599 | 0 | 0 | 0 | 373 | 1 | 0 | 0 | 75 | 63 | no |
| TOTAL | 1160 | 0 | 0 | 0 | 758 | 1 | 0 | 0 | 106 | 258 | 0 |

## Budget verdict (design S9)

- **fhss_1mhz_grid_candidate == 0**: PASS -- 0/1160
- **fhss_2mhz_grid_candidate == 0**: PASS -- 0/1160
- **rc_link_family_candidate <= 1**: PASS -- 0/1160
- **droneid_cadence_candidate == 0 (window and session)**: PASS -- 0/1160 windows, 0/6 sessions
- **hopping_candidate <= 5% of windows**: FAIL -- 758/1160 = 65.34%

**Overall: FAIL -- see per-rule detail above and per-session table**

Discount tags (informational, not budgeted): wifi_beacon_like=0, ble_connection_like=106, INSUFFICIENT_CHANNELS=258.


**Architect note (2026-09-19):** budget PASSED for grid/DroneID-cadence/RC-family; **FAILED for `hopping_candidate` (758/1160 = 65 % vs ≤5 %)** with `wifi_beacon_like` never firing — ambient Wi-Fi bursts (≈18 MHz, edge-clipped in a 10 MHz dwell) are clustered as hops. Rule correction pending (bandwidth/edge gating + working beacon discount); this run used the pre-semantic-fix code and must be rerun.
