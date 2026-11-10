import sys, numpy as np, ncnn
src, conv = sys.argv[1], sys.argv[2]
net = ncnn.Net(); net.opt.num_threads = 4; net.opt.use_vulkan_compute = False
net.load_param(r"models\yolo11n_ncnn_fp32\model.ncnn.param"); net.load_model(r"models\yolo11n_ncnn_fp32\model.ncnn.bin")
x3 = np.random.rand(3, 640, 640).astype(np.float32); x4 = np.random.rand(1, 3, 640, 640).astype(np.float32)
for i in range(12):
    ex = net.create_extractor()
    inp = ncnn.Mat(x3).clone() if src == "3d" else ncnn.Mat(x4[0].copy()).clone()
    ex.input("in0", inp)
    rc, out = ex.extract("out0")
    if conv == "each": arr = np.array(out)
print("ok", src, conv, flush=True)