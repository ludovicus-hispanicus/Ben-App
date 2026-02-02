FROM pytorch/pytorch:1.11.0-cuda11.3-cudnn8-runtime

WORKDIR /code

COPY ./requirements.txt /code/requirements.txt

# Remove torch from requirements since it's in base image
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt
# Install detectron2 for torch 1.11
RUN pip install detectron2 -f https://dl.fbaipublicfiles.com/detectron2/wheels/cu113/torch1.10/index.html || \
    python -m pip install 'git+https://github.com/facebookresearch/detectron2.git@v0.6'
RUN apt update
RUN apt install poppler-utils -y
RUN pip install pygit2
RUN pip install pgzip

COPY src /code/src

WORKDIR /code/src

RUN mkdir -p /data/server-storage
COPY src/data/ /data/server-storage

# Create YOLO data directories
RUN mkdir -p /data/yolo/datasets /data/yolo/models /data/yolo/base_models /data/yolo/runs

# Pre-download YOLOv8 base model (small version - good balance of speed/accuracy)
RUN python -c "from ultralytics import YOLO; YOLO('yolov8s.pt')" || echo "Base model will download on first use"

# Set YOLO environment variable
ENV YOLO_DATA_PATH=/data/yolo

EXPOSE 5001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5001"]
