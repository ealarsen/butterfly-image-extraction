from __future__ import division
from __future__ import print_function
import cv2
import numpy as np
import os

def savecontours(c1img, name):
    folder = "circlecontours/{}".format(name)
    for the_file in os.listdir(folder):
        file_path = os.path.join(folder, the_file)
        os.unlink(file_path)
        
    cv2.imshow(name, c1img)
    #c1img = cv2.threshold(c1img, 20, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    #parameter = 1/8 of minimum dimension of image - must be an odd number
    window_width = int(round((min(c1img.shape[0],c1img.shape[1])/16 ))*2+1)
    #cv2.ADAPTIVE_THRESH_MEAN_C worked better than cv2.ADAPTIVE_THRESH_GAUSSIAN_C with these parameters
    c1img = cv2.adaptiveThreshold(c1img, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, window_width, 20)
    cv2.imshow("{} thresh".format(name), c1img)
    cv2.waitKey(0)

    smooth_contours = cv2.findContours(c1img.copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_TC89_KCOS)[0]

    img = np.zeros((c1img.shape[0], c1img.shape[1],3), np.uint8)
    cv2.drawContours(img, smooth_contours, -1, (255,255,255), 1)
    cv2.imwrite(os.path.join(folder, "all.png"), img)

    i=0
    for c1 in smooth_contours:
        c2 = cv2.approxPolyDP(c1,1,True)
        a1 = cv2.contourArea(c1)
        a2 = cv2.contourArea(c2)
        l1 = cv2.arcLength(c1, True)
        l2 = cv2.arcLength(c2, True)


        if l1 > 25:
            Q1 = (4*np.pi*a1)/(l1*l1)
            img = np.zeros((c1img.shape[0], c1img.shape[1],3), np.uint8)
            cv2.drawContours(img, [c1], -1, color=(255,255,255), thickness=1)
            cv2.imwrite(os.path.join(folder, "plain{:.4f}_contour{}.png".format(Q1, i)), img)

        if l2 > 25:
            Q2 = (4*np.pi*a2)/(l2*l2)
            img = np.zeros((c1img.shape[0], c1img.shape[1],3), np.uint8)
            cv2.drawContours(img, [c2], -1, color=(255,255,255), thickness=1)
            cv2.imwrite(os.path.join(folder, "approx{:.4f}_contour{}.png".format(Q2, i)), img)
        i = i+1


def plot_circular_contour(c1img, accumulate_binary, displayname=None):
    function_param_names = {k:0 for k,v in locals().viewitems()}

    #define parameters as ints or strings here
    window_width = int(round((min(c1img.shape[0],c1img.shape[1])/12))*2+1)  #parameter = 1/6 of minimum dimension of image - must be an odd number
    threshfunc = 'adaptiveThreshold'
    thresh_dist = 'ADAPTIVE_THRESH_GAUSSIAN_C' #cv2.ADAPTIVE_THRESH_MEAN_C worked better than cv2.ADAPTIVE_THRESH_GAUSSIAN_C with these parameters
    C = 10
    min_circumf = 45 #adjusted up from 25
    Qcut = 0.8 #adjusted down from 0.9
    cont_type = 'approxPolyDP'

    params = {k:v for k,v in locals().viewitems() if (k != 'function_param_names' and k not in function_param_names)}
   
    if displayname is not None:
        display_image=np.zeros((c1img.shape[0], c1img.shape[1]*3), np.uint8)
        display_image[:,0:c1img.shape[1]] = c1img
    
    c1img = getattr(cv2, threshfunc)(c1img, 255, getattr(cv2, thresh_dist), cv2.THRESH_BINARY, window_width, C)
    
    smooth_contours = cv2.findContours(c1img.copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_TC89_KCOS)[0]
    for i in range(len(smooth_contours)):
        cont = {'plain': smooth_contours[i], 'approxPolyDP': cv2.approxPolyDP(smooth_contours[i],1,True)}
        area = {k: cv2.contourArea(c) for k, c in cont.items()}
        length = {k: cv2.arcLength(c, True) for k, c in cont.items()}

        #print(l1)
        #if l1 > 40: #removed; does not give any unique circles 
        if length[cont_type] > min_circumf: 
            Q = (4*np.pi*area[cont_type])/(length[cont_type]*length[cont_type])
            if Q > Qcut: 
                cv2.drawContours(accumulate_binary, [cont[cont_type]], -1, color=(255,255,255), thickness=cv2.cv.CV_FILLED)
                if displayname is not None:
                    cv2.drawContours(display_image[:,(c1img.shape[1]*2):(c1img.shape[1]*3)], [cont[cont_type]], -1, color=(255,255,255), thickness=cv2.cv.CV_FILLED)

    if displayname is not None:
        display_image[:,c1img.shape[1]:(c1img.shape[1]*2)] = c1img
        cv2.imshow(displayname + " c1c1c1, thresh, mask", display_image) #ADDED COMMA
    return(params)


def best_outline(image_580_360, display=False):
    '''Returns the result (contour outlines), a list of parameters for saving, plus a binary mask image'''
    h, w = image_580_360.shape[0:2]
    img = image_580_360 #ADDED
    im = img.astype(np.float32)+0.001 #to avoid division by 0
    c1c2c3 = np.arctan(im/np.dstack((cv2.max(im[...,1], im[...,2]), cv2.max(im[...,0], im[...,2]), cv2.max(im[...,0], im[...,1]))))
    bimg,gimg,rimg = cv2.split(c1c2c3)
    rimg = cv2.normalize(rimg, rimg, 0,255,cv2.NORM_MINMAX,dtype=cv2.cv.CV_8UC1)
    gimg = cv2.normalize(gimg, gimg, 0,255,cv2.NORM_MINMAX,dtype=cv2.cv.CV_8UC1)
    bimg = cv2.normalize(bimg, bimg, 0,255,cv2.NORM_MINMAX,dtype=cv2.cv.CV_8UC1)
    accumulation_mask = np.zeros((img.shape[0], img.shape[1]), np.uint8)
    plot_circular_contour(gimg, accumulation_mask,  "green" if display else None)
    plot_circular_contour(bimg, accumulation_mask,  "blue" if display else None)
    params = plot_circular_contour(rimg, accumulation_mask, "red" if display else None)
    contours = cv2.findContours(accumulation_mask.copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_TC89_KCOS)[0]
    return(contours, params, accumulation_mask)
