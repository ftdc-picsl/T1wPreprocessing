#!/usr/bin/env python

import argparse
import csv
import json
import os
import subprocess
import sys
import traceback

from find_data import find_t1w_images_from_bids, find_t1w_images_from_filesystem, get_bids_layout

# Controls verbosity of subcommands
__verbose__ = False


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


#
# Conform input image to LPI orientation (RAS+) using c3d
#
# FSL's MNI template is in RPI orientation, but LPI is used by templateflow. HD-BET seems to be unaffected by
# LPI vs RPI. I think this is because it flips internally as part of its runtime data augmentation
#
def conform_image(input_image, output_image):

    output_orientation = 'LPI'

    run_command(['c3d', input_image, '-swapdim', output_orientation, '-o', output_image])


# Helps with CLI help formatting
class RawDefaultsHelpFormatter(
    argparse.RawTextHelpFormatter, argparse.ArgumentDefaultsHelpFormatter
):
    pass

def main():

    global __verbose__

    parser = argparse.ArgumentParser(formatter_class=RawDefaultsHelpFormatter,
                                    add_help = False,
                                    description='''This script prepares a batch of T1w images for HD-BET. It uses c3d to

    find T1w images in a BIDS dataset, and uses c3d to reorient them to LPI orientation as required by HD-BET.

    Output is to a folder containing all selected images, for batch processing with HD-BET.

    After doing this, you can run run_hdbet.py to run HD-BET on the prepared images, which is much faster than invoking
    hd-bet separately for each image.

    Input can either be by participant or by session. By participant:

    '--participant 01'
    '--participant-list subjects.txt' where the text file contains a list of participants, one per line.

    All available sessions will be processed for each participant. To process selected sessions:

        '--session 01,MR1'
        '--sesion-list sessions.txt' where the text file contains a list of 'subject,session', one per line.


    BIDS Filtering
    --------------

    By default, a simple file system search is used in each session, returning anything under 'anat/' that ends with ]
    '_T1w.nii.gz'.

    If you want to use a more complex BIDS filter, you can use the '--bids-filter' option to specify a JSON file containing a
    BIDS filter. Filters must have a key "t1w". The following values are required: {"datatype": "anat", "suffix": "T1w"}.
    To include regexes in the filter, add "regex": true. Example:

    {
      "t1w": {
        "datatype": "anat",
        "suffix": "T1w",
        "acquisition": "MPRAGE(-hires)?",
        "regex_search": true,
      }
    }

    If a BIDS filter is used, pybids is used to find the input images. This is much slower for large datasets. Validation
    will be turned off.


    Ranked T1w selection
    --------------------

    While the default is to process all available images, it is sometimes desirable to select a single T1w image per session.
    For example, if there are multiple T1w images, and you want to choose the one with the highest resolution. The
    `--acq-preference-ranks` option takes a text file (one entry per line) or comma-separated list of acquisition labels, in
    order of preference. The script will select the first image that has an acq label exactly matching one of the available
    options.


    Output
    ------

    The eventual output of the pipeline is to a BIDS derivative dataset, with the following files created for each input T1w
    image:
        _desc-brain_mask.nii.gz - brain mask
        _desc-preproc_T1w.nii.gz - preprocessed T1w image

    If the option '--pipeline-output-dataset' is given, the script will check for existing outputs in that dataset and skip
    processing for any images that already have outputs.

    The output of this script is the preprocessed T1w image, which should be passed as input to HD-BET for batch processing.
    ''')
    required = parser.add_argument_group('Required arguments')
    required.add_argument("--input-dataset", help="Input BIDS dataset dir, containing the source images", type=str,
                          required=True)
    required.add_argument("--output-directory", help="Output directory containing all preprocessed images", type=str,
                          required=True)
    optional = parser.add_argument_group('Optional arguments')
    optional.add_argument("-h", "--help", action="help", help="show this help message and exit")
    optional.add_argument("--participant", "--participant-list", help="Participant to process, or a text file containing a "
                          "list of participants", type=str)
    optional.add_argument("--session", "--session-list", help="Session to process, in the format 'participant,session' or a "
                          "text file containing a list of participants and sessions.", type=str)
    optional.add_argument("--bids-filter", help="JSON file containing a BIDS filter", type=str)
    optional.add_argument("--acq-preference-ranks", help="Text file or comma-separated list of acquisition labels, in order of "
                          "preference. The script will select the first image that has an acq label exactly matching one of "
                          "the available options.", type=str)
    optional.add_argument("--pipeline-output-dataset", help="Output BIDS derivative dataset dir, containing the final outputs "
                          "of the pipeline. This is only used to find existing output so that we do not duplicate processing",
                          type=str, default=None)
    optional.add_argument("--verbose", help="Verbose output", action='store_true')

    args = parser.parse_args()

    __verbose__ = args.verbose

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
    output_dir = args.output_directory

    participant_sessions = []

    pipeline_error_list = []
    manifest_rows = []

    print(f"Reading input images from dataset: {input_dataset_dir}")

    if args.participant is not None:
        if os.path.isfile(args.participant):
            with open(args.participant, 'r') as file_in:
                participants = [line.rstrip() for line in file_in]
        else:
            participants = [ args.participant ]

        for participant in participants:
            # Get list of sessions for this participant
            try:
                sessions = [
                    f.name.replace('ses-', '') for f in os.scandir(os.path.join(input_dataset_dir, f"sub-{participant}"))
                    if f.is_dir() and f.name.startswith('ses-')
                    ]
                if len(sessions) == 0:
                    print(f"No sessions found for participant {participant}")
                    pipeline_error_list.append(f"sub-{participant}\tNo sessions found")
                    continue
                participant_sessions.extend([participant, session] for session in sessions)
            except FileNotFoundError:
                print(f"Participant {participant} not found in input dataset {input_dataset_dir}")
                pipeline_error_list.append(f"sub-{participant}\tParticipant not found")
                continue
    else:
        if os.path.isfile(args.session):
            with open(args.session, 'r') as file_in:
                participant_sessions = [line.rstrip().split(',') for line in file_in]
        else:
            participant_sessions = [args.session.split(',')]

    if not os.path.isdir(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    # Not used unless user specifies a BIDS filter
    bids_layout = None
    bids_filter = None

    acq_preference_order = None

    if args.acq_preference_ranks is not None:
        if os.path.isfile(args.acq_preference_ranks):
            with open(args.acq_preference_ranks , 'r') as file_in:
                acq_preference_order = [line.rstrip() for line in file_in]
        else:
            acq_preference_order = args.acq_preference_ranks.split(',')
        print(f"Using acquisition preference order: {acq_preference_order}")
        print("Only the first image matching an acquisition label in the preference order will be selected for processing")

    if args.bids_filter is not None:
        print(f"Using BIDS filter: {args.bids_filter}")
        bids_layout = get_bids_layout(input_dataset_dir)
        with open(args.bids_filter, 'r') as f:
            bids_filter_json = json.load(f)
            if 't1w' not in bids_filter_json:
                raise ValueError(f"BIDS filter {args.bids_filter} must contain a 't1w' filter")
            bids_filter = bids_filter_json['t1w']

    for participant,sess in participant_sessions:

        print(f"Processing participant {participant}, session {sess}")

        session_full_path = os.path.join(input_dataset_dir, f"sub-{participant}", f"ses-{sess}")

        if not os.path.exists(session_full_path):
            print(f"Participant {participant} session {sess} not found in input dataset {input_dataset_dir}")
            pipeline_error_list.append(f"sub-{participant}/ses-{sess}\tSession not found")
            continue

        try:
            if bids_layout is not None:
                t1w_image_file_names = \
                    find_t1w_images_from_bids(bids_layout, participant, sess, bids_filter, acq_preference_order)
            else:
                t1w_image_file_names = find_t1w_images_from_filesystem(session_full_path, acq_preference_order)
        except FileNotFoundError:
            print(f"No anat directory for participant {participant} session {sess} in input dataset {input_dataset_dir}")
            pipeline_error_list.append(f"sub-{participant}/ses-{sess}\tanat directory not found")
            continue

        if len(t1w_image_file_names) == 0:
            print(f"No T1w images found for participant {participant} session {sess} in input dataset {input_dataset_dir}")
            pipeline_error_list.append(f"sub-{participant}/ses-{sess}/anat\tNo T1w images found")
            continue

        t1w_image_files_to_process = list()

        if args.pipeline_output_dataset is not None and os.path.isdir(args.pipeline_output_dataset):
            # Check for existing outputs in the pipeline output dataset
            pipeline_output_anat_dir = os.path.join(args.pipeline_output_dataset, f"sub-{participant}", f"ses-{sess}", 'anat')
            if os.path.exists(pipeline_output_anat_dir):
                for input_t1w_fn in t1w_image_file_names:
                    output_mask_path = os.path.join(pipeline_output_anat_dir,
                                                    input_t1w_fn.replace('_T1w.nii.gz', '_desc-brain_mask.nii.gz'))
                    if os.path.exists(output_mask_path):
                        print(f"Found existing output for {input_t1w_fn}, skipping")
                    else:
                        t1w_image_files_to_process.append(input_t1w_fn)
            else:
                t1w_image_files_to_process = t1w_image_file_names
        else:
            t1w_image_files_to_process = t1w_image_file_names

        for t1w_image_file_name in t1w_image_files_to_process:

            if __verbose__:
                print(f"  Processing {t1w_image_file_name}")

            t1w_full_path = os.path.join(session_full_path, 'anat', t1w_image_file_name)

            # Output LPI T1w with same file name, used as input to hd-bet
            output_t1w_full_path = os.path.join(output_dir, t1w_image_file_name)

            try:
                conform_image(t1w_full_path, output_t1w_full_path)
            except PipelineError:
                pipeline_error_list.append(t1w_full_path)
                print(f"Error processing {t1w_full_path}")
                continue

            manifest_rows.append({
                'Participant': participant,
                'Session': sess,
                'T1wBasename': os.path.basename(t1w_image_file_name),
            })

    manifest_path = os.path.join(output_dir, 't1w_preproc_selected_input.csv')
    with open(manifest_path, 'w', newline='') as manifest_file:
        fieldnames = ['Participant', 'Session', 'T1wBasename']
        writer = csv.DictWriter(manifest_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(manifest_rows)

    print(f"Wrote selected input manifest: {manifest_path}")

    # Print list of errors
    if len(pipeline_error_list) > 0:
        print("Total errors: " + str(len(pipeline_error_list)))
        print("Path\t\tError:")
        for error_img in pipeline_error_list:
            print(error_img)
    else:
        print("Total errors: 0")

if __name__ == "__main__":
    main()
