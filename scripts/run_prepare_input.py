#!/usr/bin/env python

import argparse
import os
import subprocess
import sys
import traceback

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

    Output is to a BIDS derivative dataset, with the following files created for each input T1w image:
        _desc-brain_mask.nii.gz - brain mask
        _desc-preproc_T1w.nii.gz - preprocessed T1w image

    In addition, a QC PNG image is created for each input image, showing the brain mask and the trimmed region.

    If the output dataset does not exist, it will be created.

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

    if not os.path.isdir(output_dir):
        os.makedirs(output_dir, exist_ok=True)

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

    # Print list of errors
    if len(pipeline_error_list) > 0:
        print("Total errors: " + str(len(pipeline_error_list)))
        print("Errors occurred on the following images:")
        for error_img in pipeline_error_list:
            print(error_img)
    else:
        print("Total errors: 0")

if __name__ == "__main__":
    main()