FROM python:3.9

WORKDIR /code

COPY ./requirements.txt /code/requirements.txt

RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt
RUN pip install git+https://github.com/facebookresearch/detectron2.git
RUN apt update
RUN apt install poppler-utils -y
RUN pip install pygit2
RUN pip install pgzip

COPY src /code/src

WORKDIR /code/src

RUN mkdir -p /data/server-storage
COPY src/data/ /data/server-storage


EXPOSE 5001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5001"]
