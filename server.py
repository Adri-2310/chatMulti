# server.py
import asyncio
import json
import logging
import socket

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s:%(name)s: %(message)s'
)
logger = logging.getLogger("chat-server")


def get_local_ip():
    """Retourne l'IP locale probable de la machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # On ne contacte pas vraiment 8.8.8.8, on utilise juste la stack réseau
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


class ChatServer:
    def __init__(self, host, port=8888):
        self.host = host
        self.port = port

        # username -> {"writer": StreamWriter, "room": "general" | None}
        self.clients = {}

        # room_name -> set(usernames)
        self.rooms = {"general": set()}  # salon par défaut

    async def start(self):
        server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )

        # IP "réelle" de la machine (pour les clients)
        ip_locale = get_local_ip()

        # Log propre, sans ('0.0.0.0', 8888)
        logger.info(f"Server started on {ip_locale}:{self.port}")

        async with server:
            await server.serve_forever()

    async def handle_client(self, reader: asyncio.StreamReader,
                            writer: asyncio.StreamWriter):
        peer = writer.get_extra_info('peername')
        logger.info(f"New connection from {peer}")
        username = None

        try:
            while True:
                data = await reader.readline()
                if not data:
                    break  # client déconnecté

                try:
                    message = json.loads(data.decode().strip())
                except json.JSONDecodeError:
                    await self.send_error(writer, "Invalid JSON")
                    continue

                action = message.get("action")
                if action == "register":
                    username = await self.handle_register(message, writer)
                elif action == "list_rooms":
                    await self.handle_list_rooms(writer)
                elif action == "create_room":
                    await self.handle_create_room(message, writer, username)
                elif action == "join_room":
                    await self.handle_join_room(message, writer, username)
                elif action == "leave_room":
                    await self.handle_leave_room(writer, username)
                elif action == "send_message":
                    await self.handle_send_message(message, writer, username)
                else:
                    await self.send_error(writer, "Unknown action")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception(f"Error with client {peer}: {e}")
        finally:
            logger.info(f"Connection closed: {peer}")
            if username:
                await self.cleanup_client(username)
            writer.close()
            await writer.wait_closed()

    async def handle_register(self, msg, writer):
        username = msg.get("username")
        if not username:
            await self.send_error(writer, "username required")
            return None

        if username in self.clients:
            await self.send_error(writer, "username already taken")
            return None

        # Enregistrer le client et l'ajouter au salon "general"
        self.clients[username] = {"writer": writer, "room": "general"}
        self.rooms["general"].add(username)

        await self.send_json(writer, {
            "type": "info",
            "message": f"Registered as {username}",
            "room": "general"
        })
        logger.info(f"User registered: {username}")
        return username

    async def handle_list_rooms(self, writer):
        await self.send_json(writer, {
            "type": "room_list",
            "rooms": list(self.rooms.keys())
        })

    async def handle_create_room(self, msg, writer, username):
        if not username:
            await self.send_error(writer, "register first")
            return

        room = msg.get("room")
        if not room:
            await self.send_error(writer, "room name required")
            return

        if room in self.rooms:
            await self.send_error(writer, "room already exists")
            return

        self.rooms[room] = set()
        logger.info(f"Room created: {room}")

        # Info au créateur
        await self.send_json(writer, {
            "type": "info",
            "message": f"Room '{room}' created"
        })
        # En plus : renvoyer la liste des salons à jour à ce client
        await self.send_json(writer, {
            "type": "room_list",
            "rooms": list(self.rooms.keys())
        })

    async def handle_join_room(self, msg, writer, username):
        if not username:
            await self.send_error(writer, "register first")
            return

        room = msg.get("room")
        if not room:
            await self.send_error(writer, "room name required")
            return

        if room not in self.rooms:
            await self.send_error(writer, "room does not exist")
            return

        # quitter l'ancien salon
        current_room = self.clients[username]["room"]
        if current_room and username in self.rooms.get(current_room, set()):
            self.rooms[current_room].remove(username)

        # rejoindre le nouveau
        self.rooms[room].add(username)
        self.clients[username]["room"] = room

        await self.send_json(writer, {
            "type": "room_joined",
            "room": room
        })
        logger.info(f"{username} joined room {room}")

    async def handle_leave_room(self, writer, username):
        if not username:
            await self.send_error(writer, "register first")
            return

        current_room = self.clients[username]["room"]
        if current_room and username in self.rooms.get(current_room, set()):
            self.rooms[current_room].remove(username)
            self.clients[username]["room"] = None

            await self.send_json(writer, {
                "type": "room_left",
                "room": current_room
            })
            logger.info(f"{username} left room {current_room}")
        else:
            await self.send_error(writer, "not in a room")

    async def handle_send_message(self, msg, writer, username):
        if not username:
            await self.send_error(writer, "register first")
            return

        text = msg.get("message")
        if not text:
            await self.send_error(writer, "message required")
            return

        room = self.clients[username]["room"]
        if not room:
            await self.send_error(writer, "join a room first")
            return

        logger.info(f"Message from {username} in {room}: {text}")
        await self.broadcast_room(room, {
            "type": "chat_message",
            "room": room,
            "from": username,
            "message": text
        })

    async def broadcast_room(self, room, payload):
        users = self.rooms.get(room, set())
        data = (json.dumps(payload) + "\n").encode()
        for user in users:
            writer = self.clients[user]["writer"]
            try:
                writer.write(data)
                await writer.drain()
            except Exception:
                logger.warning(f"Failed to send to {user}")

    async def send_error(self, writer, message):
        await self.send_json(writer, {
            "type": "error",
            "message": message
        })

    async def send_json(self, writer, payload):
        data = (json.dumps(payload) + "\n").encode()
        writer.write(data)
        await writer.drain()

    async def cleanup_client(self, username):
        info = self.clients.pop(username, None)
        if not info:
            return

        room = info["room"]
        if room and username in self.rooms.get(room, set()):
            self.rooms[room].remove(username)
        logger.info(f"Cleaned up client {username}")


async def main():
    # écouter sur toutes les interfaces pour que les autres machines puissent se connecter
    server = ChatServer(host="0.0.0.0", port=8888)

    ip_locale = get_local_ip()
    print("Serveur de chat démarré.")
    print(f"Adresse IP de cette machine (à utiliser dans le client) : {ip_locale}")
    print(f"Port : {server.port}")
    print(f"Dans le client, entre IP = {ip_locale} et Port = {server.port}")

    await server.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")