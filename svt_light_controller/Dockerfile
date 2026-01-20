ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-paho-mqtt tzdata

COPY svtlc.py /svtlc.py
COPY ui_server.py /ui_server.py
COPY webui /webui
COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
