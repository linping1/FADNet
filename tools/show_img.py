import os
from subprocess import Popen
import re
import numpy as np
import argparse

ORIGINAL_DATAPATH = '/media/sf_Shared_Data/gpuhomedataset/FlyingThings3D_release/disparity/TEST'
#ORIGINAL_DATAPATH = '/media/sf_Shared_Data/gpuhomedataset/clean_dispnet/FlyingThings3D_release/disparity/TEST'
#PREDICT_DATAPATH = '/media/sf_Shared_Data/gpuhome/repositories/pytorch-dispnet/detect_result_cd'
PREDICT_DATAPATH = '/media/sf_Shared_Data/gpuhome/repositories/pytorch-dispnet/detect_result_csr'
BIN = 'jview'
#result_name = 'predict_A_0019_0015.pfm'
#result_name = 'predict_A_0011_0007.pfm'
#result_name = 'predict_A_0009_0014.pfm'
#result_name = 'predict_A_0011_0012.pfm'
result_name = 'predict_A_0011_0006.pfm'

def load_pfm(filename):

  file = open(filename, 'r')
  color = None
  width = None
  height = None
  scale = None
  endian = None

  header = file.readline().rstrip()
  if header == 'PF':
    color = True    
  elif header == 'Pf':
    color = False
  else:
    raise Exception('Not a PFM file.')

  dim_match = re.match(r'^(\d+)\s(\d+)\s$', file.readline())
  if dim_match:
    width, height = map(int, dim_match.groups())
  else:
    raise Exception('Malformed PFM header.')

  scale = float(file.readline().rstrip())
  if scale < 0: # little-endian
    endian = '<'
    scale = -scale
  else:
    endian = '>' # big-endian

  data = np.fromfile(file, endian + 'f')
  shape = (height, width, 3) if color else (height, width)
  file.close()
  return np.reshape(data, shape), scale


def _get_view_cmd(filepath):
    cmd = '{} {}'.format(BIN, filepath)
    return cmd

def _execute(cmd):
    p = Popen(cmd.split(' '))
    return p
    #os.system(cmd)

def show_img(filepath):
    return _execute(_get_view_cmd(filepath))

def show_images(result_name):
    ps = []
    # show original
    name_items = result_name.split('_')
    print('name_items:', name_items)
    left_image_path = os.path.join(ORIGINAL_DATAPATH, name_items[1], name_items[2], 'left', name_items[3])
    print('left_image_path:', left_image_path)
    #right_image_path = os.path.join(ORIGINAL_DATAPATH, name_items[1], name_items[2], 'right', name_items[3])
    #depth_np, scale = load_pfm(left_image_path)
    #if np.sum(depth_np) != 0:
    #    return True
    #else:
    #    return False
    left_cmd = _get_view_cmd(left_image_path)
    #right_cmd = _get_view_cmd(right_image_path)
    p = _execute(left_cmd)
    ps.append(p)
    #p = _execute(right_cmd)
    #ps.append(p)

    # show prediction
    show_original_cmd = _get_view_cmd(os.path.join(PREDICT_DATAPATH, result_name))
    p = _execute(show_original_cmd)
    ps.append(p)

    raw_input("Press Enter to continue...")
    for p in ps:
        p.terminate()


if __name__ == '__main__':

    # f = open("CC_FlyingThings3D_release_TRAIN.list", "r")
    # imgList = f.readlines()
    # f.close()

    # new_f = open("CC_FlyingThings3D_release_TRAIN_NEW.list", "w")

    # for img in imgList:
    #     depth_path = img.split()[2].split("/")
    #     depth_path = 'predict_%s_%s_%s' % (depth_path[-4], depth_path[-3], depth_path[-1])
    #     if show_images(depth_path):
    #         # print depth_path
    #         print "done!"
    #         new_f.write(img)
    #     else:
    #         print "%s all 0." % depth_path
    parser = argparse.ArgumentParser()
    parser.add_argument('--fn', type=str, help='File name', default=None)
    opt = parser.parse_args()
    rn = opt.fn if opt.fn else result_name
    show_images(rn)

