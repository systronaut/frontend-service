import requests

headers = {
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Referer': 'http://localhost:5000/',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 11_0_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36',
    'Content-Type': 'application/json; charset=UTF-8',
}

data = '{"hostname":"app01","mac":"00:00:00:00:01:01","ip":"192.168.10.112","lease":"72h","action":"new_host"}'

response = requests.post('http://localhost:8081/api/dnsmasq/add/host', headers=headers, data=data)

	return reponse

