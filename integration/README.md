# Server-side RF integration (moved out of aerix_v2)

`aerix_v2-server-integration.patch` is the part of the old `aerix-rf` branch
(aerix_v2 PR #8) that touched the platform itself: 9 files under `services/`,
`db/` and `contracts/` (an RF observation source, its migrations and contract
changes), 530 insertions. It was taken against aerix_v2 main of 2026-09-04
and no longer applies cleanly; it is kept here as the record of what the RF
detector needs from the platform. Re-derive it against current main when the
RF path is brought back into the product.

Everything else in this repository ran on the HackRF box and never touched
the platform.
