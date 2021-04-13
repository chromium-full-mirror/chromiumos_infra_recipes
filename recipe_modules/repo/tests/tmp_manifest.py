# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/context',
    'recipe_engine/path',
    'repo',
]

from recipe_engine.recipe_api import StepFailure


def RunSteps(api):
  with api.context(cwd=api.path['cleanup']):
    # create_tmp_manifest should raise a StepFailure if there's no repo root
    # set up.
    try:
      api.repo.create_tmp_manifest(None)
    except StepFailure:
      pass


def GenTests(api):
  yield api.test('tests')
