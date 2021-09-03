from sqlite3 import OperationalError
from pathlib import Path
from deemon.core.db import Database
from deemon.core.config import Config as config
from deemon.utils import startup, menu
import logging
import deezer

logger = logging.getLogger(__name__)


def monitor(profile, value, bitrate, r_type, alerts, remove=False, reset=False, dl_obj=None):

    dz = deezer.Deezer()
    db = Database(startup.get_database())

    def purge_playlist(i, title):
        values = {'id': api_result['id']}
        db.query("DELETE FROM 'playlists' WHERE id = :id", values)
        logger.debug(f"Playlist {i} removed from monitoring")
        db.query("DELETE FROM 'playlist_tracks' WHERE playlist_id = :id", values)
        logger.debug(f"All releases tracked for playlist {i} have been removed")
        db.commit()
        logger.info(f"No longer monitoring playlist '{title}'")

    def purge_artist(i, name):
        values = {'id': api_result['id']}
        db.query("DELETE FROM 'monitor' WHERE artist_id = :id", values)
        logger.debug(f"Artist {i} removed from monitoring")
        db.query("DELETE FROM 'releases' WHERE artist_id = :id", values)
        logger.debug(f"All releases tracked for artist {i} have been removed")
        db.commit()
        logger.info(f"No longer monitoring artist '{name}'")

    def get_best_result(api_data):
        matches: list = []
        for idx, artist in enumerate(api_result):
            if value == artist['name']:
                matches.append(artist)
        if len(matches) == 1:
            return matches[0]
        elif len(matches) > 1:
            m = menu.Menu("Multiple exact matches found: ", matches)
            ask_user = m.get_user_choice()
            if type(ask_user) is int:
                return matches[ask_user]
        else:
            m = menu.Menu("Showing closest results, please choose:", api_result)
            ask_user = m.get_user_choice()
            if type(ask_user) is int:
                return api_result[ask_user]

    if reset:
        db.reset_database()
        return

    if not Path(config.download_path()).exists:
        return logger.error(f"Invalid download path: {config.download_path()}")

    if profile in ['artist', 'artist_id']:
        if profile == "artist":
            try:
                api_result = dz.api.search_artist(value, limit=10)["data"]
            except (deezer.api.DataException, IndexError):
                logger.error(f"Artist {value} not found.")
                return
            api_result = get_best_result(api_result)
            if not api_result:
                return
        else:
            try:
                api_result = dz.api.get_artist(value)
            except deezer.api.DataException:
                logger.error(f"Artist ID {value} not found.")
                return
        sql_values = {'id': api_result['id']}
        artist_exists = db.query("SELECT * FROM 'monitor' WHERE artist_id = :id", sql_values).fetchone()
        if remove:
            if not artist_exists:
                logger.warning(f"{api_result['name']} is not being monitored yet")
                return
            purge_artist(api_result['id'], api_result['name'])
            return
        if artist_exists:
            logger.warning(f"Artist '{api_result['name']}' is already being monitored")
            return

        sql_values = {
            'artist_id': api_result['id'],
            'artist_name': api_result['name'],
            'bitrate': bitrate,
            'record_type': r_type,
            'alerts': alerts,
            'download_path': config.download_path()
        }
        query = ("INSERT INTO monitor (artist_id, artist_name, bitrate, record_type, alerts, download_path) "
                 "VALUES (:artist_id, :artist_name, :bitrate, :record_type, :alerts, :download_path)")

        try:
            db.query(query, sql_values)
        except OperationalError as e:
            logger.info(e)

        logger.info(f"Now monitoring artist '{api_result['name']}'")
        logger.debug(f"bitrate: {bitrate}, record_type: {r_type}, "
                     f"alerts: {alerts}, download_path: {config.download_path()}")
        if dl_obj:
            dl_obj.download(None, [api_result['id']], None, None, bitrate, r_type, None, False)
        db.commit()
        return api_result['id']

    if profile == "playlist":
        playlist_id_from_url = value.split('/playlist/')
        try:
            playlist_id = int(playlist_id_from_url[1])
        except (IndexError, ValueError):
            logger.error(f"Invalid playlist URL -- {playlist_id_from_url}")
            return
        try:
            api_result = dz.api.get_playlist(playlist_id)
        except deezer.api.DataException:
            logger.error(f"Playlist ID {playlist_id} not found.")
            return
        sql_values = {'id': api_result['id']}
        playlist_exists = db.query("SELECT * FROM 'playlists' WHERE id = :id", sql_values).fetchone()
        if remove:
            if not playlist_exists:
                logger.warning(f"Playlist '{api_result['title']}' is not being monitored yet")
                return
            purge_playlist(api_result['id'], api_result['title'])
            return True
        if playlist_exists:
            logger.warning(f"Playlist '{api_result['title']}' is already being monitored")
            return
        sql_values = {'id': api_result['id'], 'title': api_result['title'], 'url': api_result['link'],
                      'bitrate': bitrate, 'alerts': alerts, 'download_path': config.download_path()}
        query = ("INSERT INTO playlists ('id', 'title', 'url', 'bitrate', 'alerts', 'download_path') "
                 "VALUES (:id, :title, :url, :bitrate, :alerts, :download_path)")

        try:
            db.query(query, sql_values)
        except OperationalError as e:
            logger.error(e)

        logger.info(f"Now monitoring playlist '{api_result['title']}'")
        if dl_obj:
            dl_obj.download(None, None, None, [api_result['link']], bitrate, r_type, None, False)
        db.commit()
        return api_result['id']
