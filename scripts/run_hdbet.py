#!/usr/bin/env python

import argparse
import os
import subprocess
import sys
import time
import traceback
# For QC
from PIL import Image

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


# Runs HD-BET brain extraction
# Inputs:
#   input_directory - the input directory, every image in this directory will be processed.
#   hdbet_device_settings - a list of hd-bet settings for device selection, e.g. ['-device', 'cuda']
#
def run_hdbet(input_directory, hdbet_device_settings, verbose=False):

    # Check there are at least some NIfTI files in the input directory
    nii_files = [f for f in os.listdir(input_directory) if f.endswith('.nii.gz')]

    if len(nii_files) == 0:
        print(f"No NIfTI files found in input directory {input_directory}")
        return

    # Now call hd-bet
    hd_bet_cmd = ['hd-bet', '-i', input_directory, '-o', input_directory, '--no_bet_image', '--save_bet_mask']
    hd_bet_cmd.extend(hdbet_device_settings)
    if verbose:
        hd_bet_cmd.append('--verbose')

    run_command(hd_bet_cmd)


# Helps with CLI help formatting
class RawDefaultsHelpFormatter(
    argparse.RawTextHelpFormatter, argparse.ArgumentDefaultsHelpFormatter
):
    pass

def main():

    global __verbose__

    parser = argparse.ArgumentParser(formatter_class=RawDefaultsHelpFormatter,
                                    add_help = False,
                                    description='''Wrapper for batch processing of T1-weighted images using HD-BET brain
                                    extraction.

    Input is a directory containing T1w images. Output is to the same directory. Masks will be created with the suffix
    '_bet.nii.gz'.

    ''')
    required = parser.add_argument_group('Required arguments')
    required.add_argument("--input-directory", help="Input directory, containing the source images", type=str,
                          required=True)

    optional = parser.add_argument_group('Optional arguments')
    optional.add_argument("-h", "--help", action="help", help="show this help message and exit")
    optional.add_argument("--device", help="GPU device to use. Supported GPUs are 'cuda', 'mps'. For cpu mode, use 'cpu'. Note "
                          "CPU mode is many times slower and may not be as robust, or even work at all", type=str,
                          default='cuda')
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

    try:
        start = time.time()
        run_hdbet(args.input_directory, hdbet_device_settings, verbose=args.verbose)
        end = time.time()
        print(f"HD-BET processing completed in {end - start:.0f} seconds")
    except PipelineError:
        print("HD-BET processing failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()