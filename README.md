# T1wPreprocessing

Container for pre-processing T1w data before running structural analyses.

Images are available on [Docker
Hub](https://hub.docker.com/repository/docker/cookpa/ftdc-t1w-preproc/general).

It is highly recommended to run with a GPU, so that the 'accurate' mode of HD-BET can be
used. Run time for accurate mode on a GPU is still much less than for 'fast' mode on the
CPU. Multi-threading for the CPU may be controlled by the `OMP_NUM_THREADS` environment
variable.


## Input

Input is a BIDS dataset and a list of participants or sessions.

### Participant input

For example `--participant 123456` or `--participant-list participants.txt`.

All sessions and T1w images under `anat/` will be processed, but existing preprocessed
images and masks will not be overwritten. The participant list should be a list of subject
labels without the `sub-` prefix.


### Session input

For example `--session 123456,MR1` for `sub-123456/ses-MR1` or `--session-list
sessions.txt` for a list of sessions, one per line, in CSV format. Only selected sessions
wil be processed.


## Preprocessing steps

1. Reorient image to LPI using `c3d -swapdim`. Note this is not a registration, it
   just reorders the voxels in the image to produce an orientation close to the requested
   code (LPI). The physical space of the voxels in the image is unchanged, but the header
   transformation from voxel to physical space is changed.

2. Compute a brain mask with HD-BET.

3. (optional) Trim the neck with the `trim_neck.sh` script. Resample brain mask into the trimmed space.

4. (optional) Set the origin of the trimmed T1w and brain mask to the centroid of the
   brain mask (off by default).

5. Generate QC image.


## Output

Output is to a BIDS derivatives dataset. The preprocessed T1w (`_desc-preproc_T1w.nii.gz`)
and brain mask (`_desc-brain_mask.nii.gz`) are written to the `anat` folder of the
session, with links to the source data in their respective sidecars. A QC PNG is created
showing the trimmed region and the brain mask on the original data.
