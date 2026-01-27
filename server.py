from flask import Flask, request, jsonify, send_from_directory
import requests
import os
from urllib.parse import urlparse, parse_qs
import random
from ytmusicapi import YTMusic
from flask_cors import CORS

app = Flask(__name__, static_url_path='', static_folder='.')
CORS(app) 
yt = YTMusic(auth=None)
yt.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

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
        except: pass

    video_id = request.args.get('id')
    if not video_id: return jsonify({'lyrics': ''})
    try:
        watch_playlist = yt.get_watch_playlist(videoId=video_id)
        lyrics_id = watch_playlist.get('lyrics')
        if lyrics_id:
            lyrics_data = yt.get_lyrics(lyrics_id)
            return jsonify({'lyrics': lyrics_data['lyrics'], 'synced': False})
    except: pass

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
        except: pass

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
            tracks = []
            for track in playlist.get('tracks', []):
                if not track.get('videoId'): continue
                tracks.append({
                    'id': track['videoId'],
                    'title': track['title'],
                    'artist': track['artists'][0]['name'] if track.get('artists') else 'Unknown',
                    'artistId': track['artists'][0]['id'] if track.get('artists') else None,
                    'thumb': track['thumbnails'][-1]['url'] if track.get('thumbnails') else '',
                    'duration': parse_duration_from_string(track.get('duration'))
                })
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
        processed_tracks = []
        for track in raw_tracks:
            if not track.get('videoId'): continue
            processed_tracks.append({
                'id': track['videoId'],
                'title': track.get('title'),
                'artist': track['artists'][0]['name'] if track.get('artists') and track['artists'] else 'Unknown',
                'artistId': track['artists'][0]['id'] if track.get('artists') and track['artists'] and track['artists'][0].get('id') else None,
                'thumb': track['thumbnails'][-1]['url'] if track.get('thumbnails') else '',
                'duration': parse_duration_from_string(track.get('duration'))
            })
            
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
            except Exception:
                continue # Skip if artist can't be fetched
        return jsonify(artists_with_thumbs)
    except Exception as e:
        print(f"Get Artist Thumbnails Error: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    # The server will automatically log its startup. This print is redundant.
    app.run(host='0.0.0.0', port=port)