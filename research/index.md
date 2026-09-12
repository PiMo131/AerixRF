# AERIX RF research index

Maintained by `research-librarian`.

This is a catalog, not the full research notebook. Keep entries compact and point to focused briefs where available.

| Source | Date | Type | Tags | Relevance | Confidence | Read status | Brief |
|---|---|---|---|---|---|---|---|
| proto17/dji_droneid | current repository reference | code/reverse engineering | DJI, DroneID, OFDM | Existing decoder reference used by AERIX RF | To verify | Referenced by project; librarian to audit | — |
| anarkiwi/samples2djidroneid | current repository reference | code/reverse engineering | DJI, DroneID, IQ | Independent parameter/decode cross-check | To verify | Referenced by project; librarian to audit | — |
| Olafseisler/dji-drone-detector | current repository reference | code | DJI, OcuSync, detection | Detection/correlation reference | To verify | Referenced by project; librarian to audit | — |
| IQTLabs/RFClassification | current repository reference | code/research | RF classification, ML | Feature/model scaffolding reference | To verify | Referenced by project; librarian to audit | — |
| arXiv:2207.10795 | current repository reference | academic paper | DJI, DroneID, protocol | Frame semantics / reverse-engineering evidence | To verify | Referenced by project; librarian to audit | — |
| Great Scott Gadgets HackRF documentation | current repository reference | primary manufacturer docs | HackRF, SDR | Host/device capture stack and hardware constraints | High when exact page/version verified | Referenced by project; HackRF specialist + librarian to audit | `briefs/hackrf.md` when created |
| ANTSDR E200 vendor documentation | — | primary manufacturer docs | ANTSDR, E200, AD9361 | Target Phase-3 hardware | To verify | Bootstrap required | `briefs/antsdr-e200.md` when created |
| Analog Devices AD9361 documentation | — | primary silicon docs | AD9361, RF transceiver | RF/clock/sample capabilities underlying E200 | High when exact document verified | Bootstrap required | `briefs/antsdr-e200.md` when created |

## Librarian bootstrap TODO

- Audit the sources already cited in `README.md` and `AERIX_RF_ANTSDR_PROJECT.md`.
- Add exact URLs, versions/dates, authors/organizations and read status.
- Inventory `research/library/` for local papers/manuals.
- Identify duplicates and weak secondary sources.
- Create focused briefs only for questions that are active or likely to recur.
