# python latest
FROM python:latest

# install git
RUN apt-get update && apt-get install -y git

# set working directory
WORKDIR /usr/src/app

# copy requirements.txt
COPY requirements.txt ./

# install requirements
RUN pip install --no-cache-dir -r requirements.txt

# copy app
COPY . .

# run app
CMD [ "python", "./app.py" ]