#!/usr/bin/env python

import argparse
import copy
import filelock
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
# For QC
from PIL import Image

# Controls verbosity of subcommands
__verbose__ = False

# Get a dictionary for the GeneratedBy field for the BIDS dataset_description.json
# This is used to record the software used to generate the dataset
# The environment variables DOCKER_IMAGE_TAG and DOCKER_IMAGE_VERSION are used if set
#
# Container type is assumed to be "docker" unless the variable SINGULARITY_CONTAINER
# is defined
def _get_generated_by(existing_generated_by=None):
    """Get a list of dict for the GeneratedBy field for the BIDS dataset_description.json

    This is used to record the software used to generate the dataset
    The environment variables DOCKER_IMAGE_TAG and DOCKER_IMAGE_VERSION are used if set

    Container type is assumed to be "docker" unless the variable SINGULARITY_CONTAINER or APPTAINER_CONTAINER
    is defined

    Parameters:
    -----------
    existing_generated_by : list of dict, optional
        Existing GeneratedBy from dataset_description.json, if any. If the current pipeline is already present,
        it will not be added again.
    """
    import copy

    generated_by = list()

    if existing_generated_by is not None:
        if isinstance(existing_generated_by, dict):
            existing_generated_by = [existing_generated_by]
        elif not isinstance(existing_generated_by, list):
            raise ValueError("existing_generated_by must be a list of dict or a dict")

        generated_by = copy.deepcopy(existing_generated_by)
        for gb in existing_generated_by:
            if gb['Name'] == 'T1wPreprocessing' and gb['Container']['Tag'] == os.environ.get('DOCKER_IMAGE_TAG'):
                # Don't overwrite existing generated_by if it's already set to this pipeline
                return generated_by

    container_type = 'docker'

    if 'APPTAINER_CONTAINER' in os.environ:
        container_type = 'apptainer'
    elif 'SINGULARITY_CONTAINER' in os.environ:
        container_type = 'singularity'

    gen_dict = {'Name': 'T1wPreprocessing',
                'Version': os.environ.get('DOCKER_IMAGE_VERSION', 'unknown'),
                'CodeURL': os.environ.get('GIT_REMOTE', 'unknown'),
                'Container': {'Type': container_type, 'Tag': os.environ.get('DOCKER_IMAGE_TAG', 'unknown')}
                }

    generated_by.append(gen_dict)
    return generated_by

def _get_dataset_links(existing_dataset_links, dataset_link_paths):
    """Get a dictionary for the DatasetLinks field for the BIDS dataset_description.json.

    This is used to record links to other datasets. If the dataset link already exists, the URI is checked to ensure it
    matches the existing URI.

    Templateflow is added automatically, if not already present.

    Parameters:
    ----------
        existing_dataset_links : dict or None
            The existing DatasetLinks field, if any.
        dataset_link_paths : list of str or None
            The new dataset links to add.

    Returns:
    --------
        dict :
            A dictionary for the DatasetLinks field in the dataset_description.json

    Raises:
    -------
    ValueError : If a dataset link already exists with a different URI.
    """
    if existing_dataset_links is None:
        dataset_links = {}
    else:
        dataset_links = copy.deepcopy(existing_dataset_links)

    if dataset_link_paths is None:
        dataset_link_paths = {}

    for path in dataset_link_paths:
        # Get the dataset name from the dataset_description.json
        path_link = _get_single_dataset_link(path)

        name = path_link['Name']
        uri = path_link['URI']

        if name in dataset_links:
            if dataset_links[name] != uri:
                raise ValueError(f"Dataset link {name} already exists with URI {dataset_links[name]}, but new URI "
                                 f"{uri} provided")
        else:
            dataset_links[name] = uri

    return dataset_links


def _get_single_dataset_link(dataset_path):
    """Get a dataset link for the BIDS dataset_description.json from a path to a dataset.

    Parameters:
    -----------
    dataset_path : str
        Path to the dataset directory.

    Returns:
    --------
    dict :
        A dictionary for the dataset link, with keys 'Name' and 'URI'. The URI is a file:// URI to the dataset.
    """
    description_file = os.path.join(dataset_path, 'dataset_description.json')
    if not os.path.exists(description_file):
        raise FileNotFoundError(f"dataset_description.json not found in dataset path {dataset_path}")

    with open(description_file, 'r', encoding="utf-8") as f:
        ds_description = json.load(f)

    if 'Name' not in ds_description:
        raise ValueError("Dataset name ('Name') not found in dataset_description.json")

    dataset_link = { 'Name':ds_description['Name'], 'URI': f"file://{os.path.abspath(dataset_path)}" }

    return dataset_link


def update_output_dataset(output_dataset_dir, output_dataset_name, dataset_link_paths=None):
    """Create or update a BIDS output dataset

    This is used to make or update an output dataset. If the dataset exists, its metadata is updated. Specifically, the
    GeneratedBy field is updated to include this pipeline, if needed. If dataset links are provided, they are added to the
    description if needed. Templateflow is added automatically, if needed.

    Parameters:
    -----------
    output_dataset_dir : str
        Path to the output dataset directory. If the directory does not exist, it will be created.
    output_dataset_name : str
        Name of the output dataset, used if the dataset_description.json file does not exist.
    dataset_link_paths : list of str, optional
        List of paths to other datasets, to which the output dataset is linked.

    Raises:
    -------
    ValueError: If dataset_link_paths provides a name that already exists, but with a different URI.
    """
    os.makedirs(output_dataset_dir, exist_ok=True)

    lock_file = os.path.join(output_dataset_dir, 't1wpreprocessing_dataset_metadata.lock')

    if os.path.exists(lock_file):
        print(f"WARNING: lock file exists in dataset {output_dataset_dir}. Will wait for it to be released.")

    with filelock.SoftFileLock(lock_file, timeout=30):
        if not os.path.exists(os.path.join(output_dataset_dir, 'dataset_description.json')):
            # Write dataset_description.json
            output_ds_description = {'Name': output_dataset_name, 'BIDSVersion': '1.10.1',
                                    'DatasetType': 'derivative', 'GeneratedBy': _get_generated_by()
                                    }
            if (dataset_link_paths is not None):
                output_ds_description['DatasetLinks'] = _get_dataset_links(None, dataset_link_paths)
            # Write json to output dataset
            with open(os.path.join(output_dataset_dir, 'dataset_description.json'), 'w', encoding="utf-8") as file_out:
                json.dump(output_ds_description, file_out, indent=4, sort_keys=True)
        else:
            # Get output dataset metadata
            with open(f"{output_dataset_dir}/dataset_description.json", 'r', encoding="utf-8") as file_in:
                output_ds_description = json.load(file_in)
            # Check dataset name
            if not 'Name' in output_ds_description:
                raise ValueError(f"Output dataset description is missing Name, check "
                                    f"{output_dataset_dir}/data_description.json")

            old_gen_by = output_ds_description.get('GeneratedBy')

            # If this container doesn't already exist in the generated_by list, it will be added
            output_ds_description['GeneratedBy'] = _get_generated_by(old_gen_by)

            old_ds_links = output_ds_description.get('DatasetLinks', )

            output_ds_description['DatasetLinks'] = _get_dataset_links(old_ds_links, dataset_link_paths)

            ds_modified = False

            if old_gen_by is None or len(output_ds_description['GeneratedBy']) > len(old_gen_by):
                ds_modified = True
            if dataset_link_paths is not None:
                if old_ds_links is None or len(output_ds_description['DatasetLinks']) > len(old_ds_links):
                    ds_modified = True

            if ds_modified:
                with open(f"{output_dataset_dir}/dataset_description.json", 'w', encoding="utf-8") as file_out:
                    json.dump(output_ds_description, file_out, indent=4, sort_keys=True)



# Catches pipeline errors from helper functions
class PipelineError(Exception):
    """Exception raised when helper functions encounter an error"""
    pass

# Uses subprocess.run to run a command, and prints the command and output if verbose is set
#
# Example:
#   result = run_command(['c3d', my_image, '-swapdim', output_orientation, '-o', reoriented_image])
#
# Input: a list of command line arguments
#
# Returns a dictionary with keys 'cmd_str', 'stderr', 'stdout'
#
# Raises PipelineError if the command returns a non-zero exit code
#
def run_command(cmd):
    # Just to be clear we use the global var set by the main function
    global __verbose__

    if (__verbose__):
        print(f"--- Running {cmd[0]} ---")
        print(" ".join(cmd))

    result = subprocess.run(cmd, check = False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if (__verbose__):
        print("--- command stdout ---")
        print(result.stdout)
        print("--- command stderr ---")
        print(result.stderr)
        print(f"--- end {cmd[0]} ---")

    if result.returncode != 0:
        print(f"Error running command: {' '.join(cmd)}")
        traceback.print_stack()
        if not __verbose__: # print output if not already printed
            print('command stdout:\n' + result.stdout)
            print('command stderr:\n' + result.stderr)
            raise PipelineError(f"Error running command: {' '.join(cmd)}")

    return { 'cmd_str': ' '.join(cmd), 'stderr': result.stderr, 'stdout': result.stdout }

# Reset image and mask origin to mask centroid
#
# Returns: dictionary with keys 'output_image', 'output_mask'
#
def reset_origin(input_image, input_mask, working_dir):

    output_image = os.path.join(working_dir, 'inputOriginReset.nii.gz')
    output_mask = os.path.join(working_dir, 'inputOriginReset_mask.nii.gz')

    # Set origin to mask centroid - this prevents a shift in single-subject template construction
    # because the raw origins are not set consistently across sessions or protocols
    result = run_command(['c3d', input_mask, '-centroid'])
    centroid_pattern = r'CENTROID_VOX \[([\d\.-]+), ([\d\.-]+), ([\d\.-]+)\]'

    match = re.search(centroid_pattern, result['stdout'])

    if match:
        # Extract the values from the match
        mask_centroid_vox = [float(match.group(1)), float(match.group(2)), float(match.group(3))]
    else:
        raise PipelineError("Could not get centroid from mask {input_mask}")

    # Set origin to centroid for both mask and T1w
    centroid_str = str.join('x',[str(c) for c in mask_centroid_vox]) + "vox"
    result = run_command(['c3d', input_image, '-origin-voxel', centroid_str, '-o', output_image,
                                input_mask, '-origin-voxel', centroid_str, '-type', 'uchar', '-o', output_mask])

    return { 'output_image': output_image, 'output_mask': output_mask }

# Helper function for QC images
def tile_images(image_files, output_path):

    # Load the images from the provided paths
    images = [Image.open(file) for file in image_files]

    # Get the maximum height among all images
    max_height = max([img.height for img in images])

    # Zero-fill images to match the maximum height
    zero_filled_images = []
    for img in images:
        width, height = img.size
        blank = Image.new('RGB', (width, max_height), color='black')
        blank.paste(img, (0, max_height - height))
        zero_filled_images.append(blank)

    # Calculate the total width required for the stitched image
    total_width = sum(img.width for img in zero_filled_images)

    # Create a new blank image to stitch the images together
    stitched = Image.new('RGB', (total_width, max_height), color='black')

    # Paste the zero-filled images onto the new image from left to right
    current_width = 0
    for img in zero_filled_images:
        stitched.paste(img, (current_width, 0))
        current_width += img.width

    # Save the result
    stitched.save(output_path)


# QC using c3d. Inputs in the untrimmed space (we QC both neck trimming and brain masking)
#
# If the brain mask is blank or extends outside the trim region, qc_failure will be set to True
#
# Inputs:
#   full_coverage_t1w - the original T1w image, reoriented to LPI (returned from run_hdbet)
#   brain_mask - the brain mask from hd-bet, in the untrimmed space
#   trim_region - a mask in the original space containing 1 for voxels in the trimmed region and 0 for voxels outside.
#                 If None (neck trimming is turned off), the trimmed region encompasses the entire T1w image
#   working_dir - the working directory
#
# Returns: dictionary with keys 'qc_rgb_png', 'qc_failure'
def get_qc_data(full_coverage_t1w, brain_mask, working_dir, trim_region_mask=None):
    qc_failure = False

    if trim_region_mask is None:
        # If trim region is None, it means the entire T1w image is the trimmed region
        trim_region_mask = os.path.join(working_dir, 'full_coverage_mask.nii.gz')
        result = run_command(['c3d', full_coverage_t1w, '-thresh', '0', '0', '1', '1', '-o', trim_region_mask])

    # Make a combined mask of the brain mask and the trimmed region
    combined_mask = os.path.join(working_dir, 'combined_mask.nii.gz')
    # Multiply brain mask by 2 to make it brighter, then add to trimmed region
    result = run_command(['c3d', brain_mask, '-scale', '2', trim_region_mask, '-add', '-o', combined_mask])

    # The result should be a mask with 3 for voxels in the brain, and 1 for voxels in the trimmed region but
    # outside the brain. Use this to make a plot of the brain mask on the T1w image

    # Volume of mask in mm^3
    result = run_command(['c3d', combined_mask, '-dup', '-lstat'])

    # Parse output for labels 2 and 3 - 2 should not exist, if it does, it implies the brain mask is
    # outside the trimmed region
    lstats = [line.lstrip() for line in result['stdout'].splitlines()]
    label2_found = False
    label3_found = False

    for lstat in lstats:
        if lstat.startswith('2'):
            label2_found = True
        if lstat.startswith('3'):
            label3_found = True

    if label2_found:
        print(f"Neck trimming error: brain mask extends outside trimmed region")
        qc_failure = True

    if not label3_found:
        print(f"Brain masking error: no brain voxels inside trimmed T1w space")
        qc_failure = True

    # Make an RGB image of the trim and brain mask on the T1w image
    # Need to rescale T1w to range 0-255, then overlay colors
    # First define a color LUT
    color_lut = os.path.join(working_dir, 'color_lut.txt')
    # LUT columns "label_value red green blue alpha"
    # Alpha values must be between 0 and 1. Red, green and blue values should be on the same
    # order as the intensity of the grey image (typically 0-255).
    with open(color_lut, 'w') as file_out:
        file_out.write("0 0 0 0 0\n")
        file_out.write("1 255 0 0 0.3\n")
        file_out.write("2 128 255 0 0.3\n")
        file_out.write("3 32 32 255 0.3\n")

    qc_sag_slice = os.path.join(working_dir, 'qc_sag_slice.png')
    qc_cor_slice = os.path.join(working_dir, 'qc_cor_slice.png')

    qc_rgb_slices = os.path.join(working_dir, 'qc_rgb_slices.png')

    # slice the overlay image for QC - output coronal and sagittal slice
    result = run_command(['c3d', '-type', 'uchar', full_coverage_t1w, '-stretch', '0', '99%', '0', '250', '-clip', '0', '255',
                             '-as', 'gray', '-slice', 'x', '50%', '-popas', 'gslice_sag', '-push', 'gray', '-slice', 'y',
                            '50%', '-popas', 'gslice_cor', combined_mask, '-as', 'mask', '-slice', 'x', '50%', '-popas',
                            'mslice_sag', '-push', 'mask', '-slice', 'y', '50%', '-popas', 'mslice_cor', '-clear', '-push',
                            'gslice_cor', '-push', 'mslice_cor', '-foreach', '-flip', 'xy', '-endfor', '-oli', color_lut, '1',
                            '-clear', '-push', 'gslice_sag', '-push', 'mslice_sag', '-foreach', '-flip', 'xy', '-endfor',
                            '-oli', color_lut, '1', '-omc', qc_sag_slice, '-clear', '-push', 'gslice_cor', '-push',
                            'mslice_cor', '-foreach', '-flip', 'xy', '-endfor', '-oli', color_lut, '1', '-omc', qc_cor_slice])

    # tile the slices left-right into a single image
    tile_images([qc_sag_slice, qc_cor_slice], qc_rgb_slices)

    return { 'qc_rgb_png': qc_rgb_slices, 'qc_failure': qc_failure }


# Runs preprocessing and HD-BET brain extraction
# The image will be reoriented to LPI orientation before processing - it is a requirement of HD-BET
# that the image be "in the same orientation as the MNI template". Most structural images from dcm2niix
# already meet this requirement.
#
# FSL's MNI template has a negative determinant for the transformation matrix, which dcm2niix output and
# templateflow templates do not. But it does not appear to cause problems for HD-BET.
#
# Inputs:
#   input_image - the input T1w image
#   working_dir - the working directory
#   hdbet_device_settings - a list of hd-bet settings e.g. ['-device', '0', '-mode', 'fast', '-tta', '0']
#
# Returns: dictionary with keys 'reoriented_image', 'mask'
def run_hdbet(input_image, working_dir, hdbet_device_settings):

    output_orientation = 'LPI'

    # Conform input to orientation and write to temp dir
    reoriented_image = os.path.join(working_dir, f"input_reoriented_{output_orientation}.nii.gz")

    result = run_command(['c3d', input_image, '-swapdim', output_orientation, '-o', reoriented_image])

    # This isn't actually written because we use the -b 0 option to hd-bet
    tmp_output_image = os.path.join(working_dir, 'hdBetOutput.nii.gz')

    # This is determined by hd-bet based on tmp_output_image
    tmp_mask = os.path.join(working_dir, 'hdBetOutput_bet.nii.gz')

    # Now call hd-bet
    hd_bet_cmd = ['hd-bet', '-i', reoriented_image, '-o', tmp_output_image, '--no_bet_image', '--save_bet_mask', '--verbose']
    hd_bet_cmd.extend(hdbet_device_settings)

    result = run_command(hd_bet_cmd)

    return { 'reoriented_image': reoriented_image, 'mask': tmp_mask }


# Trim the neck from the image, and pad with empty space on all sides.
# Resample the mask into the trimmed space
# Return trimmed images plus a mask in the original space containing the trim region
# and brain mask for QC
#
# Inputs:
#   input_image - the input T1w image to this should be the output from run_hdbet (already reoriented to LPI)
#   input_mask - the brain mask from hd-bet, in the untrimmed space
#   working_dir - the working directory
#   pad_mm - number of mm to pad on each side after trimming
#
def trim_neck(input_image, input_mask, working_dir, pad_mm=10):
    # trim neck with c3d, reslice mask into trimmed space
    tmp_image_trim = os.path.join(working_dir, 'T1wNeckTrim.nii.gz')
    tmp_mask_trim = os.path.join(working_dir, 'T1wNeckTrim_mask.nii.gz')

    # This is in the original space, and contains 1 for voxels in the trimmed output
    # and 0 for voxels outside the trimmed region. Used for QC
    tmp_trim_region_image = os.path.join(working_dir, 'T1wNeckTrim_region.nii.gz')

    result = run_command(['trim_neck.sh', '-d', '-c', '20', '-w', working_dir, '-m', tmp_trim_region_image, input_image,
                            tmp_image_trim])

    # Pad image with c3d and reslice mask to same space
    result = run_command(['c3d', tmp_image_trim, '-pad', f"{pad_mm}x{pad_mm}x{pad_mm}mm",
                            f"{pad_mm}x{pad_mm}x{pad_mm}mm", '0', '-o', tmp_image_trim, '-interpolation',
                            'NearestNeighbor', input_mask, '-reslice-identity', '-type', 'uchar', '-o', tmp_mask_trim])

    return { 'output_image': tmp_image_trim, 'output_mask': tmp_mask_trim, 'trim_region_input_space': tmp_trim_region_image }


#
# Get the volume of the mask in ml
# Inputs: mask_image - the mask image, must be binary
# Returns: float containing the volume in mm^3
#
def get_mask_volume(mask_image):

    result = run_command(['c3d', mask_image, '-voxel-integral'])

    # Parse output to get volume
    # Expected output example: Voxel Integral: 1.14778e+07
    volume = float(result['stdout'].splitlines()[0].split()[2])

    # Convert to ml
    volume_ml = volume / 1000

    return { 'volume_ml': volume_ml }


# Helps with CLI help formatting
class RawDefaultsHelpFormatter(
    argparse.RawTextHelpFormatter, argparse.ArgumentDefaultsHelpFormatter
):
    pass

def main():

    global __verbose__

    parser = argparse.ArgumentParser(formatter_class=RawDefaultsHelpFormatter,
                                    add_help = False,
                                    description='''Wrapper for brain extraction using using HD-BET followed by neck
                                    trimming with c3d. Images will be reoriented to LPI orientation before processing.

    Input can either be by participant or by session. By participant:

    '--participant 01'
    '--participant-list subjects.txt' where the text file contains a list of participants, one per line.

    All available sessions will be processed for each participant. To process selected sessions:

        '--session 01,MR1'
        '--sesion-list sessions.txt' where the text file contains a list of 'subject,session', one per line.

    Output is to a BIDS derivative dataset, with the following files created for each input T1w image:
        _desc-brain_mask.nii.gz - brain mask
        _desc-preproc_T1w.nii.gz - preprocessed T1w image

    In addition, a QC PNG image is created for each input image, showing the brain mask and the trimmed region.

    If the output dataset does not exist, it will be created.

    ''')
    required = parser.add_argument_group('Required arguments')
    required.add_argument("--input-dataset", help="Input BIDS dataset dir, containing the source images", type=str,
                          required=True)
    required.add_argument("--output-dataset", help="Output BIDS dataset dir", type=str, required=True)
    optional = parser.add_argument_group('Optional arguments')
    optional.add_argument("-h", "--help", action="help", help="show this help message and exit")
    optional.add_argument("--device", help="GPU device to use. Supported GPUs are 'cuda', 'mps'. For cpu mode, use 'cpu'. Note "
                          "CPU mode is many times slower and may not be as robust", type=str, default='cuda')
    optional.add_argument("--participant", "--participant-list", help="Participant to process, or a text file containing a "
                          "list of participants", type=str)
    optional.add_argument("--session", "--session-list", help="Session to process, in the format 'participant,session' or a "
                          "text file containing a list of participants and sessions.", type=str)
    optional.add_argument("--reset-origin", help="Reset image and mask origin to mask centroid", action='store_true')
    optional.add_argument("--trim-neck", help="Trim neck from image", action='store_true')
    optional.add_argument("--keep-workdir", help="Copy working directory to output, for debugging purposes. Either 'never', "
                          " 'on_error', or 'always'.", choices=['never', 'on_error', 'always'], type=str.lower,
                          default='on_error')
    optional.add_argument("--verbose", help="Verbose output", action='store_true')

    args = parser.parse_args()

    __verbose__ = args.verbose

    # Check for the existence of the nvidia controller
    if (args.device != 'cpu'):
        if (args.device == 'cuda'):
            cuda_visible_devices = os.getenv('CUDA_VISIBLE_DEVICES')
            if not cuda_visible_devices:
                print("CUDA_VISIBLE_DEVICES is not set. No GPUs are visible to the process.")
                sys.exit(1)
        elif (args.device == 'mps'):
            print("Using Apple MPS (assuming supported GPU)")

    hdbet_device_settings = ['-device', args.device]

    if (args.device == 'cpu'):
        print('Warning: CPU mode is many times slower than GPU mode, and results may be suboptimal.')
        hdbet_device_settings = ['-device', 'cpu', '--disable_tta']

    # accept input as participants or sessions
    # if given participants, look for available sessions and make a list of all sessions for each participant
    # If given sessions as {participant},{session}, use those

    if args.participant is None and args.session is None:
        print("Either --participant or --session must be specified")
        sys.exit(1)

    if args.participant is not None and args.session is not None:
        print("Only one of --participant or --session can be specified")
        sys.exit(1)


    input_dataset_dir = args.input_dataset
    output_dataset_dir = args.output_dataset

    participant_sessions = []

    # List maximum possible combination of subject,session,image for all errors
    pipeline_error_list = []

    if args.participant is not None:
        if os.path.isfile(args.participant):
            with open(args.participant, 'r') as file_in:
                participants = [line.rstrip() for line in file_in]
        else:
            participants = [ args.participant ]

        for participant in participants:
            # Get list of sessions for this participant
            try:
                sessions = [f.name.replace('ses-', '') for f in os.scandir(os.path.join(input_dataset_dir, f"sub-{participant}"))
                    if f.is_dir() and f.name.startswith('ses-')]
                if len(sessions) == 0:
                    print(f"No sessions found for participant {participant}")
                    pipeline_error_list.append(f"sub-{participant}")
                    continue
                participant_sessions.extend([participant, session] for session in sessions)
            except FileNotFoundError:
                print(f"Participant {participant} not found in input dataset {input_dataset_dir}")
    else:
        if os.path.isfile(args.session):
            with open(args.session, 'r') as file_in:
                participant_sessions = [line.rstrip().split(',') for line in file_in]
        else:
            participant_sessions = [args.session.split(',')]

    # Make this under system TMPDIR, cleaned up automatically
    base_working_dir_tmpdir = tempfile.TemporaryDirectory(suffix='t1wpreproc.tmpdir')
    base_working_dir = base_working_dir_tmpdir.name

    # Get BIDS dataset name
    with open(f"{input_dataset_dir}/dataset_description.json", 'r') as file_in:
        input_dataset_json = json.load(file_in)

    input_dataset_name = input_dataset_json['Name']

    # Check if output bids dir exists, and if not, create it
    if not os.path.isdir(output_dataset_dir):
        os.makedirs(output_dataset_dir, exist_ok=True)

    # Update dataset_description.json if needed
    update_output_dataset(output_dataset_dir, f"{input_dataset_name} T1w Preprocessed", [input_dataset_dir])

    for participant,sess in participant_sessions:

        print(f"Processing participant {participant}, session {sess}")

        session_full_path = os.path.join(input_dataset_dir, f"sub-{participant}", f"ses-{sess}")

        try:
            t1w_image_file_names = [f.name for f in os.scandir(os.path.join(session_full_path, 'anat'))
                    if f.is_file() and f.name.endswith('_T1w.nii.gz')]
        except FileNotFoundError:
            print(f"Participant {participant} Session {sess} not found in input dataset {input_dataset_dir}")
            pipeline_error_list.append(f"sub-{participant}/ses-{sess}")
            continue

        if len(t1w_image_file_names) == 0:
            print(f"No T1w images found for participant {participant} session {sess}")
            pipeline_error_list.append(f"sub-{participant}/ses-{sess}")
            continue

        for t1w_image_file_name in t1w_image_file_names:

            match = re.match('(.*)_T1w\.nii\.gz$', t1w_image_file_name)

            t1w_source_entities = match.group(1)

            working_dir_tmpdir = tempfile.TemporaryDirectory(dir=base_working_dir, suffix=f"_{t1w_source_entities}.tmpdir")
            working_dir = working_dir_tmpdir.name

            print(f"Processing {t1w_image_file_name}")

            t1w_full_path = os.path.join(session_full_path, 'anat', t1w_image_file_name)

            # Want this relative to input data set, will be the source data in output sidecars
            t1w_ds_rel_path = os.path.relpath(t1w_full_path, input_dataset_dir)

            output_anat_dir_full_path = os.path.join(output_dataset_dir, f"sub-{participant}", f"ses-{sess}", 'anat')

            # Output preprocessed T1w
            output_t1w_full_path = os.path.join(output_anat_dir_full_path, f"{t1w_source_entities}_desc-preproc_T1w.nii.gz")
            # Output mask
            output_mask_full_path = os.path.join(output_anat_dir_full_path, f"{t1w_source_entities}_desc-brain_mask.nii.gz")

            # Check for existing mask
            if os.path.exists(output_mask_full_path):
                print(f"Mask already exists: {output_mask_full_path}")
                continue

            output_mask_dir = os.path.dirname(output_mask_full_path)

            if not os.path.isdir(output_mask_dir):
                os.makedirs(output_mask_dir)

            try:
                hdbet_results = run_hdbet(t1w_full_path, working_dir, hdbet_device_settings)

                output_t1w_image = hdbet_results['reoriented_image']
                output_mask_image = hdbet_results['mask']

                qc_data = None

                if (args.trim_neck):
                    trim_results = trim_neck(hdbet_results['reoriented_image'], hdbet_results['mask'], working_dir)
                    output_t1w_image = trim_results['output_image']
                    output_mask_image = trim_results['output_mask']
                    # Use the trimmed region image and the hdbet mask to make QC images
                    qc_data = get_qc_data(hdbet_results['reoriented_image'], hdbet_results['mask'],
                                          working_dir, trim_results['trim_region_input_space'])
                else:
                    qc_data = get_qc_data(output_t1w_image, output_mask_image, working_dir)

                if (args.reset_origin):
                    reset_origin_results = reset_origin(output_t1w_image, output_mask_image, working_dir)
                    output_t1w_image = reset_origin_results['output_image']
                    output_mask_image = reset_origin_results['output_mask']

                if qc_data['qc_failure']:
                    raise(PipelineError("QC failure"))

                # Get mask volume in the trimmed space - just in case there's any small differences due to reslicing
                mask_vol = get_mask_volume(output_mask_image)
            except PipelineError:
                pipeline_error_list.append(t1w_ds_rel_path)

                print(f"Error processing {t1w_ds_rel_path}")
                if (args.keep_workdir != 'never'):
                    print("Copying working directory to output for debugging")
                    # copy workingdir to output dir
                    output_working_dir = os.path.join(output_anat_dir_full_path, 'workdir')
                    shutil.copytree(working_dir, output_working_dir)

                # Write qc image if the file exists
                if os.path.exists(qc_data['qc_rgb_png']):
                    output_qc_image = os.path.join(output_anat_dir_full_path,
                                                    f"{t1w_source_entities}_desc-qcslice_rgb.png")
                    shutil.copyfile(qc_data['qc_rgb_png'], output_qc_image)
                continue

            # Copy preprocessed images and masks to output dataset and make sidecars
            shutil.copyfile(output_t1w_image, output_t1w_full_path)
            shutil.copyfile(output_mask_image, output_mask_full_path)

            output_t1w_sidecar_json = {'SkullStripped': False, 'Sources': [f"bids:{input_dataset_name}:{t1w_ds_rel_path}"]}
            output_t1w_sidecar_full_path = re.sub('\.nii\.gz$', '.json', output_t1w_full_path)
            with open(output_t1w_sidecar_full_path, 'w') as sidecar_out:
                json.dump(output_t1w_sidecar_json, sidecar_out, indent=2, sort_keys=True)

            output_t1w_ds_rel_path = os.path.relpath(output_t1w_full_path, output_dataset_dir)

            output_mask_sidecar_json = {'Type': 'Brain', 'Sources': [f"bids:{input_dataset_name}:{t1w_ds_rel_path}",
                                        f"bids::{output_t1w_ds_rel_path}"],
                                        'Volume': mask_vol['volume_ml'], 'VolumeUnit': 'ml'}
            output_mask_sidecar_full_path = re.sub('\.nii\.gz$', '.json', output_mask_full_path)
            with open(output_mask_sidecar_full_path, 'w') as sidecar_out:
                json.dump(output_mask_sidecar_json, sidecar_out, indent=2, sort_keys=True)

            output_qc_image = os.path.join(output_anat_dir_full_path, f"{t1w_source_entities}_desc-qcslice_rgb.png")
            shutil.copyfile(qc_data['qc_rgb_png'], output_qc_image)

            # Copy working dir to output dir if requested
            if args.keep_workdir == 'always':
                print("Copying working directory to output")
                # copy workingdir to output dir
                output_working_dir = os.path.join(output_anat_dir_full_path, 'workdir')
                shutil.copytree(working_dir, output_working_dir)

            # Clean up working dir
            working_dir_tmpdir.cleanup()

    print("Input dataset: " + input_dataset_dir + "\nOutput dataset: " + output_dataset_dir)

    # Print list of errors
    if len(pipeline_error_list) > 0:
        print("Total errors: " + str(len(pipeline_error_list)))
        print("Errors occurred on the following subjects / sessions / images:")
        for error_img in pipeline_error_list:
            print(error_img)
    else:
        print("Total errors: 0")

if __name__ == "__main__":
    main()