import socket

s = socket.socket()
s.settimeout(2)
try:
    s.connect(('127.0.0.1', 8001))
    print('Connected')
except Exception as e:
    print('Error:', e)
finally:
    s.close()