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

Output is to a BIDS derivative dataset, with the following files created for each input T1w image:
    _desc-brain_mask.nii.gz - brain mask
    _desc-preproc_T1w.nii.gz - preprocessed T1w image

If the output dataset does not exist, it will be created.

''')
required = parser.add_argument_group('Required arguments')
required.add_argument("--input-dataset", help="Input BIDS dataset dir, containing the source images", type=str, required=True)
required.add_argument("--output-dataset", help="Output BIDS dataset dir", type=str, required=True)
required.add_argument("--participant", help="Participant to process, or a text file containing a list of participants",
                      type=str, required=True)
optional = parser.add_argument_group('Optional arguments')
optional.add_argument("-h", "--help", action="help", help="show this help message and exit")
optional.add_argument("--device", help="GPU device to use, or 'cpu' to use CPU. Note CPU mode is many times slower", type=str, default='0')
args = parser.parse_args()

# Check for the existence of the nvidia controller
if (args.device != 'cpu'):
    try:
        nvidia_status = subprocess.check_output(['nvidia-smi', '-i', args.device])
        print(nvidia_status.decode('utf-8'))
    except Exception: # this command not being found can raise quite a few different errors depending on the configuration
        print('Cannot get status of GPU device ' + args.device + ' using nvidia-smi.'
              'Please check that the device is available and that nvidia-smi is installed.')
        sys.exit(1)

# For GPU systems
hdbet_device_settings = ['-device', args.device, '-mode', 'accurate', '-tta', '1']

if (args.device == 'cpu'):
    print('Warning: CPU mode is many times slower than GPU mode, and results may be suboptimal.')
    hdbet_device_settings = ['-device', args.device, '-mode', 'fast', '-tta', '0']

# Make this under system TMPDIR, cleaned up automatically
working_dir_tmpdir = tempfile.TemporaryDirectory(suffix=f".t1wpreproc.tmpdir")
working_dir = working_dir_tmpdir.name

input_dataset_dir = args.input_dataset
output_dataset_dir = args.output_dataset

participants = [ args.participant ]

# See if participant is a file, and if so, read it
if os.path.isfile(args.participant):
    with open(args.participant, 'r') as file_in:
        participants = [line.rstrip() for line in file_in]


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
    output_ds_description = {'Name': input_dataset_name + '_T1wpreprocessed', 'BIDSVersion': '1.8.0', 'DatasetType': 'derivative',
                            'PipelineDescription': {'Name': 'T1wPreprocessing',
                                                    'CodeURL': 'https://github.com/ftdc-picsl/T1wPreprocessing'}}

    # Write json to output dataset
    with open(os.path.join(output_dataset_dir, 'dataset_description.json'), 'w') as file_out:
        json.dump(output_ds_description, file_out, indent=2, sort_keys=True)

# Lots of paths here, use the following naming conventions:
# _full_path - full path to file
# _ds_rel_path - path relative to input dataset
# _image - image file name
# _source_entities - BIDS file name entities for source image, create derivatives by appending to this

for participant in participants:

    print(f"Processing participant {participant}")

    sessions = [f.name.replace('ses-', '') for f in os.scandir(os.path.join(input_dataset_dir, f"sub-{participant}")) if f.is_dir()
                and f.name.startswith('ses-')]

    for sess in sessions:

        print(f"Processing session {sess}")

        session_full_path = os.path.join(input_dataset_dir, f"sub-{participant}", f"ses-{sess}")

        t1w_images = [f.name for f in os.scandir(os.path.join(session_full_path, 'anat'))
                    if f.is_file() and f.name.endswith('_T1w.nii.gz')]

        for t1w_image in t1w_images:

            t1w_full_path = os.path.join(session_full_path, 'anat', t1w_image)

            # Want this relative to input data set to be the source data in output sidecars
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

            # Now call hd-bet
            hd_bet_cmd = ['hd-bet', '-i', tmp_t1w, '-o', tmp_output_t1w, '-b', '0', '-s',
                            '1', '-pp', '1']
            hd_bet_cmd.extend(hdbet_device_settings)
            subprocess.run(hd_bet_cmd, check = True)

            # For testing - output resliced image and mask without trimming
            # shutil.copyfile(tmp_t1w, os.path.join(output_dataset_dir, f"sub-{participant}", f"ses-{sess}", 'anat',
            #                                      f"{t1w_source_entities}_space-orig_desc-resliced_T1w.nii.gz"))
            # shutil.copyfile(tmp_mask, os.path.join(output_dataset_dir, f"sub-{participant}", f"ses-{sess}", 'anat',
            #                                      f"{t1w_source_entities}_space-orig_desc-brain_mask.nii.gz"))

            # trim neck with c3d, reslice mask into trimmed space
            tmp_t1w_trim = os.path.join(working_dir, 'T1wNeckTrim.nii.gz')
            tmp_mask_trim = os.path.join(working_dir, 'T1wNeckTrim_mask.nii.gz')

            subprocess.run(['trim_neck.sh', '-d', '-c', '10', tmp_t1w, tmp_t1w_trim], check = True)

            # Pad image with c3d and reslice mask to same space
            pad_mm = 10
            subprocess.run(['c3d', tmp_t1w_trim, '-pad', f"{pad_mm}x{pad_mm}x{pad_mm}mm", f"{pad_mm}x{pad_mm}x{pad_mm}mm", '0', '-o',
                            tmp_t1w_trim, '-interpolation', 'NearestNeighbor', tmp_mask, '-reslice-identity', '-type', 'uchar',
                                '-o', tmp_mask_trim], check = True)

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
