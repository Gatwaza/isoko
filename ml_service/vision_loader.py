"""Load community image classifiers whose repos lack a usable preprocessor config (transformers 5.x)."""
from transformers import (AutoImageProcessor, AutoModelForImageClassification, MobileNetV2ImageProcessor,
                          ViTImageProcessor, pipeline)


def image_classifier(model_id: str, device: str = "cpu"):
    model = AutoModelForImageClassification.from_pretrained(model_id)
    try:
        proc = AutoImageProcessor.from_pretrained(model_id)
    except Exception:
        if model.config.model_type == "mobilenet_v2":
            proc = MobileNetV2ImageProcessor(size={"shortest_edge": 256}, crop_size={"height": 224, "width": 224})
        else:  # ViT-family fine-tunes of google/vit-base-patch16-224(-in21k): 224px, mean/std 0.5
            proc = ViTImageProcessor(size={"height": 224, "width": 224}, image_mean=[0.5] * 3, image_std=[0.5] * 3)
    return pipeline("image-classification", model=model, image_processor=proc, device=device)
