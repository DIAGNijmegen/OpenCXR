# -*- coding: utf-8 -*-
"""
Created on Fri July  2 2021

@author: ecem
"""
import opencxr
from opencxr.algorithms.base_algorithm import BaseAlgorithm
import numpy as np
from opencxr.utils.resize_rescale import resize_long_edge_and_pad_to_square, rescale_to_min_max
import os
from opencxr.utils.normalization import Normalizer
from opencxr.utils.mask_crop import crop_to_mask

class CXRStandardizationAlgorithm(BaseAlgorithm):

    def __init__(self):
        # create an instance of lung segmentation algorithm so we only need to do this once
        self.lung_seg_alg = opencxr.load(opencxr.algorithms.lung_seg)

    def name(self):
        return 'CXRStandardizationAlgorithm'

    def run(self, image_np, spacing, do_crop_to_lung_box=True, final_square_size=1024):
        """

        Args:
            image_np: np array, x, y ordering,
            spacing: tuple or list of spacing values
            do_crop_to_lung_box: boolean to indicate whether to crop around the lung segmentation
            final_square_size: The size (pixels) of the final output image (aspect ratio preserved, short side padded)

        Returns:
            standard_image: np array image with standardized intensities, cropped around lungs, resized to 1024x1024 with padding to preserve aspect ratio
            new_spacing: the new spacing of the image
            size_changes: A dict identifying size changes that took place (to enable users to repeat these on related images if needed)
        """

        # normalize intensities (this will also crop black borders and resize image to width 2048 and aspect preserved height)
        norm_img_np, new_spacing, size_changes_in_norm = Normalizer.do_full_normalization(image_np, spacing, self.lung_seg_alg)


        if do_crop_to_lung_box:
            #segment lungs on normalized image
            lung_mask_np = self.lung_seg_alg.run(norm_img_np)

            # crop to lung borders
            # first need to make the lung mask binary
            lung_mask_np = rescale_to_min_max(lung_mask_np, new_min=0, new_max=1)
            # then crop to the mask with margin
            lung_cropped_np, size_changes_lung_crop = crop_to_mask(norm_img_np, new_spacing, lung_mask_np, margin_in_mm=15.0)

        # now resize the normalized image to max dim specified, preserving aspect ratio and padding to square img.
        final_lung_cropped_resized, newest_spacing, size_changes_square_pad = resize_long_edge_and_pad_to_square(lung_cropped_np, new_spacing, final_square_size)
        final_lung_cropped_resized = np.clip(final_lung_cropped_resized, 0, 4095).astype(np.uint16)
        # and join all the size changes that were made, in order
        size_changes_final = size_changes_in_norm + size_changes_lung_crop + size_changes_square_pad



        return final_lung_cropped_resized, newest_spacing, size_changes_final

   
        
        
        
        
        
        
    
