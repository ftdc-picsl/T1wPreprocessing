# T1wPreprocessing

Container for pre-processing T1w data before running structural analyses.

Images are available on [Docker
Hub](https://hub.docker.com/repository/docker/cookpa/ftdc-t1w-preproc/general).

## Input

Input is a BIDS dataset and a list of participants. All sessions and T1w images under
`anat/` will be processed, but existing preprocessed images and masks will not be
overwritten.


## Preprocessing steps

1. Reorient image to LPI using `c3d -swapdim`. Note this is not a registration, it
   just reorders the voxels in the image to produce an orientation close to the requested
   code (LPI). The physical space of the voxels in the image is unchanged, but the header
   transformation from voxel to physical space is changed.

2. Compute a brain mask with HD-BET.

3. Trim the neck with the `trim_neck.sh` script.

4. Set the origin of the trimmed T1w and brain mask to the centroid of the brain mask.


## Output

Output is to a BIDS derivatives dataset. The preprocessed T1w (`_desc-preproc_T1w.nii.gz`)
and brain mask (`_desc-brain_mask.nii.gz`) are written to the `anat` folder of the
session, with links to the source data in their respective sidecars.


## Usage

Output of `docker run --rm -it cookpa/ftdc-t1w-preproc:latest --help`

```
usage: HD-BET brain extraction and additional preprocessing --input-dataset INPUT_DATASET --output-dataset OUTPUT_DATASET [-h] [--device DEVICE] [--participant PARTICIPANT] [--session SESSION]

Wrapper for brain extraction using using HD-BET followed by neck trimming with c3d. Images will be
reoriented to LPI orientation before processing.

Input can either be by participant or by session. By participant:

   '--participant 01'
   '--participant-list subjects.txt' where the text file contains a list of participants, one per line.

All available sessions will be processed for each participant. To process selected sessions:

    '--session 01,MR1'
    '--sesion-list sessions.txt' where the text file contains a list of 'subject,session', one per line.

Output is to a BIDS derivative dataset, with the following files created for each input T1w image:
    _desc-brain_mask.nii.gz - brain mask
    _desc-preproc_T1w.nii.gz - preprocessed T1w image

If the output dataset does not exist, it will be created.

Required arguments:
  --input-dataset INPUT_DATASET
                        Input BIDS dataset dir, containing the source images
  --output-dataset OUTPUT_DATASET
                        Output BIDS dataset dir

Optional arguments:
  -h, --help            show this help message and exit
  --device DEVICE       GPU device to use, or 'cpu' to use CPU. Note CPU mode is many times slower
  --participant PARTICIPANT, --participant-list PARTICIPANT
                        Participant to process, or a text file containing a list of participants
  --session SESSION, --session-list SESSION
                        Session to process, in the format 'participant,session' or a text file containing a list of
                        participants and sessions.

```