# AERIX RF dataset workspace

This directory tracks (but does not store) the external public RF/IQ datasets used
for AERIX RF detection/classification/fingerprinting/localization research.

## Where the actual data lives

Bulk dataset files are NOT stored in this git repository (too large, and mostly
under external licences). They live on disk under:

```
$AERIX_RF_DATASET_ROOT   (default: ~/rf-datasets)
```

Layout convention per dataset (canonical folder name is the manifest `dataset_id`,
e.g. `dronerf`, not a display name like `DroneRF`; `manifest.json` records this as
each entry's `local_path`, relative to the root):

```
$AERIX_RF_DATASET_ROOT/<dataset_id>/original/   # untouched downloaded files
$AERIX_RF_DATASET_ROOT/<dataset_id>/prepared/   # AERIX-side extracted/converted data (if any)
$AERIX_RF_DATASET_ROOT/manifests/               # download manifest, logs, status.sh
```

Legacy display-name folders (e.g. `DroneRF/`) may exist as transitional symlinks
to the `dataset_id` folder; do not write data through them, and do not rely on
them remaining once the transition period ends.

Check current download status at any time with:

```bash
bash ~/rf-datasets/manifests/status.sh
```

(reads `$AERIX_RF_DATASET_ROOT` if set, otherwise defaults to `~/rf-datasets`).

## What's in this directory

- `manifest.json` - machine-readable catalog of every dataset known to AERIX RF
  (present, downloading, planned, or access-gated), mirrored from
  `~/rf-datasets/manifests/datasets.json`. Fields include access/download status,
  signal format, sample rate, bands, device counts, labels, and an
  `intended_aerix_use` note. Treat `not confirmed this pass` / `unknown` fields
  as genuinely unverified, not as "assume typical values."
- `USER_TODO.md` - exact manual steps needed for datasets gated behind an
  account, subscription, or researcher-request form (IEEE DataPort, etc).

## Ownership and update discipline

Owned by `research-librarian`. Do not hand-edit `manifest.json` from other
agents/roles; route dataset questions through the architect to
`research-librarian`, who will update the manifest and this README together.

Every entry in `manifest.json` distinguishes:
- claims read directly from a primary source this pass (paper, dataset landing
  page, repo README);
- claims carried over from a prior pass's corpus pointer (cited as such,
  not re-verified);
- fields left `unknown`/`not confirmed this pass` because no source was read yet.

Do not upgrade an `unknown` field to a confident value without actually reading
the source.
