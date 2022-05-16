# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for sync stable vesrion for ChromeOS build targets & models."""

from PB.recipes.chromeos.lab_platform.sync_stable_version import \
  SyncStableVersionProperties

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'stable_version',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = SyncStableVersionProperties


def fetch_and_commit(api):
  """Fetch the newest stable version and commit it to config file on git.

  Returns:
    A string gerrit CL link.
  """
  with api.step.nest('fetch and commit'):
    api.stable_version.fetch_and_commit()


def validate_stable_version(api):
  """Validate the remote stable version config file.

  Returns: JSON response with validation result"""
  with api.step.nest('validate stable version'):
    api.stable_version.validate_stable_version()


# pylint: disable=unused-argument
def RunSteps(api, properties):
  # TODO(xixuan): Re-consider the whole processes:
  #   1. log the CL link of automatic stable version update.
  #   2. pass in the real parameters.
  #   3. separate the whole process to individual steps.
  validate_stable_version(api)
  fetch_and_commit(api)


def GenTests(api):
  yield api.test(
      'end-to-end-test-for-updating-stable-version',
      api.step_data('fetch and commit.call stable_version2.update-with-omaha',
                    stdout=api.raw_io.output('http://CL/123')),
  )
