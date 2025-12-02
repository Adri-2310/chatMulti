# client.py
import asyncio
import json
import threading
import queue
import tkinter as tk
from tkinter import scrolledtext, messagebox
import ttkbootstrap as tb
from ttkbootstrap.constants import *


class ChatClientAsync:
    def __init__(self, incoming_queue: queue.Queue, ui_callback_on_disconnect):
        self.reader = None
        self.writer = None
        self.username = None
        self.connected = False
        self.incoming_queue = incoming_queue
        self.on_disconnect = ui_callback_on_disconnect

    async def connect(self, host, port, username):
        self.reader, self.writer = await asyncio.open_connection(host, port)
        self.username = username
        self.connected = True

        await self.send_json({
            "action": "register",
            "username": username
        })

        asyncio.create_task(self.read_loop())

        await self.send_json({"action": "list_rooms"})

    async def read_loop(self):
        try:
            while self.connected:
                data = await self.reader.readline()
                if not data:
                    break
                try:
                    msg = json.loads(data.decode().strip())
                except json.JSONDecodeError:
                    continue
                self.incoming_queue.put(msg)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.incoming_queue.put({"type": "error", "message": str(e)})
        finally:
            self.connected = False
            self.incoming_queue.put({"type": "disconnected"})
            if self.on_disconnect:
                self.on_disconnect()

    async def send_json(self, payload):
        if not self.writer:
            return
        data = (json.dumps(payload) + "\n").encode()
        self.writer.write(data)
        await self.writer.drain()

    async def disconnect(self):
        self.connected = False
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        self.writer = None
        self.reader = None




class ChatClientGUI:
    def __init__(self):
        self.root = tb.Window(themename="cosmo")
        self.root.title("Client Chat - ttkbootstrap")


        self.incoming_queue = queue.Queue()

        self.loop = asyncio.new_event_loop()
        self.async_thread = threading.Thread(
            target=self.run_loop, daemon=True
        )
        self.async_thread.start()

        self.client = ChatClientAsync(
            incoming_queue=self.incoming_queue,
            ui_callback_on_disconnect=self.on_disconnected
        )

        self.current_room = None

        self.build_ui()

        self.root.after(100, self.process_incoming)

   

    def run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run_coro(self, coro):
        """Planifie un coroutine dans la boucle asyncio."""
        asyncio.run_coroutine_threadsafe(coro, self.loop)


    def build_ui(self):
        frame_conn = tb.Labelframe(self.root, text="Connexion")
        frame_conn.pack(fill=X, padx=10, pady=5)

        tb.Label(frame_conn, text="IP:").grid(row=0, column=0, padx=5, pady=2)
        self.entry_ip = tb.Entry(frame_conn)
        self.entry_ip.insert(0)
        self.entry_ip.grid(row=0, column=1, padx=5, pady=2)

        tb.Label(frame_conn, text="Port:").grid(row=0, column=2, padx=5, pady=2)
        self.entry_port = tb.Entry(frame_conn, width=6)
        self.entry_port.insert(0, "8888")
        self.entry_port.grid(row=0, column=3, padx=5, pady=2)

        tb.Label(frame_conn, text="Username:").grid(row=0, column=4, padx=5, pady=2)
        self.entry_username = tb.Entry(frame_conn)
        self.entry_username.grid(row=0, column=5, padx=5, pady=2)

        self.btn_connect = tb.Button(
            frame_conn, text="Se connecter", bootstyle=SUCCESS,
            command=self.on_connect_click
        )
        self.btn_connect.grid(row=0, column=6, padx=5, pady=2)

        self.btn_disconnect = tb.Button(
            frame_conn, text="Déconnexion", bootstyle=DANGER,
            command=self.on_disconnect_click, state=DISABLED
        )
        self.btn_disconnect.grid(row=0, column=7, padx=5, pady=2)

        frame_main = tb.Frame(self.root)
        frame_main.pack(fill=BOTH, expand=True, padx=10, pady=5)

        frame_rooms = tb.Labelframe(frame_main, text="Salons")
        frame_rooms.pack(side=LEFT, fill=Y, padx=(0, 5))

        self.list_rooms = tk.Listbox(frame_rooms, height=10)
        self.list_rooms.pack(side=TOP, fill=BOTH, expand=True, padx=5, pady=5)

        btn_refresh = tb.Button(
            frame_rooms, text="Rafraîchir",
            command=self.on_refresh_rooms
        )
        btn_refresh.pack(side=TOP, fill=X, padx=5, pady=2)

        btn_join = tb.Button(
            frame_rooms, text="Rejoindre",
            command=self.on_join_room
        )
        btn_join.pack(side=TOP, fill=X, padx=5, pady=2)

        btn_leave = tb.Button(
            frame_rooms, text="Quitter le salon",
            command=self.on_leave_room
        )
        btn_leave.pack(side=TOP, fill=X, padx=5, pady=2)

        frame_new_room = tb.Frame(frame_rooms)
        frame_new_room.pack(side=TOP, fill=X, padx=5, pady=5)

        self.entry_new_room = tb.Entry(frame_new_room)
        self.entry_new_room.pack(side=LEFT, fill=X, expand=True, padx=(0, 5))

        btn_create = tb.Button(
            frame_new_room, text="Créer",
            command=self.on_create_room
        )
        btn_create.pack(side=LEFT)

        frame_chat = tb.Labelframe(frame_main, text="Chat")
        frame_chat.pack(side=LEFT, fill=BOTH, expand=True)

        self.text_chat = scrolledtext.ScrolledText(
            frame_chat, state="disabled", wrap="word", height=15
        )
        self.text_chat.pack(fill=BOTH, expand=True, padx=5, pady=5)

        frame_input = tb.Frame(frame_chat)
        frame_input.pack(fill=X, padx=5, pady=(0, 5))

        self.entry_message = tb.Entry(frame_input)
        self.entry_message.pack(side=LEFT, fill=X, expand=True, padx=(0, 5))
        self.entry_message.bind("<Return>", self.on_send_message)

        self.btn_send = tb.Button(
            frame_input, text="Envoyer",
            command=self.on_send_message, state=DISABLED
        )
        self.btn_send.pack(side=LEFT)


    def on_connect_click(self):
        host = self.entry_ip.get().strip()
        port = self.entry_port.get().strip()
        username = self.entry_username.get().strip()

        if not host or not port or not username:
            messagebox.showerror("Erreur", "IP, port et username sont obligatoires")
            return

        try:
            port = int(port)
        except ValueError:
            messagebox.showerror("Erreur", "Port invalide")
            return

        self.append_chat(f"Connexion à {host}:{port} en tant que {username}...\n")

        async def do_connect():
            try:
                await self.client.connect(host, port, username)
                self.on_connected()
            except Exception as e:
                self.append_chat(f"Échec de connexion : {e}\n")
                messagebox.showerror("Erreur", f"Impossible de se connecter : {e}")

        self.run_coro(do_connect())

    def on_disconnect_click(self):
        if not self.client.connected:
            return

        async def do_disc():
            await self.client.disconnect()

        self.run_coro(do_disc())

    def on_connected(self):
        def _update():
            self.btn_connect.config(state=DISABLED)
            self.btn_disconnect.config(state=NORMAL)
            self.btn_send.config(state=NORMAL)
            self.append_chat("Connecté.\n")

        self.root.after(0, _update)

    def on_disconnected(self):
        def _update():
            self.btn_connect.config(state=NORMAL)
            self.btn_disconnect.config(state=DISABLED)
            self.btn_send.config(state=DISABLED)
            self.append_chat("Déconnecté du serveur.\n")

        self.root.after(0, _update)

    def on_refresh_rooms(self):
        if not self.client.connected:
            return
        self.run_coro(self.client.send_json({"action": "list_rooms"}))

    def on_join_room(self):
        if not self.client.connected:
            return
        selection = self.list_rooms.curselection()
        if not selection:
            return
        room = self.list_rooms.get(selection[0])
        self.run_coro(self.client.send_json({
            "action": "join_room",
            "room": room
        }))

    def on_leave_room(self):
        if not self.client.connected:
            return
        self.run_coro(self.client.send_json({"action": "leave_room"}))

    def on_create_room(self):
        if not self.client.connected:
            return
        room = self.entry_new_room.get().strip()
        if not room:
            return
        self.run_coro(self.client.send_json({
            "action": "create_room",
            "room": room
        }))
        self.entry_new_room.delete(0, tk.END)

    def on_send_message(self, event=None):
        if not self.client.connected:
            return
        msg = self.entry_message.get().strip()
        if not msg:
            return
        self.entry_message.delete(0, tk.END)
        self.run_coro(self.client.send_json({
            "action": "send_message",
            "message": msg
        }))


    def process_incoming(self):
        """Appelée régulièrement par Tk pour traiter la file."""
        while True:
            try:
                msg = self.incoming_queue.get_nowait()
            except queue.Empty:
                break
            self.handle_server_message(msg)

        self.root.after(100, self.process_incoming)

    def handle_server_message(self, msg):
        mtype = msg.get("type")
        if mtype == "info":
            self.append_chat(f"[INFO] {msg.get('message')}\n")
            room = msg.get("room")
            if room:
                self.current_room = room
                self.append_chat(f"Salon actuel : {room}\n")
        elif mtype == "error":
            self.append_chat(f"[ERREUR] {msg.get('message')}\n")
        elif mtype == "room_list":
            self.update_room_list(msg.get("rooms", []))
        elif mtype == "room_joined":
            room = msg.get("room")
            self.current_room = room
            self.append_chat(f"Vous avez rejoint le salon : {room}\n")
        elif mtype == "room_left":
            room = msg.get("room")
            self.append_chat(f"Vous avez quitté le salon : {room}\n")
            self.current_room = None
        elif mtype == "chat_message":
            room = msg.get("room")
            sender = msg.get("from")
            text = msg.get("message")
            self.append_chat(f"[{room}] {sender}: {text}\n")
        elif mtype == "disconnected":
            # géré aussi par on_disconnected
            pass

    def update_room_list(self, rooms):
        self.list_rooms.delete(0, tk.END)
        for r in rooms:
            self.list_rooms.insert(tk.END, r)

    def append_chat(self, text):
        self.text_chat.config(state="normal")
        self.text_chat.insert(tk.END, text)
        self.text_chat.see(tk.END)
        self.text_chat.config(state="disabled")

    # --- Boucle principale ---

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.mainloop()

    def on_close(self):
        # arrêter proprement
        if self.client.connected:
            self.run_coro(self.client.disconnect())
        # arrêter la boucle asyncio
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.root.destroy()


if __name__ == "__main__":
    app = ChatClientGUI()
    app.run()