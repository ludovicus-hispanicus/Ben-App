FROM python:3.7

WORKDIR /code

# Upgrade pip and install setuptools first to avoid version conflicts
RUN pip install --upgrade pip setuptools wheel

COPY ./requirements.txt /code/requirements.txt

RUN pip install --no-cache-dir -r /code/requirements.txt
COPY src /code/src

WORKDIR /code/src


EXPOSE 5002

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5002"]
