import time
import cv2
import os
import numpy as np
import pywt
from matplotlib import pyplot as plt
from scipy.signal import convolve2d
from math import sqrt
from scipy.ndimage.filters import gaussian_filter
from scipy.signal import medfilt
from scipy.fft import dct, idct
import math

# Possible modifications:
# - Change alpha
# - Change alpha scaling factor in different modes
# - Change the values used by the attacks
# - Change the function (average, median, etc.) used in spatial domain

# - Change number of blocks
# - Change block size
# - Change number of watermarks concatenated to embed

'''PARAMETERS'''
alpha = 8  # 8 is the lower limit that can be used
n_blocks_to_embed = 1024
block_size = 4
spatial_weight = 0.5 # 0: no spatial domain, 1: only spatial domain

attack_weight = 1.0 - spatial_weight

'''EMBEDDING'''
def embedding(original_image):
    watermark_size = 1024
    watermark_path = "howimetyourmark.npy"
    watermark_to_embed = np.load(watermark_path)

    blocks_to_watermark = []

    blank_image = np.float64(np.zeros((512, 512)))

    start = time.time()

    QF = [5,6, 7, 8,9, 10]
    for qf in QF:
        attacked_image_tmp = jpeg_compression(original_image, qf)
        blank_image += np.abs(attacked_image_tmp - original_image)

    blur_sigma_values = [0.1, 0.5,
                         1, 2,
                         [1, 1], [2, 1]
                         ]
    for sigma in blur_sigma_values:
        attacked_image_tmp = blur(original_image, sigma)
        blank_image += np.abs(attacked_image_tmp - original_image)

    kernel_size = [3, 5, 7, 9, 11]
    for k in kernel_size:
        attacked_image_tmp = median(original_image, k)
        blank_image += np.abs(attacked_image_tmp - original_image)

    awgn_std = [0.1, 0.5, 2, 5, 10]
    for std in awgn_std:
        attacked_image_tmp = awgn(original_image, std, 0)
        blank_image += np.abs(attacked_image_tmp - original_image)

    sharpening_sigma_values = [0.1, 0.5, 2, 100]
    sharpening_alpha_values = [0.1, 0.5, 1, 2]
    for sharpening_sigma in sharpening_sigma_values:
        for sharpening_alpha in sharpening_alpha_values:
            attacked_image_tmp = sharpening(original_image, sharpening_sigma, sharpening_alpha)
            blank_image += np.abs(attacked_image_tmp - original_image)

    resizing_scale_values = [0.5, 0.75, 0.9, 1.1, 1.5]
    for scale in resizing_scale_values:
        attacked_image_tmp = cv2.resize(original_image, (0, 0), fx=scale, fy=scale)
        attacked_image_tmp = cv2.resize(attacked_image_tmp, (512, 512))
        blank_image += np.abs(attacked_image_tmp - original_image)
    #plot blank image
    plt.imshow(blank_image, cmap='gray')
    plt.show()
    # end time
    end = time.time()
    print("Time of attacks for embedding: " + str(end - start))

    # find the min blocks (sum or mean of the 64 elements for each block) using sorting (min is best)

    for i in range(0, original_image.shape[0], block_size):
        for j in range(0, original_image.shape[1], block_size):
            block_tmp = {'locations': (i, j),
                         'spatial_value': np.average(original_image[i:i + block_size, j:j + block_size]),
                         'attack_value': np.average(blank_image[i:i + block_size, j:j + block_size])
                         }
            blocks_to_watermark.append(block_tmp)

    blocks_to_watermark = sorted(blocks_to_watermark, key=lambda k: k['spatial_value'], reverse=True)
    for i in range(len(blocks_to_watermark)):
        blocks_to_watermark[i]['merit'] = i*spatial_weight

    blocks_to_watermark = sorted(blocks_to_watermark, key=lambda k: k['attack_value'], reverse=False)
    for i in range(len(blocks_to_watermark)):
        blocks_to_watermark[i]['merit'] += i*attack_weight

    blocks_to_watermark = sorted(blocks_to_watermark, key=lambda k: k['merit'], reverse=True)

    blank_image = np.float64(np.zeros((512, 512)))

    blocks_to_watermark_final = []
    for i in range(n_blocks_to_embed):
        tmp = blocks_to_watermark.pop()
        blocks_to_watermark_final.append(tmp)
        blank_image[tmp['locations'][0]:tmp['locations'][0] + block_size,
        tmp['locations'][1]:tmp['locations'][1] + block_size] = 1

    blocks_to_watermark_final = sorted(blocks_to_watermark_final, key=lambda k: k['locations'], reverse=False)

####################################################################################################################

    divisions = original_image.shape[0] / block_size

    shape_LL_tmp = np.floor(original_image.shape[0]/ (2*divisions))
    shape_LL_tmp = np.uint8(shape_LL_tmp)
    watermarked_image=original_image.copy()
    # loops trough x coordinates of blocks_to_watermark_final
    for i in range(len(blocks_to_watermark_final)):

        x = np.uint16(blocks_to_watermark_final[i]['locations'][0])
        y = np.uint16(blocks_to_watermark_final[i]['locations'][1])

        #get the block from the original image
        block = original_image[x:x + block_size, y:y + block_size]
        #compute the LL of the block
        Coefficients = pywt.wavedec2(block, wavelet='haar', level=1)
        LL_tmp = Coefficients[0]
        # SVD
        Uc, Sc, Vc = np.linalg.svd(LL_tmp)
        Sw = Sc.copy()

        # embedding

        for px in range(0, np.uint16(watermark_size/n_blocks_to_embed)):
            if watermark_to_embed[np.uint16(px + (i * np.uint16(watermark_size/n_blocks_to_embed)))] == 1:
                Sw[px] += alpha

        LL_new = np.zeros((shape_LL_tmp, shape_LL_tmp))
        LL_new = (Uc).dot(np.diag(Sw)).dot(Vc)
        #compute the new block
        Coefficients[0] = LL_new
        block_new = pywt.waverec2(Coefficients, wavelet='haar')
        #replace the block in the original image
        watermarked_image[x:x + block_size, y:y + block_size] = block_new


####################################################################################################################

    watermarked_image = np.uint8(watermarked_image)

    difference = (-watermarked_image + original_image) * np.uint8(blank_image)
    watermarked_image = original_image + difference
    watermarked_image += np.uint8(blank_image)

    # Compute quality
    w = wpsnr(original_image, watermarked_image)
    print('[EMBEDDING] wPSNR: %.2fdB' % w)

    return watermarked_image


'''DETECTION'''
def detection(original_image, watermarked_image, attacked_image):
    watermark_size = 1024
    # start time
    start = time.time()
    #extract watermark from watermarked image
    watermarked_image_dummy = watermarked_image.copy()
    watermark_extracted_wm = extraction(original_image, watermarked_image, watermarked_image_dummy)

    #starting extraction
    blocks_with_watermark = []
    divisions = original_image.shape[0] / block_size
    watermark_extracted = np.float64(np.zeros(watermark_size))
    blank_image = np.float64(np.zeros((512, 512)))
    # compute difference between original and watermarked image

    difference = (watermarked_image - original_image)

    # fill blocks in differece where the difference is bigger o less than 0
    for i in range(0, original_image.shape[1], block_size):
        for j in range(0, original_image.shape[0], block_size):
            block_tmp = {'locations': (i, j)}
            if np.average(difference[i:i + block_size, j:j + block_size]) > 0:
                blank_image[i:i + block_size, j:j + block_size] = 1
                blocks_with_watermark.append(block_tmp)
            else:
                blank_image[i:i + block_size, j:j + block_size] = 0

    attacked_image -= np.uint8(blank_image)

    ####################################################################################################################

    shape_LL_tmp = np.floor(original_image.shape[0] / divisions)
    shape_LL_tmp = np.uint8(shape_LL_tmp)

    watermark_extracted = np.zeros(1024)
    # print(watermark_extracted)
    for i in range(len(blocks_with_watermark)):
        x = np.uint16(blocks_with_watermark[i]['locations'][0])
        y = np.uint16(blocks_with_watermark[i]['locations'][1])
        # get the block from the attacked image
        block = attacked_image[x:x + block_size, y:y + block_size]
        # compute the LL of the block
        Coefficients = pywt.wavedec2(block, wavelet='haar', level=1)
        LL_tmp = Coefficients[0]
        # SVD
        Uc, Sc, Vc = np.linalg.svd(LL_tmp)
        # get the block from the original image
        block_ori = original_image[x:x + block_size, y:y + block_size]
        # compute the LL of the block
        Coefficients_ori = pywt.wavedec2(block_ori, wavelet='haar', level=1)
        LL_ori = Coefficients_ori[0]
        # SVD
        Uc_ori, Sc_ori, Vc_ori = np.linalg.svd(LL_ori)

        Sdiff = Sc_ori - Sc

        block_limit = np.uint16(watermark_size / n_blocks_to_embed)

        for px in range(0, block_limit):
            watermark_extracted[px + i * block_limit] = Sdiff[px] / alpha

    ####################################################################################################################
    #end of extraction

    sim = similarity(watermark_extracted_wm, watermark_extracted)
    if sim > T:
        watermark_status = 1
    else:
        watermark_status = 0

    output1 = watermark_status
    output2 = wpsnr(watermarked_image, attacked_image)

    # end time
    end = time.time()
    print('[DETECTION] Time: %.2fs' % (end - start))

    return output1, output2

def extraction(original_image, watermarked_image, attacked_image):
    watermark_size = 1024
    # start time
    start = time.time()

    blocks_with_watermark = []
    divisions = original_image.shape[0] / block_size
    watermark_extracted = np.float64(np.zeros(watermark_size))
    blank_image = np.float64(np.zeros((512, 512)))
    # compute difference between original and watermarked image

    difference = (watermarked_image - original_image)

    # fill blocks in differece where the difference is bigger o less than 0
    for i in range(0, original_image.shape[1], block_size):
        for j in range(0, original_image.shape[0], block_size):
            block_tmp = {'locations': (i, j)}
            if np.average(difference[i:i + block_size, j:j + block_size]) > 0:
                blank_image[i:i + block_size, j:j + block_size] = 1
                blocks_with_watermark.append(block_tmp)
            else:
                blank_image[i:i + block_size, j:j + block_size] = 0

    attacked_image-=np.uint8(blank_image)

####################################################################################################################


    shape_LL_tmp = np.floor(original_image.shape[0] / divisions)
    shape_LL_tmp = np.uint8(shape_LL_tmp)

    watermark_extracted = np.zeros(1024)
    #print(watermark_extracted)
    for i in range(len(blocks_with_watermark)):
        x = np.uint16(blocks_with_watermark[i]['locations'][0])
        y = np.uint16(blocks_with_watermark[i]['locations'][1])
        #get the block from the attacked image
        block = attacked_image[x:x + block_size, y:y + block_size]
        #compute the LL of the block
        Coefficients = pywt.wavedec2(block, wavelet='haar', level=1)
        LL_tmp = Coefficients[0]
        # SVD
        Uc, Sc, Vc = np.linalg.svd(LL_tmp)
        #get the block from the original image
        block_ori = original_image[x:x + block_size, y:y + block_size]
        #compute the LL of the block
        Coefficients_ori = pywt.wavedec2(block_ori, wavelet='haar', level=1)
        LL_ori = Coefficients_ori[0]
        # SVD
        Uc_ori, Sc_ori, Vc_ori = np.linalg.svd(LL_ori)

        Sdiff = Sc_ori-Sc

        block_limit = np.uint16(watermark_size/n_blocks_to_embed)

        for px in range(0,block_limit):
            watermark_extracted[px + i * block_limit] = Sdiff[px]/ alpha

####################################################################################################################

    #end time
    end = time.time()
    print('[EXTRACTION] Time: %.2fs' % (end - start))

    return watermark_extracted


'''UTILITY'''
def wpsnr(img1, img2):
    img1 = np.float32(img1) / 255.0
    img2 = np.float32(img2) / 255.0

    difference = img1 - img2
    same = not np.any(difference)
    if same is True:
        return 9999999
    csf = np.genfromtxt('utility/csf.csv', delimiter=',')
    ew = convolve2d(difference, np.rot90(csf, 2), mode='valid')
    decibels = 20.0 * np.log10(1.0 / sqrt(np.mean(np.mean(ew ** 2))))
    return decibels


def get_histogram(x, path):
    img = cv2.imread(x)
    hist = cv2.calcHist([img], [0], None, [256], [0, 256])
    plt.plot(hist)
    plt.xlim([0, 256])
    plt.savefig(path)
    plt.close()


def similarity(X, X_star):
    # Computes the similarity measure between the original and the new watermarks.
    s = np.sum(np.multiply(X, X_star)) / np.sqrt(np.sum(np.multiply(X_star, X_star)))
    return s


def compute_thr(mark_size, w):  # w é il watermark originale
    SIM = np.zeros(100)
    for i in range(0, 100):
        r = np.random.uniform(0.0, 1.0, mark_size)
        SIM[i] = similarity(w, r)
    SIM.sort()
    t = SIM[-10]
    #T = t + (0.1 * t)  # forse da integrare con la ROC
    T = t  # forse da integrare con la ROC
    print('[COMPUTE_THR] Threshold: ' + str(T))
    return T


'''ATTACKS PARAMETERS'''
# brute force attack
successful_attacks = []
# attacks = ["awgn", "blur", "sharpening", "median", "resizing", "jpeg_compression"]
# attacks = ["blur", "median", "jpeg_compression"]
attacks = ["jpeg_compression", "awgn", "blur"]

# setting parameter ranges

# awgn
awgn_std_values = [2.0, 4.0, 10.0, 20.0, 30.0, 40.0, 50.0]
# awgn_seed_values = []
awgn_mean_values = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]

# jpeg_compression
jpeg_compression_QF_values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25,
                              26, 27, 28, 29, 30, 40, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100]

# blur
blur_sigma_values = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9,
                     1, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9,
                     2, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9,
                     3, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9,
                     4, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9,
                     5, 6, 7, 8, 9, 10,
                     [1, 1], [1, 2], [1, 3], [1, 4], [1, 5],
                     [2, 1], [2, 2], [2, 3], [2, 4], [2, 5],
                     [3, 1], [3, 2], [3, 3], [3, 4], [3, 5],
                     [4, 1], [4, 2], [4, 3], [4, 4], [4, 5],
                     [5, 1], [5, 2], [5, 3], [5, 4], [5, 5]
                     ]

# sharpening
sharpening_sigma_values = [0.01, 0.1, 0.5, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 25, 30, 40, 50, 75, 100]
sharpening_alpha_values = [0.01, 0.1, 0.5, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 25, 30, 40, 50, 75, 100]

# median
median_kernel_size_values = [[1, 3], [1, 5],
                             [3, 1], [3, 3], [3, 5],
                             [5, 1], [5, 3], [5, 5],
                             [7, 1], [7, 3], [7, 5],
                             [9, 1], [9, 3], [9, 5]]

# resizing
resizing_scale_values = [0.01, 0.05, 0.1, 0.5, 0.75, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

'''ATTACKS'''
def jpeg_compression(img, QF):
    import cv2
    cv2.imwrite('tmp.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), QF])
    attacked = cv2.imread('tmp.jpg', 0)
    os.remove('tmp.jpg')
    return attacked


def blur(img, sigma):
    attacked = gaussian_filter(img, sigma)
    return attacked


def awgn(img, std, seed):
    mean = 0.0
    # np.random.seed(seed)
    attacked = img + np.random.normal(mean, std, img.shape)
    attacked = np.clip(attacked, 0, 255)
    return attacked


def sharpening(img, sigma, alpha):
    filter_blurred_f = gaussian_filter(img, sigma)
    attacked = img + alpha * (img - filter_blurred_f)
    return attacked


def median(img, kernel_size):
    attacked = medfilt(img, kernel_size)
    return attacked

def plot_attack(original_image, watermarked_image, attacked_image):
    plt.figure(figsize=(15, 6))
    plt.subplot(131)
    plt.title('Original')
    plt.imshow(original_image, cmap='gray')
    plt.subplot(132)
    plt.title('Watermarked')
    plt.imshow(watermarked_image, cmap='gray')
    plt.subplot(133)
    plt.title('Attacked')
    plt.imshow(attacked_image, cmap='gray')
    plt.show()



def print_successful_attacks(successful_attacks, image_name='lena.bmp'):
    import json
    output_file = open('Paper2_successful_attacks_' + image_name + '.txt', 'w', encoding='utf-8')
    output_file.write(image_name + "\n")
    for dic in successful_attacks:
        json.dump(dic, output_file)
        output_file.write("\n")


def bf_attack(original_image, watermarked_image):
    current_best_wpsnr = 0

    for attack in attacks:
        ########## JPEG ##########
        if attack == 'jpeg_compression':
            for QF_value in jpeg_compression_QF_values:
                watermarked_to_attack = watermarked_image.copy()
                print(watermarked_to_attack.dtype)
                attacked_image = jpeg_compression(watermarked_to_attack, QF_value)

                watermarked_extracted = extraction(original_image, watermarked_image, attacked_image)

                sim = similarity(watermark, watermarked_extracted)

                if sim > T:
                    watermark_status = 1
                else:
                    watermark_status = 0

                current_attack = {}
                current_attack["Attack_name"] = 'JPEG_Compression'
                current_attack["QF"] = QF_value

                tmp_wpsnr = wpsnr(watermarked_image, attacked_image)
                current_attack["WPSNR"] = tmp_wpsnr

                if watermark_status == 0:
                    if tmp_wpsnr >= 35.0:
                        successful_attacks.append(current_attack)
                        if tmp_wpsnr > current_best_wpsnr:
                            current_best_wpsnr = tmp_wpsnr
                        print('[' + str(current_attack) + ']', 'SIM = %f' % sim,
                              '[watermark_status = ' + str(watermark_status) + '] - !!!SUCCESS!!!')
                        # plot_attack(original_image, watermarked_image, attacked_image)
                    else:
                        print('[' + str(current_attack) + ']', 'SIM = %f' % sim,
                              '[watermark_status = ' + str(watermark_status) + '] - FAILED')
                else:
                    print('[' + str(current_attack) + ']', 'SIM = %f' % sim,
                          '[watermark_status = ' + str(watermark_status) + '] - FAILED')

        ########## BLUR ##########
        if attack == 'blur':
            for sigma_value in blur_sigma_values:
                watermarked_to_attack = watermarked_image.copy()
                attacked_image = blur(watermarked_to_attack, sigma_value)

                watermarked_extracted = extraction(original_image, watermarked_image, attacked_image)

                sim = similarity(watermark, watermarked_extracted)

                if sim > T:
                    watermark_status = 1
                else:
                    watermark_status = 0

                current_attack = {}
                current_attack["Attack_name"] = 'blur'
                current_attack["sigma"] = sigma_value

                tmp_wpsnr = wpsnr(watermarked_image, attacked_image)
                current_attack["WPSNR"] = tmp_wpsnr

                if watermark_status == 0:
                    if tmp_wpsnr >= 35.0:
                        successful_attacks.append(current_attack)
                        if tmp_wpsnr > current_best_wpsnr:
                            current_best_wpsnr = tmp_wpsnr
                        print('[' + str(current_attack) + ']', 'SIM = %f' % sim,
                              '[watermark_status = ' + str(watermark_status) + '] - !!!SUCCESS!!!')
                        plot_attack(original_image, watermarked_image, attacked_image)
                    else:
                        print('[' + str(current_attack) + ']', 'SIM = %f' % sim,
                              '[watermark_status = ' + str(watermark_status) + '] - FAILED')
                else:
                    print('[' + str(current_attack) + ']', 'SIM = %f' % sim,
                          '[watermark_status = ' + str(watermark_status) + '] - FAILED')

        ########## AWGN ##########
        if attack == 'awgn':
            for std_value in awgn_std_values:
                for mean_value in awgn_mean_values:
                    watermarked_to_attack = watermarked_image.copy()
                    attacked_image = awgn(watermarked_to_attack, std_value, mean_value)

                    watermarked_extracted = extraction(original_image, watermarked_image, attacked_image)

                    sim = similarity(watermark, watermarked_extracted)

                    if sim > T:
                        watermark_status = 1
                    else:
                        watermark_status = 0

                    current_attack = {}
                    current_attack["Attack_name"] = 'awgn'
                    current_attack["std"] = std_value
                    current_attack["mean"] = mean_value

                    tmp_wpsnr = wpsnr(watermarked_image, attacked_image)
                    current_attack["WPSNR"] = tmp_wpsnr

                    if watermark_status == 0:
                        if tmp_wpsnr >= 35.0:
                            successful_attacks.append(current_attack)
                            if tmp_wpsnr > current_best_wpsnr:
                                current_best_wpsnr = tmp_wpsnr
                            print('[' + str(current_attack) + ']', 'SIM = %f' % sim,
                                  '[watermark_status = ' + str(watermark_status) + '] - !!!SUCCESS!!!')
                            plot_attack(original_image, watermarked_image, attacked_image)
                        else:
                            print('[' + str(current_attack) + ']', 'SIM = %f' % sim,
                                  '[watermark_status = ' + str(watermark_status) + '] - FAILED')
                    else:
                        print('[' + str(current_attack) + ']', 'SIM = %f' % sim,
                              '[watermark_status = ' + str(watermark_status) + '] - FAILED')

        ########## SHARPENING ##########
        if attack == 'sharpening':
            for sigma_value in sharpening_sigma_values:
                for alpha_value in sharpening_alpha_values:
                    watermarked_to_attack = watermarked_image.copy()
                    attacked_image = sharpening(watermarked_to_attack, sigma_value, alpha_value)

                    watermarked_extracted = extraction(original_image, watermarked_image, attacked_image)

                    sim = similarity(watermark, watermarked_extracted)
                    if sim > T:
                        watermark_status = 1
                    else:
                        watermark_status = 0

                    current_attack = {}
                    current_attack["Attack_name"] = 'Sharpening'
                    current_attack["sigma"] = sigma_value
                    current_attack["alpha"] = alpha_value

                    tmp_wpsnr = wpsnr(watermarked_image, attacked_image)
                    current_attack["WPSNR"] = tmp_wpsnr

                    if watermark_status == 0:
                        if tmp_wpsnr >= 35.0:
                            successful_attacks.append(current_attack)
                            if tmp_wpsnr > current_best_wpsnr:
                                current_best_wpsnr = tmp_wpsnr
                            print('[' + str(current_attack) + ']', 'SIM = %f' % sim,
                                  '[watermark_status = ' + str(watermark_status) + '] - !!!SUCCESS!!!')
                            plot_attack(original_image, watermarked_image, attacked_image)
                        else:
                            print('[' + str(current_attack) + ']', 'SIM = %f' % sim,
                                  '[watermark_status = ' + str(watermark_status) + '] - FAILED')
                    else:
                        print('[' + str(current_attack) + ']', 'SIM = %f' % sim,
                              '[watermark_status = ' + str(watermark_status) + '] - FAILED')

        ########## MEDIAN ##########
        if attack == 'median':
            for kernel_size_value in median_kernel_size_values:
                watermarked_to_attack = watermarked_image.copy()
                attacked_image = median(watermarked_to_attack, kernel_size_value)

                watermarked_extracted = extraction(original_image, watermarked_image, attacked_image)

                sim = similarity(watermark, watermarked_extracted)

                if sim > T:
                    watermark_status = 1
                else:
                    watermark_status = 0

                current_attack = {}
                current_attack["Attack_name"] = 'median'
                current_attack["kernel_size_value"] = kernel_size_value

                tmp_wpsnr = wpsnr(watermarked_image, attacked_image)
                current_attack["WPSNR"] = tmp_wpsnr

                if watermark_status == 0:
                    if tmp_wpsnr >= 35.0:
                        successful_attacks.append(current_attack)
                        if tmp_wpsnr > current_best_wpsnr:
                            current_best_wpsnr = tmp_wpsnr
                        print('[' + str(current_attack) + ']', 'SIM = %f' % sim,
                              '[watermark_status = ' + str(watermark_status) + '] - !!!SUCCESS!!!')
                        plot_attack(original_image, watermarked_image, attacked_image)
                    else:
                        print('[' + str(current_attack) + ']', 'SIM = %f' % sim,
                              '[watermark_status = ' + str(watermark_status) + '] - FAILED')
                else:
                    print('[' + str(current_attack) + ']', 'SIM = %f' % sim,
                          '[watermark_status = ' + str(watermark_status) + '] - FAILED')

        ########## RESIZING ##########
        if attack == 'resizing':
            for scale_value in resizing_scale_values:
                watermarked_to_attack = watermarked_image.copy()

                watermarked_extracted = extraction(original_image, watermarked_image, attacked_image)

                sim = similarity(watermark, watermarked_extracted)

                if sim > T:
                    watermark_status = 1
                else:
                    watermark_status = 0

                current_attack = {}
                current_attack["Attack_name"] = 'resizing'
                current_attack["scale"] = scale_value

                tmp_wpsnr = wpsnr(watermarked_image, attacked_image)
                current_attack["WPSNR"] = tmp_wpsnr

                if watermark_status == 0:
                    if tmp_wpsnr >= 35.0:
                        successful_attacks.append(current_attack)
                        if tmp_wpsnr > current_best_wpsnr:
                            current_best_wpsnr = tmp_wpsnr
                        print('[' + str(current_attack) + ']', 'SIM = %f' % sim,
                              '[watermark_status = ' + str(watermark_status) + '] - !!!SUCCESS!!!')
                        plot_attack(original_image, watermarked_image, attacked_image)
                    else:
                        print('[' + str(current_attack) + ']', 'SIM = %f' % sim,
                              '[watermark_status = ' + str(watermark_status) + '] - FAILED')
                else:
                    print('[' + str(current_attack) + ']', 'SIM = %f' % sim,
                          '[watermark_status = ' + str(watermark_status) + '] - FAILED')

'''MAIN CODE'''
np.set_printoptions(threshold=np.inf)
watermark_size = 1024
original_image_path = "images/lena.bmp"
original_image = cv2.imread(original_image_path, 0)
watermarked_image = embedding(original_image)
#extract watermark from watermarked image
watermarked_image_dummy = watermarked_image.copy()
watermark = extraction(original_image, watermarked_image, watermarked_image_dummy)
plt.subplot(121)
plt.title('Original')
plt.imshow(original_image, cmap='gray')
plt.subplot(122)
plt.title('Watermarked')
plt.imshow(watermarked_image, cmap='gray')
plt.show()
T = compute_thr(watermark_size, watermark)
bf_attack(original_image, watermarked_image)
#print_successful_attacks(successful_attacks)









