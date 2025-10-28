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

3. (optional) Trim the neck with the `trim_neck.sh` script. Resample brain mask into the
   trimmed space.


4. (optional) Set the origin of the trimmed T1w and brain mask to the centroid of the
   brain mask.

5. Generate QC image.


## Output

Output is to a BIDS derivatives dataset. The preprocessed T1w (`_desc-preproc_T1w.nii.gz`)
and brain mask (`_desc-brain_mask.nii.gz`) are written to the `anat` folder of the
session, with links to the source data in their respective sidecars. A QC PNG is created
showing the trimmed region and the brain mask on the original data.


## Computational workflow

** The processing workflow has been updated to use the GPU more efficiently **

In order to maximize GPU utilization, the processing is now done in three stages. If you
are on PMACS, this is handled transparently by
[pmacsT1wPreproccessing](https://github.com/ftdc-picsl/pmacsT1wPreprocessing).

Otherwise, the stages are as follows:

```
# Step 1
docker run --rm \
        -v ${inputBIDS}:${inputBIDS}:ro \
        -v /path/to/output_staging_dir:/workdir \
        -v /path/to/list.txt:/input/list.txt:ro \
        ${container} \
        prepare_input \
        --input-dataset ${inputBIDS} \
        --output-directory /workdir \
        --${level}-list /input/list.txt

# step 2: HD-BET (GPU required)
docker run --gpus all --rm \
      -v /scratch:/tmp,/path/to/output_staging_dir:/workdir \
      ${container} \
        hdbet \
        --input-directory /workdir

# steps 3-5 (set options for neck trim and origin reset as needed)
docker run --rm \
      -v /scratch:/tmp,/path/to/output_staging_dir:/workdir \
      -v ${inputBIDS}:${inputBIDS}:ro \
      -v ${outputBIDS}:${outputBIDS} \
      -v /path/to/list.txt:/input/list.txt:ro \
      ${container} \
        postprocessing \
        --input-dataset ${inputBIDS} \
        --hd-bet-input-dir /workdir \
        --output-dataset ${outputBIDS} \
        --${level}-list /input/list.txt

# Optionally clean up /path/to/output_staging_dir here
```

By splitting the workflow, we can only use the GPU for the HD-BET step, and also run the
HD-BET step on all subjects in a single process, which is much faster than running each
image individually.

Please open an issue if you are not on PMACS and would like a combined script to run all
these steps. If you are running locally or have a different cluster environment that
enables shared GPU access, a combined script may work just as well. On the PMACS LSF, we
have to block the GPU for the entire job duration to prevent processes filling the GPU
memory, so we need to split the processing into stages that can be submitted separately.
