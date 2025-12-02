import asyncio
import json
import logging
import random

# --- CONFIGURATION ---
HOST = '0.0.0.0'  # Écoute sur toutes les interfaces
PORT = 8888
DEFAULT_ROOM = "general"

# --- LOGGING SETUP ---
# Configuration du système de journalisation (CLI output)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("ChatServer")

# --- STRUCTURES DE DONNÉES EN MÉMOIRE ---
# Clients: Map<StreamWriter, Dict>
# Associe la connexion (socket) aux infos du client
connected_clients = {} 

# Salons: Map<NomSalon, Set<StreamWriter>>
# Associe un nom de salon à un ensemble de connexions
rooms = {DEFAULT_ROOM: set()}

# --- PROTOCOLE & UTILITAIRES ---

async def send_json(writer, message_dict):
    """Envoie un objet JSON suivi d'un saut de ligne (délimiteur)."""
    try:
        data = json.dumps(message_dict) + "\n"
        writer.write(data.encode('utf-8'))
        await writer.drain() # Attendre que le buffer soit vidé (non-bloquant)
    except Exception as e:
        logger.error(f"Erreur d'envoi: {e}")

def change_room(writer, target_room):
    """Gère la logique de déplacement d'un utilisateur d'un salon à un autre."""
    client_info = connected_clients.get(writer)
    if not client_info:
        return

    old_room = client_info['room']
    
    # 1. Retirer de l'ancien salon
    if old_room in rooms:
        rooms[old_room].discard(writer)
        # Optionnel: supprimer le salon s'il est vide et n'est pas le défaut
        if not rooms[old_room] and old_room != DEFAULT_ROOM:
            del rooms[old_room]
            logger.info(f"Salon supprimé (vide) : {old_room}")

    # 2. Créer le nouveau salon si nécessaire
    if target_room not in rooms:
        rooms[target_room] = set()
        logger.info(f"Nouveau salon créé : {target_room}")

    # 3. Ajouter au nouveau salon
    rooms[target_room].add(writer)
    client_info['room'] = target_room
    
    logger.info(f"Client {client_info['id']} déplacé: {old_room} -> {target_room}")
    return old_room

async def broadcast_to_room(writer, content):
    """Envoie un message à tous les membres du salon actuel de l'expéditeur."""
    client_info = connected_clients.get(writer)
    if not client_info:
        return

    current_room = client_info['room']
    sender_id = client_info['id']
    
    if current_room in rooms:
        # Création du message de notification
        notification = {
            "type": "NEW_MSG",
            "payload": {
                "from": sender_id,
                "content": content,
                "room": current_room
            }
        }
        
        # Envoi à tous sauf à l'expéditeur
        for client_writer in rooms[current_room]:
            if client_writer != writer:
                await send_json(client_writer, notification)
        
        logger.info(f"Message diffusé dans [{current_room}] par {sender_id}")

# --- GESTIONNAIRE DE CONNEXION ---

async def handle_client(reader, writer):
    """Gère une connexion client unique de manière asynchrone."""
    
    # 1. Initialisation du client
    addr = writer.get_extra_info('peername')
    client_id = f"User-{random.randint(1000, 9999)}"
    
    # Enregistrement dans les structures globales
    connected_clients[writer] = {'id': client_id, 'room': DEFAULT_ROOM}
    rooms[DEFAULT_ROOM].add(writer)
    
    logger.info(f"Nouvelle connexion: {addr} assigné à {client_id} dans {DEFAULT_ROOM}")
    
    # Message de bienvenue
    await send_json(writer, {
        "type": "INFO",
        "payload": {"message": f"Bienvenue {client_id}. Vous êtes dans '{DEFAULT_ROOM}'."}
    })

    try:
        # 2. Boucle de lecture des messages
        while True:
            # Lecture asynchrone jusqu'au saut de ligne
            data = await reader.readline()
            if not data: # Connexion fermée par le client
                break
            
            message_text = data.decode('utf-8').strip()
            if not message_text:
                continue

            try:
                # Parsing JSON
                request = json.loads(message_text)
                action = request.get('action')
                payload = request.get('payload', {})
                
                # Routing des actions
                if action == 'CREATE_ROOM' or action == 'JOIN_ROOM':
                    room_name = payload.get('roomName')
                    if room_name:
                        change_room(writer, room_name)
                        await send_json(writer, {"type": "INFO", "payload": {"message": f"Rejoint salon: {room_name}"}})
                
                elif action == 'LEAVE_ROOM':
                    change_room(writer, DEFAULT_ROOM)
                    await send_json(writer, {"type": "INFO", "payload": {"message": f"Retour au salon par défaut"}})
                
                elif action == 'SEND_MSG':
                    content = payload.get('content')
                    if content:
                        await broadcast_to_room(writer, content)
                
                else:
                    await send_json(writer, {"type": "ERROR", "payload": {"message": "Action inconnue"}})

            except json.JSONDecodeError:
                logger.warning(f"JSON invalide reçu de {client_id}")
                await send_json(writer, {"type": "ERROR", "payload": {"message": "JSON invalide"}})
            except Exception as e:
                logger.error(f"Erreur de traitement: {e}")

    except ConnectionResetError:
        logger.warning(f"Connexion réinitialisée par {client_id}")
    finally:
        # 3. Nettoyage à la déconnexion
        if writer in connected_clients:
            room = connected_clients[writer]['room']
            if room in rooms:
                rooms[room].discard(writer)
            del connected_clients[writer]
            logger.info(f"Déconnexion propre: {client_id}")
        
        writer.close()
        await writer.wait_closed()

# --- POINT D'ENTRÉE MAIN ---

async def main():
    server = await asyncio.start_server(
        handle_client, HOST, PORT
    )

    addrs = ', '.join(str(sock.getsockname()) for sock in server.sockets)
    logger.info(f"Serveur démarré sur {addrs}")

    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        # Lancement de la boucle d'événements asyncio
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Arrêt du serveur demandé.")