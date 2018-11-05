def kill_compression(i, i2, cid): #in
	i = re.sub('accept-encoding: .*\r\n', '', i, flags = re.I)
	return i


def kill_keepalive(i, i2, cid): #in
	i = re.sub('connection: .*\r\n', '', i, flags = re.I)
	return i

def kill_keepalive(i, i2, cid): #out
	i = re.sub('keep-alive: .*\r\n', '', i, flags = re.I)
	return i