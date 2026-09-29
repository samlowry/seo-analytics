#!/usr/bin/env python3
"""Minimal local SOCKS5 (no auth) that exits via this host's default route.

Used as the Mac side of an ssh -R tunnel for genhost Camoufox. Only CONNECT.
"""
from __future__ import annotations

import argparse
import asyncio
import socket
import struct


async def pipe(a: asyncio.StreamReader, b: asyncio.StreamWriter):
    try:
        while True:
            data = await a.read(65536)
            if not data:
                break
            b.write(data)
            await b.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
        pass
    finally:
        try:
            b.close()
        except Exception:
            pass


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    peer = writer.get_extra_info("peername")
    try:
        hdr = await reader.readexactly(2)
        nmethods = hdr[1]
        await reader.readexactly(nmethods)
        writer.write(b"\x05\x00")  # no auth
        await writer.drain()

        req = await reader.readexactly(4)
        if req[0] != 5 or req[1] != 1:  # CONNECT
            writer.write(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()
            return
        atyp = req[3]
        if atyp == 1:
            addr = socket.inet_ntop(socket.AF_INET, await reader.readexactly(4))
        elif atyp == 3:
            ln = (await reader.readexactly(1))[0]
            addr = (await reader.readexactly(ln)).decode()
        elif atyp == 4:
            addr = socket.inet_ntop(socket.AF_INET6, await reader.readexactly(16))
        else:
            writer.write(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()
            return
        port = struct.unpack("!H", await reader.readexactly(2))[0]

        try:
            remote_r, remote_w = await asyncio.open_connection(addr, port)
        except OSError:
            writer.write(b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()
            return

        writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        await writer.drain()
        await asyncio.gather(pipe(reader, remote_w), pipe(remote_r, writer))
    except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
        pass
    except Exception as e:
        print(f"client {peer}: {type(e).__name__}: {e}", flush=True)
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def main(host: str, port: int):
    server = await asyncio.start_server(handle, host, port)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets or [])
    print(f"socks5 listening on {addrs}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1080)
    a = ap.parse_args()
    asyncio.run(main(a.host, a.port))
