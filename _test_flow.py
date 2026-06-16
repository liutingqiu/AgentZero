import urllib.request, urllib.error, json

# 测试健康检查
r = urllib.request.urlopen('http://127.0.0.1:5052/health')
print('=== health ===')
print(r.read().decode('utf-8'))

# 认证
req = urllib.request.Request('http://127.0.0.1:5052/api/auth',
    data=json.dumps({'code': '柳橙'}).encode('utf-8'),
    headers={'Content-Type': 'application/json'})
r = urllib.request.urlopen(req)
d = json.loads(r.read().decode('utf-8'))
print('=== auth ===')
print(d)
token = d.get('token', '')

# 设置
req = urllib.request.Request('http://127.0.0.1:5052/api/settings',
    headers={'Authorization': 'Bearer ' + token})
r = urllib.request.urlopen(req)
print('=== settings ===')
print(json.loads(r.read().decode('utf-8')))

# 普通聊天 POST
req = urllib.request.Request('http://127.0.0.1:5052/api/chat',
    data=json.dumps({'message': '用一句话解释什么是快速排序'}).encode('utf-8'),
    headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
r = urllib.request.urlopen(req)
print('=== chat POST ===')
print(json.loads(r.read().decode('utf-8')))
