# Adapted in part from Olivier Hagolle
# https://github.com/olivierhagolle/LANDSAT-Download
import os
import re
import sys, math, time
import urllib
import urllib2
import tarfile
import requests
from datetime import datetime, timedelta

import web_tools


class StationNotFoundError(Exception):
    pass


class BadRequestsResponse(Exception):
    pass


class InvalidSatelliteError(Exception):
    pass


class NotaTGZError(Exception):
    pass


def connect_earth_explorer(usgs):
    # mkmitchel (https://github.com/mkmitchell) solved the token issue
    cookies = urllib2.HTTPCookieProcessor()
    opener = urllib2.build_opener(cookies)
    urllib2.install_opener(opener)

    data = urllib2.urlopen("https://ers.cr.usgs.gov").read()
    m = re.search(r'<input .*?name="csrf_token".*?value="(.*?)"', data)
    if m:
        token = m.group(1)
    else:
        print "Error : CSRF_Token not found"
        # sys.exit(-3)

    params = urllib.urlencode(dict(username=usgs['account'], password=usgs['passwd'], csrf_token=token))
    request = urllib2.Request("https://ers.cr.usgs.gov/login", params, headers={})
    f = urllib2.urlopen(request)

    data = f.read()
    f.close()
    if data.find('You must sign in as a registered user to download data or place orders for USGS EROS products') > 0:
        print "Authentification failed"
        # sys.exit(-1)
    return


def download_chunks(url, out_dir, tgz_file):

    local_file = os.path.join(out_dir, tgz_file)
    print 'url: {}'.format(url)
    print 'file: {}'.format(local_file)

    r = requests.get(url, stream=True)

    if r.status_code == 200:
        with open(local_file, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024 * 10):
                print chunk
                f.write(chunk)


def unzip_image(tgzfile, outputdir):
    target_tgz = os.path.join(outputdir, tgzfile)
    print 'target tgz: {}'.format(target_tgz)
    if os.path.exists(target_tgz):
        tfile = tarfile.open(target_tgz, 'r:gz')
        tfile.extractall(outputdir)
        print 'unzipped\ndeleting tgz: {}'.format(target_tgz)
        os.remove(target_tgz)
    else:
        raise NotImplementedError('Did not find download output directory to unzip: {}'.format(target_tgz))
    return None


def get_credentials(usgs_path):
    with file(usgs_path) as f:
        (account, passwd) = f.readline().split(' ')
        if passwd.endswith('\n'):
            passwd = passwd[:-1]
        usgs = {'account': account, 'passwd': passwd}
        return usgs


def get_station_list_identifier(product):
    if product.startswith('LC8'):
        identifier = '4923'
        stations = ['LGN']
    elif product.startswith('LE7'):
        identifier = '3373'
        stations = ['EDC', 'SGS', 'AGS', 'ASN', 'SG1', 'CUB', 'COA']
    elif product.startswith('LT5'):
        identifier = '3119'
        stations = ['GLC', 'ASA', 'KIR', 'MOR', 'KHC', 'PAC',
                    'KIS', 'CHM', 'LGS', 'MGR', 'COA', 'MPS', 'CUB']
    else:
        raise NotImplementedError('Must provide valid product string...')

    return identifier, stations


def find_valid_scene(ref_time, prow, sat, delta=16):
    scene_found = False

    possible_l7_stations = ['EDC', 'SGS', 'AGS', 'ASN', 'SG1', 'CUB', 'COA']
    possible_l8_stations = ['LGN']
    possible_l5_stations = ['PAC', 'GLC', 'ASA', 'KIR', 'MOR', 'KHC',
                            'KIS', 'CHM', 'LGS', 'MGR', 'COA', 'MPS', 'CUB']

    if sat == 'LC8':
        station_list = possible_l8_stations
    elif sat == 'LE7':
        station_list = possible_l7_stations
    elif sat == 'LT5':
        station_list = possible_l5_stations
    else:
        raise InvalidSatelliteError('Must provide valid satellite...')

    attempts = 0
    while attempts < 5:

        date_part = datetime.strftime(ref_time, '%Y%j')
        padded_pr = '{}{}'.format(str(prow[0]).zfill(3), str(prow[1]).zfill(3))

        if not scene_found:

            print 'Looking for version/station combination....'
            for archive in ['00', '01', '02']:

                for location in station_list:

                    scene_str = '{}{}{}{}{}'.format(sat, padded_pr, date_part, location, archive)

                    if web_tools.verify_landsat_scene_exists(scene_str):
                        version = archive
                        print 'using version: {}, location: {}'.format(version, location)
                        return padded_pr, date_part, location, archive

                if scene_found:
                    break

            if not scene_found:
                ref_time += timedelta(days=delta)
                print 'No scene, moving {} days ahead to {}'.format(delta, datetime.strftime(ref_time, '%Y%j'))
                attempts += 1

    raise StationNotFoundError('Did not find a valid scene within time frame.')


def assemble_scene_id_list(ref_time, prow, sat, end_date, delta=16):

    scene_id_list = []

    padded_pr, date_part, location, archive = find_valid_scene(ref_time, prow, sat)

    while ref_time < end_date:

        scene_str = '{}{}{}{}{}'.format(sat, padded_pr, date_part, location, archive)

        print 'add scene: {}, for {}'.format(scene_str,
                                             datetime.strftime(ref_time, '%Y-%m-%d'))
        scene_id_list.append(scene_str)

        ref_time += timedelta(days=delta)

        date_part = datetime.strftime(ref_time, '%Y%j')

    return scene_id_list


def get_candidate_scenes_list(path_row, sat_name, start_date, end_date):
    """
    
    :param path_row: path, datetime obj
    :param sat_name: 'LT5', 'LE7', or 'LC8'
    :param start_date: datetime object start image search
    :param end_date: datetime object finish image search
    :param max_cloud_cover: percent cloud cover according to USGS image metadata, float
    :param limit_scenes: max number scenese, int
    :return: reference overpass = str('YYYYDOY'), station str('XXX') len=3
    """

    reference_overpass = web_tools.landsat_overpass_time(path_row,
                                                         start_date, sat_name)

    scene_list = assemble_scene_id_list(reference_overpass, path_row, sat_name, end_date)
    return scene_list


def down_usgs_by_list(scene_list, output_dir, usgs_creds_txt):

    usgs_creds = get_credentials(usgs_creds_txt)
    connect_earth_explorer(usgs_creds)

    for product in scene_list:
        identifier, stations = get_station_list_identifier(product)
        base_url = 'https://earthexplorer.usgs.gov/download/'
        tail_string = '{}/{}/STANDARD/EE'.format(identifier, product)
        url = '{}{}'.format(base_url, tail_string)

        tgz_file = '{}.tgz'.format(product)
        download_chunks(url, output_dir, tgz_file)
        print 'image: {}'.format(os.path.join(output_dir, tgz_file))
        unzip_image(tgz_file, output_dir)

    return None


if __name__ == '__main__':
    pass

# ===============================================================================
