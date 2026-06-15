import json
import os

from bids import BIDSLayout, BIDSLayoutIndexer

# Shared functions for finding T1w images in a BIDS session directory. It's important that the run_prepare_input script
# and the run_postprocessing script use consistent logic for finding T1w images, because it's an error if images selected
# in the run_prepare_input script are not found in the run_postprocessing script.


def find_t1w_images_from_bids(bids_layout, participant, session, bids_filter=None, acq_preference_order=None):
    """Find T1w images in a BIDS session directory, using a BIDS layout with pybids.

    If acq_preference_order is not None, it should be a list of acquisition labels in order of preference. The function will
    select the first image that has an acq label exactly matching one of the available options

    Parameters:
    -----------
    bids_layout : BIDSLayout
        A pybids BIDSLayout object for the dataset.
    participant : str
        The participant label (e.g. '01').
    session : str
        The session label (e.g. '01').
    bids_filter : dict, optional
        Filter queries for the BIDS layout.
    acq_preference_order : list of str, optional
        A list of acquisition labels in order of preference (e.g. ['acq-1', 'acq-2']). If None, no preference will be applied
        and all T1w images will be returned.
    """
    t1w_images_bids = bids_layout.get(subject=participant, session=session, extension=".nii.gz", **(bids_filter or {}))

    t1w_image_file_names = [image.filename for image in t1w_images_bids]

    if acq_preference_order is not None:
        preferred_image = find_preferred_t1w_image(t1w_image_file_names, acq_preference_order)
        return [preferred_image] if preferred_image is not None else []
    else:
        return t1w_image_file_names


def find_t1w_images_from_filesystem(session_full_path, acq_preference_order=None):
    """Find T1w images in a BIDS session directory using a simple file system search.

    If acq_preference_order is not None, it should be a list of acquisition labels in order of preference. The function will
    select the first image that has an acq label exactly matching one of the available options.

    Parameters:
    -----------
    session_full_path : str
        Full path to the BIDS session directory (e.g. '/path/to/dataset/sub-01/ses-01').
    acq_preference_order : list of str, optional
        A list of acquisition labels in order of preference (e.g. ['acq-1', 'acq-2']). If None, no preference will be applied
        and all T1w images will be returned.


    # default list
    available_images = [f.name for f in os.scandir(os.path.join(session_full_path, 'anat'))
                        if f.is_file() and f.name.endswith('_T1w.nii.gz')]
    """
    t1w_image_file_names = [f.name for f in os.scandir(os.path.join(session_full_path, 'anat'))
                            if f.is_file() and f.name.endswith('_T1w.nii.gz')]

    if acq_preference_order is not None:
        preferred_image = find_preferred_t1w_image(t1w_image_file_names, acq_preference_order)
        return [preferred_image] if preferred_image is not None else []
    else:
        return t1w_image_file_names


def find_preferred_t1w_image(t1w_image_file_names, acq_preference_order):
    """Find the preferred T1w image based on acquisition label preference.

    Parameters:
    -----------
    t1w_image_file_names : list of str
        A list of T1w image file names (e.g. ['sub-01_ses-01_acq-1_T1w.nii.gz', 'sub-01_ses-01_acq-2_T1w.nii.gz']).
    acq_preference_order : list of str
        A list of acquisition labels in order of preference (e.g. ['acq-1', 'acq-2']).

    Returns:
    --------
    str or None : The file name of the preferred T1w image, or None if no preferred image is found.
    """
    for acq_label in acq_preference_order:
        for file_name in t1w_image_file_names:
            if f'acq-{acq_label}' in file_name:
                return file_name
    return None


def get_bids_layout(dataset_path):
    """Get a BIDSLayout for the dataset, with an indexer that only indexes T1w images."""
    indexer = BIDSLayoutIndexer(
        validate=False,
        index_metadata=False,
        datatype="anat",
        suffix="T1w",
    )

    layout = BIDSLayout(
        dataset_path,
        indexer=indexer,
    )

    return layout
