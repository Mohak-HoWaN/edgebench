import sys, numpy as np, ncnn
th, iters, keep = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
net = ncnn.Net(); net.opt.num_threads = th; net.opt.use_vulkan_compute = False
net.load_param(r"models\yolo11n_ncnn_fp32\model.ncnn.param"); net.load_model(r"models\yolo11n_ncnn_fp32\model.ncnn.bin")
x = np.random.rand(3, 640, 640).astype(np.float32)
for i in range(iters):
    ex = net.create_extractor(); ex.input("in0", ncnn.Mat(x).clone()); rc, out = ex.extract("out0")
    arr = np.array(out)            # copy the result out before anything is released
    if keep == "release": del ex, out
print("ok", th, iters, keep, arr.shape, flush=True)