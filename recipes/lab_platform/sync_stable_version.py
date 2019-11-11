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

PROPERTIES = SyncStableVersionProperties

def fetch_and_commit(api):
  """Fetch the newest stable version and commit it to config file on git.

  Returns:
    A string gerrit CL link.
  """
  with api.step.nest('fetch and commit') as step:
    api.stable_version.fetch_and_commit()


def RunSteps(api, properties):
  # TODO(xixuan): Re-consider the whole processes:
  #   1. log the CL link of automatic stable version update.
  #   2. pass in the real parameters.
  #   3. separate the whole process to individual steps.
  fetch_and_commit(api)

def GenTests(api):
  yield (
    api.test('fetch and commit') + #
    api.step_data('fetch and commit.call stable_version2.update-with-omaha',
                  stdout=api.raw_io.output_text('http://CL/123'))
  )