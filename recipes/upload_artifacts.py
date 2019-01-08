# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/archive',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/python',
    'recipe_engine/step',
    'cros_sdk',
    'payloads',
    'artifacts'
]


PREFIX = 'chromeos'
SUFFIX = 'dev.bin'
STATEFUL_FILE = 'stateful.tgz'


def RunSteps(api):
  base_path = api.path['cleanup']
  archive_path = base_path.join('archive')
  payload_path = base_path.join(api.payloads.payload_path)

  api.file.ensure_directory('create archive dir', archive_path)
  api.file.ensure_directory('create payload dir', payload_path)

  #generate payloads
  image_path = api.properties['image_path']
  os_version = api.properties['os_version']
  build_target = api.properties['build_target']

  output_full_filename = full_filename(os_version, build_target)
  output_delta_filename = delta_filename(os_version, build_target)

  api.payloads.generate_full(image_path,
      output_full_filename,
      'full_dev_part_KERN.bin',
      'full_dev_part_ROOT.bin')
  api.payloads.generate_delta(image_path, output_delta_filename)
  api.payloads.generate_stateful(image_path)

  # archive
  api.file.move('move full payload',
      payload_path.join(output_full_filename), archive_path)
  api.file.move('move delta payload',
      payload_path.join(output_delta_filename), archive_path)
  api.file.move('move stateful payload',
      payload_path.join(STATEFUL_FILE), archive_path)

  for partition in ['KERN', 'ROOT']:
    src = payload_path.join('full_dev_part_%s.bin' % partition)
    dest = archive_path.join('full_dev_part_%s.bin.gz' % partition)

    compress_file(api.python, 'archive partition %s' % partition,
                  src, dest)

  # upload
  api.artifacts.upload(
      archive_path,
      api.properties['buildername'],
      api.properties['build_id'],
      api.properties.get('gs_buckets'))

def full_filename(os_version, build_target):
  # Full payload names look something like this:
  # chromeos_R37-5952.0.2014_06_12_2302-a1_link_full_dev.bin
  return '_'.join([PREFIX, os_version, build_target, 'full', SUFFIX])

def delta_filename(os_version, build_target):
  # Delta payload names look something like this:
  # chromeos_R37-5952.0.2014_06_12_2302-a1_R37-
  # 5952.0.2014_06_12_2302-a1_link_delta_dev.bin
  return '_'.join([PREFIX, os_version, os_version, build_target,
                   'delta', SUFFIX])

def compress_file(python, name, src, dest):
  python.inline(name,
    """
import gzip

with open('%s', 'rb') as src:
  with gzip.open('%s', 'wb') as dest:
    dest.writelines(src)
    """ % (src, dest)
  )

def GenTests(api):
  yield (
    api.test('basic') +
    api.properties(
        image_path=api.path['start_dir'].join('chroot', 'images', 'image.img'),
        os_version='R37-5952.0.2014_06_12_2302-a1',
        build_target='build_target',
        buildername='builder',
        build_id='123456',
        gs_buckets=None
    ) +
    api.step_data('archive partition KERN', retcode=0) +
    api.step_data('archive partition ROOT', retcode=0)
  )
