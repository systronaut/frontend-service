FROM alpine:latest

LABEL maintainer "iDustBin"

# Install the necessary packages
RUN apk upgrade --no-cache \
    && apk add --update \
        build-base \
        dnsmasq \
        wget \
        python3 \
        python3-dev \
    && rm -rf /var/cache/apk/*

ENV SYSLINUX_VERSION 6.03
ENV TEMP_SYSLINUX_PATH /tmp/syslinux-"$SYSLINUX_VERSION"

WORKDIR /tmp

RUN \
  mkdir -p "$TEMP_SYSLINUX_PATH" \
  && wget -q https://www.kernel.org/pub/linux/utils/boot/syslinux/syslinux-"$SYSLINUX_VERSION".tar.gz \
  && tar -xzf syslinux-"$SYSLINUX_VERSION".tar.gz \
  && mkdir -p /var/lib/tftpboot \
  && cp "$TEMP_SYSLINUX_PATH"/bios/core/pxelinux.0 /var/lib/tftpboot/ \
  && cp "$TEMP_SYSLINUX_PATH"/bios/com32/libutil/libutil.c32 /var/lib/tftpboot/ \
  && cp "$TEMP_SYSLINUX_PATH"/bios/com32/elflink/ldlinux/ldlinux.c32 /var/lib/tftpboot/ \
  && cp "$TEMP_SYSLINUX_PATH"/bios/com32/menu/menu.c32 /var/lib/tftpboot/ \
  && rm -rf "$TEMP_SYSLINUX_PATH" \
  && rm /tmp/syslinux-"$SYSLINUX_VERSION".tar.gz

# Download and extract MemTest86+
ENV MEMTEST_VERSION 5.01
RUN wget -q http://www.memtest.org/download/"$MEMTEST_VERSION"/memtest86+-"$MEMTEST_VERSION".bin.gz \
  && gzip -d memtest86+-"$MEMTEST_VERSION".bin.gz \
  && mkdir -p /var/lib/tftpboot/memtest \
  && mv memtest86+-$MEMTEST_VERSION.bin /var/lib/tftpboot/memtest/memtest86+

RUN mkdir -p /var/lib/tftpboot/pxelinux.cfg/

# Configure DNSMASQ
COPY etc/ /etc

RUN mkdir -p /user/api

COPY ./requirements.txt /user/api/requirements.txt
RUN python3 -m ensurepip
RUN python3 -m pip install --upgrade pip

RUN pip3 install -r /user/api/requirements.txt

COPY ./ /user/api
COPY dnsmasq-api.py /user/api/dnsmasq-api.py

RUN chmod a+x /user/api/dnsmasq-api.py

COPY start.sh /user/api/start.sh

RUN chmod a+x /user/api/start.sh

EXPOSE 53 53/udp
EXPOSE 69 69/udp
EXPOSE 8081 8081/tcp
# Start dnsmasq. It picks up default configuration from /etc/dnsmasq.conf and
# /etc/default/dnsmasq plus any command line switch
# ENTRYPOINT ["dnsmasq", "--no-daemon"]
# ENTRYPOINT ["--dhcp-range=192.168.10.2,proxy"]
CMD ["/user/api/start.sh"]