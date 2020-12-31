from flask import Flask, jsonify, request
from flask_cors import CORS
import os.path
import subprocess

dnsmasq_app = Flask(__name__)
cors = CORS(dnsmasq_app, resources={r"/api/*": {"origins": "*"}})

reload_command = "/usr/bin/killall -HUP dnsmasq"
lease_file = "/var/lib/misc/dnsmasq.leases"

@dnsmasq_app.route("/api/dnsmasq/version", methods=["GET"])
def version():
    os.system("dnsmasq -v")
    return jsonify({'version'}), 200

@dnsmasq_app.route("/api/dnsmasq/status", methods=["GET"])
def status():
    os.system("dnsmasq status")
    return jsonify({'status'}), 200

@dnsmasq_app.route("/api/dnsmasq/add/host", methods=["POST"])
def add_host():
    new_host = request.get_json()['mac']
    ip_address = request.get_json()['ip']
    host_name = request.get_json()['hostname']
    lease_time = request.get_json()['lease']
    os.system("echo "+"dhcp-host="+str(new_host+',')+str(ip_address+',')+str(host_name+',')+str(lease_time)+" >> /etc/dnsmasq.conf")    
    mac_address_replace = request.get_json()['mac'].replace(":", "-")
    parent_dir = "/var/lib/tftpboot/pxelinux.cfg/"
    add_host = os.path.join('/var/lib/tftpboot/pxelinux.cfg/' + request.get_json()['mac'].replace(":", "-"))
    add_host = os.path.join(parent_dir, add_host) 
    os.makedirs(add_host) 
    print(add_host)
    if not os.path.isdir('/var/lib/tftpboot/pxelinux.cfg'):
         os.mkdir('/var/lib/tftpboot/pxelinux.cfg/'+ new_host)
    os.mkdir(new_host)
    return jsonify({}), 200

# @dnsmasq_app.route("/api/dnsmasq/edit/host", methods=["POST"])
# def edit_host():
#     new_host = request.get_json()['new_host']
#     line_index = request.get_json()['id']
#     dhcp_hosts = []
#     f = open("/etc/dnsmasq.conf")
#     dns_conf = f.read()
#     f.close()
#     confs = dns_conf.split('\n')
#     for i in range(len(confs)):
#         print(i)
#         if confs[i].split('=')[0] == 'dhcp-host':
#             dhcp_hosts.append(confs[i].split('=')[1])
#             confs.pop(i)
#     for j in range(len(dhcp_hosts)):
#         if j == line_index:
#             dhcp_hosts[j] = "dhcp-host="+new_host
#     new_confs = confs+dhcp_hosts
#     for i in range(len(new_confs)):
#         if i == 0:
#             os.system("echo " + new_confs[i] + " > /etc/dnsmasq.conf")
#         else:
#             os.system("echo " + new_confs[i] + " >> /etc/dnsmasq.conf")
#         # os.system("/etc/init.d/dnsmasq restart")
#     return jsonify({}), 200

# @dnsmasq_app.route("/api/dnsmasq/delete/host", methods=["POST"])
# def delete_host():
#     line_index = request.get_json()['id']
#     dhcp_hosts = []
#     f = open("/etc/dnsmasq.conf")
#     dns_conf = f.read()
#     f.close()
#     confs = dns_conf.split('\n')
#     for i in range(len(confs)):
#         print(i)
#         if confs[i].split('=')[0] == 'dhcp-host':
#             dhcp_hosts.append(confs[i].split('=')[1])
#             confs.pop(i)
#     dhcp_hosts.pop(line_index)
#     new_confs = confs+dhcp_hosts
#     for i in range(len(new_confs)):
#         if i == 0:
#             os.system("echo " + new_confs[i] + " > /etc/dnsmasq.conf")
#         else:
#             os.system("echo " + new_confs[i] + " >> /etc/dnsmasq.conf")
#         # os.system("/etc/init.d/dnsmasq restart")
#     return jsonify({}), 200

# read hosts file from different directory
@dnsmasq_app.route("/api/dnsmasq/hosts")
def hosts():
    dhcp_hosts = []
    f = open("/etc/dnsmasq.conf")
    dns_conf = f.read()
    f.close()
    confs = dns_conf.split('\n')
    for i in range(len(confs)):
        print(i)
        if confs[i].split('=')[0] == 'dhcp-host':
            host = confs[i].split('=')[1]
            dhcp_hosts.append(host)
            # dhcp_hosts.append(host.split(','))
    return jsonify({'dhcp_host': dhcp_hosts}), 200

@dnsmasq_app.route("/api/dnsmasq/config/load")
def config():
    os.system("dnsmasq --conf-file=/etc/dnsmasq.conf")
    return jsonify({'status'}), 200

@dnsmasq_app.route("/api/dnsmasq/config/resolv")
def resolv():
    os.system("dnsmsq --no-resolv")
    return jsonify({'status'}), 200

@dnsmasq_app.route('/ping', methods=['GET'])
def ping_pong():
    return jsonify('pong!')

if __name__ == '__main__':
    dnsmasq_app.run(debug=True, host='0.0.0.0', port=8081)
