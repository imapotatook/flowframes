import os
import sys
import cv2
import torch
import argparse
import numpy as np
#from tqdm import tqdm
from torch.nn import functional as F
import warnings
import _thread

abspath = os.path.abspath(__file__)
dname = os.path.dirname(abspath)
print("Changing working dir to {0}".format(dname))
os.chdir(os.path.dirname(dname))
print("Added {0} to PATH".format(dname))
sys.path.append(dname)

warnings.filterwarnings("ignore")

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

if torch.cuda.is_available():
    torch.set_grad_enabled(False)
    torch.backends.cudnn.enabled = True
    torch.backends.cudnn.benchmark = True
else:
    print("WARNING: CUDA is not available, RIFE is running on CPU! [ff:nocuda-cpu]")
    

parser = argparse.ArgumentParser(description='Interpolation for a pair of images')
parser.add_argument('--input', required=True)
parser.add_argument('--imgformat', default="png")
parser.add_argument('--skip', dest='skip', action='store_true', help='whether to remove static frames before processing')
parser.add_argument('--png', dest='png', default=True, action='store_true', help='whether to output png format outputs')
parser.add_argument('--ext', dest='ext', type=str, default='mp4', help='output video extension')
parser.add_argument('--times', dest='exp', type=int, default=1, help='interpolation exponent (default: 1)')
args = parser.parse_args()
#assert (args.exp in [1, 2, 3])
#args.times = 2 ** args.exp

from model.RIFE import Model
model = Model()
model.load_model(os.path.join(dname, "models"))
model.eval()
model.device()


videoCapture = cv2.VideoCapture("{}/%08d.png".format(args.input),cv2.CAP_IMAGES)
success, frame = videoCapture.read()

if not (success):
    print("fuck")

h, w, _ = frame.shape

path = args.input
name = os.path.basename(path)
interp_output_path = (name+'-interpolated').join(path.rsplit(name, 1))

if not os.path.exists(interp_output_path):
    os.mkdir(interp_output_path)
vid_out = None
    
cnt = 0
skip_frame = 1
buffer = []

def write_frame(i0, infs, i1, p, user_args):
    global skip_frame, cnt    
    for i in range(i0.shape[0]):
        # A video transition occurs.
        #if p[i] > 0.2:
        #    if user_args.exp > 1:
        #        infs = [i0[i] for _ in range(len(infs) - 1)]
        #        infs[-1] = i1[-1]
        #    else:
        #        infs = [i0[i] for _ in range(len(infs))]
        
        # Result was too similar to previous frame, skip if given.
        #if p[i] < 5e-3 and user_args.skip:
        #    if skip_frame % 100 == 0:
        #        print("Warning: Your video has {} static frames, "
        #              "skipping them may change the duration of the generated video.".format(skip_frame))
        #    skip_frame += 1
        #    continue
        
        # Write results.        
        buffer.append(i0[i])
        for inf in infs:
            buffer.append(inf[i])

def clear_buffer(user_args, buffer):
    global cnt
    for i in buffer:
        print("Writing {}/{:0>7d}.{}".format(interp_output_path, cnt, args.imgformat))
        cv2.imwrite('{}/{:0>7d}.{}'.format(interp_output_path, cnt, args.imgformat), i)
        cnt += 1

def make_inference(model, I0, I1, exp):
    middle = model.inference(I0, I1)
    if exp == 1:
        return [middle]
    first_half = make_inference(model, I0, middle, exp=exp - 1)
    second_half = make_inference(model, middle, I1, exp=exp - 1)
    return [*first_half, middle, *second_half]


ph = ((h - 1) // 32 + 1) * 32
pw = ((w - 1) // 32 + 1) * 32
padding = (0, pw - w, 0, ph - h)
tot_frame = videoCapture.get(cv2.CAP_PROP_FRAME_COUNT)
print('{} frames in total'.format(tot_frame))
#pbar = tqdm(total=tot_frame)
img_list = [frame]
while success:
    success, frame = videoCapture.read()
    if success:
        img_list.append(frame)
    if len(img_list) == 5 or (not success and len(img_list) > 1):
        imgs = torch.from_numpy(np.transpose(img_list, (0, 3, 1, 2))).to(device, non_blocking=True).float() / 255.
        I0 = imgs[:-1]
        I1 = imgs[1:]
        p = (F.interpolate(I0, (16, 16), mode='bilinear', align_corners=False)
             - F.interpolate(I1, (16, 16), mode='bilinear', align_corners=False)).abs()
        I0 = F.pad(I0, padding)
        I1 = F.pad(I1, padding)
        inferences = make_inference(model, I0, I1, exp=args.exp)

        I0 = np.array(img_list[:-1])
        I1 = np.array(img_list[1:])
        inferences = list(map(lambda x: ((x[:, :, :h, :w] * 255.).byte().cpu().detach().numpy().transpose(0, 2, 3, 1)), inferences))
        
        write_frame(I0, inferences, I1, p.mean(3).mean(2).mean(1), args)
        #pbar.update(4)
        img_list = img_list[-1:]
    if len(buffer) > 100:
        _thread.start_new_thread(clear_buffer, (args, buffer))
        buffer = []
_thread.start_new_thread(clear_buffer, (args, buffer))
#pbar.close()