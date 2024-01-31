# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine.recipe_api import StepFailure

DEPS = [
    'recipe_engine/context',
    'recipe_engine/path',
    'repo',
]



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
