# -*- coding: utf-8 -*-
"""Return 1 if TCP port is free on 127.0.0.1 else 0."""
import socket
import sys


def is_free(port: int, host: str = "127.0.0.1") -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind((host, port))
        s.close()
        return True
    except OSError:
        return False


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9001
    print("1" if is_free(port) else "0")
