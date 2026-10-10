"""Validate the explicitly trusted proxy address before starting Uvicorn."""
import ipaddress
import os


def trusted_proxies():
    value=os.getenv('CHESS_TRUSTED_PROXY_IPS','127.0.0.1')
    addresses=[address.strip() for address in value.split(',') if address.strip()]
    if not addresses:
        raise ValueError('Configure a trusted proxy IP address.')
    for address in addresses:
        network=ipaddress.ip_network(address,strict=False)
        if network.prefixlen==0:
            raise ValueError('Do not trust all IP addresses for forwarded headers.')
    return ','.join(addresses)


if __name__=='__main__':
    print(trusted_proxies())
