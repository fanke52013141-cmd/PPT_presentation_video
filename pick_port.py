import socket


def free_port(start: int = 8000, host: str = "127.0.0.1") -> int:
    """Return the first free TCP port at or after `start` on `host`."""
    p = start
    while p < start + 100:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind((host, p))
            s.close()
            return p
        except OSError:
            p += 1
    return start


if __name__ == "__main__":
    print(free_port())
