# Author: github.com/iDustBin
# !/usr/bin/env python3
# -*- coding: utf-8 -*-

#base_url = "http://dnsmasq-exec:8081"

import os
from flask import Flask, render_template, request

webapp = Flask(__name__)



@webapp.route('/')
def index():
    return render_template('index.html')

@webapp.route('/dhcp/host', methods=['GET', 'POST'])
def dhcp_host():
    if request.method == 'GET':
        return render_template('dhcp_host.html')


@webapp.route('/api/generate', methods=['GET', 'POST'])
def config():
    # if GET open the input page for a specific type (input.html)
    if request.method == 'GET':
        if request.args.get('autoGenerate') == 'debian':
            return render_template('input.html', autoGenerate='debian')
        elif request.args.get('autoGenerate') == 'centos':
            return render_template('input.html', autoGenerate='centos')
        else:
            return 'Error on GET'
    # if POST generate the output page for a specific type


@webapp.route('/api/generate/debian/server/<conf_name>/<level>/', methods=['GET', 'POST'])
def debian(conf_name, level):
    # if request.method == ('POST'):
    #     return render_template('output.html', 
    #         autoGenerate='debian',
    #         form=request.form,
    #         level=level,)
    return render_template('inputs/debian_input.html', 
        autoGenerate='debian', 
        level=level,
        conf_name=conf_name)


@webapp.route('/api/generate/windows/server/<conf_name>/<level>/', methods=['GET', 'POST'])
def windows(conf_name, level):
    # if request.method == 'POST':
    #     return render_template('output.html', 
    #         autoGenerate='windows', 
    #         form=request.form, 
    #         conf_name=conf_name,
    #         level=level)
    return render_template('inputs/windows_input.html', 
        autoGenerate='windows', 
        level=level, 
        conf_name=conf_name)


@webapp.route('/test')
def test():
    return create_response(message='Hello,Test!')

if __name__ == "__main__":
    webapp.run(host='0.0.0.0', port=5000, debug=True)