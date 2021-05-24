# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api
import os
import random

DUMMY_IMAGE = 'cos-rc-85-13310-1015-0'
GCE_PREFIX = 'gce-tests'
GCE_TEST_BUCKET = 'images-in-test'
RAW_IMAGE_NAME = 'disk.raw'
TEST_IMAGE_NAME = 'chromiumos_test_image.bin'


class GcloudApi(recipe_api.RecipeApi):
  """A module to process tast-results/ directory."""

  def set_gce_project(self, project):
    """Set the default project for gcloud command.
    Args:
      project(str): Google Cloud project name.
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('set gcloud project',
                  ['gcloud', 'config', 'set', 'project', project])

  def auth_list(self, step_name=None):
    """Print out the auth creds currently on the bot.

    Args:
      step_name(str): Name of the step.
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step(step_name or 'gcloud auth', ['gcloud', 'auth', 'list'])

  def prep_image(self, source_bucket, source_path, uniq_id):
    """Prepare the image to be used for testing.

    Args:
      source_bucket(str): Source GS bucket to download from.
      source_path(str): Path in GS to the build artifacts.
      uniq_id(int): ID to differentiate the image. Usually
          buildbucket_id of the build that generated the image.

    Returns: Path to the image tar file.
    """
    with self.m.step.nest('prepare image'):
      image_archive_dir = self.m.path.mkdtemp(prefix='image-archive')
      test_image_zip = image_archive_dir.join('image.zip')
      test_image_dir = image_archive_dir.join('image')
      test_image_path = str(test_image_dir.join(TEST_IMAGE_NAME))
      raw_image_path = str(test_image_dir.join(RAW_IMAGE_NAME))
      self.m.gsutil.download(source_bucket,
                             os.path.join(source_path,
                                          'image.zip'), test_image_zip,
                             name='download image bundle from GS')
      self.m.archive.extract('unzip image bundle', test_image_zip,
                             test_image_dir, include_files=[TEST_IMAGE_NAME])
      # Rename image and tar it up.
      self.m.file.move('Rename image to disk.raw', test_image_path,
                       raw_image_path)
      tar_file = '{}.tar.gz'.format(uniq_id)
      tar_path = str(test_image_dir.join(tar_file))
      with self.m.context(cwd=test_image_dir):
        self.m.step(
            'tar image',
            ['tar', '--format=oldgnu', '-Sczf', tar_file, RAW_IMAGE_NAME])
      return tar_path

  def create_image(self, tar_path, target, uniq_id):
    """Create an image in the GCE project.

    Args:
      tar_path(str): Path to the requisite image tar_file.
      target(str): Target being tested. (Ex:betty-arc-r)
      uniq_id(int): ID to differentiate the image. Usually
        buildbucket_id of the build that generated the image.

    Returns: A string name of the image.
    """
    with self.m.step.nest('create image'):
      tar_file = '{}.tar.gz'.format(uniq_id)
      self.m.gsutil.upload(tar_path, GCE_TEST_BUCKET,
                           '{}/{}'.format(target, tar_file))
      with self.m.context(env={'VIRTUAL_ENV': '1'}):
        image_name = '{}-{}'.format(target, uniq_id)
        self.m.step('gce create image', [
            'gcloud',
            'compute',
            'images',
            'create',
            image_name,
            '--source-uri=gs://{}/{}/{}'.format(GCE_TEST_BUCKET, target,
                                                tar_file),
        ])
        return image_name

  def delete_image(self, image_name):
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('delete image', [
          'gcloud',
          'compute',
          'images',
          'delete',
          image_name,
          '--quiet',
      ])

  def create_instance(self, image, project, machine, zone, network=None,
                      subnet=None):
    """Create an instance in the GCE project.

    Args:
      image(str): GCE image to use for the instance.
      project(str): Google Cloud project name.
      machine(str): GCE machine type
      zone(str): GCE zone to create instance.
      network(str): Network name to use.
      subnet(str): Network subnet on which to create instance.

    Returns: A string name of the instance.
    """
    extra_args = []
    if network:
      extra_args.append('--network={}'.format(network))
    if subnet:
      extra_args.append('--subnet={}'.format(subnet))
    gcloud_cmd = [
        'gcloud', 'compute', 'instances', 'create', image,
        '--image={}'.format(image), '--project={}'.format(project),
        '--machine-type={}'.format(machine), '--no-scopes', '--no-address',
        '--zone={}'.format(zone)
    ]
    gcloud_cmd.extend(extra_args)
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('create instance', gcloud_cmd)

  def delete_instance(self, instance, project, zone):
    """Delete a GCE instance.

    Args:
      instance(str): GCE instance to be deleted.
      project(str): Google Cloud project name.
      zone(str): GCE zone to create instance.
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('delete instance', [
          'gcloud', 'compute', 'instances', 'delete', instance, '--quiet',
          '--zone={}'.format(zone), '--project={}'.format(project)
      ])
