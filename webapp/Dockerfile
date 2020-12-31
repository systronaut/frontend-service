FROM python:3.8.5-alpine
MAINTAINER iDustBin "systronaut.de"

WORKDIR /webapp

ADD . /webapp

# We copy just the requirements.txt first to leverage Docker cache
COPY ./requirements.txt /webapp/requirements.txt

RUN python3 -m pip install --upgrade pip

RUN pip3 install -r requirements.txt

COPY ./ /webapp
COPY run.py /webapp

RUN chmod a+x ./run.py

# ENTRYPOINT [ "python3" ]

EXPOSE 5000/tcp

CMD [ "python3", "run.py" ]