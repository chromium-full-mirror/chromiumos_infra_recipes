# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api
import random

DUMMY_IMAGE = 'cos-rc-85-13310-1015-0'
GCE_PREFIX = 'gce-tests'


class GcloudApi(recipe_api.RecipeApi):
  """A module to process tast-results/ directory."""

  def set_gce_project(self):
    """Set the default project for gcloud command."""
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('set gcloud project',
                  ['gcloud', 'config', 'set', 'project', 'chromeos-gce-tests'])

  def auth_list(self, step_name=None):
    """Print out the auth creds currently on the bot.

    Args:
      step_name(str): Name of the step.
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step(step_name or 'gcloud auth', ['gcloud', 'auth', 'list'])

  def create_instance(self, image=DUMMY_IMAGE):
    """Create an instance in the GCE project.

    Args:
      image(str): GCE image to use for the instance.

    Returns: A string name of the instance.
    """
    self.m.random.seed(int(self.m.time.time()))
    rand_int = self.m.random.randint(10000, 99999)
    instance_name = '{}-{}-{}'.format(GCE_PREFIX, image, rand_int)
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('create instance', [
          'gcloud', 'compute', 'instances', 'create', instance_name,
          '--image={}'.format(image), '--image-project=cos-cloud',
          '--project=chromeos-gce-tests', '--machine-type=n1-standard-4',
          '--no-scopes', '--no-address', '--network=chromeos-gce-tests',
          '--subnet=us-central1', '--zone=us-central1-a'
      ])

    return instance_name

  def delete_instance(self, instance):
    """Delete a GCE instance.

    Args:
      instance(str): GCE instance to be deleted.
    """
    with self.m.context(env={'VIRTUAL_ENV': '1'}):
      self.m.step('delete instance', [
          'gcloud', 'compute', 'instances', 'delete', instance, '--quiet',
          '--zone=us-central1-a', '--project=chromeos-gce-tests'
      ])
