import ast
import onnx
import onnxruntime as ort
import cv2
from huggingface_hub import hf_hub_download
import numpy as np

# Download the model from the Hugging Face Hub
model = hf_hub_download(
    repo_id="wybxc/DocLayout-YOLO-DocStructBench-onnx",
    filename="doclayout_yolo_docstructbench_imgsz1024.onnx",
)
model = onnx.load(model)
metadata = {prop.key: prop.value for prop in model.metadata_props}

names = ast.literal_eval(metadata["names"])
stride = ast.literal_eval(metadata["stride"])

# Load the model with ONNX Runtime
session = ort.InferenceSession(model.SerializeToString())


def resize_and_pad_image(image, new_shape, stride=32):
    """
    Resize and pad the image to the specified size, ensuring dimensions are multiples of stride.

    Parameters:
    - image: Input image
    - new_shape: Target size (integer or (height, width) tuple)
    - stride: Padding alignment stride, default 32

    Returns:
    - Processed image
    """
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)

    h, w = image.shape[:2]
    new_h, new_w = new_shape

    # Calculate scaling ratio
    r = min(new_h / h, new_w / w)
    resized_h, resized_w = int(round(h * r)), int(round(w * r))

    # Resize image
    image = cv2.resize(image, (resized_w, resized_h), interpolation=cv2.INTER_LINEAR)

    # Calculate padding size and align to stride multiple
    pad_w = (new_w - resized_w) % stride
    pad_h = (new_h - resized_h) % stride
    top, bottom = pad_h // 2, pad_h - pad_h // 2
    left, right = pad_w // 2, pad_w - pad_w // 2

    # Add padding
    image = cv2.copyMakeBorder(
        image, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114)
    )

    return image


def scale_boxes(img1_shape, boxes, img0_shape):
    """
    Rescales bounding boxes (in the format of xyxy by default) from the shape of the image they were originally
    specified in (img1_shape) to the shape of a different image (img0_shape).

    Args:
        img1_shape (tuple): The shape of the image that the bounding boxes are for, in the format of (height, width).
        boxes (torch.Tensor): the bounding boxes of the objects in the image, in the format of (x1, y1, x2, y2)
        img0_shape (tuple): the shape of the target image, in the format of (height, width).

    Returns:
        boxes (torch.Tensor): The scaled bounding boxes, in the format of (x1, y1, x2, y2)
    """

    # Calculate scaling ratio
    gain = min(img1_shape[0] / img0_shape[0], img1_shape[1] / img0_shape[1])

    # Calculate padding size
    pad_x = round((img1_shape[1] - img0_shape[1] * gain) / 2 - 0.1)
    pad_y = round((img1_shape[0] - img0_shape[0] * gain) / 2 - 0.1)

    # Remove padding and scale boxes
    boxes[..., :4] = (boxes[..., :4] - [pad_x, pad_y, pad_x, pad_y]) / gain
    return boxes


class YoloResult:
    def __init__(self, boxes, names):
        self.boxes = [YoloBox(data=d) for d in boxes]
        self.boxes = sorted(self.boxes, key=lambda x: x.conf, reverse=True)
        self.names = names


class YoloBox:
    def __init__(self, data):
        self.xyxy = data[:4]
        self.conf = data[-2]
        self.cls = data[-1]


def inference(image):
    """
    Run inference on the input image.

    Parameters:
    - image: Input image, HWC format and RGB order

    Returns:
    - YoloResult object containing the predicted boxes and class names
    """

    # Preprocess image
    orig_h, orig_w = image.shape[:2]
    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    pix = resize_and_pad_image(image, new_shape=int(image.shape[0] / stride) * stride)
    pix = np.transpose(pix, (2, 0, 1))  # CHW
    pix = np.expand_dims(pix, axis=0)  # BCHW
    pix = pix.astype(np.float32) / 255.0  # Normalize to [0, 1]
    new_h, new_w = pix.shape[2:]

    # Run inference
    preds = session.run(None, {"images": pix})[0]

    # Postprocess predictions
    preds = preds[preds[..., 4] > 0.25]
    preds[..., :4] = scale_boxes((new_h, new_w), preds[..., :4], (orig_h, orig_w))
    return YoloResult(boxes=preds, names=names)


if __name__ == "__main__":
    import sys
    import matplotlib
    import matplotlib.pyplot as plt
    import matplotlib.colors as colors

    image = sys.argv[1]
    image = cv2.imread(image)
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    layout = inference(image)

    bitmap = np.ones(image.shape[:2], dtype=np.uint8)
    h, w = bitmap.shape
    vcls = ["abandon", "figure", "table", "isolate_formula", "formula_caption"]
    for i, d in enumerate(layout.boxes):
        x0, y0, x1, y1 = d.xyxy.squeeze()
        x0, y0, x1, y1 = (
            np.clip(int(x0 - 1), 0, w - 1),
            np.clip(int(h - y1 - 1), 0, h - 1),
            np.clip(int(x1 + 1), 0, w - 1),
            np.clip(int(h - y0 + 1), 0, h - 1),
        )
        if layout.names[int(d.cls)] in vcls:
            bitmap[y0:y1, x0:x1] = 0
        else:
            bitmap[y0:y1, x0:x1] = i + 2
    bitmap = bitmap[::-1, :]

    # map bitmap to color
    colormap = matplotlib.colormaps["Pastel1"]
    norm = colors.Normalize(vmin=bitmap.min(), vmax=bitmap.max())
    colored_bitmap = colormap(norm(bitmap))
    colored_bitmap = (colored_bitmap[:, :, :3] * 255).astype(np.uint8)

    # overlay bitmap on image
    image_with_bitmap = cv2.multiply(image, colored_bitmap, scale=1 / 255)

    # show the results
    fig, ax = plt.subplots(1, 3, figsize=(15, 6))
    ax[0].imshow(image)
    ax[1].imshow(bitmap, cmap="Pastel1")
    ax[2].imshow(image_with_bitmap)
    plt.show()
