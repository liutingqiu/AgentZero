import urllib.request, urllib.error, json

# 娴嬭瘯鍋ュ悍妫€鏌?r = urllib.request.urlopen('http://127.0.0.1:5052/health')
print('=== health ===')
print(r.read().decode('utf-8'))

# 璁よ瘉
req = urllib.request.Request('http://127.0.0.1:5052/api/auth',
    data=json.dumps({'code': '鏌虫'}).encode('utf-8'),
    headers={'Content-Type': 'application/json'})
r = urllib.request.urlopen(req)
d = json.loads(r.read().decode('utf-8'))
print('=== auth ===')
print(d)
token = d.get('token', '')

# 璁剧疆
req = urllib.request.Request('http://127.0.0.1:5052/api/settings',
    headers={'Authorization': 'Bearer ' + token})
r = urllib.request.urlopen(req)
print('=== settings ===')
print(json.loads(r.read().decode('utf-8')))

# 鏅€氳亰澶?POST
req = urllib.request.Request('http://127.0.0.1:5052/api/chat',
    data=json.dumps({'message': '鐢ㄤ竴鍙ヨ瘽瑙ｉ噴浠€涔堟槸蹇€熸帓搴?}).encode('utf-8'),
    headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
r = urllib.request.urlopen(req)
print('=== chat POST ===')
print(json.loads(r.read().decode('utf-8')))
