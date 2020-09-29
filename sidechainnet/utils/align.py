"""
This file will implement functions that allow the merging of sidechain data with
Mohammed AlQuraishi's ProteinNet. It works by conforming the data I have
generated with sidechain information to match the sequence and mask reported by
ProteinNet.

Author: Jonathan King
Date : 3/09/2020
"""

import numpy as np
from Bio import Align

from sidechainnet.utils.build_info import NUM_COORDS_PER_RES, PRODY_CA_DIST
from sidechainnet.utils.download import ASTRAL_ID_MAPPING, determine_pnid_type


def init_basic_aligner(allow_mismatches=False):
    """ Returns an aligner with minimal assumptions about gaps."""
    a = Align.PairwiseAligner()
    if allow_mismatches:
        a.mismatch_score = -1
        a.gap_score = -3
        a.target_gap_score = -np.inf
    if not allow_mismatches:
        a.mismatch = -np.inf
        a.mismatch_score = -np.inf
    return a


def init_aligner(allow_target_gaps=False, allow_target_mismatches=False):
    """
    Creates an aligner whose weights penalize excessive gaps, make gaps
    in the ProteinNet sequence impossible, and prefer gaps at the tail ends
    of sequences.
    """
    a = Align.PairwiseAligner()
    a.mismatch = -np.inf
    a.mismatch_score = -np.inf

    # Don't allow for gaps or mismatches with the target sequence
    if not allow_target_gaps:
        a.target_gap_score = -np.inf

    # Do not let matching items overwhelm determining where gaps should go
    if not allow_target_gaps:
        a.match = 10
    else:
        a.match = 200

    if allow_target_mismatches:
        a.mismatch = 200

    # Generally, prefer to extend gaps than to create them
    a.query_extend_gap_score = 99
    a.query_open_gap_score = 49

    # Set slight preference for open gaps on the edges, however, if present, strongly prefer single edge gaps
    a.query_end_open_gap_score = 50
    a.query_end_extend_gap_score = 100

    return a


def get_mask_from_alignment(al):
    """ For a single alignment, return the mask as a string of '+' and '-'s. """
    alignment_str = str(al).split("\n")[1]
    return alignment_str.replace("|", "+")


def get_padded_second_seq_from_alignment(al):
    """ For a single alignment, return the second padded string. """
    alignment_str = str(al).split("\n")[2]
    return alignment_str


def locate_char(c, s):
    """ Returns a list of indices of character c in string s."""
    return [i for i, l in enumerate(s) if l == c]


def masks_match(pn, new):
    """ Returns true if the two masks match, or if pn is a subset of new."""
    if pn == new:
        return True
    elif new.count("-") > pn.count("-"):
        # If all of the gaps specified by ProteinNet are found by our
        # alignment, but there are some additional gaps, this is acceptable.
        new_gap_locs = locate_char("-", new)
        pn_gap_locs = locate_char("-", pn)
        pn_gaps_still_present = all([pn_gap in new_gap_locs for pn_gap in pn_gap_locs])
        return pn_gaps_still_present
    else:
        return False


def shorten_ends(s1, s2, s1_ang, s1_crd):
    """Shortens s1 by removing characters at either end that don't match s2.

    Args:
        s1: String, longer than s2
        s2: String

    Returns:
        A possibly shortened version of s1, with non-matching start and end
        characters trimmed off.
    """
    aligner = init_aligner(allow_target_gaps=True)
    a = aligner.align(s1, s2)
    mask = get_padded_second_seq_from_alignment(a[0])
    i = len(mask) - 1
    while mask[i] == "-":
        s1 = s1[:-1]
        s1_ang = s1_ang[:-1]
        s1_crd = s1_crd[:-NUM_COORDS_PER_RES]
        mask = mask[:-1]
        i -= 1
    while mask[0] == "-":
        s1 = s1[1:]
        s1_ang = s1_ang[1:]
        s1_crd = s1_crd[NUM_COORDS_PER_RES:]
        mask = mask[1:]
    return s1, s1_ang, s1_crd


def merge(aligner, pn_seq, my_seq, ang, crd, pn_mask, pnid, attempt_number=0):
    """
    Returns True iff when pn_seq and my_seq are aligned, the resultant mask
    is the same as reported by ProteinNet. Also returns the computed_mask that
    matches with ProteinNet
    """
    a = aligner.align(pn_seq, my_seq)
    pn_mask = binary_mask_to_str(pn_mask)
    warning = None

    try:
        n_alignments = len(a)
    except OverflowError:
        n_alignments = 50

    if n_alignments == 0 and attempt_number == 0:
        # Use aligner with a typical set of assumptions.
        aligner = init_aligner()
        return merge(aligner, pn_seq, my_seq, ang, crd, pn_mask, pnid, attempt_number=1)

    if n_alignments == 0 and attempt_number == 1:
        # If there appear to be no alignments, it may be the case that there
        # were residues observed that were not present in the ProteinNet
        # sequence. If this occurs at the edges, we can safely trim the
        # observed sequence and try alignment once again
        my_seq, ang, crd = shorten_ends(my_seq, pn_seq, ang, crd)
        return merge(aligner, pn_seq, my_seq, ang, crd, pn_mask, pnid, attempt_number=2)

    if n_alignments == 0 and attempt_number == 2:
        # Try making very few assumptions about gaps before allowing mismatches/gaps in
        # the target sequence.
        aligner = init_basic_aligner(allow_mismatches=True)
        return merge(aligner, pn_seq, my_seq, ang, crd, pn_mask, pnid, attempt_number=3)

    elif n_alignments == 0 and attempt_number == 3:
        aligner = init_aligner(allow_target_gaps=True, allow_target_mismatches=True)
        mask, a0, ang, crd, warning = merge(aligner,
                                            pn_seq,
                                            my_seq,
                                            ang,
                                            crd,
                                            pn_mask,
                                            pnid,
                                            attempt_number=4)
        warning = warning + ", mismatch used in alignment" if warning else "mismatch used in alignment"
        return mask, a0, ang, crd, warning

    elif n_alignments == 0 and attempt_number == 4:
        warning = "failed"
        return None, None, ang, crd, warning

    elif n_alignments == 1:
        a0 = a[0]
        computed_mask = get_mask_from_alignment(a0)
        if attempt_number == 4:
            if computed_mask.count("X") + computed_mask.count(".") > 5:
                warning = "too many wrong AAs"
            computed_mask = computed_mask.replace("X", "+").replace(".", "+")
        if not masks_match(pn_mask, computed_mask):
            if "astral" in determine_pnid_type(pnid):
                pdbid, chain = ASTRAL_ID_MAPPING[pnid.split("_")[1].replace("-", "_")]
                if "A" not in chain:
                    # This suggests that ProteinNet made a mistake and parsed
                    # chain A when they should have parsed the correct chain.
                    # This is therefore not an alignment error.
                    pass
                else:
                    # If the above case is not True, then we should still expect
                    # the mask we compute to match the one computed by ProteinNet
                    warning = "single alignment, mask mismatch"
            else:
                warning = "single alignment, mask mismatch"
        return computed_mask, a0, ang, crd, warning

    elif n_alignments > 1:
        best_mask = None
        found_a_match = False
        best_alignment = None
        best_idx = 0
        has_many_alignments = n_alignments >= 200
        for i, a0 in enumerate(a):
            if has_many_alignments and i >= 200:
                break
            computed_mask = get_mask_from_alignment(a0)
            if attempt_number == 4:
                if computed_mask.count("X") + computed_mask.count(".") > 5:
                    warning = "too many wrong AAs"
                computed_mask = computed_mask.replace("X", "+").replace(".", "+")
            if not best_mask:
                best_mask = computed_mask
                best_idx = i
            if not best_alignment:
                best_alignment = a0
            if masks_match(pn_mask, computed_mask) or assert_mask_gaps_are_correct(
                    computed_mask, crd)[0]:
                found_a_match = True
                best_mask = computed_mask
                best_alignment = a0
                best_idx = i
                break
        if found_a_match:
            warning = "multiple alignments, found matching mask" if not warning else warning + ", multiple alignments, found matching mask"
            if has_many_alignments:
                warning += ", many alignments"
            return best_mask, best_alignment, ang, crd, warning
        else:
            mask = get_mask_from_alignment(a[0])
            warning = "multiple alignments, mask mismatch" if not warning else warning + ", multiple alignments, mask mismatch"
            if has_many_alignments:
                warning += ", many alignments"
            return mask, a[0], ang, crd, warning


def other_alignments_with_same_score(all_alignments, cur_alignment_idx,
                                     cur_alignment_score):
    """Returns True if there are other alignments with identical scores.

    Args:
        all_alignments: PairwiseAlignment iterable object from BioPython.Align
        cur_alignment_idx: The index of the desired alignment
        cur_alignment_score: The score of the desired alignment

    Returns:
        True if any alignments other than the one specified have scores that
        are identical to the specified alignment.
    """
    if len(all_alignments) <= 1:
        return False

    for i, a0 in enumerate(all_alignments):
        if i > 0 and a0.score < cur_alignment_score:
            break
        if i == cur_alignment_idx:
            continue
        elif a0.score == cur_alignment_score:
            return True

    return False


def binary_mask_to_str(m):
    """
    Given an iterable or list of 1s and 0s representing a mask, this returns
    a string mask with '+'s and '-'s.
    """
    m = list(map(lambda x: "-" if x == 0 else "+", m))
    return "".join(m)


def unmask_seq(ang, seq):
    """
    Given an angle array that is padded with np.nans, applies this padding to
    the sequence, and returns the sequence without any padding. This means
    that the input sequence contains residues that may be missing, while the
    returned sequence contains only observed residues.
    """
    mask = np.logical_not(np.isnan(ang).all(axis=-1))
    new_seq = ""
    for m, s in zip(mask, seq):
        if m:
            new_seq += s
        else:
            continue

    return new_seq


def coordinate_iterator(coords, atoms_per_res):
    """Iterates over coordinates in a numpy array grouped by residue.

    Args:
        coords: Numpy array of coordinates. (L x atoms_per_res) x 3.
        atoms_per_res: Number of atomic coordinates per residue.

    Returns:
        An iterator where every next call returns the next atoms_per_res
            coordinates.
    """
    assert len(coords) % atoms_per_res == 0, f"There must be {atoms_per_res}" \
                                             f" atoms for every residue.\n" \
                                             f"len(coords) = {len(coords)}"
    i = 0
    while i + atoms_per_res <= len(coords):
        yield coords[i:i + atoms_per_res]
        i += atoms_per_res


def expand_data_with_mask(data, mask):
    """Uses mask to expand data as necessary.

    Args:
        data: May be evolutionary (numpy array, Lx21), secondary (unsupported),
            angles (2D numpy array, Lx12), coordinates (2D numpy array,
             (Lx13)x3).
        mask: String of '+'s and '-'s representing if data is present with
            respect to protein primary sequence.

    Returns:
        Data in the same format, possibly extending L to match the length of
        the mask, that now contains padding.
    """
    if mask.count("-") == 0 and data.shape[0] == len(mask):
        return data

    size = data.shape[-1]
    if size == 3:
        data = coordinate_iterator(data, NUM_COORDS_PER_RES)
        blank = np.empty((NUM_COORDS_PER_RES, 3))
    else:
        data = iter(data)
        blank = np.empty((size,))

    blank[:] = np.nan

    new_data = []
    for m in mask:
        if m == "+" or m == ".":
            new_data.append(next(data))
        elif m == "-":
            new_data.append(blank.copy())
        else:
            raise ValueError(f"Unknown mask character '{m}'.")

    return np.vstack(new_data)


def pad_seq_with_mask(seq, mask):
    """Given a shorter sequence, expands it to match the padding in mask.

    Args:
        seq: String with length smaller than mask.
        mask: String of '+'s and '-'s used to expand seq.

    Returns:
        New string of seq but with added '-'s where indicated by mask.
    """
    seq_iter = iter(seq)
    new_seq = ""
    for m in mask:
        if m == "+":
            new_seq += next(seq_iter)
        elif m == "-":
            new_seq += "-"
    return new_seq


def manually_adjust_data(pnid, sc_entry):
    """ Returns a modified version of sc_entry to fix some issues manually.

    Args:
        pnid: string, ProteinNet ID
        sc_entry: dictionary containing "seq", "ang", "crd" data

    Returns:
        If sc_entry must be modified, then it is corrected and returned.
        Otherwise, it is returned without modifications.

    """

    # In the case of 5FXN, ProDy mistakenly parses two extranneous residues "VK"
    # from the file due to the file not distinguishing these resides as being
    # on a different segment. We can manually remove this data here before
    # proceeding with alignment.
    # https://github.com/prody/ProDy/issues/1045
    if "5FXN" in pnid and len(sc_entry["seq"]) == 316 and sc_entry["seq"][-3:] == "VVK":
        sc_entry["seq"] = sc_entry["seq"][:-2]
        sc_entry["ang"] = sc_entry["ang"][:-2]
        sc_entry["crd"] = sc_entry["crd"][:-NUM_COORDS_PER_RES * 2]

    return sc_entry


def assert_mask_gaps_are_correct(mask, coordinates):
    """ Returns True if the structure supports the mask.

    Args:
        mask: string of "+" and "-"s, denoting missing residues
        coordinates: numpy array (L x 14 x 3) of atomic coordinates

    Returns:
        True iff the mask is supported by the structure. If False, also returns length
        of the offending Ca-Ca distance.
    """
    CA_IDX = 1
    if mask.count("-") == 0:
        return True, 0

    # This should never happen
    if mask.count("+") != len(coordinates) // NUM_COORDS_PER_RES:
        return False, 0

    # First, build a nested list that holds all contiguous regions of the data
    # according to the mask
    coord_iter = coordinate_iterator(coordinates, NUM_COORDS_PER_RES)
    coord_contigs = []
    cur_contig = []

    for m in mask:
        if m == "-":
            if cur_contig != []:
                coord_contigs.append(cur_contig.copy())
                cur_contig = []
            continue
        else:
            cur_contig.append(next(coord_iter))
    if cur_contig != []:
        coord_contigs.append(cur_contig.copy())

    # Once the contiguous regions are reported, we check that the distance
    # between all alpha-carbons is less than ProDy's cutoff (4.1 Angstrom)
    for coord_contig in coord_contigs:
        if len(coord_contig) == 1:
            continue
        prev_ca = coord_contig[0][CA_IDX]
        for cur_res in coord_contig[1:]:
            cur_ca = cur_res[CA_IDX]
            if np.linalg.norm(cur_ca - prev_ca) > PRODY_CA_DIST * 1.85:
                return False, np.linalg.norm(cur_ca - prev_ca)
            prev_ca = cur_ca.copy()

    return True, 0
