
def get_unique_id():
    try:
        import machine
        import ubinascii
        return ubinascii.hexlify(machine.unique_id())
    except:
        return b'set-a-unique-device-id'

def get_local_ip():
    try:
        import network
        return bytes(network.WLAN(0).ifconfig()[0], 'utf-8')
    except:
        return b'127.0.0.1'

def get_local_mac():
    try:
        import network
        import ubinascii
        return ubinascii.hexlify(network.WLAN(0).config('mac'), ':')
    except:
        return b'cannotgetlocalmac'