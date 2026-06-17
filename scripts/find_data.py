import json
import os
import re

from bids import BIDSLayout, BIDSLayoutIndexer

# Shared functions for finding T1w images in a BIDS session directory. It's important that the run_prepare_input script
# and the run_postprocessing script use consistent logic for finding T1w images, because it's an error if images selected
# in the run_prepare_input script are not found in the run_postprocessing script.


def find_t1w_images_from_bids(bids_layout, participant, session, bids_filter=None, acq_preference_order=None,
                              last_run_only=False):
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
    last_run_only : bool, optional
        If True, only consider images from the last run (default is False).
    """
    t1w_images_bids = bids_layout.get(subject=participant, session=session, extension=".nii.gz", **(bids_filter or {}))

    t1w_image_file_names = [image.filename for image in t1w_images_bids]

    if acq_preference_order is not None:
        t1w_image_file_names = find_preferred_t1w_acquisition(t1w_image_file_names, acq_preference_order)

    if last_run_only:
        t1w_image_file_names = get_last_run_only(t1w_image_file_names)

    return t1w_image_file_names


def find_t1w_images_from_filesystem(session_full_path, acq_preference_order=None, last_run_only=False):
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
        t1w_image_file_names = find_preferred_t1w_acquisition(t1w_image_file_names, acq_preference_order)

    if last_run_only:
        t1w_image_file_names = get_last_run_only(t1w_image_file_names)

    return t1w_image_file_names


def find_preferred_t1w_acquisition(t1w_image_file_names, acq_preference_order):
    """Find the preferred T1w image based on acquisition label preference.

    Parameters:
    -----------
    t1w_image_file_names : list of str
        A list of T1w image file names (e.g. ['sub-01_ses-01_acq-1_T1w.nii.gz', 'sub-01_ses-01_acq-2_T1w.nii.gz']).
    acq_preference_order : list of str
        A list of acquisition labels in order of preference (e.g. ['acq-1', 'acq-2']).

    Returns:
    --------
    list of str: The file name of the preferred T1w image, which may be empty if no preferred image is found.
    """
    preferred_images = []

    for acq_label in acq_preference_order:
        for file_name in t1w_image_file_names:
            # Need exact match here
            # Get all runs for the preferred acquisition
            if f"_acq-{acq_label}_" in file_name:
                preferred_images.append(file_name)
        # If we found any preferred images for this acquisition label, we can stop looking further down the preference list
        if preferred_images:
            break

    return preferred_images


def get_last_run_only(t1w_image_file_names):
    """Filter a list of T1w image file names to only include those from the last run.

    Each acquisition may have multiple runs (e.g. 'run-1', 'run-2', etc.). This function will keep only the image from the
    highest run number for each acquisition, as grouped by the acq- label. If an image does not have a run entity, it will
    be included.

    Parameters:
    -----------
    t1w_image_file_names : list of str
        A list of T1w image file names (e.g. ['sub-01_ses-01_run-1_T1w.nii.gz', 'sub-01_ses-01_run-2_T1w.nii.gz']).

    Returns:
    --------
    list of str: A list of T1w image file names from the last run for each acquisition
    """
    if not t1w_image_file_names:
        return []

    t1w_image_file_entities = {file_name: get_bids_file_entities(file_name) for file_name in t1w_image_file_names}

    # Find the highest run number for each acquisition label. Files with a run
    # entity but no acq entity are grouped together.
    highest_run_by_acq = {}
    for file_name in t1w_image_file_names:
        entities = t1w_image_file_entities[file_name]
        if 'run' not in entities:
            continue

        acq_label = entities.get('acq')
        run_number = int(entities['run'])
        highest_run_by_acq[acq_label] = max(run_number, highest_run_by_acq.get(acq_label, -1))

    last_run_images = []
    for file_name in t1w_image_file_names:
        entities = t1w_image_file_entities[file_name]
        if 'run' not in entities:
            last_run_images.append(file_name)
        elif int(entities['run']) == highest_run_by_acq[entities.get('acq')]:
            last_run_images.append(file_name)

    return last_run_images


def get_bids_file_entities(file_path):
    """
    Parse a BIDS-like filename into entity-label pairs plus 'suffix' and 'extension'.

    Rules:
    - Split on '_' into N tokens [0..N-1].
    - For tokens 0..N-2: split on '-' into exactly two parts (entity, label).
        Both must be strictly alphanumeric (A-Za-z0-9). Otherwise raise ValueError.
    - For token N-1: split at the FIRST '.' into [suffix, rest].
        - suffix must be strictly alphanumeric.
        - extension is '.' + rest, and must match (?:\\.[A-Za-z0-9]+)+ (e.g., '.nii.gz').


    Parameters:
    -----------
    file_path : str
        The path to the file (e.g. '/path/to/dataset/sub-01_ses-01_acq-1_T1w.nii.gz' or 'sub-01_ses-01_acq-1_T1w.nii.gz').

    Returns:
    --------
        dict
            {'entity': 'label', ..., 'suffix': <suffix>, 'extension': <extension>}
    """
    filename = os.path.basename(file_path)
    if not filename or "_" not in filename:
        raise ValueError("Filename must contain at least one '_' separating entities from suffix/extension.")

    tokens = filename.split("_")
    if len(tokens) < 2 or "." not in tokens[-1]:
        raise ValueError("Filename must have at least one entity-label pair and a suffix/extension.")

    file_entities: dict[str, str] = {}

    # Parse entity-label pairs
    for part in tokens[:-1]:
        etokens = part.split("-", 1)
        if len(etokens) != 2:
            raise ValueError(f"Invalid entity-label pair (missing single '-'): {part}")
        entity, label = etokens[0], etokens[1]
        if not (entity.isalnum() and label.isalnum()):
            raise ValueError(f"Entity and label must be alphanumeric: {part}")
        file_entities[entity] = label

    # Parse suffix + extension from the last token
    last = tokens[-1]
    dtokens = last.split(".", 1)
    if len(dtokens) != 2:
        raise ValueError("Final token must contain a '.' separating suffix and extension.")
    suffix, ext_rest = dtokens[0], dtokens[1]
    if not suffix.isalnum():
        raise ValueError(f"Suffix must be alphanumeric: {suffix}")

    extension = f".{ext_rest}"
    if re.fullmatch(r"(?:\.[A-Za-z0-9]+)+", extension) is None:
        raise ValueError(f"Extension must be alphanumeric segments prefixed by dots: {extension}")

    file_entities["suffix"] = suffix
    file_entities["extension"] = extension
    return file_entities



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
