# -*- coding: utf-8 -*-
"""
@author: keelin
"""

import numpy as np
from opencxr.utils.mask_crop import crop_img_borders
from opencxr.utils.resize_rescale import resize_preserve_aspect_ratio
from scipy import ndimage


class Normalizer:
    """
    Implements the method of Philipsen et al, IEEE Transactions on Medical Imaging, 2015
    https://ieeexplore.ieee.org/document/7073580
    "Localized Energy-Based Normalization of Medical Images: Application to Chest Radiography"

    In general users of opencxr need only access method do_full_normalization()

    The coefficients used here (coeffs70 and coeffs_lungseg) are generated by opencxr team,
    using a private set of 50 CXR images as described in the Philipsen paper
    """

    @classmethod
    def split_energy_bands(cls, image, sigmas):
        """
        Split an np image to energy bands as described in section III.A of Philipsen et al, also reference [40] of that work.
        :param image: the input image
        :param sigmas: The array of sigmas, set as per Philipsen at [1, 2, 4, 8, 16]
        :return: The array of energy band images from 16 to 1, with the filtered image in the last place
        """

        bands = np.zeros((len(sigmas) + 1,) + image.shape)

        curr_I_x = image
        for sigma_ind, sigma in enumerate(sigmas):
            curr_L_x = ndimage.filters.gaussian_filter(curr_I_x, sigma, mode="wrap")

            bands[sigma_ind] = curr_I_x - curr_L_x

            # when we have no sigmas left, store the final filtered image in the last band (Fig 3 and reference [40])
            if sigma_ind == len(sigmas) - 1:
                bands[sigma_ind + 1] = curr_L_x

            curr_I_x = curr_L_x

        # return the bands in reverse order of sigmas ([16,8,4,2,1])
        return bands[::-1]

    @classmethod
    def report_energy_bands(cls, bands, mask=1):
        """
        given the energy bands of the image, and a region to focus on
        returns the means, stdevs of the energy bands in that region
        the stdevs are the "energy values" e_i_omega as used in formula 5 of Philipsen paper
        :param bands: energy bands from split_energy_bands method
        :param mask: region of interest (either central 70% of image, or a lung mask)
        :return: a list of means and a list of std-devs
        """
        means = []
        stdevs = []
        shape = bands[0].shape
        if isinstance(
            mask, np.ndarray
        ):  # if the mask provided is an array (a lung mask)
            for band in bands:
                values = band[mask > 0]
                means.append(values.mean())
                stdevs.append(values.std())
        else:  # otherwise we have no lung mask, just use central 70% of the image
            for band in bands:
                sub_im = band[
                    int(0.15 * shape[0]) : int(0.85 * shape[0]),
                    int(0.15 * shape[1]) : int(0.85 * shape[1]),
                ]
                means.append(sub_im.mean())
                stdevs.append(sub_im.std())
        return means, stdevs

    @classmethod
    def reconstruct(cls, bands, means, stdevs, coefficients):
        """
        reconstructs the normalized image from the energybands and reference coefficients
        see formula 5 of Philipsen et al
        :param bands: the bands from split_energy_bands method
        :param means: the means from report_energy_bands method
        :param stdevs: the stddevs from report_energy_bands method
        :param coefficients: the coefficients which are constants derived from a reference dataset
        :return: The reconstructed normalized image
        """
        bands[0] = (bands[0] - means[0]) / stdevs[0]
        for j in range(1, bands.shape[0]):
            bands[j] = bands[j] * coefficients[j] / stdevs[j]
        return bands.sum(0)

    @classmethod
    def get_norm_central_70(cls, img_np, spacing):
        """
        Get a normalized image based on central 70% of the image
        Will first crop the image (removing homogeneous black border regions) and resize it to 2048 wide (preserving aspect ratio)
        :param img_np: The input image to be normalized
        :param spacing: the spacing of the input image
        :return: A normalized image for feeding to step 2 of the normalization algorithm (using a lung mask)
                 The same normalized image that is rescaled/clipped so that it is nicer to view
                 The spacing of the returned image
                 The list of size changes carried out for reference or future use (see utils __init__.py)
        """
        # the coefficients lambda, calculated by opencxr team, based on a private reference set of 50 images (see formula 4 in Philipsen et al)
        coeffs70 = [1, 0.15046743, 0.09473514, 0.06337214, 0.0451897, 0.03574716]
        # 6 sigma bands as per the Philipsen paper.
        sigmas = sigmas = [1, 2, 4, 8, 16]
        # make sure the image is float
        img_np = img_np.astype(np.float64)
        # crop away black borders
        img_np, size_changes_border_crop = crop_img_borders(
            img_np, in_thresh_factor=0.05
        )
        # resize to width of 2048
        img_np, new_spacing, size_changes_2048 = resize_preserve_aspect_ratio(
            img_np, spacing, 2048, 0
        )
        # split into energy bands
        bands = cls.split_energy_bands(img_np, sigmas)
        # get means and stddevs of the energy bands
        means, stdevs = cls.report_energy_bands(bands)
        # reconstruct an image from the energy bands and the reference values
        norm_70 = cls.reconstruct(bands, means, stdevs, coeffs70)

        # the norm_70 image can be fed to the next normalization step.  But for a nice readable image we can scale/clip it.
        # set to min, max 0,4095
        new_min = 0
        new_max = 4095
        img_mean = norm_70.mean()
        set_min = img_mean - 5.0
        set_max = img_mean + 5.0
        readable_img = np.clip(
            (new_max - new_min) * ((norm_70 - set_min) / (set_max - set_min)) + new_min,
            new_min,
            new_max,
        ).astype(np.uint16)

        # combine all size changes in a single list to return
        size_changes_border_crop.extend(size_changes_2048)

        # return the norm_70 for step2, the readable norm70, the new spacing, and the list of size changes
        return norm_70, readable_img, new_spacing, size_changes_border_crop

    @classmethod
    def get_norm_lung_mask(cls, img_np_norm70, lung_mask_np):
        """
        The second normalization step.  This takes the norm_70 image from get_norm_central_70, and a lung mask of it.
        The second normalization step is applied.
        :param img_np_norm70: The input image, the first image returned by get_norm_central_70()
        :param lung_mask_np: The lung mask of the input image
        :return: the final normalized image, scaled and clipped for best viewing
        """

        # the coefficients lambda based on a reference set of 50 images (see formula 4 in Philipsen et al)
        coeffs_lungseg = [1, 0.26093275, 0.18805708, 0.13976646, 0.1033522, 0.07498657]
        # 6 sigma bands as per the Philipsen paper.
        sigmas = [1, 2, 4, 8, 16]
        # split into energy bands
        bands = cls.split_energy_bands(img_np_norm70, sigmas)
        # get means and stddevs of the energy bands
        means, stdevs = cls.report_energy_bands(bands, mask=lung_mask_np)
        # reconstruct from the energy bands and reference coefficients
        norm = cls.reconstruct(bands, means, stdevs, coeffs_lungseg)

        # rescale and clip to more readable values:
        new_min = 0
        new_max = 4095
        #
        set_min = -5.0
        set_max = 5.0

        # rescale from range -5, +5 to 0,4095
        # and clip values that end up outside that range
        readable_img = np.clip(
            (new_max - new_min) * ((norm - set_min) / (set_max - set_min)) + new_min,
            new_min,
            new_max,
        )

        return readable_img

    @classmethod
    def do_full_normalization(cls, img_in, spacing, lung_seg_algorithm):
        """
        Does full 2 step normalization including an intermediate lung segmentation
        :param img_in: The input image to be normalized
        :param spacing: The spacing of the input image
        :param lung_seg_algorithm: an instance of the lung segmentation algorithm
        :return: The normalized image with larger axis at size 2048 pixels
                  The new spacing for the normalized image
                  The list of size changes carried out for reference or future use (see utils __init__.py)
        """

        # do norm step 1 (central 70%)
        norm_70, readable_img, new_spacing, size_changes = cls.get_norm_central_70(
            img_in, spacing
        )

        # do a lung segmentation on the norm image
        lung_seg_mask = lung_seg_algorithm.run(readable_img)

        # if the lung seg mask is completely empty this is probably not a lung image at all so we should fail gracefully
        # i.e. return an empty image
        if np.max(lung_seg_mask) == 0:
            print("lung seg finds no lung so cxr standardization returning empty image")
            return lung_seg_mask, new_spacing, size_changes

        # do norm step 2 using the lung segmentation image
        final_norm_img = cls.get_norm_lung_mask(norm_70, lung_seg_mask)

        return final_norm_img, new_spacing, size_changes
