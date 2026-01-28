from flask import Flask, request, jsonify, send_from_directory
import requests
import os
from urllib.parse import urlparse, parse_qs
import random
from ytmusicapi import YTMusic
from flask_cors import CORS
import sqlite3
import json
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__, static_url_path='', static_folder='.')
CORS(app) 
socketio = SocketIO(app, cors_allowed_origins="*", ping_timeout=60, ping_interval=25)
yt = YTMusic(auth=None)
yt.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

# Database Setup
def init_db():
    with sqlite3.connect('aura_users.db') as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (google_id TEXT PRIMARY KEY, email TEXT, data TEXT)''')
        conn.commit()

init_db()

# Security: Block access to source code and config files
@app.route('/health')
def health():
    return "OK", 200

@app.before_request
def block_sensitive_files():
    if request.path.endswith('.py') or request.path in ['/requirements.txt', '/Procfile', '/.env']:
        return "Access Denied", 403

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/search')
def search():
    print(f"Search Request: {request.args.get('q')}") # Debug log
    try:
        query = request.args.get('q')
        if not query: return jsonify([])
        
        # Use 'songs' for official tracks, 'videos' for lyrics/fallbacks
        search_filter = "videos" if " lyrics" in query.lower() else "songs"
        return jsonify(yt.search(query, filter=search_filter))
    except Exception as e:
        print(f"Search Error: {e}") # Check Render Logs for this
        return jsonify({'error': str(e)}), 500

@app.route('/lyrics')
def lyrics():
    title = request.args.get('title')
    artist = request.args.get('artist')
    
    # Try fetching synced lyrics from LRCLIB (often sources from Musixmatch/Spotify)
    if title and artist:
        # Clean title: remove (Official Video), [Lyrics], etc. for better matching
        clean_title = title.split('(')[0].split('[')[0].strip()
        try:
            resp = requests.get("https://lrclib.net/api/get", params={'artist_name': artist, 'track_name': clean_title})
            data = resp.json()
            if data.get('syncedLyrics'):
                return jsonify({'lyrics': data['syncedLyrics'], 'synced': True})
            if data.get('plainLyrics'):
                return jsonify({'lyrics': data['plainLyrics'], 'synced': False})
        except (requests.exceptions.RequestException, json.JSONDecodeError): pass

    video_id = request.args.get('id')
    if not video_id: return jsonify({'lyrics': ''})
    try:
        watch_playlist = yt.get_watch_playlist(videoId=video_id)
        lyrics_id = watch_playlist.get('lyrics')
        if lyrics_id:
            lyrics_data = yt.get_lyrics(lyrics_id)
            return jsonify({'lyrics': lyrics_data['lyrics'], 'synced': False})
    except Exception: pass

    # Fallback: If direct ID failed, search for the official song on YT Music
    if title and artist:
        try:
            search_results = yt.search(f"{title} {artist}", filter="songs")
            if search_results:
                official_id = search_results[0]['videoId']
                if official_id != video_id:
                    watch_playlist = yt.get_watch_playlist(videoId=official_id)
                    lyrics_id = watch_playlist.get('lyrics')
                    if lyrics_id:
                        lyrics_data = yt.get_lyrics(lyrics_id)
                        return jsonify({'lyrics': lyrics_data['lyrics'], 'synced': False})
        except Exception: pass

    return jsonify({'lyrics': 'Lyrics not available.'})

def parse_duration_from_string(duration_str):
    if not duration_str: return 0
    parts = duration_str.split(':')
    seconds = 0
    try:
        if len(parts) == 2:
            seconds = int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except (ValueError, IndexError):
        return 0
    return seconds

def _format_track(track):
    """Helper to format track data consistently."""
    if not track or not track.get('videoId'):
        return None
    
    artist_name = 'Unknown'
    artist_id = None
    if track.get('artists'):
        artist_name = track['artists'][0].get('name', 'Unknown')
        artist_id = track['artists'][0].get('id')

    return {
        'id': track['videoId'],
        'title': track.get('title', 'Untitled'),
        'artist': artist_name,
        'artistId': artist_id,
        'thumb': track['thumbnails'][-1]['url'] if track.get('thumbnails') else '',
        'duration': parse_duration_from_string(track.get('duration'))
    }

@app.route('/import_playlist', methods=['POST'])
def import_playlist():
    try:
        data = request.get_json() or {}
        url = data.get('url')
        if not url:
            return jsonify({'error': 'URL is required'}), 400

        playlist_id = None
        if 'youtube.com' in url or 'youtu.be' in url:
            query_params = parse_qs(urlparse(url).query)
            if 'list' in query_params:
                playlist_id = query_params['list'][0]
        
        if playlist_id:
            playlist = yt.get_playlist(playlist_id, limit=200)
            tracks = [
                formatted_track for track in playlist.get('tracks', [])
                if (formatted_track := _format_track(track)) is not None
            ]
            return jsonify({'title': playlist.get('title', 'Imported Playlist'), 'tracks': tracks})

        return jsonify({'error': 'Invalid or unsupported YouTube playlist URL'}), 400
    except Exception as e:
        print(f"Import Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/recommend', methods=['POST'])
def recommend():
    try:
        data = request.get_json() or {}
        history = data.get('history', []) # Expecting a list of videoIds
        
        raw_tracks = []
        if history and len(history) > 0:
            # Use a random song from history as a seed for YouTube's ML recommendation engine
            seed_id = random.choice(history)
            watch_list = yt.get_watch_playlist(videoId=seed_id, limit=20)
            raw_tracks = watch_list.get('tracks', [])
        else:
            # Fallback to trending/top hits if no history (Random/Initial state)
            queries = ['Top Global Hits', 'New Music', 'Trending Songs', 'Viral Hits']
            raw_tracks = yt.search(random.choice(queries), filter='songs', limit=20)

        # Process tracks into a consistent format for the frontend
        processed_tracks = [
            formatted_track for track in raw_tracks
            if (formatted_track := _format_track(track)) is not None
        ]
            
        return jsonify(processed_tracks)
    except Exception as e:
        print(f"Recommend Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/get_artist_thumbnails', methods=['POST'])
def get_artist_thumbnails():
    try:
        artists_req = request.get_json() or []
        artists_with_thumbs = []
        for artist_data in artists_req:
            try:
                artist_id = artist_data.get('id')
                if not artist_id: continue
                artist_details = yt.get_artist(artist_id)
                artists_with_thumbs.append({
                    'name': artist_data.get('name'),
                    'browseId': artist_id,
                    'thumbnail': artist_details['thumbnails'][-1]['url'] if artist_details.get('thumbnails') else ''
                })
            except Exception as e:
                print(f"Could not fetch artist {artist_id}: {e}")
                continue # Skip if artist can't be fetched, log the error
        return jsonify(artists_with_thumbs)
    except Exception as e:
        print(f"Get Artist Thumbnails Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/login', methods=['POST'])
def google_login():
    try:
        token = request.json.get('credential')
        client_id = request.json.get('clientId')
        
        if not token: return jsonify({'error': 'No token provided'}), 400

        # Verify the token
        id_info = id_token.verify_oauth2_token(token, google_requests.Request(), client_id)
        user_id = id_info['sub']
        email = id_info.get('email')

        with sqlite3.connect('aura_users.db') as conn:
            c = conn.cursor()
            c.execute("SELECT data FROM users WHERE google_id = ?", (user_id,))
            row = c.fetchone()
            
            user_data = {}
            if row and row[0]:
                user_data = json.loads(row[0])
            else:
                # New user
                c.execute("INSERT OR IGNORE INTO users (google_id, email, data) VALUES (?, ?, ?)", (user_id, email, '{}'))
            
        return jsonify({
            'status': 'success', 
            'data': user_data,
            'user_info': {
                'id': user_id,
                'name': id_info.get('name'),
                'picture': id_info.get('picture'),
                'email': email
            }
        })
    except ValueError as e:
        print(f"Auth Error (Invalid Token): {e}")
        return jsonify({'error': 'Invalid or expired token'}), 401
    except Exception as e:
        print(f"Auth Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/sync', methods=['POST'])
def sync_user_data():
    try:
        token = request.json.get('credential')
        client_id = request.json.get('clientId')
        data = request.json.get('data')
        
        if not token or not data: return jsonify({'error': 'Missing data'}), 400

        # Verify token again for security on write
        id_info = id_token.verify_oauth2_token(token, google_requests.Request(), client_id)
        user_id = id_info['sub']

        with sqlite3.connect('aura_users.db') as conn:
            c = conn.cursor()
            c.execute("UPDATE users SET data = ? WHERE google_id = ?", (json.dumps(data), user_id))
            
        return jsonify({'status': 'synced'})
    except ValueError as e:
        print(f"Sync Auth Error (Invalid Token): {e}")
        return jsonify({'error': 'Invalid or expired token'}), 401
    except Exception as e:
        print(f"Sync Error: {e}")
        return jsonify({'error': str(e)}), 500

# Socket.IO Events for Listen Along
# NOTE: This in-memory state will be lost on server restart.
# For production, consider using a persistent store like Redis.
party_rooms = {}
sid_to_room = {}

def emit_users(room):
    if room in party_rooms:
        users_list = []
        host_sid = party_rooms[room]['host']
        host_id = party_rooms[room]['users'].get(host_sid, {}).get('id')
        
        for sid, u in party_rooms[room]['users'].items():
            users_list.append({
                'id': u['id'],
                'name': u['name'],
                'avatar': u['avatar'],
                'isHost': (sid == host_sid)
            })
        emit('party_users', {'users': users_list, 'hostId': host_id}, room=room)

@socketio.on('join_party')
def on_join(data):
    room = str(data['room']).strip().lower()
    print(f"Join Party: {room} | User: {data.get('username')} | PID: {os.getpid()}")
    username = data.get('username', 'Guest')
    user_id = data.get('userId')
    avatar = data.get('avatar')
    
    join_room(room)
    sid_to_room[request.sid] = room
    
    if room not in party_rooms:
        # First user to join creates the party, becomes host, and defines the initial state
        print(f"Creating new party room: {room} on PID {os.getpid()}")
        party_rooms[room] = {
            'host': request.sid, 
            'users': {},
            'state': { 'song': None, 'isPlaying': False, 'time': 0, 'queue': [] }
        }
    
    party_rooms[room]['users'][request.sid] = {
        'id': user_id,
        'name': username,
        'avatar': avatar
    }
    
    # Immediately send the current, authoritative party state to the user who just joined.
    # The client should use this to sync its player and queue.
    emit('party_state_update', party_rooms[room]['state'], room=request.sid)

    emit('party_notification', {'msg': f'{username} joined the party!'}, room=room)
    emit_users(room)

@socketio.on('leave_party')
def on_leave(data):
    room = str(data['room']).strip().lower()
    username = data.get('username', 'Guest')
    leave_room(room)
    sid_to_room.pop(request.sid, None)
    
    if room in party_rooms and request.sid in party_rooms[room]['users']:
        del party_rooms[room]['users'][request.sid]
        if party_rooms[room]['host'] == request.sid:
            if party_rooms[room]['users']:
                party_rooms[room]['host'] = next(iter(party_rooms[room]['users']))
            else:
                del party_rooms[room]
    
    emit('party_notification', {'msg': f'{username} left the party.'}, room=room)
    emit_users(room)

@socketio.on('kick_user')
def on_kick(data):
    room = data.get('room')
    if room: room = str(room).strip().lower()
    target_id = data.get('targetId')
    
    if room in party_rooms and party_rooms[room]['host'] == request.sid:
        target_sid = None
        target_name = "User"
        for sid, user in party_rooms[room]['users'].items():
            if user['id'] == target_id:
                target_sid = sid
                target_name = user['name']
                break
        
        if target_sid:
            try:
                leave_room(room, sid=target_sid)
                sid_to_room.pop(target_sid, None)
            except Exception: pass # Target might have already disconnected
            
            del party_rooms[room]['users'][target_sid]
            emit('kicked', room=target_sid)
            emit('party_notification', {'msg': f'{target_name} was kicked.'}, room=room)
            emit_users(room)

@socketio.on('disconnect')
def on_disconnect():
    room_id = sid_to_room.pop(request.sid, None)
    if not room_id or room_id not in party_rooms:
        return

    room_data = party_rooms[room_id]
    user = room_data['users'].pop(request.sid, None)
    if not user:
        return

    emit('party_notification', {'msg': f"{user.get('name', 'A user')} disconnected."}, room=room_id)

    if not room_data['users']:
        del party_rooms[room_id]
    elif room_data['host'] == request.sid:
        room_data['host'] = next(iter(room_data['users']))
        emit_users(room_id)
    else:
        emit_users(room_id)

@socketio.on('party_action')
def on_party_action(data):
    # Robustly determine the room: prefer server-side state, fallback to payload
    room = sid_to_room.get(request.sid)
    if not room and data.get('room'):
        room = str(data.get('room')).strip().lower()

    action_type = data.get('type')

    if not room or not action_type or room not in party_rooms:
        print(f"Ignored Action: {action_type} | Room: {room} | SID: {request.sid}")
        return

    room_data = party_rooms[room]
    is_host = request.sid == room_data['host']
    state = room_data['state']

    # --- Host-only playback controls ---
    if action_type in ['play_song', 'play', 'pause', 'seek']:
        if not is_host:
            return # Ignore action from non-host

        # Create a payload for broadcasting. Start with the original data from the host.
        broadcast_data = data.copy()

        # Update the server's authoritative state based on the host's action
        if action_type == 'play_song':
            state['song'] = data.get('song')
            state['time'] = 0
            state['isPlaying'] = True
            # The original 'data' is sufficient for this action.
        elif action_type == 'play':
            state['isPlaying'] = True
            if 'time' in data: state['time'] = data['time'] # Host's time is source of truth
            # Always include the server's authoritative time in the broadcast.
            broadcast_data['time'] = state['time']
        elif action_type == 'pause':
            state['isPlaying'] = False
            if 'time' in data: state['time'] = data['time']
            # Always include the server's authoritative time in the broadcast.
            broadcast_data['time'] = state['time']
        elif action_type == 'seek':
            if 'time' in data: state['time'] = data['time']
            # The original 'data' is sufficient as 'seek' must include time.
        
        # Broadcast the host's action to all other clients in the room
        emit('party_update', broadcast_data, room=room, include_self=False)

    # --- Queue management (anyone can do) ---
    elif action_type == 'add_to_queue':
        song_to_add = data.get('song')
        if song_to_add and song_to_add.get('id') not in [s['id'] for s in state['queue']]:
            state['queue'].append(song_to_add)
            # Broadcast the "add" action so all clients can update their queue UI
            emit('party_update', data, room=room, include_self=True)
    
    elif action_type == 'remove_from_queue':
        song_id_to_remove = data.get('songId')
        if song_id_to_remove:
            state['queue'] = [s for s in state['queue'] if s['id'] != song_id_to_remove]
            emit('party_update', data, room=room, include_self=True)

    elif action_type == 'update_queue': # For drag-and-drop reordering
        new_queue = data.get('queue')
        if isinstance(new_queue, list):
            state['queue'] = new_queue
            emit('party_update', data, room=room, include_self=False)

@socketio.on('party_chat')
def on_party_chat(data):
    room = sid_to_room.get(request.sid)
    if not room and data.get('room'):
        room = str(data.get('room')).strip().lower()
        
    if room:
        socketio.emit('party_chat', data, room=room)

@socketio.on('typing')
def on_typing(data):
    room = sid_to_room.get(request.sid)
    if not room and data.get('room'):
        room = str(data.get('room')).strip().lower()
        
    if room:
        emit('typing', data, room=room, include_self=False)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host='0.0.0.0', port=port)