from __future__ import division
from __future__ import print_function
import cv2
import numpy as np
import urllib
import gspread
import random
import re
import os
import glob
import sys

from image_tiling import tiled_img
from contour_metrics import contour_metrics, contour_metrics_output
import frame_detection
import background_detection
import shadow_detection

def refine_background_via_grabcut(img, is_background, dilate=False):
    #use grabcut (http://docs.opencv.org/trunk/doc/py_tutorials/py_imgproc/py_grabcut/py_grabcut.html) 
    # to cut out other background pixels
    bgdModel = np.zeros((1,65),np.float64)
    fgdModel = np.zeros((1,65),np.float64)
    rect = (0,0,img.shape[1],img.shape[0])
    grabcut_mask = np.where(is_background!=0,cv2.GC_BGD,cv2.GC_PR_FGD).astype(np.uint8) #background should be 0, probable foreground = 3 
    cv2.grabCut(img, grabcut_mask,rect,bgdModel,fgdModel,5,cv2.GC_INIT_WITH_MASK)
    return np.where((grabcut_mask ==2)|(grabcut_mask ==0),0,1).astype(np.uint8)
    

def grab_butterfly(small_img, large_img, EoLobjectID, param_dir = None, composite_file_dir = True, butterfly_with_contour_file_dir = "butterflies"):
    '''Process a small and a large butterfly file, under a certain objectID. If a param_dir is give, save potential butterfly outlines and relevant parameters there (useful 
    for constructing logistic regression models to predict whether a contour is a butterfly shape or not). If save_composite_file is given, save a composite, tiled image 
    of the various stages of background subtraction. If butterfly_with_contour_file_dir is given, save the final output in this dir'''
    H, W = large_img.shape[:2]
    h, w = small_img.shape[:2]
    flood_cutoff = {'n_areas':3, 'percent': 25.0} #cutoffs for deciding if image is pinned

    # First crop any exterior frames (only if inner rect > 60% of picture)
    crop_left,crop_top,crop_right,crop_bottom = frame_detection.using_rectangular_contour(small_img, 0.6)
    img = small_img[crop_top:(h-crop_bottom), crop_left:(w-crop_right),:]

    #remove non-linear noise, to cope with speckled backgrounds. A few rounds of filtering required
    despeckled = cv2.bilateralFilter(img, 5, 100, 100)
    despeckled = cv2.bilateralFilter(despeckled, 7, 50, 50)
    despeckled = cv2.bilateralFilter(despeckled, 9, 20, 20)

    #use spatial mean-shift to unify the background colours without affecting edges where there is a distinct colour / intensity shift
    quantized = cv2.pyrMeanShiftFiltering(despeckled, 20, 20, 3)

    #find the largest areas of +- coherent colour, using floodfilling from multiple points
    dummy_mask, mask_after_flood, flood_param = background_detection.using_floodfill(despeckled, quantized, flood_cutoff["n_areas"], flood_cutoff["n_areas"], [1.4,0.9], flood_type=0, reflood=False)
    
    #make the estimated background a bit smaller than the coherent colour areas, in case we accidentally included some real butterfly
    conservative_background = cv2.erode(mask_after_flood,np.ones((5,5),np.uint8))[..., None] 
    if cv2.countNonZero(conservative_background) == 0:
        conservative_background = mask_after_flood #just in case we eroded all the background (this is certainly not a pinned butterfly)
        
    #Convert to the larger filesize, so that the largest possible image is used for the grabcut routine to work its magic
    conservative_background = cv2.copyMakeBorder(conservative_background, crop_top, crop_bottom, crop_left, crop_right, cv2.BORDER_CONSTANT,1)
    conservative_background = cv2.resize(conservative_background, (W, H))
    mask_after_grabcut = refine_background_via_grabcut(large_img, conservative_background)
    
    butterfly_metrics = contour_metrics(mask_after_grabcut)
    
    if param_dir is not None:
        if not hasattr(grab_butterfly, "params_output"):
            grab_butterfly.params_output = contour_metrics_output(param_dir, "param.data")
        grab_butterfly.params_output.write(butterfly_metrics, EoLobjectID, output_contour_pics=True)

    if composite_file_dir is not None or butterfly_with_contour_file_dir is not None:

        p, idx, contours = butterfly_metrics.find_butterfly()

        idx_txt = " ".join(np.char.mod("%i", idx).flatten())
        floodfilled_percent = cv2.countNonZero(mask_after_flood) / mask_after_flood.shape[0] / mask_after_flood.shape[1] * 100
        category = "good" if floodfilled_percent > flood_cutoff['percent'] else "bad"
        print("{} deemed {}, as largest {} flooded areas sum to {:0.2f} % (best contour IDs are {})".format(EoLobjectID, category, flood_cutoff["n_areas"], floodfilled_percent, idx_txt))  

        if composite_file_dir is not None:
            composite_filename = os.path.join(composite_file_dir,"{}_{}_{:02.0f}_{}.jpg".format(category, flood_param, floodfilled_percent, EoLobjectID))
            tiled = tiled_img()
            tiled.add(small_img, "Original")
            tiled.add(despeckled, "Bilateral Filter")
            tiled.add(quantized, "Meanshift filter")

            mask_details = np.zeros((img.shape[0], img.shape[1], 3), np.uint8)
            mask_details[...,2:3] = (1-mask_after_flood)*255
            mask_details[...,1] = cv2.resize((1-conservative_background)*255, (w,h))[crop_top:(h-crop_bottom), crop_left:(w-crop_right)]
            mask_details[...,0] = cv2.resize(mask_after_grabcut*255, (w,h))[crop_top:(h-crop_bottom), crop_left:(w-crop_right)]
            tiled.add(255-mask_details, "masks", True)
    
            for i in idx:
                contour_mask = np.zeros((img.shape[0], img.shape[1], 1), np.uint8)
                contour = contours[i] * [w/W, h/H] - [crop_left, crop_top]
                cv2.drawContours(contour_mask,[np.rint(contour).astype(int)], 0, color=1, thickness = cv2.cv.CV_FILLED)
            butterfly = cv2.bitwise_and(img, img, mask = contour_mask)
            tiled.add(butterfly, "Best")

            tiled.imwrite(composite_filename)

        if butterfly_with_contour_file_dir is not None:
            butterfly_filenames = [os.path.join(butterfly_with_contour_file_dir,"{}_{}_{:1.5f}_{}.jpg".format(category, chr(i + ord('a')), p[i], EoLobjectID)) for i in range(len(p))]
            contour_filenames = [os.path.join(butterfly_with_contour_file_dir,"{}_{}_{:1.5f}_{}.npy".format(category, chr(i + ord('a')), p[i], EoLobjectID)) for i in range(len(p))]


            #add the portion of img covered by the best contours
            for i in range(len(p)):
                roi = np.asarray(cv2.boundingRect(contours[idx[i]]))
                expand_by_px = 5
                crop_x = np.cumsum(roi[[0,2]]) + [-5,5] #turn into x-5, x+w+5
                crop_y = np.cumsum(roi[[1,3]]) + [-5,5] #turn into y-5, y+h+5
                np.clip(crop_x, 0, W, out=crop_x)
                np.clip(crop_y, 0, H, out=crop_y)
                cv2.imwrite(butterfly_filenames[i], large_img[slice(*crop_y), slice(*crop_x),...])
                np.save(contour_filenames[i], contours[idx[i]]-[crop_x[0], crop_y[0]])



################## main script here

contour_dir = "contours" #set to None unless you want to output params to model probability that a contour outline is a butterfly.
folders = ["classification", "butterflies"];
for folder in folders:
    for the_file in os.listdir(folder):
        file_path = os.path.join(folder, the_file)
        try:
            if os.path.isfile(file_path):
                os.unlink(file_path)
        except Exception, e:
            print(e)

image_folder = '' #this should contain ID_580_360.jpg files together with the full-sized ID.xxx files. If it is empty or does not exist, get them from google docs
if os.path.isdir(image_folder):
    pattern = re.compile("(.*)_580_360.jpg$");
    for img_file in os.listdir(image_folder):
        match = pattern.search(img_file)
        if match is not None:
            tmpID = match.group(1)
            small_file = os.path.join(image_folder, img_file)
            match_glob = os.path.join(image_folder, tmpID+".*");
            large_files = glob.glob(match_glob)
            if len(large_files) ==1:
                print("opening {} and {} (ID={})".format(small_file, large_files[0], tmpID))
                grab_butterfly(cv2.imread(small_file, cv2.CV_LOAD_IMAGE_COLOR), cv2.imread(large_files[0], cv2.CV_LOAD_IMAGE_COLOR), tmpID, contour_dir, folders[0], folders[1])
            else:
                print("problem with opening {}: found {} files when matching {}".format(small_file, len(large_files), match_glob))                
else:
    gc = gspread.login("EOLBHL2014","xtoyeriircodojww")
    sh = gc.open_by_key("0AsbkF6jVHju6dEktcmFfVzBEeV9PUURjSnJTTzJndVE") #this is the 35000 row spreadsheet
    #sh = gc.open_by_key("0AsbkF6jVHju6dGVKYUpiQmpDbjRweVo3YUNkeG9adEE") #this is the test spreadsheet
    worksheet = sh.get_worksheet(0)
    names = worksheet.row_values(1)

    random.seed(123);
    test_rows = random.sample(range(2, worksheet.row_count+1), 400)
    
    print("using rows ", end="")
    print(", ".join([str(x) for x in test_rows]))
    for r in test_rows:
        row = dict(zip(names, worksheet.row_values(r))) # r+1 so that we miss the first (header) row
        row['fullsizeURL'] = row['URL'].replace("_260_190.jpg", "_orig.jpg")
        print("Data_object {}: opening {}".format(row['ID'], row['URL'])) #to download these, try perl -ne 'if (/^Data_object (\d+): opening ([^_]*(.*)?\.(\w+))$/) {system "wget -O $1$3.$4 $2"}'
        req1 = urllib.urlopen(row['URL'])
        arr1 = np.asarray(bytearray(req1.read()), dtype=np.uint8)
        print("Data_object {}: opening {}".format(row['ID'], row['fullsizeURL']))
        req2 = urllib.urlopen(row['fullsizeURL'])
        arr2 = np.asarray(bytearray(req2.read()), dtype=np.uint8)
        grab_butterfly(cv2.imdecode(arr1,cv2.CV_LOAD_IMAGE_COLOR), cv2.imdecode(arr2,cv2.CV_LOAD_IMAGE_COLOR), row['ID'], contour_dir, folders[0], folders[1])

