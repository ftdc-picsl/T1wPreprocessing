#!/usr/bin/env python

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile


parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter,
                                 prog="HD-BET brain extraction and additional preprocessing", add_help = False, description='''
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


''')
required = parser.add_argument_group('Required arguments')
required.add_argument("--input-dataset", help="Input BIDS dataset dir, containing the source images", type=str, required=True)
required.add_argument("--output-dataset", help="Output BIDS dataset dir", type=str, required=True)
optional = parser.add_argument_group('Optional arguments')
optional.add_argument("-h", "--help", action="help", help="show this help message and exit")
optional.add_argument("--device", help="GPU device to use, or 'cpu' to use CPU. Note CPU mode is many times slower", type=str,
                      default='0')
optional.add_argument("--participant", "--participant-list", help="Participant to process, or a text file containing a list of "
                      "participants", type=str)
optional.add_argument("--session", "--session-list", help="Session to process, in the format 'participant,session' or a text "
                      "file containing a list of participants and sessions.", type=str)
args = parser.parse_args()

# Check for the existence of the nvidia controller
if (args.device != 'cpu'):
    try:
        nvidia_status = subprocess.check_output(['nvidia-smi', '-i', args.device])
        print("Using GPU device " + args.device + ". Device status:")
        print(nvidia_status.decode('utf-8'))
    except Exception:
        print('Cannot get status of GPU device ' + args.device + ' using nvidia-smi.'
              'Please check that the device is available and that nvidia-smi is installed.')
        sys.exit(1)

# For GPU systems
hdbet_device_settings = ['-device', args.device, '-mode', 'accurate', '-tta', '1']

if (args.device == 'cpu'):
    print('Warning: CPU mode is many times slower than GPU mode, and results may be suboptimal.')
    hdbet_device_settings = ['-device', args.device, '-mode', 'fast', '-tta', '0']

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
    os.makedirs(output_dataset_dir)

    # Write dataset_description.json
    # Can't get too descriptive on the pipeline description as we can't be sure what version of this
    # pipeline will be used in some later run. But can at least say what it is
    output_ds_description = {'Name': input_dataset_name + '_T1wpreprocessed', 'BIDSVersion': '1.8.0',
                             'DatasetType': 'derivative', 'PipelineDescription': {'Name': 'T1wPreprocessing',
                             'CodeURL': 'https://github.com/ftdc-picsl/T1wPreprocessing'}}

    # Write json to output dataset
    with open(os.path.join(output_dataset_dir, 'dataset_description.json'), 'w') as file_out:
        json.dump(output_ds_description, file_out, indent=2, sort_keys=True)

# Lots of paths here, use the following naming conventions:
# _full_path - full path to file
# _ds_rel_path - path relative to input dataset
# _image - image file name
# _source_entities - BIDS file name entities for source image, create derivatives by appending to this

for participant,sess in participant_sessions:

    print(f"Processing participant {participant}, session {sess}")

    working_dir_tmpdir = tempfile.TemporaryDirectory(dir=base_working_dir, suffix=f"_{participant}_{sess}.tmpdir")
    working_dir = working_dir_tmpdir.name

    session_full_path = os.path.join(input_dataset_dir, f"sub-{participant}", f"ses-{sess}")

    try:
        t1w_images = [f.name for f in os.scandir(os.path.join(session_full_path, 'anat'))
                if f.is_file() and f.name.endswith('_T1w.nii.gz')]
    except FileNotFoundError:
        print(f"Participant {participant} Session {sess} not found in input dataset {input_dataset_dir}")
        pipeline_error_list.append(f"sub-{participant}/ses-{sess}")
        continue

    if len(t1w_images) == 0:
        print(f"No T1w images found for participant {participant} session {sess}")
        pipeline_error_list.append(f"sub-{participant}/ses-{sess}")
        continue

    for t1w_image in t1w_images:

        t1w_full_path = os.path.join(session_full_path, 'anat', t1w_image)

        # Want this relative to input data set, will be the source data in output sidecars
        t1w_ds_rel_path = os.path.relpath(t1w_full_path, input_dataset_dir)

        print(f"Processing {t1w_image}")

        match = re.match('(.*)_T1w\.nii\.gz$', t1w_image)

        t1w_source_entities = match.group(1)

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

        # Conform input to LPI orientation and write to temp dir
        tmp_t1w = os.path.join(working_dir, 'hdBetInput.nii.gz')
        tmp_output_t1w = os.path.join(working_dir, 'hdBetOutput.nii.gz')
        # This is determined by hd-bet based on tmp_output_t1w
        tmp_mask = os.path.join(working_dir, 'hdBetOutput_mask.nii.gz')

        subprocess.run(['c3d', t1w_full_path, '-swapdim', 'LPI', '-o', tmp_t1w])

        pipeline_error = False

        # Now call hd-bet
        hd_bet_cmd = ['hd-bet', '-i', tmp_t1w, '-o', tmp_output_t1w, '-b', '0', '-s',
                        '1', '-pp', '1']
        hd_bet_cmd.extend(hdbet_device_settings)
        result = subprocess.run(hd_bet_cmd, check = False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            print(f"Error running hd-bet on {t1w_image}")
            pipeline_error = True

        # For testing - output resliced image and mask without trimming
        # shutil.copyfile(tmp_t1w, os.path.join(output_dataset_dir, f"sub-{participant}", f"ses-{sess}", 'anat',
        #                                      f"{t1w_source_entities}_space-orig_desc-resliced_T1w.nii.gz"))
        # shutil.copyfile(tmp_mask, os.path.join(output_dataset_dir, f"sub-{participant}", f"ses-{sess}", 'anat',
        #                                      f"{t1w_source_entities}_space-orig_desc-brain_mask.nii.gz"))

        # trim neck with c3d, reslice mask into trimmed space
        tmp_t1w_trim = os.path.join(working_dir, 'T1wNeckTrim.nii.gz')
        tmp_mask_trim = os.path.join(working_dir, 'T1wNeckTrim_mask.nii.gz')

        result = subprocess.run(['trim_neck.sh', '-d', '-c', '10', '-w', working_dir, tmp_t1w, tmp_t1w_trim], check = False,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            print(f"Error trimming neck on {t1w_image}")
            print(result.stderr)
            pipeline_error = True

        # Pad image with c3d and reslice mask to same space
        pad_mm = 10
        result = subprocess.run(['c3d', tmp_t1w_trim, '-pad', f"{pad_mm}x{pad_mm}x{pad_mm}mm",
                                f"{pad_mm}x{pad_mm}x{pad_mm}mm", '0', '-o', tmp_t1w_trim, '-interpolation',
                                'NearestNeighbor', tmp_mask, '-reslice-identity', '-type', 'uchar', '-o', tmp_mask_trim],
                                check = False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            print(f"Error padding image {tmp_t1w_trim}")
            print(result.stderr)
            pipeline_error = True

        # Set origin to mask centroid - this prevents a shift in single-subject template construction
        # because the raw origins are not set consistently
        result = subprocess.run(['c3d', tmp_mask_trim, '-centroid'], check = False, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        centroid_pattern = r'CENTROID_VOX \[([\d\.-]+), ([\d\.-]+), ([\d\.-]+)\]'

        match = re.search(centroid_pattern, result.stdout)

        if match:
            # Extract the values from the match
            mask_centroid_vox = [float(match.group(1)), float(match.group(2)), float(match.group(3))]
        else:
            print("Could not get centroid from mask {tmp_mask_trim}")
            print(result.stderr)
            pipeline_error = True

        # Set origin to centroid for both mask and T1w
        centroid_str = str.join('x',[str(c) for c in mask_centroid_vox]) + "vox"
        result = subprocess.run(['c3d', tmp_t1w_trim, '-origin-voxel', centroid_str, '-o', tmp_t1w_trim,
                                    tmp_mask_trim, '-origin-voxel', centroid_str, '-o', tmp_mask_trim],
                                check = False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            print(f"Error setting origin image on {tmp_t1w_trim}")
            print(result.stderr)
            pipeline_error = True

        # In case of error, don't write output files
        if pipeline_error:
            pipeline_error_list.append(f"sub-{participant}/ses-{sess}/anat/{t1w_image}")
            continue

        # Now copy to output dataset and make sidecars
        shutil.copyfile(tmp_t1w_trim, output_t1w_full_path)
        shutil.copyfile(tmp_mask_trim, output_mask_full_path)

        output_t1w_sidecar_json = {'SkullStripped': False, 'Sources': [f"bids:{input_dataset_name}:{t1w_ds_rel_path}"]}
        output_t1w_sidecar_full_path = re.sub('\.nii\.gz$', '.json', output_t1w_full_path)
        with open(output_t1w_sidecar_full_path, 'w') as sidecar_out:
            json.dump(output_t1w_sidecar_json, sidecar_out, indent=2, sort_keys=True)

        output_mask_sidecar_json = {'Type': 'Brain', 'Sources': [f"bids:{input_dataset_name}:{t1w_ds_rel_path}"]}
        output_mask_sidecar_full_path = re.sub('\.nii\.gz$', '.json', output_mask_full_path)
        with open(output_mask_sidecar_full_path, 'w') as sidecar_out:
            json.dump(output_mask_sidecar_json, sidecar_out, indent=2, sort_keys=True)

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