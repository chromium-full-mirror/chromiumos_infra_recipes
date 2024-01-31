# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for syncing to our local cache LVFS files (https://fwupd.org/)."""
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi


DEPS = [
    'cros_lvfs_mirror',
]


def RunSteps(api: RecipeApi):
  api.cros_lvfs_mirror.configure(
      mirror_address='https://cdn.fwupd.org/downloads',
      gs_uri='gs://chromeos-localmirror/lvfs')
  api.cros_lvfs_mirror.run()


def GenTests(api: RecipeTestApi):
  yield api.test('basic')
