#!/bin/sh
dnsmasq --no-daemon --dhcp-range=192.168.10.2,proxy &
python3 /user/api/dnsmasq-api.py