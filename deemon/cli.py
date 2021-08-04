from deemon.app import settings, monitor, download, notify
from deemon.app.logger import setup_logger
from deemon.app.batch import BatchJobs
from deemon.app.refresh import Refresh
from deemon.app.show import ShowStats
from deemon import __version__
from datetime import datetime
from deemon.app import utils
from pathlib import Path
import tarfile
import logging
import click
import sys

logger = logging.getLogger(__name__)

appdata = utils.get_appdata_dir()
utils.init_appdata_dir(appdata)
settings = settings.Settings()
settings.load_config()
config = settings.config

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


@click.group(context_settings=CONTEXT_SETTINGS)
@click.option('-v', '--verbose', is_flag=True, help='Enable verbose output')
@click.version_option(__version__, '-V', '--version', message='deemon %(version)s')
def run(verbose):
    """Monitoring and alerting tool for new music releases using the Deezer API.

    deemon is a free and open source tool. To report issues or to contribute,
    please visit https://github.com/digitalec/deemon
    """
    setup_logger(log_level='DEBUG' if verbose else 'INFO', log_file=utils.get_log_file())

    new_version = utils.check_version()
    if new_version:
        print("*" * 50)
        logger.info(f"* New version is available: v{__version__} -> v{new_version}")
        logger.info("* To upgrade, run `pip install --upgrade deemon`")
        print("*" * 50)


@run.command(name='test')
def test():
    """Test email server settings by sending a test notification"""
    notification = notify.Notify()
    notification.test()


@run.command(name='download')
@click.option('-a', '--artist', metavar='NAME', type=str, help='Download all by artist name')
@click.option('-i', '--artist-id', metavar='ID', type=int, help='Download all by artist ID')
@click.option('-A', '--album-id', metavar='ID', type=int, help='Download by album ID')
@click.option('-u', '--url', metavar='URL', help='Download by URL of artist/album/track')
@click.option('-f', '--file', 'input_file', metavar='FILE', help='Download batch of artists from file, one per line')
@click.option('-b', '--bitrate', metavar='N', type=int, default=config["bitrate"],
              help='Set custom bitrate for this operation')
@click.option('-r', '--record-type', metavar='TYPE', default=config["record_type"],
              help='Only get certain record types')
def download_command(artist, artist_id, album_id, url, input_file, bitrate, record_type):
    """Download specific artist, album ID or by URL"""

    params = {
        'artist': artist,
        'artist_id': artist_id,
        'album_id': album_id,
        'url': url,
        'bitrate': bitrate,
        'record_type': record_type,
        'file': input_file
    }

    dl = download.Download()
    dl.download(params)


@run.command(name='monitor', context_settings={"ignore_unknown_options": True})
@click.argument('artist', nargs=-1)
@click.option('-i', '--artist-id', multiple=True, type=int, metavar="ID", help="Monitor artist by ID")
@click.option('-p', '--playlist', multiple=True, metavar="URL", help='Monitor Deezer playlist by URL')
@click.option('-n', '--no-refresh', is_flag=True, help='Skip refresh after adding or removing artist')
@click.option('-r', '--record-type', type=click.Choice(['album', 'ep', 'single'], case_sensitive=False),
              help='Specify record type to monitor (default=ALL)')
@click.option('-u', '--url', multiple=True, metavar="URL", help='Monitor artist by URL')
@click.option('-R', '--remove', is_flag=True, help='Stop monitoring an artist')
@click.option('--reset', is_flag=True, help='Remove all artists/playlists from monitoring')
def monitor_command(artist, playlist, no_refresh, record_type, artist_id, remove, url, reset):
    """
    Monitor artist for new releases by ID, URL or name.

    \b
    Examples:
        monitor Mozart
        monitor --artist-id 100
        monitor --url https://www.deezer.com/us/artist/000
    """

    artists = ' '.join(artist)
    artists = artists.split(',')
    artists = [x.lstrip() for x in artists]

    artist_id = list(artist_id)
    url = list(url)
    playlists = list(playlist)

    new_artists = []
    new_playlists = []

    if reset:
        logger.warning("** ALL ARTISTS AND PLAYLISTS WILL BE REMOVED! **")
        confirm = input("Type 'reset' to confirm: ")
        if confirm == "reset":
            monitor.monitor(profile=None, value=None, reset=True)
        else:
            logger.info("Reset aborted. Database has NOT been modified.")
        return

    if artist:
        for a in artists:
            result = monitor.monitor("artist", a, remove=remove, rtype=record_type)
            if type(result) == int:
                new_artists.append(result)

    if artist_id:
        for aid in artist_id:
            result = monitor.monitor("artist_id", aid, remove=remove, rtype=record_type)
            if type(result) == int:
                new_artists.append(result)

    if url:  # TODO cleanup, merge with artist_id somehow?
        for u in url:
            id_from_url = u.split('/artist/')
            try:
                artist_id = int(id_from_url[1])
            except (IndexError, ValueError):
                logger.error(f"Invalid URL -- {url}")
                sys.exit(1)
        result = monitor.monitor("artist_id", artist_id, remove=remove, rtype=record_type)
        if type(result) == int:
            new_artists.append(result)

    if playlists:
        for p in playlists:
            result = monitor.monitor("playlist", p, remove=remove)
            if type(result) == int:  # TODO is this needed? What return values are possible? if result > 0?
                new_playlists.append(result)
    if (len(new_artists) > 0 or len(new_playlists) > 0) and not no_refresh:
        logger.debug("Requesting refresh, standby...")
        logger.debug(f"new_artists={new_artists}")
        logger.debug(f"new_playlists={new_playlists}")
        Refresh(artist_id=new_artists, playlist_id=new_playlists) # TODO will an empty list cause an issue?


@run.command(name='refresh')
@click.option('-s', '--skip-download', is_flag=True, help="Skips downloading of new releases")
@click.option('-t', '--time-machine', metavar='DATE', type=str, help='Refresh as if it were this date (YYYY-MM-DD)')
def refresh_command(skip_download, time_machine):
    """Check artists for new releases"""
    Refresh(skip_download=skip_download, time_machine=time_machine)


@run.command(name='show')
@click.option('-a', '--artists', is_flag=True, help='Show artists currently being monitored')
@click.option('-i', '--artist-ids', is_flag=True, help='Show artist IDs currently being monitored')
@click.option('-p', '--playlists', is_flag=True, help='Show playlists currently being monitored')
@click.option('-c', '--csv', is_flag=True, help='Used with --artists, output artists as CSV')
@click.option('-n', '--new-releases', metavar='N', type=int, help='Show new releases from last N days')
def show_command(artists, artist_ids, playlists, new_releases, csv):
    """
    Show monitored artists, latest new releases and various statistics
    """
    show = ShowStats()
    if artists or artist_ids:
        show.artists(csv, artist_ids)
    elif playlists:
        show.playlists(csv)
    elif new_releases:
        show.releases(new_releases)


@run.command(name='import')
@click.argument('path')
@click.option('-i', '--artist-ids', is_flag=True, help='Import file of artist IDs')
def import_cmd(path, artist_ids):
    """Import artists from CSV, text file or directory"""
    batch = BatchJobs()
    batch.import_artists(path, artist_ids)


@run.command()
@click.option('--include-logs', is_flag=True, help='include log files in backup')
def backup(include_logs):
    """Backup configuration and database to a tar file"""

    def filter_func(item):
        exclusions = ['deemon/backups']
        if not include_logs:
            exclusions.append('deemon/logs')
        if item.name not in exclusions:
            return item

    backup_tar = datetime.today().strftime('%Y%m%d-%H%M%S') + ".tar"
    backup_path = Path(settings.config_path / "backups")

    with tarfile.open(backup_path / backup_tar, "w") as tar:
        tar.add(settings.config_path, arcname='deemon', filter=filter_func)
        logger.info(f"Backed up to {backup_path / backup_tar}")

